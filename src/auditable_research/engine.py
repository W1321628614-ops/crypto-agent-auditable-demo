"""Small offline adapter around reused integrity, journal and broker primitives.

The engine owns the synthetic tape; only packet() is decision-provider input.
This causal interface is not system-level isolation against an adversarial process.
"""
from __future__ import annotations
import copy,json
from datetime import datetime,timezone
from pathlib import Path
import jsonschema
from . import provenance as av
from .journal import Journal
from .matching import Matching,aggregate

HERE=Path(__file__).resolve().parent
DEFAULT=dict(initial_cash=1000.0,fee_bps=2.0,slippage_bps=1.0,funding_bps=0.0,
             warmup=96,decision_every=96,risk_cap=0.02,notional_cap=1.0)

def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def runtime_hashes():
    return {p.name:av.digest(p) for p in sorted(HERE.iterdir()) if p.suffix=='.py' or p.name=='answer_schema.json'}

def validate_bundle(bundle):
    if bundle.get('data_status')!='synthetic_fixture' or bundle.get('symbol')!='DEMOUSD':
        raise ValueError('This public demo accepts only explicitly labelled DEMOUSD synthetic fixtures')
    if bundle.get('market') not in ('spot','usd_m_perpetual') or bundle.get('base_timeframe')!='15m':
        raise ValueError('unsupported synthetic market/timeframe')
    bars=bundle['candles']
    for b in bars:
        if any(not av.finite(b.get(k)) for k in ('open','high','low','close','volume')):
            raise ValueError('finite numeric OHLCV required')
        if min(b[k] for k in ('open','high','low','close'))<=0:
            raise ValueError('positive prices required')
        if any(type(b.get(k)) is not int for k in ('open_time_ms','close_time_ms')):
            raise ValueError('integer timestamps required')
    av.validate_and_partition_klines(dict(symbol='DEMOUSD',interval='15m',candles=bars,returned=len(bars)),
        symbol='DEMOUSD',interval='15m',requested_limit=len(bars),historical=True,
        observation_cutoff_utc=av.utc_iso_from_ms(bars[-1]['close_time_ms']))
    return copy.deepcopy(bars)

class Engine(Journal,Matching):
    @classmethod
    def create(cls,path,bundle,config=None):
        bars=validate_bundle(bundle);cfg={**DEFAULT,**(config or {})}
        if set(cfg)!=set(DEFAULT): raise ValueError('unknown configuration field')
        if any(not av.finite(v) for v in cfg.values()): raise ValueError('finite configuration required')
        if cfg['initial_cash']<=0 or any(not 0<=cfg[k]<10000 for k in ('fee_bps','slippage_bps')) or abs(cfg['funding_bps'])>=10000:
            raise ValueError('invalid cost/cash configuration')
        if not 0<cfg['risk_cap']<=0.1 or not 0<cfg['notional_cap']<=1:
            raise ValueError('collateral and illustrative risk caps required')
        if bundle['market']=='spot' and cfg['funding_bps']!=0: raise ValueError('spot funding forbidden')
        if any(type(cfg[k]) is not int or cfg[k]<1 for k in ('warmup','decision_every')) or cfg['warmup']>=len(bars):
            raise ValueError('invalid warmup/schedule')
        p=Path(path);p.mkdir(parents=True,exist_ok=False)
        for name in ('journal','requests','imports'): (p/name).mkdir()
        av.write_new(p/'input.json',bundle)
        av.write_new(p/'manifest.json',dict(version='public_offline_v1',config=cfg,input_sha256=av.digest(p/'input.json'),
            runtime_hashes=runtime_hashes(),created_at=now(),model_calls=0,network_calls=0,
            scope='synthetic offline demonstration; not live AI inference or profitability evidence'))
        obj=cls(p)
        with obj.lock():obj._request('initial_after_warmup')
        return obj

    def __init__(self,path):
        self.path=Path(path);self.manifest=av.read(self.path/'manifest.json')
        if self.manifest['input_sha256']!=av.digest(self.path/'input.json'): raise ValueError('input hash mismatch')
        if self.manifest['runtime_hashes']!=runtime_hashes(): raise ValueError('runtime/schema changed; start a new version')
        self.bundle=av.read(self.path/'input.json');self.bars=validate_bundle(self.bundle)
        self.config=self.manifest['config'];self._reload()

    def _reload(self):
        super()._reload()
        for e in self.events:
            if e['kind'] in ('decision','rejected_import'):
                f=self.path/'imports'/e['data']['raw_file']
                if f.parent!=self.path/'imports' or av.digest(f)!=e['data']['raw_sha256']:
                    raise ValueError('raw imported answer changed')

    def _request(self,reason):
        if self.state['request_id']: return
        rid=f"request_{len(self.events):06d}"
        visible=aggregate(self.bars[:self.state['index']+1],'15m')
        visible={tf:rows for tf,rows in visible.items() if rows}
        for tf,rows in visible.items():
            for b in rows:b['evidence_id']=f"{tf}:{b['open_time_ms']}"
        packet=dict(request_id=rid,symbol='DEMOUSD',market=self.bundle['market'],data_status='synthetic_fixture',
            observation_cutoff=av.utc_iso_from_ms(self.bars[self.state['index']]['close_time_ms']),
            closed_candles_by_timeframe=visible,reason=reason,
            account=dict(equity=self.equity(self.bars[self.state['index']]['close']),position=copy.deepcopy(self.state['position'])),
            risk_cap=self.config['risk_cap'],notional_cap=self.config['notional_cap'],
            note='Mock answers in demo; no real model or market request')
        packet['request_sha256']=av.canonical_json_sha256(packet)
        f=self.path/'requests'/f'{rid}.json';av.write_new(f,packet)
        self.state['request_id']=rid;self.state['wait_reason']=reason
        self._commit('request',dict(request_id=rid,packet_file_sha256=av.digest(f)))

    def packet(self):
        self._reload();rid=self.state['request_id']
        return av.read(self.path/'requests'/f'{rid}.json') if rid else None

    def _validate_answer(self,d):
        av.canonical_json_bytes(d) # Reject non-standard JSON NaN/Infinity before any state change.
        jsonschema.Draft202012Validator(av.read(HERE/'answer_schema.json')).validate(d)
        av.normalize_cutoff_utc(d['created_at']) # Never infer a timezone for naive timestamps.
        packet=self.packet()
        if not packet or any(d[k]!=packet[k] for k in ('request_id','request_sha256')): raise ValueError('stale input binding')
        if self.state['paused']: raise ValueError('resume operator pause before importing')
        available=packet['closed_candles_by_timeframe']
        if any(d[k] not in available for k in ('analysis_timeframe','execution_timeframe')): raise ValueError('unavailable timeframe')
        ids={b['evidence_id'] for rows in available.values() for b in rows}
        if not d['references'] or not set(d['references']).issubset(ids): raise ValueError('unknown or future evidence reference')
        if len(d['references'])!=len(set(d['references'])):raise ValueError('duplicate evidence reference')
        if self.state['position'] and d['action']!='no_trade': raise ValueError('single position; existing protection cannot be replaced by this demo')
        p=d['plan'];action=d['action']
        if action=='no_trade':
            if p is not None or not d['no_trade_reason']:raise ValueError('no_trade requires reason and null plan')
        else:
            if not p or d['no_trade_reason'] is not None: raise ValueError('trade requires plan and null no_trade reason')
            if action=='short' and self.bundle['market']=='spot': raise ValueError('spot short forbidden')
            if not 0<p['risk_fraction']<=self.config['risk_cap']:raise ValueError('risk cap exceeded')
            s=1 if action=='long' else -1
            if p['entry_type']=='next_open':
                if p['entry_price'] is not None: raise ValueError('future open unknown; next_open price must be null')
                entry=self.bars[self.state['index']]['close']
            else:entry=p['entry_price']
            if entry is None or s*(entry-p['stop_loss'])<=0 or s*(p['take_profit']-entry)<=0:raise ValueError('invalid bracket')
            equity=packet['account']['equity'];fee=self.config['fee_bps']/10000;slip=self.config['slippage_bps']/10000
            loss=abs(entry-p['stop_loss']*(1-s*slip))+entry*fee+p['stop_loss']*(1-s*slip)*fee
            if p['quantity']*entry>equity*self.config['notional_cap'] or p['quantity']*loss>equity*p['risk_fraction']:
                raise ValueError('frozen quantity exceeds notional or cost-inclusive risk; no silent resizing')
        seen=set()
        for e in d['events']:
            if e['id'] in seen:raise ValueError('duplicate event id')
            seen.add(e['id'])
            if e['timeframe'] not in available:raise ValueError('event timeframe unavailable')

    def import_answer(self,source):
        """Preserve exact supplied bytes, including on schema/admission failure."""
        raw=Path(source).read_bytes()
        with self.lock():
            name=f"answer_{len(self.events):06d}.json";f=self.path/'imports'/name
            with f.open('xb') as out:out.write(raw)
            meta=dict(raw_file=name,raw_sha256=av.digest(f),received_at=now())
            try:d=json.loads(raw.decode('utf-8-sig'));self._validate_answer(d)
            except (ValueError,KeyError,TypeError,jsonschema.ValidationError) as error:
                meta['reason']=str(error).splitlines()[0];self._commit('rejected_import',meta)
                raise ValueError('requires_review: '+meta['reason']) from error
            cutoff=self.bars[self.state['index']]['close_time_ms'];interval=av.FIXED_INTERVAL_MS[d['execution_timeframe']]
            start=((cutoff+1+interval-1)//interval)*interval
            p=d['plan'];self.state['order']=None
            if p:
                self.state['order']=dict(plan=copy.deepcopy(p),sign=1 if d['action']=='long' else -1,
                    action=d['action'],start_ms=start,expires_ms=start+p['valid_bars']*interval-1,
                    decision_id=d['request_id'],execution_timeframe=d['execution_timeframe'])
            self.state['last_decision']=dict(index=self.state['index'],cutoff_ms=cutoff,start_ms=start,
                execution_timeframe=d['execution_timeframe'],events=copy.deepcopy(d['events']),action=d['action'])
            self.state['fired']=[];self.state['request_id']=None;self.state['wait_reason']=None
            meta.update(answer=d,decision_frozen_at=now());self._commit('decision',meta)
        return dict(status='accepted',raw_sha256=meta['raw_sha256'])

    def _hits(self,b):
        last=self.state['last_decision'];out=[]
        if not last:return out
        for e in last['events']:
            if e['id'] in self.state['fired']:continue
            interval=av.FIXED_INTERVAL_MS[e['timeframe']]
            if (b['close_time_ms']+1)%interval:continue
            if b['close_time_ms']>last['cutoff_ms']+e['valid_bars']*interval:continue
            if (b['close']>=e['price'] if e['operator']=='gte' else b['close']<=e['price']):out.append(e)
        return out

    def _before_orders(self,b):
        # A close event may have preceded an intrabar entry: choose cancellation, never a favorable fill.
        if self.state['order'] and any(e['classification']!='observation_only' for e in self._hits(b)):
            self.state['order']=None
            self._commit('cancel',dict(reason='mandatory_and_entry_ordering_unknown; cancel conservatively',bar_close=av.utc_iso_from_ms(b['close_time_ms'])))

    def _after_bar(self,b):
        for e in self._hits(b):
            self.state['fired'].append(e['id'])
            classification=e['classification'] or 'mandatory_reassessment'
            self._commit('market_event',dict(event=e,classification=classification,observed_at=av.utc_iso_from_ms(b['close_time_ms'])))
            if classification=='mandatory_reassessment':
                self.state['order']=None;self._request('mandatory_reassessment')
        last=self.state['last_decision']
        if not self.state['request_id'] and self.state['index']-last['index']>=self.config['decision_every']:
            self._request('scheduled_decision')
        return 'paused_for_decision' if self.state['request_id'] else 'advanced'

    def set_paused(self,paused):
        with self.lock():
            self.state['paused']=paused
            self._commit('operator_pause' if paused else 'operator_resume',dict(at=now()))

    def advance(self,max_bars=1):
        if type(max_bars)is not int or max_bars<1:raise ValueError('positive max_bars required')
        status='advanced'
        for _ in range(max_bars):
            status=self.step()
            if status!='advanced':break
        return dict(status=status,index=self.state['index'],position=bool(self.state['position']),awaiting_decision=bool(self.state['request_id']))

    def report(self):
        self._reload();bars=[e['data'] for e in self.events if e['kind']=='bar']
        trades=[dict(x,bar_close=b['close_time_UTC']) for b in bars for x in b['fills']]
        exits=[x for x in trades if x['kind']=='exit'];equities=[self.config['initial_cash']]+[b['equity'] for b in bars]
        peak=equities[0];drawdown=0
        for v in equities:peak=max(peak,v);drawdown=max(drawdown,(peak-v)/peak)
        gross=sum(t['gross_pnl'] for t in exits);net=sum(t['net_pnl'] for t in exits)
        return dict(scope='synthetic offline demonstration; not real AI or trading evidence',model_calls=0,network_calls=0,
            status='operator_paused' if self.state['paused'] else ('awaiting_decision' if self.state['request_id'] else 'ready'),
            cutoff=av.utc_iso_from_ms(self.bars[self.state['index']]['close_time_ms']),
            input_sha256=self.manifest['input_sha256'],journal_head_sha256=self.state['last_hash'],
            simulated_bars=len(bars),closed_trades=len(exits),trades=trades,equity_curve=bars,
            account_equity=self.equity(self.bars[self.state['index']]['close']),max_close_drawdown=drawdown,
            gross_closed_pnl=gross,net_closed_pnl=net,gross_points=sum(x['points'] for x in exits),
            costs=dict(fee_bps=self.config['fee_bps'],slippage_bps=self.config['slippage_bps'],funding_bps=self.config['funding_bps'],
                       double_cost_approximation=2*net-gross,note='Fixed fills/quantities approximation, not a rerun; synthetic assumptions'),
            market_events=[e['data'] for e in self.events if e['kind']=='market_event'],
            rejected_imports=sum(e['kind']=='rejected_import' for e in self.events),
            pending_order=copy.deepcopy(self.state['order']),position=copy.deepcopy(self.state['position']),
            limitations=['bar chronology uncertain: adverse stop first, favorable entry-bar exit deferred',
                'gap loss can exceed planned risk; no liquidity, liquidation or real funding model',
                'local hashes detect accidental changes, not hostile rewrite or file-system access',
                'operator pause halts ingestion; resume must replay all contiguous bars and frozen protection before new decisions'])
