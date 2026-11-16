# The README leads with Expectrail's premise, like the front page

## What changed

Sean asked for the front-page changes (#512) to be carried to the GitHub repository, modelled on how strong
open-source projects present themselves. The README now follows the pattern of those projects (for example uv and
Playwright): a centred logo with a dark-mode variant, a one-line tagline, a few truthful badges, a row of links, then
the problem, the mechanism, the proof, and a table that routes each kind of reader to the right entry point.

- **Top:** logo (`docs/brand/expectrail-logo.svg`, with `expectrail-logo-reverse.svg` in dark mode), the tagline, badges
  for CI on main, the Apache 2.0 license, Python 3.12+ and the evidence ledger, and links to the website, quickstart,
  concepts, guides, positioning and ledger.
- **The premise:** the front page's headline and two paragraphs, with repair described as opt-in and reviewed by a
  person (Sean's decision on #512), and a Mermaid diagram of the flow: change, replay, runtime record and vision,
  deterministic evaluator, accept / needs-review / reject, opt-in repair.
- **Why single-channel verification fails:** the measured matrix from #512 as the README's proof, each number linked to
  its bench file, with the recorded runs below it (in the place where uv puts its benchmark chart).
- **Get started:** a table routing readers by goal: the quickstart, the GitHub Action guide, repair, bring your own
  model, vision or fixer, concepts, and the ledger.
- **How we stress-tested the premise** and **Proved in game engines, built for stateful visual software:** the three
  acts and the bug-family table from #512, with the same line that only the web checkout page has been measured
  outside games.
- **Kept word for word:** the prerequisites (now in a collapsible block under Install), "Start with an honest result",
  "What a result means", "What’s been shown", "Verify, then repair" with the Meta models table, and "Development and
  license". "Results" is renamed "Evidence and limits", with its text unchanged.

Not changed, because they are repository settings, which only Sean may change (AGENTS.md): the About description,
website, topics and social preview. A draft for Sean is in the pull request.

## What was run

On `claude/readme-premise`, from main `b947635`:

- `python3 -m tools.front_door`: 0 problems, no network requests (it checks every README link and fragment).
- `python3 -m expectrail.capabilities check`: exit 0 (every model, command, workflow and doc the README names has a
  ledger row).
- `python3 -m unittest tests.test_capabilities tests.test_loop_story tests.test_outside_result_pages
  tests.test_python_floor tests.test_quickstart_ci tests.test_runit_links tests.test_package tests.test_discovery_freeze
  tests.test_new_work`: `Ran 103 tests`, `OK`.
- `python3 -m unittest discover -s tests -t .`: `Ran 3881 tests`, `OK (skipped=40)`.

## Not done

- Not rendered locally: GitHub's Markdown API is not reachable from this session, so the logo switch, badges, the
  collapsible block and the Mermaid diagram were checked on github.com after pushing (see the pull request).
- The About description, topics and social preview are drafted for Sean, not set.
- No new bench or model run; every number is from an earlier recorded run. Nothing was spent.

## Files

- `README.md`
- `docs/new-work/2026-11-15-readme-premise.md`
