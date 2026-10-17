"""Generic limit/stop/next-open matching and cost arithmetic, adapted from a tested broker.
Synthetic, collateral-limited simulation only. No liquidation, live orders or real funding feed.
"""
from . import provenance as av
from .provenance import FIXED_INTERVAL_MS as MS
TFS=('15m','1h','4h','1d')
def aggregate(bars, base_tf):
    streams = {}
    for tf in TFS:
        if MS[tf] < MS[base_tf]:
            continue
        groups = {}
        for b in bars:
            start = b['open_time_ms'] // MS[tf] * MS[tf]
            groups.setdefault(start, []).append(b)
        out = []
        for start, rows in sorted(groups.items()):
            if len(rows) != MS[tf] // MS[base_tf] or rows[0]['open_time_ms'] != start or rows[-1]['close_time_ms'] != start + MS[tf] - 1:
                continue  # Partial high-timeframe candles never become confirmed data.
            out.append(dict(open_time_ms=start, close_time_ms=start+MS[tf]-1,
                open=rows[0]['open'], high=max(r['high'] for r in rows),
                low=min(r['low'] for r in rows), close=rows[-1]['close'],
                volume=sum(r['volume'] for r in rows)))
        streams[tf] = out
    return streams

class Matching:
    def equity(self,price):
        p=self.state['position']
        return self.state['cash']+(p['margin']+p['sign']*p['qty']*(price-p['entry_price']) if p else 0)
    def step(self):
        with self.lock():
            if self.state['paused']: return 'paused_by_user'
            if self.state['request_id'] and not self.state['position']: return 'paused_for_decision'
            # Waiting blocks new orders, but frozen protective brackets still execute.
            if self.state['request_id'] and self.state['order']: raise ValueError('unsafe pending order while waiting')
            i=self.state['index']+1
            if i>=len(self.bars): return 'complete'
            b=self.bars[i];fills=[];uncertain=[]; funding=0
            slip=self.config['slippage_bps']/10000;fee=self.config['fee_bps']/10000
            last=self.state['last_decision']; interval=MS[last['execution_timeframe']]
            def exit(base,reason):
                p=self.state['position'];price=base*(1-p['sign']*slip);cost=p['qty']*price*fee
                gross=p['sign']*p['qty']*(base-p['entry_base'])
                self.state['cash']+=p['margin']+p['sign']*p['qty']*(price-p['entry_price'])-cost
                fills.append(dict(kind='exit',side='sell' if p['sign']==1 else 'buy',action=p['action'],price=price,qty=p['qty'],fee=cost,reason=reason,
                    points=p['sign']*(base-p['entry_base']),gross_pnl=gross,
                    net_pnl=p['sign']*p['qty']*(price-p['entry_price'])-cost-p['entry_fee']-p['funding_cost'],
                    slippage_cost=p['qty']*abs(price-base),entry_decision=p['decision_id'],execution_timeframe=p['execution_timeframe']))
                self.state['position']=None
            p=self.state['position']
            if p and self.bundle['market']=='usd_m_perpetual' and b['open_time_ms']%(8*MS['1h'])==0:
                funding=p['sign']*p['qty']*b['open']*self.config['funding_bps']/10000
                self.state['cash']-=funding;p['funding_cost']+=funding
            if self.state['close_position'] and b['open_time_ms']>=last['start_ms'] and self.state['position']:
                exit(b['open'],'frozen_close_next_execution_open');self.state['close_position']=False
            self._before_orders(b)
            order=self.state['order']
            if order:
                p=order['plan']; s=order['sign']
                if b['open_time_ms']>order['expires_ms']:
                    self.state['order']=None
                    self._commit('order_expired',dict(decision_id=order['decision_id'],at=av.utc_iso_from_ms(b['open_time_ms'])))
                elif b['open_time_ms']>=order['start_ms'] and (p['entry_type']=='next_open' or ((b['low']<=p['entry_price'] if s==1 else b['high']>=p['entry_price']) if p['entry_type']=='limit' else (b['high']>=p['entry_price'] if s==1 else b['low']<=p['entry_price']))):
                    base=b['open'] if p['entry_type']=='next_open' else ((min(b['open'],p['entry_price']) if s==1 else max(b['open'],p['entry_price'])) if p['entry_type']=='limit' else (max(b['open'],p['entry_price']) if s==1 else min(b['open'],p['entry_price'])))
                    price=base*(1+s*slip)
                    if p['entry_type']=='limit':
                        price=min(price,p['entry_price']) if s==1 else max(price,p['entry_price'])
                    if s*(price-p['stop_loss'])<=0 or s*(p['take_profit']-price)<=0:
                        uncertain.append('gap/slippage invalidated bracket; entry skipped')
                    else:
                        equity=self.equity(b['open'])
                        risk_unit=abs(price-p['stop_loss']*(1-s*slip))+price*fee+p['stop_loss']*(1-s*slip)*fee
                        qty=p['quantity']
                        if qty*price*(1+fee)>self.state['cash'] or qty*price>equity*self.config['notional_cap'] or qty*risk_unit>equity*p['risk_fraction']:
                            self.state['order']=None
                            self._commit('entry_blocked',dict(reason='frozen_quantity_exceeds_actual_fill_risk_or_collateral'))
                            self.state['index']=i
                            self._commit('bar',dict(index=i,close_time_UTC=av.utc_iso_from_ms(b['close_time_ms']),fills=[],uncertainties=['entry blocked by actual-fill risk'],equity=self.equity(b['close']),funding_cost=0,exposure=0))
                            return self._after_bar(b)
                        margin=qty*price;cost=margin*fee;self.state['cash']-=margin+cost
                        self.state['position']=dict(sign=s,action=order['action'],qty=qty,margin=margin,entry_price=price,entry_base=base,entry_fee=cost,
                            stop=p['stop_loss'],target=p['take_profit'],entry_bar=i,decision_id=order['decision_id'],execution_timeframe=order['execution_timeframe'],funding_cost=0,
                            planned_risk=qty*risk_unit,risk_budget=equity*p['risk_fraction'])
                        fills.append(dict(kind='entry',side='buy' if s==1 else 'sell',action=order['action'],price=price,qty=qty,fee=cost,slippage_cost=qty*abs(price-base),
                            planned_risk=qty*risk_unit,risk_budget=equity*p['risk_fraction'],execution_timeframe=order['execution_timeframe']))
                    self.state['order']=None
            p=self.state['position']
            if p:
                s=p['sign'];stop=p['stop'];target=p['target'];new=p['entry_bar']==i
                sh=b['low']<=stop if s==1 else b['high']>=stop
                th=b['high']>=target if s==1 else b['low']<=target
                if not new and s*(b['open']-stop)<=0: exit(b['open'],'gap_stop')
                elif not new and s*(b['open']-target)>=0: exit(target,'gap_target_conservative')
                elif sh:
                    if th: uncertain.append('both brackets touched; adverse stop-first')
                    if new: uncertain.append('entry-bar adverse extreme may precede entry; conservative stop after entry')
                    exit(stop,'stop')
                elif th:
                    if new and p['entry_price']!=b['open']*(1+s*slip):
                        uncertain.append('entry-bar target chronology unknown; defer favorable exit')
                    else: exit(target,'target')
            self.state['index']=i
            self._commit('bar',dict(index=i,close_time_UTC=av.utc_iso_from_ms(b['close_time_ms']),fills=fills,uncertainties=uncertain,
                equity=self.equity(b['close']),funding_cost=funding,exposure=self.state['position']['qty']*b['close'] if self.state['position'] else 0))
            return self._after_bar(b)
