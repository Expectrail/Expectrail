# Independent-author Breakout trial (#263, Part B of #259)

## What changed

Selected and pinned `mike0697/Breakout` before integration inspection; MIT,
`0ac7aed444ea593a023d9b666c211d7ab8acd51e`. Added only trial inputs and evidence.
No core edits after Part A; 287 safe-named core files compare byte-for-byte.
The choice was not replaced when mouse control and menu-start coverage stopped it.
See the [report](../outside-trials/breakout/report.md),
[numbered log](../outside-trials/breakout/commands.md),
[results](../outside-trials/breakout/results.json) and
[proposed issue text](../outside-trials/breakout/issues.md).

## What was run

Full suite before: 4179 tests in 432.924s, 0 failures, 0 errors,
50 skips. Full suite after: 4179 tests in 456.857s, 0 failures,
0 errors, 50 skips. Failing test names compared: `[]` before and `[]` after.
The before log is the final Part A full run, completed before any Part B trial
files were added; it is reused as the unchanged-core baseline, not represented
as another invocation. The fresh after command was
`python3 -m unittest discover -s tests -t .`. See `test-comparison.json`,
`logs/before.log`, `logs/before.json`, `logs/after.log` and `logs/after.json` in the ZIP.


The 37 numbered trial commands took 192.859
subprocess seconds ([timing scope](../outside-trials/breakout/timing.json)).
Init, inspect, doctor, auto-route and all three config-based verify invocations
were real commands. Auto-route made three equal 93-tick traces but reported no
useful movement. Separate diagnostic captures produced 120 frames per variant;
their traces are identical and all remain on the start menu.

Pinned / harmless / broken CLI verdicts are all needs-review, zero approved checks
run, with config and checks still drafts. Engine diagnostics: bounds not exercised;
ball-launch assertion fails equally on each unstarted menu at frame 40 by 104 px.
The defect never executed. Both patches applied and reverse-checked. No approval
or bug-detection success is inferred from those diagnostics.

Godot 4.7.2, OpenGL3, llvmpipe LLVM 19.1.7. The display/disk prerequisites were
resolved through existing tools and documented environment settings; nested
bubblewrap was unavailable and captures record that they are not isolated.
The source and core audits, initial authoring mistakes and final corrections are
retained in the command log/handover.

## Not done

Gameplay onboarding failed. The working trial list was not extended. No core fixes,
new approvals, model spend, vision calibration, isolated CI run, workflow edits,
native macOS or first-user test. Human minutes were not measured. The initial
repository-search/pin lookup and artifact preparation were not separately timed.
Sean should file the proposed follow-ups, then arrange a replay of the same pin
with usable pointer control before reviewing the drafts for approval.

## Files

- `tests/outside/breakout/`: draft config, route, two check documents, two seeded
  patches and provenance README; no vendored game.
- `docs/outside-trials/breakout/`: frozen choice and pin, command/time logs,
  result and core-audit data, screenshot, raw result evidence, report and issue text.
- `docs/outside-projects.md`: honest unsuccessful-trial table.
- This work log. The separate Part A dependency is unchanged.

## Correction to the kinematic-character table (November 20)

The visual observer column said `agrees` for the broken-collision row. The recorded findings say the
after-change visual verdict on the ground check is `not-asked`: the engine alone rejected that change,
and the `agrees` referred to a separate paired anchor comparison on two frames. The table now says so,
because the old wording read as two observers confirming one real defect, which is not what happened.
The last row's recorded explanation is also marked as the one the run wrote; re-judged on main the
evaluator reports the player absent in 83 of 120 observed frames instead.

Source: the offline reproduction of run 43652198623 on main
(https://github.com/Expectrail/Expectrail/issues/244#issuecomment-7009221442), which re-judged all four
captures from the public artifact with 841 of 860 questions answered from the recording and no model call.
