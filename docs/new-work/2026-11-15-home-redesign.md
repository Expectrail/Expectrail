# The home page uses the desktop width, says less, and moves as you read

## What changed

Sean's feedback on the live home page: on a desktop it read like a phone layout, it was still wordy and did not use the
mockup's words, the repair flowchart should animate so readers can follow it, text should animate in as people scroll,
and both phone and desktop must be checked. This builds on #520's wording (cherry-picked) and replaces that pull
request.

- `docs/index.html`: rebuilt around mockup B's shorter copy, 1,083 words where main has 2,164.
  - The hero and the "which channel decides" switch are one section: copy on the left, the switch on the right from
    1,280 px up, stacked below that. The headline is the mockup's: "Your agent says it fixed the bug. Expectrail
    watches."
  - A strip of four headline numbers (8 of 8, 0 of 7, 8 of 8, 10 of 10), each linked to its run.
  - The comparison is three bar charts in place of the table; the three acts are three big-number cards; the four bug
    families are four tiles; the outside-game result sits beside its verdict table; limits sit in two columns.
  - Every figure keeps its run or bench link. Every test hook stays: the outside-game verdict and cost links, the repair
    figure with its five notes and its two required sentences, the Run it links and note, the ledger names.
- `docs/assets/home.css` (rewritten): the wide grid (1,240 px), two-column sections, the bars, cards, tiles and proof
  strip, and breakpoints at 1,080, 860 and 560 px.
- `docs/assets/home.js` (extended):
  - Scroll-in text and counting numbers, triggered as each item comes into view.
  - The repair loop plays through its five stages on its own while it is on screen (2.4 s a step, a progress bar,
    stage, note and status lit together), with Pause, Previous and Next; it stops when off screen.
  - The how-it-works flow plays the "robot drawn into the ground" path once when it first comes into view.
  - With reduced motion requested, nothing moves on its own and all text is shown at once. Text is hidden for its
    entrance only after the script has marked the page, so the page reads in full without the script.
- `tests/test_home_interactive.py`: two more tests (7 in all). Each counting number already shows its real value in
  the HTML, and scroll-in text is hidden only once the script runs, with a reduced-motion rule present.

## What was run

On `claude/home-redesign`, from main `02e66bd` plus #520's commit:

- A Playwright script in headless Chrome at 390x844, 768x1024, 1024x768, 1280x800, 1440x900 and 1920x1080 scrolled the
  whole page at each size: every scroll-in item ended visible; no horizontal overflow; no element past the edge; no
  button under 44 px tall; no script errors; no request outside the site. The hero is two columns from 1,280 px and the
  switch starts in the first screen at every size. The flow played change → replay → record → vision → evaluator →
  reject by itself; the repair loop reached "Step 3 of 5: Fix a separate copy" by itself and held still after Pause.
  With reduced motion, nothing was hidden and the loop did not start. Screenshots at each size were looked at.
- `python3 -m unittest tests.test_home_interactive -v`: `Ran 7 tests`, `OK`.
- `python3 -m unittest discover -s tests -t .`: `Ran 3939 tests`, `OK (skipped=40)`. An earlier run failed
  `tests.test_runit_links` on a shortened Run it note; the note now says "right now" again, and the test is unchanged.
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems. `python3 -m tools.front_door`: 0 problems, no
  network requests. `python3 -m expectrail.capabilities check`: exit 0.
- The five-page front-door browser check: 10 of 10 passed.

## Not done

- The overlay boxes on the game frame are still placed by hand on the recorded frame.
- No bench or model run; nothing was spent. No AI-detection tool was run.

## Files

- `docs/index.html`
- `docs/assets/home.css`
- `docs/assets/home.js`
- `tests/test_home_interactive.py`
- `docs/new-work/2026-11-15-home-redesign.md`
