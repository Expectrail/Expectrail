# Explain verification with an unconfigured After folder (#370, #826)

## What changed

The local app guide explains what a developer can do with a configured Before and an After copy missing its setup. Before supplies the checks. A measured failure can still reject a change, while a missing or changed After config prevents acceptance.

## What was run

I installed the main wheel from `de1ddd65` and submitted five jobs through Chromium using the public kinematic-character game. No draft was saved. The wrong collision layer in a plain After copy was rejected at frame 44. The player was 66.499 px past the ground boundary, and the engine failure decided the check. The restored game with a config, with only its config removed, and with all setup omitted each produced needs-review. The engine passed, and the recording had no matching visual answer. The stuck-fade game without setup also produced needs-review. Every original file in both project folders kept its hash. [Version, individual job records and controls](https://github.com/Expectrail/Expectrail/issues/826)

Full discovery ran 6,014 tests with 2 failures, 6 errors and 81 skips. Seven failures or errors match the existing repair-price blocker on main. The installed-sample test also failed on unchanged main while copying to the default temporary filesystem. In a diagnostic control on main, the isolated test passed when its sample subprocess used the roomy RAM-backed temporary directory. The full suite remains red. After the final wording edit, all 23 focused documentation and configured-folder tests passed. The public export scan covered 1,392 files with zero errors or warnings. [Main CI](https://github.com/Expectrail/Expectrail/actions/runs/45668776574) · [Repair price review](https://github.com/Expectrail/Expectrail/pull/821)

## What remains

The Check folders screen still offers a new draft for After. The separate UI change is tracked on #826. These were automated Linux runs on prepared public copies. The unaided trial on a developer’s own game remains open.

## Files

- `docs/app.md`
- `docs/new-work/2026-11-25-after-config-guide.md`
