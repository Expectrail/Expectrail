# Recheck the revised Breakout Ball draft without Start (#716)

## What changed

Started the check review with the two existing drafts. It distinguishes removing Start from stopping the Ball after launch. The document names which controls fail and which require review.

## What was run

- Six local Godot 4.6.3 headless replays, seed 1, 407 ticks each. The original route passed both draft checks three times. Removing every event failed the Ball check from frame 40 and gave needs-review on the Paddle three times. Each trio had one trace digest. [Commands, draft hashes and results](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164)
- The comparison for the stopped Ball comes from three existing public jobs. [Job links and findings](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7068866421)
- Full unittest discovery ran 5,956 tests in 660.715 seconds and passed with 78 skips. The focused paddle-rail regression passed. The public export scan checked 1,355 files with zero errors or warnings. All four relative links in the review resolved.
- After rebasing onto main at `62918117`, the full suite ran 5,959 tests in 703.412 seconds and passed with 78 skips. The public export scan checked 1,357 files with zero errors or warnings. The updated review links the integrator’s separate endpoint control.
- The frame guide links the paired comparison and three public hosted artifacts. Each archive matched its GitHub SHA-256. All three stopped-Ball findings reported 0 world pixels down between ticks 40 and 50 with 8 required, and returned needs-review. The clean centre coordinates in the guide were read from the linked trace. The frame-30 image-digest comparison and tick-70 truncation result come from the integrator’s paired runs.
- Full discovery for the final frame guide ran 5,959 tests in 685.868 seconds and passed with 78 skips. The first attempt reported two errors. Baseline worktree creation failed and a socket test could not create its temporary directory on the full filesystem. After freeing scratch space, both tests passed individually and the whole suite passed. No assertion or skip changed.

## Not done

The local runs captured no images. Bubblewrap could not set up its uid map. The stopped-after-launch case still lacks three assertion failures. The two further checks and human approval remain open.

## Files

- `docs/outside-trials/breakout-pointer/checks-for-approval.md`
- `docs/new-work/2026-11-21-breakout-launch-control.md`
