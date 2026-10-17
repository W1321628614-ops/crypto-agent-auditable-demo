"""Invented prices and mock model answers. Not market data or live AI inference."""
import math
from .engine import now

def bundle():
    start=978307200000;interval=900000;rows=[] # 2001-01-01 UTC: arbitrary synthetic clock.
    for i in range(108):
        o=50+0.15*math.sin(i/4);c=50+0.15*math.sin((i+1)/4)
        rows.append(dict(open_time_ms=start+i*interval,close_time_ms=start+(i+1)*interval-1,
            open=round(o,5),high=round(max(o,c)+0.3,5),low=round(min(o,c)-0.3,5),close=round(c,5),volume=10.0))
    samples=[(50,50.8,49.2,50.4),(50.4,51.2,50,51),(51,51.3,47,48)]
    for i,(o,h,l,c) in enumerate(samples,96):
        rows[i].update(open=o,high=h,low=l,close=c)
    return dict(symbol='DEMOUSD',market='usd_m_perpetual',base_timeframe='15m',data_status='synthetic_fixture',
        provenance='Entirely invented numbers; no account, exchange, private strategy or external data',candles=rows)

def mock_answer(packet,action='long'):
    return dict(request_id=packet['request_id'],request_sha256=packet['request_sha256'],
        source='synthetic_model_output',model_label='mock_fixture_not_AI_inference',created_at=now(),
        structure='Illustrative fabricated range, not an investment assessment',direction='bullish' if action=='long' else 'unclear',
        action=action,analysis_timeframe='4h',execution_timeframe='15m',
        references=[packet['closed_candles_by_timeframe']['15m'][-1]['evidence_id']],
        plan=(dict(entry_type='limit',entry_price=50.0,quantity=2.0,stop_loss=48.0,take_profit=54.0,
            valid_bars=4,risk_fraction=0.01) if action=='long' else None),
        no_trade_reason='Synthetic no_trade example' if action=='no_trade' else None,
        events=([dict(id='illustrative_observation',classification='observation_only',operator='gte',price=50.2,
            timeframe='15m',valid_bars=8,reason='Demonstrate a deduplicated local observation'),
            dict(id='illustrative_mandatory',classification='mandatory_reassessment',operator='gte',price=51.0,
            timeframe='15m',valid_bars=8,reason='Demonstrate waiting for review while protective stop remains active')]
            if action=='long' else []))
