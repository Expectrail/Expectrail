# The home page's wording reads as a person wrote it

## What changed

The same sweep as #519, on the home page now that #518 has merged. Claims, numbers and links are unchanged.

- `docs/index.html` (25 edits). The headline and hero no longer use em dashes or stiff terms: "cross-examines
  internal runtime telemetry against external visual observation" now reads "compares what the engine recorded with
  what was actually drawn". The formula banner ("External Perceptual Sensor × Internal Runtime Telemetry →
  Deterministic Evaluator → Evidence-Driven Repair") now reads "What was drawn, checked against what the engine
  recorded, and judged by plain code. Repair only if you ask for it." Section labels and headings are plain ("01 / Why
  it takes two sources", "02 / Trying to break it", "03 / Beyond games"), and so are the sentences around them.
- The headline now says Expectrail "checks that they actually work" where it said "proves", which is also closer to
  what a verdict establishes.
- The arrows inside the flow diagram and the "reject → opt-in repair" step are kept: in a diagram they are labels,
  not dashes.

## What was run

On `claude/home-copy-sweep`, from main `02e66bd`:

- A count of the page's visible text: 0 em dashes and 0 en dashes (3 em dashes before); one "X, not Y" left, which
  reads naturally.
- `python3 -m tools.front_door`: 0 problems, no network requests. `python3 -m expectrail.capabilities check`: exit 0.
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems.
- The home page's interaction script in headless Chrome at 1440x900 and 390x844: every switch mode, flow step,
  scenario and loop step; no script errors, no outside requests, no overflow.
- The five-page front-door browser check: 10 of 10 passed.
- `python3 -m unittest discover -s tests -t .`: `Ran 3937 tests`, `OK (skipped=40)`.

## Not done

- No AI-detection tool was run; none is available here and they are unreliable.
- The README is not swept in this change.

## Files

- `docs/index.html`
- `docs/new-work/2026-11-15-home-copy-sweep.md`
