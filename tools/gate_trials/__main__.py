"""python3 -m tools.gate_trials prepare KIND ... | read --pr N [--repo OWNER/REPO]."""
import argparse
import json
from pathlib import Path
import sys

from . import APP_ID, KINDS
from .build import TrialError, script
from .read import MAX_BYTES, collect, evaluate, render


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args)>=2 and args[0] == 'prepare' and args[1] in KINDS:
        return script(args[1], args[2:])
    parser = argparse.ArgumentParser(description='Expectrail hosted trials: local preparation and public GET only.')
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', help='build local trial refs; prints push commands only')
    prepare.add_argument('trial', choices=KINDS)
    read = sub.add_parser('read', help='read public checks and the bound bot comment; no token')
    read.add_argument('--pr', type=int, required=True)
    read.add_argument('--repo', default='Expectrail/Expectrail')
    read.add_argument('--head', help='full historical head ID; never used as current-head trial proof')
    read.add_argument('--app-id', type=int, default=APP_ID, help='expected dedicated publisher App ID')
    read.add_argument('--fixture', type=Path, help='saved public API snapshot; never calls the network')
    read.add_argument('--json', action='store_true')
    options = parser.parse_args(args)
    try:
        if options.fixture:
            data = options.fixture.read_bytes()
            if len(data)>MAX_BYTES:
                raise TrialError('saved fixture exceeds 8 MiB')
            snapshot = json.loads(data)
            if snapshot['pull']['number'] != options.pr or snapshot['repository'] != options.repo:
                raise TrialError('fixture is for a different repository or PR')
            if options.head:
                snapshot['selectedHead'] = options.head
        else:
            snapshot = collect(options.repo, options.pr, head=options.head)
        result = evaluate(snapshot, app_id=options.app_id)
    except (AttributeError, IndexError, OSError, KeyError, TypeError, ValueError) as exc:
        result = dict(result='FAIL', trial='unmatched', reason=str(exc), evidence=[])
    print(json.dumps(result, indent=2) if options.json else render(result))
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
