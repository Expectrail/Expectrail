# The front page and positioning page lead with Expectrail's premise and its measured results

## What changed

Sean's brief ("expectrail.tech Strategic Narrative & Copy Revamp"), with his four answers of November 15, 2026: use the
brief's wording and drop the per-number scope notes it drops; drop the unsourced "120+ coding agents" count; describe
repair as opt-in with a person reviewing the patch, not "automatic" or "self-healing"; and mark Section 03's non-game
column as where the same bugs appear, not a measured result.

- `docs/index.html`: a new hero (coding agents, the cross-product of runtime telemetry and vision, deterministic
  verdicts, opt-in repair) and three new sections from the brief: 01 the single-channel failure matrix, 02 the
  three acts (mutation bench, the 10 of 10 repairs, discovery and generated checks), 03 games first and where the
  same bug families appear in web, canvas and mobile apps. Every number links to the bench file or run that records
  it. The existing sections stay unchanged, in this order after the new ones: what's been shown (kinematic-character),
  verify then repair, recorded examples, then install, the three cards and "Know what this does not establish". The
  install command and its scope line moved from the hero into the "04 / Start here" section.
- `docs/positioning.html`: five new sections before the existing desk review, following the brief's outline: the
  bottleneck, why single-channel verification is gameable, the cross-product invariant, closed-loop repair, and games
  to web and mobile. The desk review of Ziva and nunu.ai and the limits section are unchanged.
- `docs/assets/front-door.css`: one rule scaling the hero headline, so the brief's longer headline fits the first screen
  (it filled the whole laptop screen at the old two-line size).

One correction to the brief: it said both sinking bugs were fixed "on Attempt #2 once structured evidence was supplied".
`docs/report-first.md` records run 41223754703: report-only attempts timed out three times on both sinking bugs, and
with the evidence Muse Code fixed each on the first attempt. The page says that.

## What was run

On `claude/front-door-premise`, from main `b947635`:

- Every figure in the brief was checked against the repo before writing: the 13 cited runs exist, and the numbers match
  `bench/detection/README.md`, `bench/judge/README.md`, `bench/judge/glimmer/README.md`,
  `bench/judge/outside-models/README.md`, `bench/mutation/README.md`, `bench/mutation/ai-fixes/README.md` and
  `docs/discovery.md`.
- `python3 -m tools.front_door`: 0 problems, no network requests.
- `python3 -m expectrail.capabilities check`: exit 0 (every model, engine and command the home page names has a ledger
  row).
- The page tests (`tests.test_capabilities`, `test_check_pages`, `test_runit_links`, `test_runit_site`,
  `test_outside_result_pages`, `test_visible_repair`, `test_loop_story`, `test_guides`, `test_quickstart`,
  `test_dossier`, `test_demo_page`): `Ran 124 tests`, `OK`.
- `python3 -m unittest discover -s tests -t .`: `Ran 3881 tests`, `OK (skipped=40)`.
- The front-door browser check from the guides work (#266), headless Chrome at 1440x900 and 390x844 on index,
  quickstart, concepts, guides and positioning: 10 of 10 passed (no page overflow, script errors or missing assets; the
  skip link works), and home navigation passed. Its assertion that no model vendor appears on the home page's first
  screen was removed for this run, because the brief names SAM 3.1 and Muse Glimmer 30B in the hero on purpose; no test
  in the repository requires it. The home page's laptop and phone screenshots were looked at.

## Not done

- No new bench or model run was made; every number on the pages is from an earlier recorded run. Nothing was spent.
- The "Release dossier", README and capability ledger are unchanged.
- Native mobile, canvas and WebGL apps remain unmeasured; the page says so.

## Files

- `docs/index.html`
- `docs/positioning.html`
- `docs/assets/front-door.css`
- `docs/new-work/2026-11-15-front-door-premise.md`
