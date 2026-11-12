# Reach: routes for pairs of actions no library probe uses together (#285)

## What changed
Step 3 of #285. One public defect, `no-shooting-in-air`, is in the engine's record whenever a route
shoots in the air, and none of the 25 library probes does: the library never presses two different
actions close together, except moving while firing.

`expectrail/repro/reach.py` makes the missing routes, with no model:

- it compiles every library probe and lists the pairs of different actions each route uses together
  (one pressed while the other is held, or within 20 ticks after the other's press);
- every pair of actions in the game's own catalog that no library route uses together gets two
  probes: hold one for 60 ticks and tap the other three times meanwhile, and the other way round;
- at most eight probes, each a bounded action program for the same route compiler. On the
  platformer: left with right, left with jump, right with jump, jump with shoot; eight probes of
  160 ticks;
- the bug report only orders them (the pair it names first). It is untrusted text and can add no
  action, duration or probe; with eight or fewer to make, every report gets the same set.

`python3 -m expectrail.repro reach` prints the probes for a report. `python3 -m expectrail.repro
visibility --reach` replays them on the bench in place of the library's probes, and the result is
kept as `bench/jit/public/visibility-reach.json`, shown on the bench's page.

Generated checks are not offered these probes: nothing under `expectrail/jit/` reads the module, so
a live run on the bench, the baseline included, is unchanged. A test holds that.

A reach probe is a route. What watches the game along it (the engine's record, or frames for a
visual observer) is the caller's choice; the module reads neither.

## What was run
- On the real engine (Godot 4.7.2, a cloud container, no model, not in CI),
  `python3 -m expectrail.repro visibility --reach --jobs 4`: 8 probes on the clean game twice and
  on each of the 24 defect builds once, 208 replays. Result: a signal moves for 14 defects, the
  record is the same on every reach probe for 10, no error, nothing unstable between the two clean
  replays, no replay made again. `no-shooting-in-air`: `projectile_count` 1 on the clean game, 0 on
  the defect build, on `reach-jump-with-shoot`. The other 13 are defects the library probes already
  showed, so with both sets a signal moves on 18 of 24 where it was 17.
- The same command again with `--only no-shooting-in-air --only air-jump --jobs 2`: the two rows
  are identical to the stored record's.
- `python3 -m unittest tests.test_repro_reach`: 47 tests, OK. They cover what counts as used
  together, what the library misses, the probes (count, length, names, the taps inside the hold),
  that a report only orders (a hostile one, a very long one, values that are not text), the limit,
  catalogs that are refused, the commands, a simulated game where no library probe sees a "cannot
  shoot in the air" defect and `reach-jump-with-shoot` does, and the stored record against the
  bench, the probes and the page.
- The full suite on the branch merged with main: in the pull request.

## Not done
- The probes are not offered to the generator, and no check has been generated on one. No model
  was called. There is still no reproduction rate; the baseline run waits for a person.
- The changed code (the diff map) is not used to order probes: with the bench's no-fix candidate
  it says nothing about the defect.
- `no-shooting-in-air` is not marked `tunedOn` in `defects.json`, though reach was built because of
  it. Changing that file makes the stored library measurement stale, so it belongs in the change
  that offers the probes and measures again. The bench's page says so in words.
- No frames were captured along the reach probes, so nothing here says what they show on screen.
- Reach pairs actions. A behaviour that needs three at once, or a state no pair of presses leads
  to (the pause menu), is still not reached.

## Files
- `expectrail/repro/reach.py` (new), `expectrail/repro/__main__.py`
- `tests/test_repro_reach.py` (new)
- `bench/jit/public/visibility-reach.json` (new), `bench/jit/public/README.md`
- `contracts/repro-visibility.v1.schema.json` (its description only), `docs/contracts.md`, `docs/jit.md`
