# Player framing on the rightward traversal (#727)

The [draft](../../specs/drafts/727/camera-viewport/checks/player-stays-in-viewport.json) checks
the full bound player drawing box against the native 800 by 480 viewport during frames 70–132
of the public [traversal route](../../harness/routes/traversal.json). The
[project fixture](../../specs/drafts/727/camera-viewport/expectrail.project.json) binds the
player by node path.

The viewport is the reference for this obligation. A camera regression can move the projected
box relative to the capture edges while the player's world position stays the same.
The independent world-space exercise check asks whether the player reached the right-hand
walkway before reversing. At tick 259 the clean player was at x=693.501, y=636.746. The draft
requires the point to lie within 12 world pixels of the rounded coordinate (694, 637). That tick
falls in scored frame 129 at 120 physics ticks and 60 captures per second. The window and the
checkpoint were set from the clean replay before applying the public defect.

The check covers framing on this route. A partially clipped box can still provide a decisive
counterexample. A frame with a fully offscreen or otherwise unobserved box supplies no geometry
for this assertion. A pass requires all 63 observations and the world checkpoint.
High-platform framing and rendered pixels require their own evidence.

## Local public controls

Source revision [640db93](https://github.com/Expectrail/Expectrail/commit/640db937fd3404a0636aab47ccdc803adf2e95a0)
and Godot 4.7.2 stable. All five arms used the same route, bindings and assertion. Each
recorded the 63-frame window.

| Arm | Draft result | Geometry judged | Evidence |
| --- | --- | --- | --- |
| Clean | 3/3 pass | 63/63 | The player box stayed inside the viewport. |
| [Camera stops right](../../bench/jit/public/camera-stops-right/defect.patch) | 3/3 decisive fail | 63/63 | The observed box extended 1.751 captured pixels past the right edge at frame 119. |
| Fixed camera | 3/3 decisive fail | 20/63 | The camera stayed at its start position. The last 43 frames lacked a player box. The first observed overhang was 0.951 px at frame 77. |
| [Comment-only edit](../../agents/fixtures/operators/comment-only.patch) | 3/3 pass | 63/63 | The player box stayed inside the viewport. |
| Frozen player from the [standard control](../../expectrail/jit/do_nothing.py) | 3/3 needs-review | 63/63 | The player stayed at x=90, y=636.5 and the world checkpoint did not fire. |

The fixed-camera control makes the camera a top-level node at its initial world position.
The world checkpoint was identical in clean, right-limit, fixed-camera and comment-only
replays. The horizontal capture transform moved from −21.425 to −291.626 in clean. It stayed
at 100 in the right-limit replays and 310 in the fixed-camera replays across the scored window.
The right-limit arm therefore gives a concrete viewport counterexample while all player boxes
remain observable. The fixed-camera arm fails from measured geometry before the player leaves
the image entirely. The frozen-player arm shows why the world checkpoint matters for Q3.

Two further geometry replays measured the maximum right edge across frames 70–132. It reached
x=434.683 on clean, leaving 365.317 captured pixels of horizontal clearance. With the
right-limit patch it reached x=825.501, an overhang of 25.501 pixels.

These are headless engine diagnostics for Q1–Q3. Bubblewrap could not set its UID map on this
host. The gate reader found one draft, zero approved checks and one route in this fixture.

## Reproduce

Set `EXPECTRAIL_GODOT` to the pinned Godot 4.7.2 binary. Run from the checkout with the standard
Python dependencies. The harness applies all patches in disposable game copies. For a setup
review on the bundled game, copy the supplied project config into a disposable game copy and
select the draft and the existing traversal route.

```bash
python3 - <<'PY'
from difflib import unified_diff
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from expectrail.contracts import load_strict, validate
from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations
from expectrail.jit.do_nothing import controls
from expectrail.observation_timeline import view_for
from expectrail.project_config import validate as validate_project
from harness.run import run

game = Path("game/platformer").resolve()
route = Path("harness/routes/traversal.json")
fixture = Path("specs/drafts/727/camera-viewport")
draft_path = fixture / "checks/player-stays-in-viewport.json"
draft_bytes = draft_path.read_bytes()
draft = json.loads(draft_bytes)
config = json.loads((fixture / "expectrail.project.json").read_bytes())
validate(draft, "test-spec")
validate_project(config, game)

scene_path = "player/player.tscn"
scene = (game / scene_path).read_text()
position = "position = Vector2(0, -28)\noffset = Vector2(0, 50)\n"
assert scene.count(position) == 1
stationary = scene.replace(
    position, "top_level = true\nposition = Vector2(90, 608.5)\noffset = Vector2(0, 50)\n",
)
profile = load_strict(Path("discovery/platformer.profile.json"), "mechanics-profile")
frozen, = controls(game, profile, ["player"])
assert frozen["mode"] == "frozen" and frozen["patchText"], frozen["reason"]

with TemporaryDirectory(prefix="expectrail-camera-viewport-") as tmp:
    work = Path(tmp)
    freeze_camera = work / "freeze-camera.patch"
    freeze_camera.write_text("".join(unified_diff(
        scene.splitlines(keepends=True), stationary.splitlines(keepends=True),
        fromfile=f"a/{scene_path}", tofile=f"b/{scene_path}",
    )))
    freeze_player = work / "freeze-player.patch"
    freeze_player.write_text(frozen["patchText"])
    for name, patch, expected in (
        ("clean", None, "pass"),
        ("right-limit", Path("bench/jit/public/camera-stops-right/defect.patch"), "fail"),
        ("fixed-camera", freeze_camera, "fail"),
        ("harmless", Path("agents/fixtures/operators/comment-only.patch"), "pass"),
        ("frozen-player", freeze_player, "needs-review"),
    ):
        for repeat in range(3):
            out = work / f"{name}-{repeat + 1}"
            replay = run(route, out, patch=patch, game=game, project=config,
                         godot=Path(os.environ["EXPECTRAIL_GODOT"]), capture_frames=False,
                         sandbox="auto")
            trace = json.loads((out / "trace.json").read_bytes())
            observed = observations(trace, sha256((out / "replay.json").read_bytes()).hexdigest())
            verdict = evaluate(draft, observed, route="traversal", trace=trace, capture_fps=60)
            checkpoint = trace["rows"][259]
            print(name, repeat + 1, verdict["result"], verdict["framesJudged"],
                  verdict["reason"], "world checkpoint", checkpoint["player"], flush=True)
            window = range(draft["window"]["fromFrame"], draft["window"]["toFrame"] + 1)
            offsets = [view_for(trace, frame)[4] for frame in window]
            print("camera x offsets", offsets[0], offsets[-1],
                  "isolation", replay["isolation"]["sandbox"], flush=True)
            assert verdict["result"] == expected, verdict
            assert verdict["coverage"]["completeWindow"]
            if expected == "pass":
                assert verdict["framesJudged"] == 63
            if expected == "fail":
                assert verdict["firstFrame"] is not None and "leaves region" in verdict["reason"]
                assert len(set(offsets)) == 1
            if name == "fixed-camera":
                seen = [frame["frame"] for frame in observed["frames"]
                        if frame["frame"] in window and frame["objects"].get("player")]
                assert seen == list(range(70, 90)), seen
            if name == "frozen-player":
                assert verdict["coverage"]["status"] == "not-reached"
    assert draft_path.read_bytes() == draft_bytes
PY
```
