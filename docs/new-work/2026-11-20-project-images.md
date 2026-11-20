# The review page offers the project's images when the player is drawn with none (#688)

## What changed
Crate Run's player is a filled `Polygon2D`, so `init` writes a review draft with no image, and the
review page (`expectrail onboard`) said only "No complete choice is available". A developer who does
not edit JSON was stuck there.

- `onboarding.inspect` now lists the project's image files as `projectImages` when the one player
  has no sprite saved under it at all: at most 12, top-level files first, the project icon last
  (`projectIcon`), and `moreProjectImages` for the rest. Hidden folders (`.godot`), folders with
  `.gdignore`, links and files outside the project are skipped. A sprite whose image cannot be read
  (an external `SpriteFrames`) is not "no sprite" and gets no list. `inspect` prints the list, and
  `init` says how many images the review page offers.
- The review page offers each one as a choice, labelled "Not drawn under `Player`: an image in the
  project" (and "This is the project's icon" for the icon). Choosing one downloads the whole config
  through the same validated download as the existing image choice. More than 12 images: the page
  says how many more and how to name one.
- `init` never binds one of these images, and the review draft file does not change: the page reads
  the project again, so drafts written before this change still review.
- `tools.setup_rehearsal` now takes the person's image from the review page's own download link
  (a new "review page" step), and fails if that choice is missing, offered twice, or not labelled as
  not drawn under the player. The scripted texture edit is gone.

## What was run
- `python3 -m unittest tests.test_onboard_project_images tests.test_onboard tests.test_inspect_atlas tests.test_init_inspect`:
  26 tests, OK.
- `python3 -m unittest tests.test_setup_rehearsal` with the pinned Godot 4.7.2 at `tools/godot` and
  `xvfb-run`: 8 tests, OK, including `RealGodotTest` (the whole Crate Run rehearsal).
- `xvfb-run -a python3 -m tools.setup_rehearsal --project crate-run --out DIR` with Godot: every step
  ended as expected. init wrote the review draft with no texture and said "The review page offers 1
  image file in the project"; the review page offered `res://crate.svg` labelled "Not drawn under
  Player: an image in the project"; with that page's config, the unchanged game gave needs-review
  (exit 2, no vision) and the seeded fall-through gave reject (exit 1).
- Four mutations were each caught by the new tests: offering images when a sprite's image is
  unreadable, dropping the "Not drawn under" label, listing hidden folders, and init binding a
  project image.
- The review page for Crate Run was opened in Chromium at 1280 and 390 pixels wide: the crate's
  image, its label and the save button show in one card; no horizontal scroll at either width.
- The full suite: see the pull request.

## Not done
- The local app's Check folders (#370, the app owner's) does not show these images yet. It can read
  `projectImages`, `moreProjectImages` and `projectIcon` from `onboarding.inspect`, the same report the
  page uses.
- An accept on Crate Run still needs a vision key and spend (#260).

## Files
- `expectrail/onboarding.py`, `expectrail/onboard.py`
- `tools/setup_rehearsal.py`
- `tests/test_onboard_project_images.py`, `tests/test_setup_rehearsal.py`
- `docs/project-config.md`
- `docs/new-work/2026-11-20-project-images.md`
