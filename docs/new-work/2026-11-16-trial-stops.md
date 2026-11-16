# Fix the three config-only trial stops (#259), Part A

## What changed

One shared static check selects a configured `entryScene` for inspect/init and
replay/auto-route, or refuses it plainly. The gate's supplied base config remains
authoritative. Unconfigured replays retain their implicit main scene.

Doctor, inspect, init, auto-route and direct replay refuse detected C#/.NET projects
before engine lookup. The reason names the detected file/settings and the GDScript-only
support limit. Candidate-side C# additions are also refused before candidate import.
Failed auto-route replays retain bounded logs and a failure.txt beside the output;
reported paths survive scratch cleanup. No unrelated symlink contents are copied.
The new helper is bundled in the wheel. Existing project and doctor formats did
not change, so there is no schema or observation format change.

The pending System Override trial patch is included as a separate dependency.
Main already contains the role-boxes prerequisite (#538). The same System Override
pin was repeated: see [commands and full refusals](../outside-trials/trial-stops/system-override-refusals.json)
and [the Part A report](../outside-trials/trial-stops/report.md).

## What was run

Full suite: before 4161 tests in 437.730s, 0 failures, 0 errors,
49 skips; after 4179 tests in 432.924s, 0 failures, 0 errors,
50 skips. Failing test names compared: `[]` before and `[]` after;
no new failures. The after command was `python3 -m unittest discover -s tests -t .`;
the before run used the same discovery with `-v` to preserve names. The new optional
real-engine class is skipped in that no-Godot-PATH suite, then explicitly run with
Godot 4.7.2: 1 test passed, three equal replays with player movement. It previously
errored when the replay started the menu.

The offline red run on old product code ran 16 tests and reported 20 failures
(including subtests), covering all three requested fixes. The final offline run
passed 18 tests. Existing focused auto-route/config/doctor/package tests:
86 tests, 1 skip, no failures. No existing test was changed, weakened or skipped.
All 18 offline tests also pass with NumPy and Pillow imports blocked.
Tree/init/inspect compatibility plus the new tests: 41 tests, all pass.

The first full after-run found two diagnostic regressions (4,179 tests,
2 failures, 0 errors, 50 skips, 468.891s):
`tests.test_init_inspect.SetupTest.test_output_directory_link_is_refused` and
`tests.test_tree.OneDefinitionTest.test_a_replay_stops_before_copying_a_game_with_a_link_that_leaves`.
Earlier preflight had shortened their established symlink diagnostics. The product
now preserves them; neither test was changed. That failed run remains in
`logs/after-diagnostic-regressions.log`; the final full rerun is the after total above.
The only edits after rendered parity were these diagnostic wrappers on error paths.

An earlier baseline attempt filled the 8 GB workspace: 4 failures, 1,524 errors,
38 skips (4,121 tests reported). It is retained as `logs/before-disk-full.log`,
with a complete failing-name list; it is not used as the clean baseline. Only
completed generated test fixtures and public replay work/frame copies were cleaned,
then the unchanged baseline was rerun successfully. No product change was used
to repair that environment failure.


Real rendered before/after parity: [machine-readable comparison](../outside-trials/trial-stops/parity.json).
Raw run paths in that comparison are relative to the handover ZIP.

| Case | Engine before / after | Verdict before / after | First failing frame | Exact trace bytes |
| --- | --- | --- | --- | --- |
| bundled-pinned | pass / pass | needs-review / needs-review | none | identical |
| bundled-broken | fail / fail | reject / reject | 5 | identical |
| kinematic-character-pinned | pass / pass | needs-review / needs-review | none | identical |
| kinematic-character-harmless | pass / pass | needs-review / needs-review | none | identical |
| kinematic-character-broken | fail / fail | reject / reject | 44 | identical |
| dodge-the-creeps-pinned | pass / pass | needs-review / needs-review | none | identical |
| dodge-the-creeps-harmless | pass / pass | needs-review / needs-review | none | identical |
| dodge-the-creeps-broken | fail / fail | reject / reject | 97 | identical |


Pinned public demo sources are the same as the previous trials; their digests and
renderer metadata are in the raw replay files. The System Override pin is
`f95712a9e88480251e3ba38880d7144bf3f7b33a`; its tracked source diff stayed empty.
Doctor exits 3, inspect/init/route exit 5, all naming `SystemOverride.csproj`.

## Not done

The new independent-author GDScript trial (Part B items 5–6) has **not started**.
The user explicitly allowed Part A to be handed over first. No game has been chosen
or replaced for that next trial. Do not close the overall trial task on this slice.

No native macOS run, live vision, model spend, approval, GitHub write, push or commit.
The rendered parity runs used Xvfb, Godot 4.7.2 and `sandbox="off"` on these already
known public fixtures. This validates local replay/engine parity, not sandbox
isolation or vision accuracy. No accept is claimed without vision. Frame images
and copied game trees were deleted after hashing to fit the disk; trace.json,
replay.json (including frame hashes), godot.log and check.json are in the ZIP.
The preliminary headless kinematic broken run did not reproduce the rendered
failure (68 judged frames, 52 missing); its raw evidence and failed assertion are
retained. That headless/rendered difference was not changed or fully investigated.

The historical third-project trial remains a failed onboarding. System Override
is still unsupported; it now refuses early rather than failing after replay starts.
No approval or spec meaning changed. The .NET preflight is a conservative support
boundary, not general C# support or a sandbox. Configured binary `.scn` entry scenes
are explicitly refused; use a `.tscn` text scene. Generated `.godot` content is ignored.


## Files

- `expectrail/godot_project.py`: shared scene and GDScript support preflight.
- `expectrail/onboarding.py`, `expectrail/doctor.py`, `expectrail/route.py`,
  `harness/run.py`: use it and retain auto-route failure logs.
- `setup.py`: bundle the helper.
- `tests/test_trial_stops.py`: offline regressions and optional real Godot replay.
- `docs/outside-trials/trial-stops/`, `docs/outside-projects.md`: repeated refusal
  and parity evidence; this work log.
- The separate dependency contains the original System Override draft artifacts,
  numbered trial log and patches, under `tests/outside/system-override/` and
  `docs/outside-trials/system-override/`, plus its original work log.
