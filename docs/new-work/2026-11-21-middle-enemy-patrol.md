# Draft a check for the middle enemy's return (#727)

## What changed

Added a public replay where the player stops within view of the middle platform. An unapproved
draft judges the bound enemy's drawing bounds against a region around a stationary flower after
the first turn. The fixture uses the existing project, route and test-spec contracts. The family
table records the precise scope and the four public controls for Q1–Q3.

## What was run

- Pinned Godot 4.7.2 on main `74d30c5`. Clean and comment-only passed 3/3 each. The committed
  fast-left defect and the standard frozen-enemy control failed decisively 3/3 each. Every replay
  judged all 31 frames.
- Validated the fixture's route, project configuration and draft against the existing contracts.
  The gate reader found one draft, zero approved checks and one route without problems.
- Ran three additional replays with the committed missing-upper-enemy defect. The draft passed
  all three with 31 frames judged, confirming its scope is one named enemy.
- The documented command reproduced the four main controls with identical verdicts. Verified
  16 relative documentation links and fetched the required historic commit.
- `python3 -m unittest discover -s tests -t .` passed with 5,805 tests reported and 82 skipped.

## Not done

The replays used headless engine geometry. Bubblewrap isolation, rendered-pixel evidence, and
human approval remain outstanding. The check covers this enemy's return region. General enemy
spawning and the other families remain on #727. The exact-score contract is tracked in #744.

## Files

- [Project bindings](../../specs/drafts/727/enemy-patrol/expectrail.project.json)
- [Route](../../specs/drafts/727/enemy-patrol/routes/enemy-patrol.json)
- [Draft](../../specs/drafts/727/enemy-patrol/checks/middle-enemy-on-return.json)
- [Measurement](../measurements/727-middle-enemy.md)
- [Family coverage](../measurements/721-family-coverage.md)
- This work-log entry.
