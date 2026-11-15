# The home page takes direction B (Night Replay), with interactive flow charts

## What changed

Sean picked direction B of the three homepage mockups (Claude Design canvas "Expectrail homepage directions") and asked
for the flow charts to be interactive. The words are the copy merged in #512; nothing about what is claimed changed.

- `docs/assets/home.css` (new, loaded only by `docs/index.html`): B's dark theme over `front-door.css`, a centred
  hero, pill buttons, and the styles for the parts below. The other pages are unchanged.
- `docs/assets/home.js` (new, local, no network): three interactive parts. The page's HTML already shows each part's
  default state, so the page reads the same without the script.
  - **The channel switch** (new section `#switch`): one recorded deceptive fix, `bad/fall-through-sink-player`, judged
    by the engine's record only (accept, wrong), a screenshot judge only (accept, wrong) and both with plain code
    (reject, correct), with the measured counts for each: 4 of 8 / 3 of 7 / 0 of 8, not a gate / 2 of 7 / 1 to 2 of 8,
    and 8 of 8 / 0 of 7 / 0 of 8. The overlays show which channel is looking.
  - **The how-it-works flow** (new section `#how`): eight steps as buttons (change, replay, runtime record, vision,
    deterministic evaluator, accept, needs-review, reject → opt-in repair); selecting one explains it and links its
    ledger row or concept. Three scenarios play the path a change takes: a correct fix (accept), the robot drawn into
    the ground (reject) and vision unavailable (needs-review, skipping vision). With reduced motion the path appears at
    once.
  - **The repair loop** (existing `#repair` diagram): Previous and Step-through buttons and clickable diagram cards light
    one stage in the diagram and its note together, with a spoken status line.
- `docs/index.html`: loads the two files, uses the reverse logo, the new hero layout (with a link to the outside-game
  result) and the two new sections. Every existing section, link and test hook is kept.
- `tests/test_home_interactive.py` (new, 5 tests): the page loads its script and styles; the switch's HTML shows the
  state the script holds for "both"; every count the switch shows is in its bench file, including the case's three
  recorded verdicts; every flow button has an explanation and every scenario a real path; the stepper covers the five
  stages and notes.

## What was run

On `claude/home-night-replay`, from main `3c7ee5c`:

- `python3 -m unittest tests.test_home_interactive -v`: `Ran 5 tests`, `OK`.
- `python3 -m unittest discover -s tests -t .`: `Ran 3911 tests`, `OK (skipped=40)`. An earlier run failed
  `tests.test_visible_repair` because a `data-loop` attribute changed the repair figure's tag; the tag is restored and
  the script finds the loop from its diagram. The test was not changed.
- `python3 -m agents.check_pages docs --offline`: 15 pages opened in Chromium, 0 problems.
- `python3 -m tools.front_door`: 0 problems, no network requests. `python3 -m expectrail.capabilities check`: exit 0.
- A Playwright script in headless Chrome at 1440x900 and 390x844 clicked every new control: each switch mode gave the
  expected verdict, count and overlays; every flow step; the reject and vision-unavailable scenarios lit
  change → replay → record → vision → evaluator → reject and change → replay → record → evaluator → needs-review; three
  loop steps reached "Step 3 of 5: Fix a separate copy" with its note lit. No script errors, no request outside the
  site, no horizontal overflow. The screenshots were looked at.
- The five-page front-door browser check (from #266, without its no-vendor assertion, as in #512): 10 of 10 passed.

## Not done

- The overlay positions on the game frame are set by hand to the recorded frame; drawing them from the run's recorded
  boxes is a follow-up. On a phone the two overlay tags sit close together.
- No new bench or model run; nothing was spent.

## Files

- `docs/index.html`
- `docs/assets/home.css`
- `docs/assets/home.js`
- `tests/test_home_interactive.py`
- `docs/new-work/2026-11-15-home-night-replay.md`
