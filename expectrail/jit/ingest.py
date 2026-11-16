"""Map snapshotted intake builds to the existing candidate-withheld JIT pipeline.

Only the existing untrustedBugReport path carries report prose. A supplied model
response is a stand-in transport. Live transport requires the existing explicit
spec-role spend cap before it is even constructed.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

from expectrail import project_job
from expectrail.contracts import digest_v1
from expectrail.jit import intent, run
from expectrail.orchestrator import request, reproduction

NO_CHANGE = '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-unchanged\n+unchanged\n'


def generate(doc, out, *, runner=None):
    out = Path(out);out.mkdir(parents=True, exist_ok=True)
    root = Path(doc['base']['checkout'])
    config = doc['propose']
    clean = root/config['clean'];bug = root/doc['project']['game']
    # Snapshot descriptors choose two already captured game trees. They are not
    # seed patches to apply to either tree. Both hashes are retained in the record.
    trees = {'clean': request.tree_digest(clean, root), 'base': request.tree_digest(bug, root)}
    base_marker = out/'jit-base-snapshot.json'
    base_marker.write_text(json.dumps(trees, sort_keys=True)+'\n')
    unchanged = out/'jit-no-change.patch';unchanged.write_text(NO_CHANGE)
    route_name = doc['coverage']['routes'][0]
    checks = request.read_checks(doc)
    route = next(json.loads(data) for name, data, _sha in checks.routes if name == route_name)
    response = None
    if config.get('response'):
        response = json.loads(project_job.regular(root, config['response'], 1024*1024).decode('utf-8'))
    model = intent.spark_intent(transport=lambda _body: response, candidate=intent.WITHHELD,
                                model='stand-in-recorded-response') if response is not None else None
    if response is None:
        from expectrail import spend
        try:
            spend.require_cap('spec')
        except spend.BudgetStop:
            pass  # No budget: existing JIT records MODEL_UNAVAILABLE without sending.
        else:
            model = intent.spark_intent(candidate=intent.WITHHELD)

    def replay(route_path, folder, patches=()):
        if runner is not None:
            return runner(route_path, folder, patches=patches)
        from harness.run import run as harness_run
        if any(Path(p) not in (base_marker, unchanged) for p in patches):
            raise ValueError('intake runner refuses an unbound snapshot selector')
        game = bug if base_marker in patches else clean
        return harness_run(route_path, folder, game=game, capture_frames=False, within=root,
                           sandbox='require' if doc['executionClass'] == 'isolated' else None)

    result = run.generate(root/config['profile'], doc['bug'], unchanged, [base_marker], out,
                          runner=replay, intent=model, variants_fn=lambda *_args: [],
                          candidate_to_model=intent.WITHHELD, report_route=route,
                          budget_usd=run.DEFAULT_BUDGET_USD)
    kept = run.from_base_alone(result)['fromBaseAlone']
    kind = 'generated-advisory' if kept else 'none'
    reason = 'generated-advisory-reproduced' if kept else (result['reason'] or 'not-reproduced')
    return reproduction.write(out, reproduction.build(kind, kept, reason, base_tree=trees['base'],
                              clean_tree=trees['clean'], jit_sha=digest_v1(result)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    doc = request.load(Path(argv[0]))
    generate(doc, Path(argv[1]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
