# A way to run the public reproduction bench live, and the scorer that reads the run (#285)

## What changed
The public bench had 24 defects and no way to measure a reproduction rate on them. This adds the
three things a baseline run needs. None of them has been run live.

- **One stand-in candidate for every defect**, `bench/jit/public/no-fix.patch`: a comment line added
  to the game's `README.md`, which the engine never loads. The generator judges a candidate change
  and reproduction has none; with this one, the check comes from the bug build and the report alone
  (issue #285, step 6), the model learns nothing about a defect from the patch, and, because no
  profile claim names that file, the diff map keeps all 25 probes. The first draft put the comment
  in `project.godot`; a test showed the profile's `player.jump` claim names that file, which would
  have narrowed the probes to the jump family for every defect, so it was moved.
  `python3 -m expectrail.repro cases` prints the 24 cases and refuses a no-fix patch that is not
  one comment line in that file, or a bench with a defect that touches it.
- **A `repro` mode in `.github/workflows/jit.yml`**: from main only, the cases from the committed
  bench and nothing typed at dispatch, through the same measure, propose, replay, revise and replay
  jobs as any live change, at $2 a defect; then a `repro-score` job with no secret. The diff adds no
  secret, no `environment:`, no permission: the keyed jobs are the two that were keyed before.
- **The scorer**, `python3 -m expectrail.repro score` (`expectrail/repro/score.py`, record
  `expectrail.repro-score/v1` with schema and example, reader `score.load` and `score-render`).
  A defect is reproduced when a generated check, in the record's own runs, passed on the clean game
  3 of 3, failed on the bug build 3 of 3, and failed 3 of 3 again on the bug build with the no-fix
  patch. The last three runs are stricter than the issue's wording: the two builds behave the same,
  so a check that fails on one and not the other is flaky. A check's standing is worked out from
  its runs; a record whose own `valid` flag disagrees, or that is for another candidate, defect or
  report, or ran each check some other number of times, is "no result". No result stays in the
  denominator. A miss gets `budget`, `flaky`, `wrong-predicate`, `no-signal` or `undetermined`,
  the last three from the committed visibility record. The scorer never gives `route-never-reaches`
  or `probe-language`: no record separates them, and the reader refuses a record that carries one.

## What was run
- `python3 -m unittest tests.test_repro_score`: 61 tests, OK. They cover every outcome and reason
  on records written by hand, the refusals, the reader, and one whole run of the real pipeline on
  the simulated game with a fake model, given the air-jump case exactly as `cases` prints it: the
  record has all probes in its diff map, the bug build as its only near miss, and scores as
  reproduced by `jit-no-extra-air-jumps`.
- The no-fix patch on the real engine, in a cloud container with the pinned Godot 4.7.2, on
  November 11, not in CI, no model: the clean game and each of the 24 defect builds were replayed
  once with the patch and once without, on one probe each (the probe where the visibility record
  shows the defect's first signal moving most, `hold-right` where it shows none; 12 different
  probes in all). `trace.json` was byte-identical in 25 of 25 pairs, no replay was made again, and
  the near-miss generator gave 0 near misses of the patch on each of the 24. One probe and one
  replay per build: it shows the patch does not change those records, not every probe.
- `python3 -m expectrail.repro check`: 24 defects, 24 apply. `python3 -m expectrail.repro cases`:
  24 cases.
- The model prompt's size was estimated offline for the air-jump report with no measurements in it:
  2,861 tokens with the no-fix patch against 2,863 with the known-bugs bench's comment-only patch,
  so a case should cost about what a known-bugs case did.
- `python3 -m tools.merge_guard --base origin/main --head HEAD` and the full suite,
  `python3 -m unittest discover -s tests -t .`, on the branch (cut from current main): the results
  are in the pull request.

## Not done
- **No live run, so no reproduction rate and no miss breakdown.** The `repro` mode has never been
  dispatched. It calls a paid model from main; a person starts it. Its plan step and its score step
  were not run in Actions: the commands they call were run here, the YAML around them was only
  parsed and read by tests.
- The scorer has read no record from a live run.
- The miss reason is a rule over two records, not a diagnosis. For the five defects the library
  probes do not see, it says `undetermined`; the bench's page has what was found by hand.
  `wrong-predicate` for `coin-stays` would be unfair to the model: its only signal is a side effect.
- Steps 3 to 6 of the issue (reach, signals, proposal evidence) are not started. Step 6's rule is
  met by construction for this bench, since no case has a candidate fix; marking checks that
  needed a candidate's patch in other runs is not built.

## Files
`expectrail/repro/score.py`, `expectrail/repro/__main__.py`, `bench/jit/public/no-fix.patch`,
`bench/jit/public/README.md`, `bench/jit/README.md`, `contracts/repro-score.v1.schema.json`,
`contracts/examples/repro-score.json`, `.github/workflows/jit.yml`, `docs/jit.md`,
`docs/contracts.md`, `tests/test_repro_score.py`
