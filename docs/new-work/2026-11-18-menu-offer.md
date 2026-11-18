# The generator can be offered the menu probes: `--offer signals-reach-evidence-menu` (#285)

## What changed
The #285 audit left one gap for the two counter defects (`coin-counts-twice`, `coin-counter-stuck`): the
menu probes reach the pause menu where the counter is drawn, and a check can now read that counter
(`ui_integer_at_end`) against `coins_collected`, but no offer of the generator had the menu probes.

- **A new setting, `signals-reach-evidence-menu`** (`expectrail/jit/offer.py`, `MENU`): the evidence
  setting's probes, signals and evidence, plus the three menu probes of `expectrail/repro/menu.py`. Every
  other setting's prompt and probe list are unchanged (the baseline digests still hold; a test shows the
  menu system prompt is the evidence prompt plus one paragraph, `intent.MENU_TEXT`).
- **Where the menu action comes from:** the reviewed mechanics profile, in a new optional field
  `menuActions` (`contracts/mechanics-profile.v1.schema.json`: plain names, one or two).
  `discovery/platformer.profile.json` names `toggle_pause`. It is refused unless the game's
  `project.godot` declares it, or if it is already in the action catalog. Under the menu setting a
  profile without `menuActions` generates nothing, with the reason in the record.
- **Who may press it:** only the menu probes the offer made. `offer.route_actions` gives a menu probe the
  catalog plus the menu action; `run.generate` compiles every probe the model wrote with the catalog alone,
  whatever family it claims, and the prompt's `actions` list stays the catalog. The measure step and the
  evidence's frame capture compile with `route_actions` too.
- **Records:** a probe from a menu probe has `source: "menu"` (`contracts/jit-run.v1.schema.json`); the
  offer enum gains the new setting there and in `contracts/repro-score.v1.schema.json`. New example
  `contracts/examples/jit-run-menu.json`, written by the simulated run in the tests.
- **The profile's digest changes.** Every run record's `inputs.profileSha256` is the digest of the profile,
  so records made after this change carry a new one. The recorded runs under `bench/` are left as they
  were; `contracts/examples/jit-run.json`, which a test rebuilds from the simulated game, gets the new
  digest. Nothing compares a record's profile digest with the current profile.
- **jit.yml:** the `offer` input and the plan's check accept the new setting. No secret, environment or
  permission is added. Its measure job gets the evidence setting's timeout and packages (the name starts
  with `signals-reach-evidence`).

## What was run
- `python3 -m unittest tests.test_jit_offer_menu`: 22 tests, OK (simulated game with coins and a counter
  label; a counter check on `hold-right-then-toggle-pause` is kept and catches a candidate that does not
  fix the counter; the same check on a walk is not kept; a model probe claiming to be a menu probe and
  pressing `toggle_pause` is refused by the route compiler).
- Full suite on the branch (main cd57180 plus the change): see the pull request for the count.
- Existing tests changed because what they guarded changed on purpose: `tests/test_repro_menu.py`
  (`NotOfferedToTheGenerator` now holds that only `offer.py` under `expectrail/jit/` reads the menu module
  and no setting but the menu one imports it), `tests/test_jit_offer.py` (the list of settings, the plan's
  message, and its proposal helpers pass the profile), `tests/test_jit_offer_evidence.py` (the plan's
  pattern), `tests/test_trace_ui_integer.py` (the menu setting offers the counter reading too),
  `tests/test_schema_pattern.py` (a sample for the new name pattern).
- Nothing was dispatched, no engine run, no model call, nothing spent.

## Not done
- No live run under the new setting. It is Sean's to dispatch (cost on #285).
- The menu probes' evidence is made by the measure step like any probe's; it was not recaptured on the
  real engine for this change.
- The diff map gives menu probes no family of their own: a candidate that maps to known families keeps
  only those families' probes, as with the reach probes.

## Files
- `expectrail/jit/offer.py`, `expectrail/jit/run.py`, `expectrail/jit/measure.py`, `expectrail/jit/cli.py`,
  `expectrail/jit/intent.py`, `expectrail/repro/screen.py`, `expectrail/repro/menu.py` (docstring)
- `contracts/mechanics-profile.v1.schema.json`, `contracts/jit-run.v1.schema.json`,
  `contracts/repro-score.v1.schema.json`, `contracts/examples/jit-run-menu.json`
- `discovery/platformer.profile.json`
- `.github/workflows/jit.yml`
- `contracts/examples/jit-run.json` (profile digest)
- `tests/test_jit_offer_menu.py` (new), `tests/test_jit_offer.py`, `tests/test_jit_offer_evidence.py`,
  `tests/test_repro_menu.py`, `tests/test_trace_ui_integer.py`, `tests/test_schema_pattern.py`
- `docs/jit.md`, `docs/repro-audit.md`, `docs/new-work/2026-11-18-menu-offer.md`
