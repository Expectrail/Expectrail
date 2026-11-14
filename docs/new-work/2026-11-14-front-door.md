# Verification first: an executable front door (#266)

## What changed

Replaced the README and site introduction with verification, the checkout install line and links to the capability ledger. Added a six-step quickstart and concepts page covering approval, routes, decisions, vision, evidence grades, release clearance, receipts and threat-model limits. Claims link to their ledger rows; no capability status or evidence grade is promoted.

The quickstart deliberately removes vision credentials. Its six command blocks are the source executed by `tools.quickstart`: install in a new virtual environment, doctor, sample, project selection, verify and report. The runner checks saved job records as well as exit codes. The unapproved Crate Run draft must need review without a judged replay; it is not presented as a successful game verification. Nine new offline tests cover the reader, shell, links and evidence checks. CI adds one step in the existing package job, without secrets, environments or permissions. Existing tests are untouched.

## What was run

- Read #266 and its comments (none), AGENTS.md, README, site and capability ledger. Required fetch of `c169a5e0da304773587304ed47bc8aabcec80da7` completed before the baseline. Patch base: `6e6ca6a8a85f7518cc890116bdcfd02d2c9d010c` (main at start).
- `python3 -m unittest discover -s tests -t .` before and after: Before: 3225 tests, OK (skipped=37), zero failures/errors. After: 3234 tests, OK (skipped=37), zero failures/errors. Failing test names in both runs: `[]`; the name-and-kind comparison found no new or resolved failures. Both logs and the comparison are in the handover.
- `python3 -m unittest tests.test_quickstart tests.test_capabilities tests.test_runit_links tests.test_check_pages tests.test_discovery_freeze`: 70 tests, OK (skipped=1). The existing browser-test class could not find its bundled browser; it was not changed. Separate checks below used the installed Chromium.
- The first after run found one README regression: `test_the_pages_name_the_command (tests.test_discovery_freeze.ReadersAreNotSentToAFailingCommand.test_the_pages_name_the_command)`. Restored the historical command with its required baseline `--root` and ledger link; the existing test stayed unchanged. `logs/after-initial-failed.log` preserves that run. The final after run above includes the correction.
- `python3 -m tools.front_door`: zero link/anchor/ledger-reference problems, no network requests. Advertisement checks include all four front-door documents.
- `python3 -m tools.quickstart --out /workspace/work/quickstart-266 --godot /workspace/work/Expectrail/tools/godot/Godot_v4.7.2-stable_linux.x86_64`: PASS with real Godot 4.7.2 and an extracted Debian Xvfb on PATH. Python 3.12.14; Mesa llvmpipe. Local `EXPECTRAIL_SANDBOX=off` was explicit because user namespaces are unavailable here. This is diagnostic, unsandboxed evidence. The CI step does not set that override. No model credentials or calls. Command exits: 0, 3, 3, 0, 2, 2. Sample decisions: needs-review, reject, needs-review. Draft project: needs-review, one draft, zero judged replays; report written.
- Opened index, quickstart and concepts in real headless Chromium 156.0.8078.79 at 1440x900 and 390x844. Inspected the rendered screenshots. No page overflow, missing assets or script errors; keyboard skip links and home-to-quickstart-to-concepts navigation passed. No model vendor in the homepage's first screen. Logs, checker and screenshots accompany the handover.

## Not done

Guides for Actions/MCP/private runners/provider adapters and a sourced positioning page remain for later slices of #266. No new paid/live-vision acceptance evidence, arbitrary-project support claim, isolated/protected grade, receipt or clearance mechanism. The draft-project walkthrough does not demonstrate gameplay coverage. GitHub CI was not run from this workspace; its new step is configured and its command was run locally. Browser inspection is Chromium viewport testing, not physical phone or Safari testing. No commits, pushes, deployment or GitHub writes.

## Files

- `.github/workflows/ci.yml`
- `README.md`
- `docs/assets/front-door.css`
- `docs/capabilities.json`
- `docs/capabilities.md`
- `docs/concepts.html`
- `docs/index.html`
- `docs/new-work/2026-11-14-front-door.md`
- `docs/quickstart.html`
- `tests/test_quickstart.py`
- `tools/front_door.py`
- `tools/quickstart.py`

## Architect run (Linux, main 6e6ca6a8)
Applied cleanly. Full suite: OK, 31 skipped. `capabilities check` exit 0; `agents.check_pages docs`: 10 pages, 0 problems. Rendered index, quickstart and concepts in headless Chromium at 1280 and 390 px wide: no script errors, no sideways scrolling. The quickstart end to end (`tools.quickstart`) was not run here, because its pip install needs the network this workspace lacks; CI's package job runs it. The two new tools are added to `.gitignore`'s allowlist like the others.
