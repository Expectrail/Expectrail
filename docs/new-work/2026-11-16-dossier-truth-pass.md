# Regenerate the release dossier from recorded evidence and audit its claims (#268)

## What changed

Read AGENTS, #268's Done when, the generator, current release bundle and its public inputs.
Worked only on `chatgpt/268-dossier-truth-pass`. The supplied branch was at
`842014238db14973567f233871014a58a4ae48b4`; it was fast-forwarded locally to fetched main
`7d61695f77534c175a57934ca06cb73b55c7417c` to include the newly merged playtester reach record.
The historical AGENTS fetch had already been done in this shared repository. No push or GitHub
write. No prior task's patch is needed here.

Ran the unchanged generator against that main before editing. The checked-in dossier reported
18 held / 13 open / 0 failed / 4 not run. Ordinary regeneration from current committed inputs
produced 21 / 9 / 0 / 5, still a local run. Replaced neither record: both exact HTML snapshots
are retained. The truth pass uses a verbatim CI artifact instead. Generated `truth-pass.md` and
`figure-changes.json` list every changed visible numeric span, occurrence count, source and
section reason, including homepage changes. SHA identities/issue IDs/percentile labels are
explicitly metadata, not new performance figures.

Added generated outside-project, failed-onboarding, playtest, template and spend sections.
False accepts, false rejects and needs-review retain separate eligible denominators. Small zeros
name their sample size; unavailable cohorts, per-phase percentiles and billing stay unmeasured.
The homepage's current-evidence summary is generated from the same inputs. Retained historical
counters/bars/cost are checked against ledger claims; numerical comparisons absent from the ledger
were removed from the homepage, without changing any underlying bench record. The outdated
three-way label was corrected after removing the unrepresented screenshot-judge comparison.

The dossier refuses uncited figures and inconsistent source/ledger totals before writing. It
reads only explicitly named public evidence; no links are followed. Captured JSON/Markdown and
Breakout files have content digests, source identities and provenance. The baseline commit link
does not pretend new files existed at that commit: the changed ledger is copied byte-for-byte
into the generated bundle and local source citations resolve there. `--check` checks the page,
ledger snapshot, figure/wording audit and generated homepage summary. No evidence grade was raised.

## Sources and what they show

- Outside: historical kinematic vision run 43652198623, four variants, $2.00 list-price amount;
  later exact-image renderer failure remains #515. Engine-only CI run 43748180876 rejects the
  broken kinematic collision and Dodge clamp cases, while other arms need review. Dodge's check
  is already approved; no Dodge vision result exists. The historical failed vision attempt
  remains a separate cohort and separate cost, not overwritten by the later success.
- System Override: committed variant results and the repeated `.NET`/GDScript-only refusal,
  including the original resource/route stops. No successful onboarding or exercised detection.
- Breakout: the raw records were absent from main. Public issue #259 confirms the pointer/menu
  follow-up. Located `Expectrail-259-part-b-breakout-trial-handover.zip` in Sean's connected Drive,
  SHA-256 `fda158bba7a785eef4d37d7ad53883b7cfe3b71e658a4518d7369ca7c05fbf18`.
  Copied only verbatim results, pin and report, with their digests/provenance. Did not apply its
  patch, run its scripts or obey instructions in its documents. All three variants need review,
  zero approved checks, identical menu traces; no pointer route/keyboard start or root-path
  registration success. Local non-isolated diagnostic, not CI or seeded-bug detection.
- Playtest: public PR #551 seeded-bugs job 133104000066, run 43808291610. The three actual
  approved-reproduction/clean-false-report/anchor-desync test pass lines are cached verbatim.
  No live model or fixer has run on a report. The separate local trace producer's published
  reach is 1/24 original → 3/24 improved on previously unused public seeds. Original clean
  policy is 0/400 distinct seeds (development plus evaluation); improved is only 0/200 on the
  same evaluation seeds. No claim of 400 improved-policy clean tests or a general zero rate.
- Template: published untuned new-route 8/341 (2.35%), unused-route 0/97, pooled 8/438 (1.83%);
  outside original-bank transfer 540/540 (100%) alarms, own-bank unavailable. Opt-in, no verdict
  contribution, no cross-game transfer claimed. Read published records only, no new pixels.
- Spend: reservation units/month limits parsed from the committed code and cross-checked with
  the ledger. Per-role caps, retries, opt-in model month and separate vision month are holds,
  not invoices. The cost inside one fixer invocation is still unbounded by its invocation hold.
- Latest completed main release suite at the final capture: run 43817779257, job 133133657309,
  main commit `12434136b8f240c98df4015720a585d84c02320a`; 35 rows, 25 held / 10 open / 0 failed /
  0 not run, 68 test outcomes. ZIP SHA-256
  `501e56f2b486fc3930bea7eb9ba4ec99881a50b9a3cec1d5382c54649c95872d` matches the API artifact
  digest. A newer run, 43819427685, was in progress with no release artifact at capture; it is
  recorded as such, never assigned these results. This CI source commit is distinct from the
  local dossier baseline. No workflow was dispatched or rerun. The connector lists PR-triggered
  runs only, so the latest main run was identified through the public API, read-only.

The ledger's aggregate outside-project row contradicted its dedicated Dodge row; both now say
approved engine check and no vision. Its playtest-intake row still called the passed CI proof
future work; it now cites that proof with the no-live-model/fixer limit. A separate experimental
standalone-playtester row keeps its producer measurement distinct from ingest and older advisory
discovery. Current release-suite and reservation-unit evidence is added without changing grades.
Generated capabilities.md and the frozen dossier snapshot match capabilities.json.

## What was run

- Original generator regeneration on main, preserved before any changes; final regeneration and
  `python3 -m tools.dossier --check` both pass offline. A subprocess audit hook blocks network and
  child creation for the generator tests. No engine/model benchmark was rerun.
- `python3 -m expectrail.capabilities check` and `render`: pass; no external recheck was invoked.
- Focused dossier, ledger, ledger-run/count, site and outside-result tests: **212 passed** in
  12.593 seconds, including 13 new truth tests and all existing refusal assertions.
- Red control: disable only the figure-citation guard in-process. The unchanged new regression
  fails with `EvidenceError not raised` for `999 requests`. Source/test files are not edited for
  this red run; its deliberately failing log is included.
- Discovery with numpy and PIL unavailable: zero load errors; 68 release-gate bodies load.
- First full suite: 4,339 tests, 54 skipped, eight failures. Seven are repeated fixture failures
  because the two new job-specific citations were absent from the old offline API fixture;
  the other is the preserved historical-heading assertion. The helper now loads the actual
  cached public job identities; no jobs are fabricated from URLs and no existing assertion is
  weakened. The heading retains the expected text while clearly labelling the historical attempt.
- Final `python3 -m unittest discover -s tests -t .`: **4,340 tests total; OK (54 skipped)**,
  463.332 seconds. No EXPECTRAIL_* shell variable was set.
- `git diff --check` passes. The patch applies to a fresh detached checkout of the named base;
  `tools.dossier --check` passes there and all **212 focused tests pass** again (11.669 seconds).
  Source hashes/final patch reverse-check are included in the handover. No protected file or
  policy was changed.

## Not done

Part of #268. Blind release test #282 and a first-user quickstart test remain unrun; Sean/Timothy
must arrange the person. Repeated comparable per-profile runtime/phase percentiles, actual billed
costs, release tag and image digests remain unmeasured. Unity is experimental (#324), exact-image
recordings remain renderer-sensitive (#515), and an outside game cannot accept without vision
(#263/#379). The dossier inventories evidence; it is not release clearance and cannot close #268.

No live model calls, paid spend, workflow dispatch/rerun, push, PR, GitHub comment, repository
setting, secret or approval change. No fresh-*, blind-set contents or private held-out repository
was read. Blind results are the existing published aggregate counts only. Original bench,
onboarding, template and local release-gate evidence files are unchanged. Source-cache additions
are verbatim captures, not edited results. The prior tasks' worktrees are untouched.

## Files

- `tools/dossier.py`, `tools/dossier_figures.py`.
- Generated `docs/release/index.html`, `truth-pass.md`, `figure-changes.json`, ledger snapshot and
  explicit raw source caches under `docs/release/sources/`.
- `docs/capabilities.json`, generated `docs/capabilities.md`, `docs/index.html`.
- `tests/test_dossier_truth.py`; existing dossier helper extended only for named local citations
  and the generated snapshot; existing capability-run helper extended with recorded job metadata.
- This work log. No .github/ change and no approval added or changed.
