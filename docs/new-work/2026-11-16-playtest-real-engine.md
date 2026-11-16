# A real-engine playtest reproduction a reviewer can open (#531)

## What changed

Applied the local round-three repair patch on current main (rounds one/two are
already merged). Added a handwritten public fall-through report and a source
proof command that ingests it with real Godot, using the existing bundled-game
engine-only collision/position observer. It retains the report, precheck proof,
traces, original manifests, selected real PNGs and an HTML index. No replay,
evaluator, keep rule, check or approval is replaced.

Registered three real tests in `tests.test_replay_sandbox`, already invoked by
CI's `seeded-bugs` job with `EXPECTRAIL_SANDBOX_TESTS=required`. They assert anchor
coverage first, approved ground failure on three base runs, reproduction kind,
and zero model/fixer boundaries; the controls assert not-reproduced and
anchor-desync. The required lane always requires Bubblewrap. Ordinary runs skip
these tests by name; an explicit local diagnostic opt-in records no isolation.
The existing `run-it-offline` upload includes their output below `runs/run-it`.
No workflow was edited.

Added `docs/playtest.md` with report/outcome/flag/cost explanations and explicit
limits. Added implemented, offline-tested ledger rows for ingest, generated
advisory reproduction and opt-in repair, with no live-model measurement claim.
The ledger page is generated through the existing renderer.

## What was run

Before edits, all EXPECTRAIL_* variables removed:
`python3 -m unittest discover -s tests -t .`: 4,237 tests in 380.870 seconds,
49 skipped, one error in
`tests.test_ingest_generated.GeneratedIngest.test_model_cannot_claim_kept_or_write_an_approval`
(JSONDecodeError parsing the CLI output). It passed in isolation without a code
change, then in the 40-test focused run (18.684 seconds). The baseline log is
retained; no test was weakened to hide it.

A real calibration replay on Godot 4.7.2 recorded player world position
(90, 636.646) at tick 0 and the body below the approved ground tolerance at tick
16. The report's route, words, fault tick and anchor were written by hand from
that trace. The report target is rebound only to each disposable project's actual
Git HEAD.

Initial proof attempts: a constructor guard replaced a class and broke an
isinstance call; corrected the guard to patch its constructor. The configured
role capture then ended inconclusive, not reproduced: the declared 800x480
viewport did not match 1600x960 captured pixels, leaving no visible player role
observations. Those attempt logs are retained. The successful diagnostic uses
the shipped bundled-game position/collision observer (`project=None`), not the
configured drawing-role observer. No protected verifier file was changed.

Real engine:
`EXPECTRAIL_PLAYTEST_DIAGNOSTIC=1 EXPECTRAIL_PLAYTEST_EVIDENCE=...
python3 -m unittest tests.test_replay_sandbox.PlaytestIngestRealEngineTest -v`:
three tests passed in 302.402 seconds, using 11 real Godot replays. The base anchor
passed three times, the approved ground check failed three times, kind was
`approved`; the clean control passed three checks and ended not-reproduced, and
the anchor moved one pixel beyond tolerance ended anchor-desync before a check.
All model/fixer constructor and sending counters were zero. The engine version
was 4.7.2.stable.official.ed1daf0bf. Traces, original replay manifests, selected
real frames and an HTML index are in the handover.

With numpy/PIL discovery and imports blocked, including an explicit import of the
new proof module: 43 tests, OK, three named integration skips, 21.858 seconds.
`python3 -m expectrail.capabilities render` and `check` exited 0; 48 capability
tests passed (1.414 seconds). The real report example was written/read by the
existing strict report APIs; no schema extension was needed.

Final full suite, all EXPECTRAIL_* variables removed:
`python3 -m unittest discover -s tests -t .`: 4,252 tests in 379.075 seconds,
OK, 52 skipped, exit 0. Failing test names: none. The three real-engine tests
are named skips in this ordinary run; their separate diagnostic run passed.
The baseline-only hostile-proposer error did not recur. Patch reconstruction,
protected-path/approval scope and retained evidence hashes were checked.

## Not done

No live model, fixer or paid API calls. No live-model proposal-quality or repair
rate measurement, no broader report-filtering rate, no visual-correctness claim
or release clearance. The local sandbox probe cannot create a user namespace:
`bwrap: setting up uid map: Read-only file system`. The local diagnostic is
explicitly unsandboxed. The required sandboxed CI invocation is wired but was not
run on GitHub; Sean's architect must apply the patch for that job to run.
No GitHub write, push or PR. No held-out/blind content read, approval changed,
protected verifier edit or game-source edit.

## Files

Round four: `.gitignore`, `contracts/examples/playtest-report-fall-through.json`,
`tools/playtest_fall_through.py`, `tests/test_replay_sandbox.py`,
`docs/playtest.md`, `docs/playtest-evidence/fall-through.json`,
`docs/playtest-evidence/fall-through-frame16.png`,
`docs/capabilities.json`, generated `docs/capabilities.md`, and this log.
The combined handover additionally contains the separately identified round-three
foundation and its original work log.
