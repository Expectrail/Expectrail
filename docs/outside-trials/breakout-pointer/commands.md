# Breakout pointer trial commands

Machine subprocess seconds below; timestamps in commands.json are UTC. Human minutes were not measured. Absolute paths describe this machine, not prerequisites on another machine. Support scripts are in [support/](support/); the handover keeps runnable copies at their recorded paths. No live providers or keys.

## 1. prepare-same-pin

```sh
python3 /workspace/work/handover-259-menu-routes/prepare-trial.py
```

0.400238 seconds; exit 0. [Output](trial-logs/01-prepare-same-pin.log).

Reused the original choice and full pin; copied only tracked files. No easier substitute.

## 2. inspect

```sh
python3 -m expectrail inspect /workspace/work/breakout-pointer-source --json
```

0.089245 seconds; exit 1. [Output](trial-logs/02-inspect.log).

STOP: operator used an unsupported module entry point (`expectrail` has no __main__). Corrected to the documented CLI module next.

## 3. inspect-cli

```sh
python3 -m expectrail.cli inspect /workspace/work/breakout-pointer-source --json
```

0.321456 seconds; exit 0. [Output](trial-logs/03-inspect-cli.log).

Two body candidates: Paddle and Ball. Pointer script and Start control reported; choose roles explicitly.

## 4. doctor-initial

```sh
python3 -m expectrail.cli doctor --project /workspace/work/breakout-pointer-source --no-fetch --json
```

14.822872 seconds; exit 3. [Output](trial-logs/04-doctor-initial.log).

STOP: workspace/temp had less than 1 GiB; doctor also named unavailable sandbox mapping and missing vision key/cap. Used roomy memory-backed TMPDIR/EXPECTRAIL_TOOLS for runs. No key supplied; diagnostic class only.

## 5. init

```sh
python3 -m expectrail.cli init /workspace/work/breakout-pointer-source
```

7.959902 seconds; exit 0. [Output](trial-logs/05-init.log).

Start control measured by the engine. Draft route contains a click and sweep; config asks which body is the player.

## 6. complete-bindings

```sh
python3 /workspace/work/handover-259-menu-routes/complete-config.py
```

0.149223 seconds; exit 0. [Output](trial-logs/06-complete-bindings.log).

User configuration only: Paddle is player, Ball is ball; bind their own texture paths. Draft retained.

## 7. inspect-config

```sh
python3 -m expectrail.cli inspect /workspace/work/breakout-pointer-source
```

0.150153 seconds; exit 0. [Output](trial-logs/07-inspect-config.log).

Static candidate inventory still names Paddle and Ball; explicit config controls replay.

## 8. auto-route

```sh
python3 -m expectrail.cli route --project /workspace/work/breakout-pointer-source --auto --out /workspace/work/breakout-pointer-source/routes/pointer-auto.json
```

52.872066 seconds; exit 0. [Output](trial-logs/08-auto-route.log).

Success: Start clicked; paddle moved; three headless traces identical. STOP: output prints hundreds of pointer events instead of a useful sweep summary (follow-up).

## 9. draft-checks

```sh
python3 /workspace/work/handover-259-menu-routes/prepare-checks.py
```

0.114362 seconds; exit 0. [Output](trial-logs/09-draft-checks.log).

Two draft checks fixed before measuring variants; no approval. Bounds window 20..70, ball-start window 40..50, and a left-lane checkpoint.

## 10. seed-variants

```sh
python3 /workspace/work/handover-259-menu-routes/prepare-variants.py
```

0.221013 seconds; exit 0. [Output](trial-logs/10-seed-variants.log).

Same historical harmless and broken patches; applied to copies, reverse-check passed.

## 11. verify-help

```sh
python3 -m expectrail.cli verify --help
```

0.114647 seconds; exit 0. [Output](trial-logs/11-verify-help.log).

Read documented verify arguments.

## 12. verify-pinned

```sh
python3 -m expectrail.cli verify --project /workspace/work/breakout-pointer-source --base /workspace/work/breakout-pointer-source --execution-class diagnostic --jobs-root /dev/shm/expectrail-menu-trial-verify/jobs/pinned --json
```

13.442456 seconds; exit 2. [Output](trial-logs/12-verify-pinned.log).

needs-review; draft config/checks, zero checks ran, no vision.

## 13. verify-harmless

```sh
python3 -m expectrail.cli verify --project /workspace/work/breakout-pointer-variants/harmless --base /workspace/work/breakout-pointer-source --execution-class diagnostic --jobs-root /dev/shm/expectrail-menu-trial-verify/jobs/harmless --json
```

13.993119 seconds; exit 2. [Output](trial-logs/13-verify-harmless.log).

needs-review; draft config/checks, zero checks ran, no vision.

## 14. verify-broken

```sh
python3 -m expectrail.cli verify --project /workspace/work/breakout-pointer-variants/broken --base /workspace/work/breakout-pointer-source --execution-class diagnostic --jobs-root /dev/shm/expectrail-menu-trial-verify/jobs/broken --json
```

13.407408 seconds; exit 2. [Output](trial-logs/14-verify-broken.log).

needs-review; draft config/checks, zero checks ran, no vision.

## 15. capture-pinned-1

```sh
python3 -m harness.run --game /workspace/work/breakout-pointer-source --route /workspace/work/breakout-pointer-source/routes/pointer-auto.json --out /dev/shm/expectrail-menu-trial-capture/runs/pinned-1 --sandbox auto
```

31.846110 seconds; exit 0. [Output](trial-logs/15-capture-pinned-1.log).

Rendered diagnostic replay, sandbox auto falls back outside isolation.

## 16. capture-pinned-2

```sh
python3 -m harness.run --game /workspace/work/breakout-pointer-source --route /workspace/work/breakout-pointer-source/routes/pointer-auto.json --out /dev/shm/expectrail-menu-trial-capture/runs/pinned-2 --sandbox auto
```

24.368148 seconds; exit 0. [Output](trial-logs/16-capture-pinned-2.log).

Repeat at same pin/seed.

## 17. capture-pinned-3

```sh
python3 -m harness.run --game /workspace/work/breakout-pointer-source --route /workspace/work/breakout-pointer-source/routes/pointer-auto.json --out /dev/shm/expectrail-menu-trial-capture/runs/pinned-3 --sandbox auto
```

27.565477 seconds; exit 0. [Output](trial-logs/17-capture-pinned-3.log).

Third rendered repeat at same pin/seed.

## 18. capture-harmless

```sh
python3 -m harness.run --game /workspace/work/breakout-pointer-variants/harmless --route /workspace/work/breakout-pointer-variants/harmless/routes/pointer-auto.json --out /dev/shm/expectrail-menu-trial-capture/runs/harmless --sandbox auto
```

32.945422 seconds; exit 0. [Output](trial-logs/18-capture-harmless.log).

Rendered harmless replay.

## 19. capture-broken

```sh
python3 -m harness.run --game /workspace/work/breakout-pointer-variants/broken --route /workspace/work/breakout-pointer-variants/broken/routes/pointer-auto.json --out /dev/shm/expectrail-menu-trial-capture/runs/broken --sandbox auto
```

30.815464 seconds; exit 0. [Output](trial-logs/19-capture-broken.log).

Rendered broken replay.

## 20. measure-draft-diagnostics

```sh
python3 /workspace/work/handover-259-menu-routes/measure-trial.py
```

0.267200 seconds; exit 0. [Output](trial-logs/20-measure-draft-diagnostics.log).

Existing observation conversion/evaluator applied to drafts separately; these are raw engine diagnostics, not approved gate results.

## 21. registration-probe

```sh
python3 /workspace/work/handover-259-menu-routes/registration-probe.py
```

0.064818 seconds; exit 2. [Output](trial-logs/21-registration-probe.log).

STOP: outside-trial list rejects root path `.`. Not registered; no core fix during trial.

## 22. source-and-core-unchanged

```sh
python3 /workspace/work/handover-259-menu-routes/freeze-check.py
```

0.164827 seconds; exit 0. [Output](trial-logs/22-source-and-core-unchanged.log).

307 core file hashes unchanged; all 105 tracked pinned game files unchanged.

Total recorded subprocess time: 266.095624 seconds (not human time).

Analysis note: the first attempt at the offline measurement helper used a nonexistent `pos` key and stopped with KeyError. Corrected the helper to the trace contract’s `player` key before step 20; no product code, route or check changed.
