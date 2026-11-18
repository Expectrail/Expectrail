# Local app demonstration on Crate Run

The second test project is a small Godot game with its own input actions and
a crate that jumps along a floor. The test copied the existing approved
ground check byte for byte and used the project's walk route. The After copy
uses the broken movement variant from `tests/test_second_project.py`.

In Chromium on November 17, 2026, the test entered the two folder paths in
the app and used **Older projects without a config → Enter paths manually**.
It selected `project`, `routes/walk.json` and `specs`. **Check folders** showed
one usable route and one approved check. **Verify** ran Godot
4.7.2.stable.official.ed1daf0bf. The test saw **Reject** and opened the job's
evidence viewer from the result screen.

| Item | Recorded value |
| --- | --- |
| App job | `1d8527e65b991388f77d4442f2a4aecf` |
| Check | `player-stays-above-ground` on `walk` |
| Before engine result | pass |
| After engine result | fail |
| Replays | 2 total, 0 sandboxed |
| Decision | reject |
| Head digest | `d9d37eede826177f91341607955b2d73a3bf27e5fc3da231ebf2b89dab69038c` |
| Base digest | `6eeaea987c8f7f775736bd1eb3eadf40b308e902098dfa530579bd2554437657` |
| Policy digest | `f188ac37e16231683706be1785c4a1a16367480132bd5379ae18d7f8d620a0aa` |

Vision settings were absent. The engine failure rejected the change. This
demonstration covers the walk route and the ground check. The non-developer
trial is separate.

Run `python3 -m unittest -v tests.test_app_engine.AppEngineTest.test_outside_crate_run_in_the_browser`
with pinned Godot, Xvfb, Chromium and Playwright installed. This uses two
temporary copies and starts the ordinary app worker.
