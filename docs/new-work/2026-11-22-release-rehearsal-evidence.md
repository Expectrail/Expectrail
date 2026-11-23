# Link the first hosted release rehearsal (#244)

## What changed

The install guide now names the three verdicts from the 22 November Linux rehearsal and links the installed-command and recorded-vision ledger rows. Its November 17 entry describes the earlier local container run. The guide explains how a missing visual answer affects a required check.

## What was run

Read the completed wheel job on main commit `4d2e095a`. Its version output identified 0.1.0 as an installed package in a clean venv. It ran doctor and sample in the image with networking disabled, checked every result against its expected verdict and printed `Recorded sample: accept / reject / accept`. The artifact listing includes `expectrail-0.1.0-wheel`. [Job and steps](https://github.com/Expectrail/Expectrail/actions/runs/44983211397/job/137088044148) · [Run and artifact](https://github.com/Expectrail/Expectrail/actions/runs/44983211397)

The artifact ZIP matched GitHub’s SHA-256 digest, and the wheel inside matched the included checksum. Full discovery ran 5,959 tests in 674.945 seconds and passed with 78 skips. The ten release-workflow tests passed. Both capability links resolved to explicit anchors. The public export scan checked 1,366 files with zero findings.

On the rebased branch, ran the recorded `sample --json` CLI with the three bundled answer banks, the existing two-observer replay fixture and network calls blocked. The first run made 14 image requests and the repeat made 18. Both matched zero saved answers. Workers cancel pending requests on the first exception. Clean and repaired returned needs-review. The seeded bug returned reject because its engine check failed. The CLI returned 3 because the sample expectations were unmet. These were fixture replays. The install guide now states both outcomes. [Recorded-sample CLI](../../expectrail/cli.py) · [Replay fixture](../../tests/test_two_observers.py)

The guide also distinguishes the installed-wheel macOS-helper test on Linux from a native macOS install. [Wheel test report](https://github.com/Expectrail/Expectrail/pull/784)

After rebasing onto `7c08b926`, full discovery passed with 5,960 tests in 640.819 seconds and 78 skips. All 17 release-workflow and recorded-sample profile tests passed. The public export scan checked 1,368 files with zero findings.

The November 17 local-container section also said CI had never run. It now links that local measurement and the later hosted rehearsal with their dates. The original test measurements are preserved.

On main `21fabcbe` plus the guide change, full discovery passed with 5,991 tests and 80 skips in 646.670 seconds. The ten release-workflow tests also passed individually. The local test record and both ledger anchors resolved. The export scan checked 1,380 files with zero errors and zero warnings.

After #796 merged, the queued patch conflicted in the release and macOS sections. I checked that #796’s cache instructions and its macOS test limits were preserved verbatim. All 36 download, release-workflow and wheel-sample tests passed. The offline sample probe on this base again returned needs-review, reject and needs-review with zero saved answers used.

On main `6db8cfb1` with this correction, full discovery ran 5,997 tests in 730.018 seconds and passed with 80 skips. The export scan checked 1,382 files with zero findings.

The Linux quickstart now distinguishes ordinary verification using live vision from the opt-in bundled sample profile. The [23 November package job](https://github.com/Expectrail/Expectrail/actions/runs/45114710696/job/137494786724) executed the six published blocks and reported needs-review, reject and needs-review, then needs-review for the draft project with zero judged replays. The page links this outcome alongside the recorded-sample rehearsal.

On main `4b6ba692` with the guide changes, full discovery passed with 6,008 tests in 898.915 seconds and 80 skips. All 49 focused quickstart, wheel sample and release workflow tests passed. The six published commands and their expected exits matched main, as did the installed-app introduction. With JavaScript disabled in Chromium at 375 px and 1280 px, the quickstart showed the sample-profile link and both run links without horizontal overflow. The front-door link check reported zero problems and the export scan checked 1,387 files with zero findings.

The price example in the quickstart called its upper bound a past charge. The [29 October experiment](../sam.md#video-input-measured-not-used-october-29) gives an image rate of $2.50 per 1,000. Two questions on each of 120 frames means 240 images and $0.60 at that rate. The quickstart now presents this as a calculation.

After the price correction, full discovery passed with 6,008 tests in 691.788 seconds and 80 skips. All 32 focused quickstart tests passed. With JavaScript disabled at 375 px and 1280 px, Chromium showed the calculation and the link to its source without horizontal overflow. The six command blocks and their expected exits matched main. The front-door checker found zero problems and the export scan had zero findings in 1,387 files.

## Not done

This documentation correction used the existing run. A version tag and publication to a registry remain with Sean.

## Files

- `docs/install.md`
- `docs/quickstart.html`
- `docs/new-work/2026-11-22-release-rehearsal-evidence.md`
