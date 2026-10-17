"""Unified offline CLI. No network, model SDK, credentials or exchange trading client."""
import argparse,json,sys
from pathlib import Path
from .engine import Engine
from .fixtures import bundle,mock_answer
from .provenance import read,write_new

def demo(path):
    e=Engine.create(path,bundle());packet=e.packet()
    write_new(Path(path)/'mock_answer.json',mock_answer(packet))
    e.import_answer(Path(path)/'mock_answer.json')
    first=e.advance(8) # Stops at the mock mandatory event; not an actual model request.
    e.set_paused(True)
    e=Engine(path) # Process-independent recovery reads and verifies the journal.
    e.set_paused(False)
    protection=e.advance(1) # Existing protection continues while awaiting a decision.
    packet=e.packet();write_new(Path(path)/'mock_no_trade.json',mock_answer(packet,'no_trade'))
    e.import_answer(Path(path)/'mock_no_trade.json');e.advance(32)
    report=e.report();report['demo_checkpoints']=dict(first_pause=first,protection_while_waiting=protection,restart_verified=True)
    write_new(Path(path)/'report.json',report)
    return dict(status='offline_demo_complete',report='report.json',closed_trades=report['closed_trades'],
        model_calls=0,network_calls=0,note='Synthetic fixture and mock answers; not AI performance')

def main(argv=None):
    ap=argparse.ArgumentParser(description='Auditable Supervised AI Research & Paper-Trading System — offline showcase')
    ap.add_argument('command',choices=['demo','start','packet','import','advance','pause','resume','status','report'])
    ap.add_argument('--run-dir',required=True);ap.add_argument('--answer');ap.add_argument('--config');ap.add_argument('--bars',type=int,default=1)
    args=ap.parse_args(argv)
    try:
        if args.command=='demo':result=demo(args.run_dir)
        elif args.command=='start':
            e=Engine.create(args.run_dir,bundle(),read(args.config) if args.config else None)
            result=dict(status='awaiting_external_answer',packet=e.packet())
        else:
            e=Engine(args.run_dir)
            if args.command=='import':
                if not args.answer:raise ValueError('--answer required')
                result=e.import_answer(args.answer)
            elif args.command=='advance':result=e.advance(args.bars)
            elif args.command in ('pause','resume'):
                e.set_paused(args.command=='pause');result=dict(status=args.command)
            elif args.command=='packet':result=e.packet()
            else:result=e.report()
        print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2));return 0
    except (ValueError,KeyError,OSError,TypeError) as error:
        print(json.dumps(dict(status='safe_stop',error=str(error)),ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
