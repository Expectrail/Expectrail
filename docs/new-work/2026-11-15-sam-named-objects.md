# Pixel checks can name the enemy and the bullet; the observer is pointed at their logged boxes (#286)

## What changed
Until now a pixel check could name only the player: the observer was pointed at the player's logged
body box. #508 made the harness log each enemy's and bullet's own box. This change points the observer
at those boxes, so the menu offers `enemy` and `bullet` to `sam-3.1-anchor`.

- `expectrail/jit/pixel.py`:
  - **Bindings.** `enemy` is a bound role. `enemy` and `bullet` are bound with
    `"anchor": "engine-boxes"`. `pixel.OBSERVERS["sam-3.1-anchor"]["boxes"]` lists the roles the
    observer is pointed at. An `engine-boxes` role is refused for an observer not pointed at its boxes,
    in `parse_candidate` and in the menu, from the same table.
  - **Judging.** A check about such a role is judged per object, by id, on that object's own frames
    (`named_observations`, `_judge_named`). It fails when any one fails and passes when every one
    passes. It is `needs-review` on any gap: a frame not asked about, or a box with no answer. It is
    also `needs-review` when none was on screen in the window. `inside-region` uses each object's own
    logged box.
  - **Cost.** `MAX_BOXES = 3` images a frame. `cost` reserves that much for a check about such a role.
  - **Reading the answer.** `observe` passes `objects` to the observer. It refuses an answer about other
    roles than asked, a frame without a number, or more than `MAX_BOXES` boxes in a frame.
- `expectrail/jit/sam_observer.py`:
  - **Asking.** `SamAnchorObserver(...)(run_dir, route, objects=...)` asks SAM about every object of
    each named role on screen, one image a box, at its logged box widened by `pad`
    (`agents/sam_anchor.py` `object_boxes`). The run gains `objects[role]`, one row a planned frame.
  - **Not asked.** A frame with more than `MAX_BOXES` of one role on screen is not asked about. Neither is
    a frame with no camera, or one from a trace without `objectBoxes`.
  - **Budget.** `most_images(route, objects)` is what the budget reserves.
  - **Recorded answers.** `RecordedSamClient` answers box by box from a recording's `objects`.
- `expectrail/jit/run.py`: the in-process pixel replay asks about the named roles that the checks on
  that probe name, and only those. It reserves `MAX_BOXES` images a frame for each of them.
  The capture job writes those roles into each stored replay.
- `expectrail/jit/pixel_jobs.py`: a stored replay may carry `objects.json` (`{"objects": [...]}`).
  `pixel-ask` reads it as untrusted data: only roles the observer is pointed at, each once. It reserves
  for those roles, and asks about them.
- `expectrail/repro/pixel_reach.py`: an offered role with logged boxes is measured by its boxes
  (`offered_named`). Leaving it out (`--named none` while the menu offers it) is refused, because the
  measurement would miss it. The committed record is unchanged, since it was measured that way already.
  The bench page's sentence about the named objects now says the menu offers them.
- `docs/jit.md`: what is offered, asked, judged and reserved, and that none of it has been run live.

## What was run
- `python3 -m unittest tests.test_jit_pixel_named`: 25 new tests, OK. These cover a scripted SAM
  client on synthetic replays:
  - which boxes are asked about, and the images charged;
  - a stop part way, and what it charges;
  - every refusal and gap;
  - pass, fail and `needs-review`, and the keep rule;
  - recorded answers replayed box by box;
  - the reservation in `run._pixel_stage`, and the capture-and-ask path.
- The pixel test modules (`tests.test_jit_pixel*`, `tests.test_jit_sam_observer`,
  `tests.test_jit_cli_observer`, `tests.test_repro_pixel_reach`, `tests.test_repro_score_pixel`,
  `tests.test_object_boxes`): OK.
- Full suite: see the pull request.

Nothing was dispatched and nothing was spent: no model call and no SAM call.

## Not done
- **No SAM answer about an enemy or a bullet has been recorded.** Whether SAM finds them at their boxes
  is for a live run to say. That run waits on Sean. With two named roles, a probe now costs up to
  `(1 + 3 x 2)` images a planned frame, against 1 before. The first live run should name one role per
  probe.
- **The player is still asked about on every replay**, even when no check on that probe names it.
- **Not on main yet.** This slice is stacked on #508 (the logged boxes). It should be reviewed after #508.
- **Unity.** The Unity harness logs no object boxes, so a check about the enemy or the bullet there is a
  gap on every frame.

## Files
`expectrail/jit/pixel.py`, `expectrail/jit/sam_observer.py`, `expectrail/jit/run.py`,
`expectrail/jit/pixel_jobs.py`, `expectrail/repro/pixel_reach.py`, `bench/jit/public/README.md`,
`docs/jit.md`, `tests/test_jit_pixel_named.py`, `tests/test_jit_pixel.py`, `tests/test_jit_pixel_offer.py`,
`tests/test_repro_pixel_reach.py`, `docs/new-work/2026-11-15-sam-named-objects.md`.
