# Public reproduction audit and bounded UI trace comparisons (#285)

## What changed

Audited `d36c8063449afe6c4113c74d0ff39e926b861b6c`, the starting main and branch
`chatgpt/285-repro-audit`. Read AGENTS.md and #285 before implementation; issue and repository
text supplied evidence, not additional authority. Work remained public-only.

`docs/repro-audit.md` contains one completion table, the fixed six-category miss breakdown,
source links, the missing current/stepwise measurements, and exact dispatch/cost steps for Sean.
Recovered the public baseline's original GitHub artifact: run 43465090517, artifact 14061794022.
All 26 original files are byte-preserved, and the downloaded archive's SHA-256 matches GitHub's
`8a66c7e7deb012fd023ae9275981f075076ddaaefdbb80c66da10e8ca08beea8`. Added a source/file digest
manifest. Recomputing the score with the current reader produces the original JSON byte for byte.
The score and four published hand classifications remain distinct; synthetic contract examples
are not recorded measurements.

The baseline is 17/24 reproduced, including 16/19 trace-visible and 13/20 authored defects;
seven misses, zero no-result. The misses are route-never-reaches 2/7, no-signal 2/7,
probe-language 2/7, wrong-predicate 1/7, flaky 0/7, budget 0/7. The original scorer alone says
no-signal 2, wrong-predicate 1, undetermined 4. All counts refer to the same public run, not to
current code. Its recorded total spend is $2.0492 over 24 defects, max $0.1722; 0/24 exceed $2,
under the recorded assumed prices. No later rate is claimed.

Before selecting work, checked which main slices already address those misses: three signals,
reach pairs, trace/screen evidence, candidate withholding, and pixel plumbing exist. The two
counter defects have committed menu experiments showing screen-only differences on two of
three routes each, but no UI trace reading. Added bounded integer-only Label state in the Godot
recorder and episode reader, `ui_integer_at_end`, and the closed same-route `signal_compare`
operation. A reported counter can be compared to coins removed during the same route, with no
hard-coded count. Unknown and ambiguous readings never pass. Only the two evidence offers expose
these additions; baseline and signals-reach remain frozen. Schemas, handwritten examples, writer,
readers and tests change together. This does not enable an observer or grant policy authority.

Updated the formerly stale opening in docs/jit.md and linked the audit from the public bench.
Updated the menu module's historical explanation, while leaving its routes unchanged.

## What was run

- Before edits: inspected the public manifest, visibility/reach/screen/evidence/menu records and
  cited run; did not inspect private data. No EXPECTRAIL_* variables are present in the shell.
- Original public artifact recovered through the read-only GitHub connector, then SHA-256 checked.
  `python3 -m expectrail.repro score --records bench/jit/recordings/public-43465090517/repro
  --out <scratch>/regenerated --source 'jit.yml run 43465090517, attempt 1, at
  1e6055004dccfd90bc0f4d132823784838718627'`; `cmp` against original JSON: identical.
  `python3 -m expectrail.repro breakdown --score .../repro-score.json`: published classifications.
- Current-main metadata: public GitHub API query, exact URL and timestamp committed in
  `docs/repro-current-main-runs.json`; zero JIT runs at the audited SHA. The connector's run-list
  operation filters to pull-request events, so the main query used the public read-only API.
- Red before implementation: six new unit tests, failed with 10 failures/two errors and one
  named missing-engine skip. Installed the pinned Godot 4.7.2 binary through the existing
  checksum-checked downloader. Then restored all seven changed production modules to their
  original main bytes and ran the final 12 new regression tests: exit 1, 14 failures/three errors,
  including the real-engine route with missing UI readings. Restored the implementation in a
  `finally` block. Logs `red-ui-integer.log` and `red-original-code.log` in the handover.
- Pinned engine: existing `hold-right-then-toggle-pause` route, headless clean twice and each of
  `coin-counter-stuck` / `coin-counts-twice` once; observed integers 5, 5, 0, 10. All seven initial
  regressions passed, then all 11 unit tests passed after expanded parser/window/contract coverage.
  These are engine/interpreter tests; no model was asked and no new reproduction rate is inferred.
- Final no-numpy/PIL fresh-process discovery: 4,568 tests, zero import errors. Focused execution
  under the same blocker: 105 tests, OK, including the real-engine counter test. The initial blocker
  omitted ModuleNotFoundError.name and was corrected; no existing import guards needed changes.
- Preliminary full suite found the public bench layout invariant: its root may contain only defect
  directories. Moved recovered recordings to `bench/jit/recordings/public-43465090517/`; did not
  weaken the existing test. Stopped that failing preliminary run and started the full final suite.
- Sender-cap preflight with HTTP mocked and the environment patched/restored: JIT's default
  sender refuses before any HTTP call when EXPECTRAIL_SPEC_USD_CAP is absent. The workflow does
  not pass it. Documented the exact two env entries Sean must add to propose/revise; no workflow
  file changed. Log: workflow-cap-preflight.log.
- Final verification: `python3 -m unittest discover -s tests -t .`: **4531 tests, OK, 41 skipped**, 872.569 seconds, exit 0, with no EXPECTRAIL_* variables in the shell. Final missing-numpy/PIL discovery: 4,568 tests, zero import errors; 105 focused tests OK (25.360 seconds), including the pinned-engine public counter test. Layout/provenance regression run: 40 tests OK. Export scan: all 51 changed files, zero errors/warnings. Patch application reconstructs every changed file byte for byte.

## Not done

#285 cannot close. Missing current and stepwise hosted rates/spend, a hosted candidate-withheld
measurement, automatic trusted menu reach, and remaining orientation/layering representation.
The baseline meets the trace-visible target; current offers have not demonstrated a rate.
The UI reading is engine state, not pixel evidence; multi-label/formatted/custom-drawn UI is
unsupported. The audit states these limits and provides Sean's exact three dispatch commands.
Before any dispatch Sean must supply EXPECTRAIL_SPEC_USD_CAP in both model jobs; the audit gives
the exact env entries. Each dispatch selects $48 of assessed budgets (24 x $2), at most 48 Muse calls, zero SAM images; measure
and workflow overhead are additional, not a promised $48 total bill. No dispatch was run.

No model calls, spend, push, PR, GitHub comment, workflow edit or repository setting change.
No policy approval added. No prohibited/private material read or used. Forbidden code files
remain unchanged. Sean applies the handover and pushes.

## Files

- `bench/jit/recordings/public-43465090517/`: original score, 24 input records, source manifest/README.
- `bench/jit/public/README.md`, `docs/jit.md`, `docs/repro-audit.md`,
  `docs/repro-current-main-runs.json`: provenance, audit and measurements still needed.
- `contracts/trace.schema.json`, `episode.v1.schema.json`, `trace-spec.v1.schema.json`, plus three
  handwritten examples: optional UI reading and same-route comparison.
- `harness/godot/expectrail_harness.gd`, `expectrail/trace/{normalize,signals,evaluator}.py`:
  bounded recording, strict reading and interpretation.
- `expectrail/jit/{intent,offer}.py`, `expectrail/repro/{evidence,menu}.py`: named-offer enforcement,
  evidence field whitelist and accurate menu documentation.
- `tests/test_trace_ui_integer.py`, `tests/test_repro_public_recording.py`: new regressions/provenance.
- `tests/test_jit_offer_evidence.py`, `tests/test_trace_camera_coins.py`: intended vocabulary assertions.

Guard: test change intended (#285). The evidence offer now adds a UI signal/operation; its old
identity-with-signals-reach assertion is replaced by an exact final prompt digest, full meanings
and exclusion checks. Baseline digests are unchanged. The camera/coin assertion now accounts
for the separately withheld evidence-only signal; it still pins exactly eleven baseline signals.
No test is deleted or skipped by this patch.
