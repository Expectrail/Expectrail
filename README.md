# Expectrail

**Verify a game change against approved checks, with evidence you can inspect.**
The installed command replays a project and reports **accept**, **reject** or **needs-review**.
An accept needs both the engine's record and vision.
[Capability ledger: installed command — integrated, diagnostic](docs/capabilities.md#installed-command).

```sh
python3 -m pip install .
```

Run that in a checkout, using a Python 3.12+ virtual environment. The packaged path is Linux;
it is **not on PyPI**. The [six-step quickstart](https://expectrail.tech/quickstart.html) covers
installation, `doctor`, `sample` and a project given by path.
[Install scope and evidence](docs/capabilities.md#installed-command).

[Quickstart](docs/quickstart.html) · [Verify, then repair](#verify-then-repair) · [Concepts and limits](docs/concepts.html) ·
[Guides](docs/guides.html) · [Positioning](docs/positioning.html) ·
[Capability ledger](docs/capabilities.md) · [Source](https://github.com/Expectrail/Expectrail)

## Start with an honest result

The quickstart deliberately uses no vision credentials and makes no model calls. Its expected
sample decisions are **needs-review / reject / needs-review**. Missing `MODEL_API_KEY` or
`EXPECTRAIL_SAM_USD_CAP` leaves passing engine checks needing review; an engine failure can still
reject. The current vision default is tested offline; the ledger's cited installed-command live
run predates it. [Installed command](docs/capabilities.md#installed-command) ·
[Orchestrator and vision requirement](docs/capabilities.md#orchestrator).

`expectrail doctor` names missing prerequisites. `expectrail report` shows a job's decision and
where its evidence is. The commands and expected nonzero exits are explained together in the
[quickstart](docs/quickstart.html), whose command blocks are run by the CI quickstart test.
[Command evidence and limits](docs/capabilities.md#installed-command) ·
[Job/report evidence](docs/capabilities.md#orchestrator).

For your project, supply a compatible game, its input route and checks a person has reviewed and
approved. The quickstart starts with the small Crate Run example and its **unapproved draft**;
it must need review and does not replay a judged route. It does not approve a check for you or
promise support for an arbitrary game. [Project-by-path scope](docs/capabilities.md#installed-command) ·
[Drafts and approval](docs/capabilities.md#spec-writer).

## What a result means

- **Accept:** the configured checks passed with the required observations. It is bounded by those
  checks and routes; it is not proof of correctness outside them.
- **Reject:** a check failed. That failure can be decisive even when vision did not run.
- **Needs-review:** there is not enough usable evidence to accept, including missing vision or
  no approved checks. It is not a weaker pass.

[Decision evidence](docs/capabilities.md#orchestrator) ·
[Checks' measured scope](docs/capabilities.md#godot-verify).

**A verdict is not release clearance.** The ledger currently records only fixture and diagnostic
evidence, no isolated or protected row. The replay can write its own frames and trace. Signing
in the historical loop is not an offline trusted receipt for the installed verifier.
[Capture limits](docs/capabilities.md#godot-harness) ·
[Sandbox limits](docs/capabilities.md#replay-sandbox) · [Signing limits](docs/capabilities.md#signing).
Read the [concepts page](docs/concepts.html) for grades, approval and the threat model.

## Results

Use the [capability ledger](docs/capabilities.md) to distinguish **implemented**, **integrated**,
**measured** and **experimental** modes. Each row keeps its recorded evidence beside its limits.
The measured Godot path is one game, with bugs the team seeded; it is not a general catch rate.
[Godot verification row](docs/capabilities.md#godot-verify).

[The interactive demo](https://expectrail.tech/demo/) shows saved captures; viewing it verifies
nothing. [Demo row](docs/capabilities.md#interactive-demo).
[Run it](https://expectrail.tech/run-it/) says whether it can start a run right now. The ledger
currently says visitors cannot start runs because the service is not deployed; its cited sample
runs were dispatched by hand. [Run it row](docs/capabilities.md#run-it).

## Verify, then repair

Auto-fix is off by default. Turn it on to try a patch **only after a reject**. The original job keeps its
reject even if a fresh job accepts the candidate. [Verify and auto-fix tests](tests/test_auto_fix.py).

From a repository checkout, set `BEFORE` and `AFTER` to the two checkout paths. This example uses the
bundled game layout and its fall-through fixture. To try a different fix, supply a patch for that game.

```sh
expectrail verify --base "$BEFORE" --head "$AFTER" --game game/platformer \
  --routes harness/routes/smoke.json --specs agents/specs \
  --auto-fix --auto-fix-fixture agents/fixtures/fix-collision-mask.patch
```

To repair an existing reject instead, set `JOB` to its ID in the same job store:

```sh
expectrail repair "$JOB" --fixture agents/fixtures/fix-collision-mask.patch
```

The fixer gets a separate game copy and public failure evidence. It never edits the verifier or specs.
Each candidate gets a fresh verification. A person reviews any winning patch. Expectrail never merges it.
[Repair tests](tests/test_repair_command.py) · [Fixture result in the evidence viewer](docs/viewer-samples/fixture-repair.html).

The [local app checkbox](docs/app.md#auto-fix-checkbox) requests live repair; spend caps are in (#436), but no live repair has been run yet.
[CI auto-fix](.github/workflows/expectrail-autofix.yml) runs only the fixture fixer, when a maintainer labels a rejected pull request, and is off by default. The [Run it card](https://expectrail.tech/run-it/#recorded-fix) is off until a real
repair is recorded. [Status and evidence](docs/new-work/2026-11-14-loop-story.md).

The historical repository command `python3 -m agents.loop` has [recorded repairs on seeded bugs in one game](docs/capabilities.md#fix-loop).

### Meta models

These are historical provider roles, not a promise that every backend is measured equally.
The quickstart needs none of their credentials. Each row links its own evidence and limits.

| Model | Recorded role | Capability ledger |
| --- | --- | --- |
| SAM 3.1 | Frame observations; measured on one game and one page | [Observer](docs/capabilities.md#sam-observer) |
| Muse Code | Historical repair loop on seeded bugs | [Fix loop](docs/capabilities.md#fix-loop) |
| Muse Wonder | Triage in that loop | [Fix loop](docs/capabilities.md#fix-loop) |
| Muse Spark | Draft checks for a person to approve | [Spec writer](docs/capabilities.md#spec-writer) |
| Muse Glimmer 30B | Alternative observer, with stated precision limits | [Observer](docs/capabilities.md#glimmer-observer) |
| Muse Spark Open | Drafting and feedback sorting | [Open-weight drafting](docs/capabilities.md#spark-open) |
| Muse Voice Transcribe | Recorded-transcript tests; not run live on audio | [Feedback intake](docs/capabilities.md#feedback-intake) |

[Recorded vision costs](docs/sam.md) are scoped to their runs, not a quote for your project.
[Observer scope](docs/capabilities.md#sam-observer).

## Development and license

Run the repository checks with `python3 -m unittest discover -s tests -t .`.
The new quickstart step also runs its published commands; the existing site check opens HTML pages
in a browser. Contributor rules are in [AGENTS.md](AGENTS.md).

For the historical discovery freeze record, use
`python3 -m expectrail.discovery.freeze verify --root runs/baseline` only with `runs/baseline`
checked out at `c169a5e0da304773587304ed47bc8aabcec80da7`. The record describes that baseline,
not current main; this is separate from the quickstart.
[Advisory discovery scope](docs/capabilities.md#discovery).

[Apache License 2.0](LICENSE) · [Third-party notices](NOTICE).
