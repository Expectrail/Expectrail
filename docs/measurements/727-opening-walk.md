# A draft check for arrival on the opening walk (#727)

The [draft](../../specs/drafts/727/player-reaches-opening-coin.json) requires the player's box to
reach the named opening coin's box on the [smoke route](../../harness/routes/smoke.json) before the
first jump. The 31-frame window covers frames 4–34. The reference's [role
bindings](../../specs/drafts/727/reference/expectrail.project.json) name the player and the first
coin in the authored row at (200, 610). The check uses existing `reaches` semantics with zero
distance between the boxes. Coin collection and speed are separate properties.

An absolute frame coordinate proved unsuitable in the opening walk. In the first clean trace,
the player went from world x=90 to x=216.25, while the legacy projected left edge stayed at x=370.5
across frames 15–34 as the camera followed it. Binding the authored coin gives the evaluator two
objects in the same captured coordinate space.

## Local public controls

Source revision [f24a6c6](https://github.com/Expectrail/Expectrail/commit/f24a6c6c0645a378d906e5d4146aeab18d337462),
engine Godot 4.7.2 stable. All arms used the same 120 Hz physics route and 60 fps observation
mapping. Each had 31 judged frames and a complete window on all three runs. Trace digests agreed
within each arm.

| Arm | Draft result | Evidence | World x before input and before jump |
| --- | --- | --- | --- |
| Clean | 3/3 pass | Reached at frame 23 | 90 → 216.25 |
| [Wrong direction](../../bugs/verification-727/opening-right-turns-left.patch) | 3/3 fail | Never reached in 31 judged frames | 90 → −36.25 |
| Frozen player from the [standard control](../../expectrail/jit/do_nothing.py) | 3/3 fail | Never reached in 31 judged frames | 90 → 90 |
| [Comment-only edit](../../agents/fixtures/operators/comment-only.patch) | 3/3 pass | Reached at frame 23 | 90 → 216.25 |
| [Half speed](../../bugs/verification-727/opening-walk-half-speed.patch) | 3/3 pass | Reached at frame 34 | 90 → 159.375 |

The draft returned a decisive failure under the same-input freeze. Half speed was the first tested
defect and made contact on the final eligible frame. The draft's content stayed fixed when the
wrong-direction case was added. This is evidence for the specific arrival obligation in Q1 and
for observed opportunity in Q3.

In six separate engine-only comparisons with the legacy bundled observation mapping, the
[existing ground assertion](../../agents/specs/player-stays-above-ground.json) passed wrong
direction and half speed 3/3 each, with 120 frames judged. The new draft adds a decisive
different outcome for wrong direction in this diagnostic comparison.

These are engine-only diagnostics. The local host refused Bubblewrap's UID setup, so the harness
used its automatic fallback. The gate reader found one draft, zero approved checks and one route
when pointed at this draft folder. Human review and the normal verifier run remain required for a
release claim.

## Reproduce

Use the pinned engine path in `EXPECTRAIL_GODOT` and run from the checkout with the
repository's Python test dependencies available. The harness applies each patch to its
disposable game copy. For setup review, put the supplied project config in a disposable copy
of the bundled game and select the draft and smoke route from this checkout.

```bash
work=$(mktemp -d)
python3 - "$work" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from expectrail.contracts import load_strict, validate
from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations
from expectrail.jit.do_nothing import controls
from expectrail.project_config import validate as validate_project
from harness.run import run

work = Path(sys.argv[1])
game = Path("game/platformer").resolve()
route = Path("harness/routes/smoke.json")
drafts = Path("specs/drafts/727")
draft = json.loads((drafts / "player-reaches-opening-coin.json").read_bytes())
validate(draft, "test-spec")
config = json.loads((drafts / "reference/expectrail.project.json").read_bytes())
validate_project(config, game)

profile = load_strict(Path("discovery/platformer.profile.json"), "mechanics-profile")
frozen, = controls(game, profile, ["player"])
freeze_patch = work / "freeze.patch"
freeze_patch.write_text(frozen["patchText"])
for name, patch, expected in (
    ("clean", None, "pass"),
    ("wrong-direction", Path("bugs/verification-727/opening-right-turns-left.patch"), "fail"),
    ("frozen", freeze_patch, "fail"),
    ("harmless", Path("agents/fixtures/operators/comment-only.patch"), "pass"),
    ("half-speed", Path("bugs/verification-727/opening-walk-half-speed.patch"), "pass"),
):
    for i in range(3):
        out = work / f"{name}-{i + 1}"
        run(route, out, patch=patch, game=game, project=config,
            godot=Path(os.environ["EXPECTRAIL_GODOT"]), capture_frames=False, sandbox="auto")
        trace = json.loads((out / "trace.json").read_bytes())
        observed = observations(trace, sha256((out / "replay.json").read_bytes()).hexdigest())
        verdict = evaluate(draft, observed, route="smoke", trace=trace, capture_fps=60)
        print(name, i + 1, verdict["result"], verdict["reason"], verdict["framesJudged"])
        assert verdict["result"] == expected and verdict["framesJudged"] == 31
PY
```

For the ground comparison, use the same loop for the wrong-direction and half-speed patches,
read the existing ground spec and pass `project=None` to `run` for the bundled observation path.
The expected result on both arms is pass with 120 frames judged.
