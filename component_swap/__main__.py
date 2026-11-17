import argparse,json,sys
from .core import build,verify,Invalid

def main():
    parser=argparse.ArgumentParser(description='Review declared component replacement constraints offline; never deploy.')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan');p.add_argument('inventory');p.add_argument('replacements');p.add_argument('--out',required=True)
    p=sub.add_parser('verify');p.add_argument('bundle')
    args=parser.parse_args()
    try:
        if args.command=='verify':result=verify(args.bundle)
        else:
            report=build(args.inventory,args.replacements,args.out)
            result={k:report[k] for k in ('baseline_status','proposed_status','changed_components','affected_components','manual_review_required')}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (Invalid,OSError,TypeError,ValueError,RecursionError):
        print('Error: input, output or bundle failed validation; private values are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
