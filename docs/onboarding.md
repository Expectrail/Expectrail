# Onboarding a Godot project

A fresh-clone rehearsal on `tests/projects/config-lane` reached
`verify` in **1.55 machine minutes** including the clone, or
**1.42 minutes** for the timed setup commands. The verifier completed
with `needs-review`. Human review time is unmeasured.

The run used public main `791f50b99b1e6a11e262088ed8b56255fa2494ad`
and the local rebase of #601 `63c97ffc3508ce7d11ad424b28b8bff7d95a823b`, plus the #332
changes in this patch. It used the source CLI on Linux with Python 3.12.14,
the pinned Godot already installed, and an existing Python environment with the
contracts extra. NumPy and Pillow were absent. The machine total sums command
times. Dependency installation, applying patches, and preparing the disposable
fixture copy were outside that total. The commands ran on a shared test runner.

| Step | Machine seconds | Recorded result |
| --- | ---: | --- |
| Clone public main | 7.504 | Checked out the recorded main commit. |
| Propose config and route | 0.085 | Draft printed. Project bytes unchanged. |
| Save draft metadata | 0.066 | Saved the same proposal in a disposable copy. |
| Inspect at tick 45 | 10.043 | Measured the bound Avatar along the first route. |
| Calibrate the clean route | 36.464 | Three identical complete engine traces. |
| Build the review page | 24.026 | One measured object and one draft check. |
| Export simulated answers in Chromium | 1.068 | Two No decisions and zero external page requests. |
| Validate the answers file | 0.157 | No selections or changes applied. |
| Verify the project | 13.504 | Completed as needs-review, exit 2. |

The record includes exact commands, exits, output hashes and review stages.
The calibration and verification records are linked separately.
[Timing record](onboarding-evidence-332/timing.json) ·
[Calibration report](onboarding-evidence-332/calibration.json) ·
[Verify job](onboarding-evidence-332/verify.json)

The proposed route was 105 physics ticks. At tick 45 the inspector reported
`Actors/Avatar`, visible and on screen, at `[168, 108, 192, 132]` in the 360 × 240
viewport. Calibration measured 105/105 visible-player
samples, a 24 × 24 player box, and 0 unjudgeable samples.
The on-floor gap ranged from -0.075 to 0.000 pixels with
median -0.075. Each of the 3
complete traces had the same SHA-256.

The review page showed the 24 × 24 SVG and three frames with engine boxes.
It reported the clean replay result for the draft visibility check. Observer
tuning and broken-copy proof were skipped in this rehearsal. Chromium executed
the page's export code in an offline document, using an automated reviewer who
answered No to the object and check. The answers were validated against the same
review and project inputs that the human importer reads. The verify job then
reported that no checks ran, the config remained a draft, and vision did not run.

## Repeat the steps

Use the public `config-lane` fixture, or substitute the folder of a Godot project
you maintain. Run the source CLI as `python3 -m expectrail.cli` or use the installed
`expectrail` entry point. For the source CLI, install the `contracts` extra before
building the review. Use a new output directory outside the project for evidence.

1. Copy `tests/projects/config-lane` to a disposable folder called GAME. Run
   `expectrail init --project GAME --dry-run` and review the proposed node, texture
   and route. Save the draft with `expectrail init --project GAME`. For the
   disposable fixture copy, add `--force` to replace its existing draft.
2. Run `expectrail inspect --project GAME --at-tick 45 --json` on the saved route.
   The project's first route is the default. Use `--route PATH` to select a
   different route. Without `--at-tick`, inspect lists saved scene information.
3. Run `expectrail calibrate --project GAME --route ROUTE --out EVIDENCE`. Use the
   draft config's first route for ROUTE and a new path for EVIDENCE. Calibration
   reports drawing geometry, floor gaps and replay stability from the clean
   engine record. Supply `--godot ENGINE` if the pinned engine is elsewhere.
4. Put your draft check in `GAME/checks/`. Run
   `expectrail onboard --project GAME --out REVIEW.html` with a new file in an
   existing directory. Open it and inspect the object, frames and check.
5. Save the answers with the reviewer's name. Run
   `expectrail onboard --check-answers ANSWERS.json` to validate the file and
   report the selected checks. The game's reviewer alone may apply their decisions
   using `expectrail onboard --approve ANSWERS.json`.
6. Run `expectrail verify --project GAME` and read its decision. To get an
   acceptance, the reviewed config must name approved checks and have the
   required visual evidence for the routes judged.

| Setup stop | What to change |
| --- | --- |
| The player or sprite is ambiguous | Review the candidates and set `bindings.player.node` and `bindings.player.texture` in the draft. |
| The inspect tick lies outside the route | Choose a tick in the range printed by inspect, or choose a longer route with `--route`. |
| Calibration rejects the capture rate | Set `captureFps` to a divisor of `physicsTicksPerSecond` in the project config. |
| The pinned engine is missing | Use `--godot ENGINE` for calibration and review, or install the engine using `expectrail doctor`. |
| The review output directory is missing, or the file already exists | Create the named directory, or choose a new `--out` file in an existing directory. |
| A reviewed route, check or other input changes | Generate a new review page and save fresh answers. |
| Verify reports a draft, no approved checks or no vision | Have a person review the draft and checks, then provide authorized visual evidence for the route. |

Issue #332 remains open for observer tuning and proof, and timed trials on two
outside projects with real reviewers. The config-lane rehearsal used a fixture
written for Expectrail.
