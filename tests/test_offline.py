"""Deterministic engineering checks. All prices and decisions are synthetic."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from auditable_research.engine import Engine,DEFAULT,validate_bundle
from auditable_research.fixtures import bundle,mock_answer
from auditable_research.cli import demo
from auditable_research.provenance import read,write_new,normalize_cutoff_utc,MarketDataIntegrityError

class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.n=0
    def tearDown(self):self.tmp.cleanup()
    def engine(self,change=None,config=None):
        b=bundle()
        if change:change(b)
        self.n+=1
        return Engine.create(self.base/f'run{self.n}',b,config)
    def answer(self,e,mutate=None):
        d=mock_answer(e.packet());d['events']=[]
        if mutate:mutate(d)
        f=self.base/f'answer{self.n}_{len(e.events)}.json'
        f.write_bytes(json.dumps(d,indent=3).encode());return f
    def put(self,e,mutate=None):e.import_answer(self.answer(e,mutate))
    def future(self,b,i=96,o=50,h=51,l=49,c=50):b['candles'][i].update(open=o,high=h,low=l,close=c)

    def test_valid_synthetic_bundle(self):self.assertEqual(len(validate_bundle(bundle())),108)
    def test_real_data_rejected(self):
        b=bundle();b['data_status']='real_history'
        with self.assertRaises(ValueError):validate_bundle(b)
    def test_gap_rejected(self):
        b=bundle();b['candles'].pop(4)
        with self.assertRaises(MarketDataIntegrityError):validate_bundle(b)
    def test_duplicate_rejected(self):
        b=bundle();b['candles'][4]=copy.deepcopy(b['candles'][3])
        with self.assertRaises(MarketDataIntegrityError):validate_bundle(b)
    def test_invalid_ohlc_rejected(self):
        b=bundle();b['candles'][2]['low']=100
        with self.assertRaises(MarketDataIntegrityError):validate_bundle(b)
    def test_nan_rejected(self):
        b=bundle();b['candles'][2]['high']=float('nan')
        with self.assertRaises(ValueError):validate_bundle(b)
    def test_naive_timestamp_rejected(self):
        with self.assertRaises(MarketDataIntegrityError):normalize_cutoff_utc('2001-01-01T00:00:00')
    def test_utc_offset_normalized(self):
        self.assertEqual(normalize_cutoff_utc('2001-01-01T08:00:00+08:00')[0],'2001-01-01T00:00:00.000Z')
    def test_partial_higher_candle_excluded(self):
        e=self.engine(config={'warmup':97});p=e.packet()
        cutoff=e.bars[96]['close_time_ms']
        self.assertEqual(len(p['closed_candles_by_timeframe']['1d']),1)
        self.assertEqual(len(p['closed_candles_by_timeframe']['1h']),24)
        self.assertTrue(all(b['close_time_ms']<=cutoff for rows in p['closed_candles_by_timeframe'].values() for b in rows))
    def test_future_tail_cannot_change_packet(self):
        a=self.engine();b=self.engine(lambda x:self.future(x,o=100,h=105,l=99,c=104))
        self.assertEqual(a.packet(),b.packet())
    def test_freeze_preserves_original_bytes(self):
        e=self.engine();f=self.answer(e);raw=f.read_bytes();e.import_answer(f)
        self.assertEqual(next((e.path/'imports').iterdir()).read_bytes(),raw)
        self.assertEqual(e.events[-1]['kind'],'decision')
    def test_future_reference_rejected_and_preserved(self):
        e=self.engine();f=self.answer(e,lambda d:d.update(references=['15m:future']))
        with self.assertRaisesRegex(ValueError,'requires_review'):e.import_answer(f)
        self.assertEqual(e.report()['rejected_imports'],1);self.assertTrue(e.state['request_id'])
    def test_stale_binding_rejected(self):
        e=self.engine()
        with self.assertRaises(ValueError):self.put(e,lambda d:d.update(request_sha256='0'*64))
    def test_natural_language_entry_rejected(self):
        e=self.engine()
        with self.assertRaises(ValueError):self.put(e,lambda d:d['plan'].update(entry_price='when it looks strong'))
    def test_nonfinite_answer_rejected_and_archived(self):
        e=self.engine()
        with self.assertRaisesRegex(ValueError,'requires_review'):self.put(e,lambda d:d['plan'].update(quantity=float('nan')))
        self.assertEqual(e.report()['rejected_imports'],1);self.assertIsNone(e.state['order'])
    def test_risk_budget_rejected_without_resizing(self):
        e=self.engine()
        with self.assertRaisesRegex(ValueError,'quantity exceeds'):self.put(e,lambda d:d['plan'].update(quantity=100))
        self.assertIsNone(e.state['order'])
    def test_risk_fraction_above_cap_rejected(self):
        e=self.engine()
        with self.assertRaisesRegex(ValueError,'risk cap'):self.put(e,lambda d:d['plan'].update(risk_fraction=0.03))
    def test_long_limit_price_not_worse_than_limit(self):
        e=self.engine(lambda b:self.future(b));self.put(e);e.advance()
        self.assertLessEqual(e.state['position']['entry_price'],50)
    def test_short_limit_price_not_worse_than_limit(self):
        e=self.engine(lambda b:self.future(b))
        def short(d):d.update(action='short');d['plan'].update(stop_loss=52,take_profit=46)
        self.put(e,short);e.advance();self.assertGreaterEqual(e.state['position']['entry_price'],50)
    def test_unfilled_limit_expires(self):
        e=self.engine()
        self.put(e,lambda d:d['plan'].update(entry_price=45,stop_loss=43,take_profit=48,valid_bars=1))
        e.advance(2);self.assertIsNone(e.state['order']);self.assertFalse(e.report()['trades'])
        self.assertTrue(any(x['kind']=='order_expired' for x in e.events))
    def test_actual_gap_risk_blocks_without_resizing(self):
        e=self.engine(lambda b:self.future(b,o=53,h=54,l=52.5,c=53.5))
        self.put(e,lambda d:d['plan'].update(entry_type='stop',entry_price=50.5,take_profit=55))
        e.advance();self.assertFalse(e.report()['trades']);self.assertIsNone(e.state['order'])
        self.assertTrue(any(x['kind']=='entry_blocked' for x in e.events))
    def test_long_stop_gap_execution(self):
        e=self.engine(lambda b:self.future(b,o=51,h=52,l=50.5,c=51.5))
        self.put(e,lambda d:d['plan'].update(entry_type='stop',entry_price=50.5,take_profit=55))
        e.advance();self.assertGreaterEqual(e.state['position']['entry_price'],51)
    def test_long_target_next_open(self):
        e=self.engine(lambda b:self.future(b,h=55,l=49,c=54))
        self.put(e,lambda d:d['plan'].update(entry_type='next_open',entry_price=None));e.advance()
        self.assertEqual(e.report()['trades'][-1]['reason'],'target')
    def test_long_stop(self):
        e=self.engine(lambda b:self.future(b,h=51,l=47,c=48))
        self.put(e);e.advance();self.assertEqual(e.report()['trades'][-1]['reason'],'stop')
    def test_short_target(self):
        e=self.engine(lambda b:self.future(b,h=51,l=45,c=46))
        def short(d):d.update(action='short');d['plan'].update(entry_type='next_open',entry_price=None,stop_loss=52,take_profit=46)
        self.put(e,short);e.advance();self.assertEqual(e.report()['trades'][-1]['reason'],'target')
    def test_short_stop(self):
        e=self.engine(lambda b:self.future(b,h=53,l=49,c=52))
        def short(d):d.update(action='short');d['plan'].update(stop_loss=52,take_profit=46)
        self.put(e,short);e.advance();self.assertEqual(e.report()['trades'][-1]['reason'],'stop')
    def test_both_brackets_adverse_first(self):
        e=self.engine(lambda b:self.future(b,h=55,l=47,c=50))
        self.put(e);e.advance();r=e.report();self.assertEqual(r['trades'][-1]['reason'],'stop')
        self.assertTrue(r['equity_curve'][0]['uncertainties'])
    def test_ambiguous_entry_target_deferred(self):
        e=self.engine(lambda b:self.future(b,o=51,h=55,l=49,c=52))
        self.put(e);e.advance();self.assertIsNotNone(e.state['position'])
        self.assertTrue(e.report()['equity_curve'][0]['uncertainties'])
    def test_costs_reduce_net(self):
        e=self.engine(lambda b:self.future(b,h=55,l=49,c=54))
        self.put(e,lambda d:d['plan'].update(entry_type='next_open',entry_price=None));e.advance();r=e.report()
        self.assertLess(r['net_closed_pnl'],r['gross_closed_pnl'])
        self.assertAlmostEqual(r['account_equity']-1000,r['net_closed_pnl'])
    def test_spot_short_rejected(self):
        e=self.engine(lambda b:b.update(market='spot'))
        def short(d):d.update(action='short');d['plan'].update(stop_loss=52,take_profit=46)
        with self.assertRaisesRegex(ValueError,'spot short'):self.put(e,short)
    def test_no_trade_is_valid(self):
        e=self.engine();d=mock_answer(e.packet(),'no_trade');f=self.base/'flat.json';write_new(f,d);e.import_answer(f)
        e.advance(2);self.assertFalse(e.report()['trades'])
    def test_pause_and_restart_resume(self):
        e=self.engine();self.put(e);e.set_paused(True);i=e.state['index']
        self.assertEqual(Engine(e.path).advance()['status'],'paused_by_user')
        e=Engine(e.path);self.assertEqual(e.state['index'],i);e.set_paused(False);e.advance();self.assertEqual(e.state['index'],i+1)
    def test_mandatory_waiting_preserves_protection(self):
        e=self.engine();f=self.base/'events.json';write_new(f,mock_answer(e.packet()));e.import_answer(f)
        e.advance(4);self.assertTrue(e.state['request_id']);self.assertIsNotNone(e.state['position'])
        self.assertEqual(e.state['wait_reason'],'mandatory_reassessment')
        e.advance();self.assertIsNone(e.state['position']);self.assertEqual(e.report()['trades'][-1]['reason'],'stop')
        self.assertEqual(len(e.report()['market_events']),2)
    def test_unknown_event_class_defaults_mandatory(self):
        e=self.engine();d=mock_answer(e.packet(),'no_trade');d['events']=[dict(id='unknown',classification=None,operator='gte',price=1,timeframe='15m',valid_bars=2,reason='unclassified')]
        f=self.base/'unknown.json';write_new(f,d);e.import_answer(f);e.advance()
        self.assertEqual(e.state['wait_reason'],'mandatory_reassessment')
    def test_mandatory_entry_same_bar_cancelled(self):
        e=self.engine();d=mock_answer(e.packet());d['events'][1]['price']=50.2
        f=self.base/'cancel.json';write_new(f,d);e.import_answer(f);e.advance()
        self.assertFalse(e.report()['trades']);self.assertIsNone(e.state['order'])
    def test_input_tampering_stops(self):
        e=self.engine();p=e.path/'input.json';p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'input hash'):Engine(e.path)
    def test_journal_tampering_stops(self):
        e=self.engine();p=next((e.path/'journal').iterdir());d=read(p);d['data']['request_id']='other';p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'content hash'):Engine(e.path)
    def test_request_tampering_stops(self):
        e=self.engine();p=next((e.path/'requests').iterdir());p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'request hash'):Engine(e.path)
    def test_import_tampering_stops(self):
        e=self.engine();self.put(e);p=next((e.path/'imports').iterdir());p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'raw imported'):Engine(e.path)
    def test_lock_conflict_fails_closed(self):
        e=self.engine();(e.path/'run.lock').write_text('test')
        with self.assertRaises(FileExistsError):e.advance()
    def test_complete_demo_without_model_or_network(self):
        result=demo(self.base/'demo');r=read(self.base/'demo/report.json')
        self.assertEqual(result['model_calls'],0);self.assertEqual(result['network_calls'],0)
        self.assertEqual(r['closed_trades'],1);self.assertTrue(r['demo_checkpoints']['restart_verified'])
    def test_cli_subprocess_restart(self):
        e=self.engine();self.put(e)
        p=subprocess.run([sys.executable,'-B','-m','auditable_research','status','--run-dir',str(e.path)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['status'],'ready')

if __name__=='__main__':unittest.main()
