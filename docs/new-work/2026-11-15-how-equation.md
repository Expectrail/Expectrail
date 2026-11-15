# How it works opens with what's new: sensor × telemetry → evaluator → repair

## What changed

Sean asked for the "Models look. Plain code decides." section to introduce Expectrail's novelty, with his text
trimmed and the chain "External Perceptual Sensor × Internal Runtime Telemetry → Deterministic Evaluator →
Evidence-Driven Repair" animated. He picked option A of three mockups on the design canvas.

- `docs/index.html`: the section now opens with the heading beside a two-paragraph lead (the problem, then the answer),
  then a four-panel equation:
  - the recorded frame with vision's box;
  - the engine's record (feet vs ground, touching, every frame);
  - the plain-code evaluator's three verdicts;
  - the opt-in repair inputs (the check's words, the route log, the first failing frame) and the link to `#repair`.

  A caption carries "Models observe, plan and patch…" and a Pause button. The clickable flow and its scenarios stay
  below under "Follow one change through".
- `docs/assets/home.css`: the equation's layout (four across; two by two under 1,080 px; one column under 640 px, with
  the arrows turned down) and its lit, current and dimmed states. The dimming applies only once the script runs.
- `docs/assets/home.js`: while the equation is on screen it walks seven beats, 1.3 s each: term, operator, term and
  so on, with the evaluator's "reject · they disagree" lighting at its beat. Pause holds it. With reduced motion,
  every term stays lit and the button is hidden.
- `tests/test_home_interactive.py`: one test checks that the four terms are in order, that the model names, the
  `#repair` link and the pause button are present, and that the both-sources sentence is there.

## What was run

- Headless Chrome at 390, 768, 1024, 1280, 1440 and 1920 px wide:
  - the equation advanced on its own and held still after Pause;
  - every scroll-in item ended visible;
  - no overflow, no script errors and no outside requests.

  With reduced motion, no term was dimmed and the button was hidden. Screenshots at the phone, tablet and desktop
  widths were looked at.
- `python3 -m unittest discover -s tests -t .`: `Ran 3984 tests`, `OK (skipped=40)`.
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems. `python3 -m tools.front_door`: 0 problems.
  `python3 -m expectrail.capabilities check`: exit 0. The five-page front-door browser check: 10 of 10 passed.

## Not done

- The vision box on the frame is placed by hand, as on the rest of the page.
- "per-change checks" from Sean's text was cut for length.

## Files

- `docs/index.html`
- `docs/assets/home.css`
- `docs/assets/home.js`
- `tests/test_home_interactive.py`
- `docs/new-work/2026-11-15-how-equation.md`
