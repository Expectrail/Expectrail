# Middle-platform enemy on its return (#727)

The [draft](../../specs/drafts/727/enemy-patrol/checks/middle-enemy-on-return.json) checks one
named enemy after its first turn on the [enemy-patrol route](../../specs/drafts/727/enemy-patrol/routes/enemy-patrol.json).
The player walks until the middle platform is in view, then stops. The
[project fixture](../../specs/drafts/727/enemy-patrol/expectrail.project.json) binds `Level/Enemies/Enemy2`
and the stationary `Level/Flowers/Flower18` by node path.

Both boxes use the same captured coordinate space. The assertion checks that the entire enemy
box stays within the flower's box expanded by 64 captured pixels, the size of one authored tile.
It requires all 31 frames from 460 through 490, a half-second window at 60 captures per second.
At 120 physics ticks per second, the clean trace placed the enemy's world-box
center at x=544.183 on tick 0, x=664.441 on tick 920, and x=653.442 on tick 980. The flower's
world box stayed at `[641.2, 382.2, 666.8, 407.8]`. The route, roles, window, and margin were set
from the clean run before replaying the defect.

The obligation is where this named enemy is during the return. It can catch a freeze at the
authored spawn and an early departure from the region. A stationary enemy already inside the
region could pass. The check uses engine drawing bounds. It gives no sprite-facing, rendered
visibility, patrol speed, or general spawn-count guarantee. An unresolved binding leaves setup
without sufficient observation.

## Local public controls

Source revision [74d30c5](https://github.com/Expectrail/Expectrail/commit/74d30c5d330a9efba2c7412ad4c127b676f003cb)
and Godot 4.7.2 stable. All four arms used the same route, bindings and assertion. All 12 runs
judged the complete 31-frame window.

| Arm | Draft result | Evidence |
| --- | --- | --- |
| Clean | 3/3 pass | The enemy box stayed in the region. |
| [Fast left](../../bench/jit/public/enemy-fast-left/defect.patch) | 3/3 decisive fail | After turning, the enemy left the region early. Its left edge was 37.295 captured pixels outside at frame 460. |
| Frozen enemy from the [standard control](../../expectrail/jit/do_nothing.py) | 3/3 decisive fail | The enemy remained at its authored spawn. Its left edge was 84.4 captured pixels outside at frame 460. |
| [Comment-only edit](../../agents/fixtures/operators/comment-only.patch) | 3/3 pass | The enemy box stayed in the region. |

The separate [missing upper enemy](../../bench/jit/public/enemy-missing/defect.patch) control
passed 3/3 with the complete window. The draft's binding covers the middle-platform enemy only.

These controls exercise specific wrong and harmless changes for Q1 and Q2. The reported
31/31 observations on every replay supply the coverage denominator for Q3. The replays are
headless engine diagnostics. Bubblewrap could not set up its UID map on this host. The gate
reader found one draft, zero approved checks and one route in this fixture.

## Reproduce

Set `EXPECTRAIL_GODOT` to the pinned Godot 4.7.2 binary and run from the checkout with the
repository's Python dependencies. The harness applies committed patches only in disposable
game copies. For setup review on the clean game, copy the supplied project config to a
disposable copy of the bundled game and select the supplied draft and route.

```bash
python3 - <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from expectrail.contracts import load_strict, validate
from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations
from expectrail.jit.do_nothing import controls
from expectrail.project_config import validate as validate_project
from harness.run import run

game = Path("game/platformer").resolve()
fixture = Path("specs/drafts/727/enemy-patrol")
route = fixture / "routes/enemy-patrol.json"
draft_path = fixture / "checks/middle-enemy-on-return.json"
draft_bytes = draft_path.read_bytes()
draft = json.loads(draft_bytes)
config = json.loads((fixture / "expectrail.project.json").read_bytes())
validate(draft, "test-spec")
validate(json.loads(route.read_bytes()), "route")
validate_project(config, game)
profile = load_strict(Path("discovery/platformer.profile.json"), "mechanics-profile")
frozen, = controls(game, profile, ["enemy"])
assert frozen["mode"] == "frozen" and frozen["patchText"], frozen["reason"]

with TemporaryDirectory(prefix="expectrail-enemy-patrol-") as tmp:
    work = Path(tmp)
    freeze_patch = work / "freeze.patch"
    freeze_patch.write_text(frozen["patchText"])
    for name, patch, expected in (
        ("clean", None, "pass"),
        ("fast-left", Path("bench/jit/public/enemy-fast-left/defect.patch"), "fail"),
        ("frozen", freeze_patch, "fail"),
        ("harmless", Path("agents/fixtures/operators/comment-only.patch"), "pass"),
    ):
        for i in range(3):
            out = work / f"{name}-{i + 1}"
            replay = run(route, out, patch=patch, game=game, project=config,
                         godot=Path(os.environ["EXPECTRAIL_GODOT"]), capture_frames=False,
                         sandbox="auto")
            trace = json.loads((out / "trace.json").read_bytes())
            observed = observations(trace, sha256((out / "replay.json").read_bytes()).hexdigest())
            result = evaluate(draft, observed, route="enemy-patrol", trace=trace, capture_fps=60)
            print(name, i + 1, result["result"], result["framesJudged"], result["reason"], flush=True)
            assert result["result"] == expected and result["framesJudged"] == 31, result
            assert result["coverage"]["completeWindow"]
            if i == 0:
                for tick in (0, 920, 980):
                    row = trace["rows"][tick]
                    boxes = {obj["role"]: obj["worldBox"] for obj in row["roleObjects"]}
                    print(tick, boxes["enemy"], boxes["landmark"], flush=True)
                print("isolation", replay["isolation"]["sandbox"], flush=True)
    assert draft_path.read_bytes() == draft_bytes
PY
```

To reproduce the scope control, add
`("upper-missing", Path("bench/jit/public/enemy-missing/defect.patch"), "pass")` to the loop.
