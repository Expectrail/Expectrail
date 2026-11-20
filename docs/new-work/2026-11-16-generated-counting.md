# Six rules for generated checks that count (#271)

## What changed

The shared decision rule accepts authenticated counting evidence separately from legacy
advisory summaries. All six rules are recomputed by the JIT assessor; base/clean/candidate
triples are checked again by the gate. Relevance uses named report behaviour OR a trusted assessor-only diff map; the candidate-withheld proposer still receives neither candidate text nor that map. Generated-only fix clearance requires base-only
reproduction. Existing failures, coverage, isolation and observer vetoes still hold.
The source certificate uses the existing receipt signature/trust-store reader; model input
and game-build bindings are checked. Readers require an independently authenticated witness.
A scoped publisher context lets existing readers use it without an environment switch.

Contracts, examples, generator metadata, counting writers/readers and receipt binding are
in this patch. Promotion remains a person's act. The ordinary gate/verifier files and
current workflows are unchanged. See [the rules and remaining deployment steps](../jit.md#generated-checks-that-count-271).

Two manual, capped public pressure commands and a workflow proposal are prepared. Correct
pressure covers 24 public exact undos plus four known correct patches, three replays per
check. A single correct-fix failure blocks release. The one-public-bug adversary uses the
existing bounded llm-patch sender and an independently calibrated oracle. Both default to
plan only; neither was dispatched or run with a live model.

Guard: test change intended (#271)

The old AST assertion that decide never mentions generated data is superseded by the new
feature. Its replacement refuses raw generated JSON; existing behavioural assertions that
legacy advisory data cannot affect decisions are retained. The golden JIT example is
regenerated with the added provenance/coverage fields; its equality assertion is unchanged.

## What was run

- Assigned branch fast-forwarded to latest main (already current): `21fde1b4be9362d209852e3d44221d059d110643`.
- Required historic fetch succeeded once.
- Full before, no EXPECTRAIL variables: 4,654 tests, 471.092s, OK (60 skipped), exit 0.
- Initial red: eight new rule tests error on unchanged main because counting was absent.
- Focused rules, gate, pipeline, withheld and schema checks: 142 tests, 13.229s, OK (before the final publisher-scope addition; final full suite will cover that too).
- Offline public audit: 24 recorded public defects, 137 checks, 0 counting, 137 advisory. No replay or model call. [Counts and source digests](../measurements/271-public-counting.md).
- Pressure unit rehearsals: two correct air-jump candidates, three results each (12 probe replays), and a synthetic overfitter detected with 15 replays and one stand-in fixer callback. No real campaign result is claimed.
- Final focused run: 157 tests, 14.694s, OK. With numpy and PIL imports/find_spec blocked: 44 tests, 5.762s, OK.
- Full final after, no EXPECTRAIL variables: 4671 tests, 487.037s, OK (60 skipped), exit 0. Product/schema hashes stayed unchanged during this run.
- Export scan and clean binary patch application were checked during packaging; exact outputs accompany the zip. Opaque blind/fresh folder entries were held aside unopened for the public scan, then restored.
- A later completed full run had one unchanged worker-timing failure: `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once` took 0.558s against a 0.5s assertion. Its isolated rerun passed unchanged; the full-suite retry is recorded separately. No timing assertion was changed.
- One completed intermediate full after run failed three unchanged architecture guards: `tests.test_repro_evidence.HeldBack.test_only_the_offer_reads_the_evidence_and_only_under_its_own_setting`, `tests.test_repro_reach.NotOfferedToTheGeneratorYet.test_nothing_under_jit_but_the_offer_reads_the_reach_module`, `tests.test_repro_screen.HeldBack.test_nothing_generated_checks_run_on_reads_the_screen_measurement`. Fixed by reading only the public registry as bounded contract data; none of these assertions changed. Interrupted runs and fixture errors are retained and not counted as successful full runs.

## Not done

No live model call, spend, dispatch, push or GitHub write. No workflow, approval, game source,
protected verifier/observations/onboarding code, capability ledger, release files or README edit.
No blind/fresh/private content opened. Current production CI stays advisory until Sean wires
its trusted producer/publisher. The live main pressure campaigns and #282 counting primary
arm are still missing. The proposed adversary holds at most $6 for one invocation; correct
pressure and vision have $0 API cost. Fresh frozen-check generation is a separate prerequisite.

## Files

- `expectrail/gate/record.py`; `expectrail/jit/assess.py`, `run.py`, `counting.py`, `pressure.py`, `bench.py` (bounded public registry data only).
- `contracts/findings.schema.json`, `jit-run.v1.schema.json`, `generated-counting.v1.schema.json`, `generated-counting-context.v1.schema.json`, `jit-pressure.v1.schema.json`, and their examples.
- `tests/test_jit_rules.py`; `docs/jit.md`; `docs/measurements/271-public-counting.md`; `docs/proposals/271-pressure.yml.txt`; this log.
