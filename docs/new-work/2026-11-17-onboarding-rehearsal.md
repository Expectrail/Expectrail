# Rehearse the Godot onboarding path from a fresh clone (#332)

## What changed

Folded the earlier SVG preview and output diagnostics into the review page from
#580. A small original PNG can be displayed without Pillow with its actual
dimensions, and bounded static SVG art has a native preview. The review route
uses the config's capture rate. The new --check-answers command shares input and
policy validation with the human importer and leaves files untouched.

## What was run

The exact fresh-clone steps, time, engine measurements and verifier decision are
recorded in docs/onboarding.md and its linked evidence. The run used #604's
inspection and the local #601 calibration rebase. The browser exported two
simulated No decisions and the answers check applied zero changes. Verification
completed needs-review. The suite logs, red and green runs, required historic
fetch and export scans are in the handover.

## Not done

Human minutes and outside-project trials remain open. The calibration measured
engine geometry. Observer tuning and proof were skipped. Zero approvals or
model calls were made in the rehearsal.

## Files

expectrail/onboard.py, expectrail/onboard_page.py, expectrail/onboard_review.py,
the two onboarding regression test modules, docs/onboarding.md and its linked
evidence, and this entry.
