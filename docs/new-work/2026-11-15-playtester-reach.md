# Playtester false reports and public reach at 200 seeds (#531, round two)

## What changed

Applied the first-round producer patch on the claimed `chatgpt/531-playtester-reach` worktree,
based on main at `a98dcb08c2d7fe068283e97148b07a37d423d91e`. The first-round checkout was preserved.
Added resumable public seed measurements, exact per-seed evidence, fixed-vocabulary miss analysis
and raw-data readback audits. The public union has 24 actual defects plus the upstream draw-order
fix; the four shared reported defects are not counted twice.

After the complete initial breakdown, added one optional generic observation: a visible bound
player's entire recorded collision body stays outside the game view for one physics second.
It uses the existing body/view trace fields, no bug identity or mechanics-specific expectation.
The pinned headless viewport was independently measured as 800×480 in trace coordinates.
The route generator and original three observation functions are unchanged, and the original
214 reports regenerated identically. The new mode uses producer version 1.1.0; the standalone
default remains the original policy, version 1.0.0. Both keep the exact issue #531 report shape.

Reserved evaluation seeds 10000–10199 before development, then froze the observer source hashes
before generating any evaluation route. The paired comparison reads original/improved reports
from each same fresh engine trace. No runtime code was retuned after evaluation started.

## What was run

- Full suite before applying the prerequisite or new code, all `EXPECTRAIL_*` variables removed:
  **4,086 tests in 459.386 s, 48 skipped, exit 0**. No failing unittest test names.
- `harness/get_godot.sh` downloaded pinned **Godot 4.7.2-stable**, SHA-512 checked. Actual engine
  version: `4.7.2.stable.official.ed1daf0bf`. No fallback engine was needed.
- Development clean first: **200 seeds, 0 reports** on each of the three observations. There
  were no false examples to show; none was fabricated.
- Same seeds 0–199 on all 25 requested distinct public patches: **214 reports**. Body-flip:
  193 turning reports, first seed 0. Additional immobility candidates: air-jump 2, first 2;
  slides-after-stop 1, first 177; jump-needs-rest 18, first 5. These immobility reports do not
  demonstrate the listed jump/slide symptoms. Every other patch produced zero reports.
- The complete breakdown preceded the improvement choice. Existing repro signals already changed
  for many misses; two pause-menu counters were never reached, and screen-only effects were
  explained using the existing public evidence and the fixed reason vocabulary.
- Before evaluation, **29 focused tests passed**, including affine geometry, window resets,
  exact report shape/anchor, unchanged original reports, complete-seed accounting, resume guards
  and fresh-process imports with numpy and PIL blocked.
- Fresh clean first: **200 seeds, 0 original reports, 0 improved reports**. False reports did
  not increase in this sample. No clean false-report examples occurred in either phase.
- Fresh paired matrix, seeds 10000–10199, 200 per build: **209 original reports → 322 improved**.
  The 113 additions were offscreen reports on air-jump (23, first 10001), camera-stops-right
  (86, first 10007), and camera-cut-top (4, first 10068). Body-flip had 190 turning reports
  under both policies. The two camera findings match the recorded right/top edges; air-jump's
  offscreen consequence is not an infinite-jump check. Other incidental candidates and every
  miss are listed in `docs/playtester-reach.md`.
- **10,400 successful primary replays** in total. Each starts from the game start, 1,200 ticks,
  through the existing headless harness. Both policies use the same fresh trace, not duplicate
  engine runs. No frame capture, model or fixer was used.
- Raw audits check all requested traces, hashes, route regeneration, game blobs, existing signal
  summaries, report regeneration/shape and actual previous-tick anchors. Audit records and all
  per-seed measurements/replay/engine records are retained in the handover.
- Two selected fresh routes (body-flip 10000, air-jump 10001), three further replays each:
  **all six full trace hashes and both report-ID sets matched**. This is not an all-seed
  three-run stability claim. An initial standalone diagnostic launch could not import the repo;
  rerunning with the repo on `PYTHONPATH` succeeded. Both logs are retained; no engine ran in
  the failed import attempt.
- Recovered engine crashes: development bullet-behind-scenery seed 27, and fresh
  bullet-through-enemy seed 10030; each first attempt exited -6 and the retry completed.
  The crash logs are retained. An earlier progress claim of no failures was corrected when
  the full audit surfaced the recovered development failure.
- Full suite after runtime freeze, all `EXPECTRAIL_*` variables removed:
  **4,115 tests in 745.594 s, 48 skipped, exit 0**. No failing unittest test names.

## Not done

No rendered-pixel verification, shared-verifier/ingest integration, generated checks, approval,
fixer or end-to-end repair rate. No private/blind data, model spend, push, GitHub comment or PR.
The original game, protected verifier/anchored/orchestrator files and `.github/` were not edited.
The other #531 builder still owns schema and ingest. Engine-predicted offscreen body geometry is
not proof about rendered artwork, and a zero clean count on these bounded routes is not a
general false-report guarantee.

The zip includes every report and per-seed measurement/replay/engine log, all raw trace hashes,
and selected raw trace witnesses with an exact selection manifest. Other raw traces remain in
the local measurement directories; game copies and caches are omitted. The documented commands
regenerate full raw data. The full auditor requires that full data.

## Files

- Prerequisite first-round files, unchanged except the producer's opt-in API and README link.
- `tools/playtester/scale.py`, `analyze_scale.py`, `audit_scale.py`, `offscreen.py`, `SCALE.md`.
- `tests/test_playtester_scale.py`, `tests/test_playtester_offscreen.py` (new test files).
- `docs/playtester-reach.md`, `docs/new-work/2026-11-15-playtester-reach.md`.

The handover includes combined `changes.patch` against BASE_COMMIT, the prerequisite patch,
and `round-two-only.patch` for applying after that prerequisite. Both application paths are
checked using a separate Git index. No existing BASE test file was edited.
