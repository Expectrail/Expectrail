# Gun cooldown evidence and the test-spec boundary (#727)

The bundled Godot gun starts its `Cooldown` timer after a successful shot. The authored
timer waits 0.3 seconds. The public long-cooldown patch changes the timer to 1.5 seconds.
The probe presses shoot at ticks 30 and 90, half a second apart at 120 physics ticks per second.
This gives both clean presses time to fire and exposes the public cooldown defect.
[Gun script](../../game/platformer/player/gun.gd) · [Timer scene](../../game/platformer/player/player.tscn) · [Public defect](../../bench/jit/public/gun-cooldown-long/defect.patch)

## Local public controls

Measured on [305cefd](https://github.com/Expectrail/Expectrail/commit/305cefdc99eb84c3f51e3dbf70b92d897c422fb1)
with pinned Godot 4.7.2. Each arm completed 132 ticks on all three repeats. The advisory
`min_event_count` operation required at least two observed projectile spawns in the complete
episode. The visibility control used a valid test-spec and the same replay's engine geometry.

| Arm | Spawn ticks on each repeat | Minimum interval | Advisory trace verdict | Visibility control |
| --- | --- | --- | --- | --- |
| Clean | 31, 91 | 60 ticks | 3/3 pass | 3/3 pass |
| Long cooldown | 31 | Unavailable | 3/3 decisive fail | 3/3 pass |
| Never-made projectile | 0 spawns in a complete trace | Unavailable | 3/3 decisive fail | 3/3 pass |
| Comment-only edit | 31, 91 | 60 ticks | 3/3 pass | 3/3 pass |

The two-shot obligation fails when only one spawn was observed and when the complete trace
records zero. The minimum-interval signal needs two spawns, so both of those cases have no
interval reading. This probe checks readiness after half a second. Earlier readiness and extra
spawns require separate evidence.

## Gate finding

The recorder and advisory evaluator can distinguish this cooldown defect. The gate's test-spec
contract supports `visible`, `inside-region`, `never-crosses` and `reaches`. Its timed windows
let geometry assertions express position or visibility deadlines. Its world checkpoints
establish that a replay reached a state. The schema refused `min_event_count` as a gate
assertion in this diagnostic. The gate reader counted the geometry file as one draft and refused
both the event-count operation inside a test-spec and the advisory trace-spec as a gate file.
The current gate has no direct projectile count or interval assertion.
[Test-spec contract](../../contracts/test-spec.schema.json) · [Trace-spec contract](../../contracts/trace-spec.v1.schema.json)

The visibility control passed all 12 runs with 46 frames judged each, including the complete
zero-shot arm. Those runs illustrate Q1–Q3 on these public controls. The results are headless
engine diagnostics without Bubblewrap isolation. The trace verdict is advisory, and the
geometry control was local. No gate draft is proposed by this finding.

## Reproduce

Set `EXPECTRAIL_GODOT` to the pinned 4.7.2 binary. Run from the checkout with the repository
Python dependencies. The harness applies the patches in disposable game copies.

```bash
python3 - <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from expectrail.contracts import ContractError, load_strict, validate
from expectrail.evaluator import evaluate as evaluate_geometry
from expectrail.gate.verify import observations, read_checks
from expectrail.jit.do_nothing import controls
from expectrail.trace.evaluator import evaluate as evaluate_trace
from expectrail.trace.normalize import from_run_dir
from expectrail.trace.signals import min_projectile_interval_ticks, spawn_ticks
from harness.run import run

game = Path("game/platformer").resolve()
route = {
    "format": "expectrail.route/v0",
    "name": "cooldown-probe",
    "ticks": 132,
    "seed": 1,
    "events": [
        {"tick": 30, "action": "shoot", "pressed": True},
        {"tick": 32, "action": "shoot", "pressed": False},
        {"tick": 90, "action": "shoot", "pressed": True},
        {"tick": 92, "action": "shoot", "pressed": False},
    ],
}
geometry_spec = {
    "format": "expectrail.test-spec/v0",
    "id": "cooldown-player-visible",
    "instruction": "Observe the player during the two-input timing probe.",
    "objects": {"player": {"prompt": "blue robot"}},
    "assertion": {"type": "visible", "object": "player", "minFraction": 1},
    "window": {"fromFrame": 10, "toFrame": 55},
    "coverage": {"routes": [route["name"]], "minFrames": 46},
}
trace_spec = {
    "format": "expectrail.trace-spec/v1",
    "id": "cooldown-two-spawns",
    "origin": "AUTO_TRACE",
    "statement": "Two shoot presses half a second apart produce at least two projectile spawns.",
    "expectationRef": {"claimId": "weapon.cooldown", "authority": "inferred_code"},
    "scope": {"class": "projectile"},
    "window": {"kind": "episode"},
    "operation": {"type": "min_event_count", "event": "projectile_spawn", "min": 2},
    "evidenceRequirement": {"minimumTriggers": 1, "minimumEvaluations": 1, "completeWindow": True},
    "guards": [],
}
validate(route, "route")
validate(geometry_spec, "test-spec")
try:
    validate({**geometry_spec, "assertion": trace_spec["operation"]}, "test-spec")
except ContractError as error:
    assert str(error).startswith("test-spec: assertion:"), error
    print("test-spec refuses min_event_count as a gate assertion", flush=True)
else:
    raise AssertionError("numeric trace operation unexpectedly accepted by test-spec")

profile = load_strict(Path("discovery/platformer.profile.json"), "mechanics-profile")
control, = controls(game, profile, ["projectile"])
assert control["mode"] == "never-made" and control["patchText"], control["reason"]

with TemporaryDirectory(prefix="expectrail-cooldown-") as tmp:
    root = Path(tmp)
    route_path = root / "route.json"
    route_path.write_text(json.dumps(route))
    checks = root / "checks"
    checks.mkdir()
    check_path = checks / "cooldown.json"
    check_path.write_text(json.dumps(geometry_spec))
    listed = read_checks(root, "checks", ["route.json"])
    assert (listed.drafts, len(listed.specs), listed.problems) == (1, 0, [])
    for invalid in ({**geometry_spec, "assertion": trace_spec["operation"]}, trace_spec):
        check_path.write_text(json.dumps(invalid))
        refused = read_checks(root, "checks", ["route.json"])
        assert (refused.drafts, len(refused.specs)) == (0, 0)
        assert any("not a valid test spec" in problem for problem in refused.problems)
        print(refused.problems[0], flush=True)

    no_projectile = root / "never-made.patch"
    no_projectile.write_text(control["patchText"])
    for name, patch, count, expected in (
        ("clean", None, 2, "pass"),
        ("long-cooldown", Path("bench/jit/public/gun-cooldown-long/defect.patch"), 1, "fail"),
        ("never-made", no_projectile, 0, "fail"),
        ("harmless", Path("agents/fixtures/operators/comment-only.patch"), 2, "pass"),
    ):
        for repeat in range(1, 4):
            out = root / f"{name}-{repeat}"
            replay = run(route_path, out, patch=patch, game=game, project=None,
                         godot=Path(os.environ["EXPECTRAIL_GODOT"]), capture_frames=False,
                         sandbox="auto")
            episode = from_run_dir(out, route, episode_id=f"{name}-{repeat}")
            ticks = spawn_ticks(episode)
            interval = min_projectile_interval_ticks(episode)
            trace_verdict = evaluate_trace(trace_spec, episode)
            trace = json.loads((out / "trace.json").read_bytes())
            seen = observations(trace, sha256((out / "replay.json").read_bytes()).hexdigest())
            geometry = evaluate_geometry(geometry_spec, seen, route=route["name"], trace=trace)
            print(name, repeat, ticks, interval, trace_verdict["result"], geometry["result"],
                  geometry["framesJudged"], replay["isolation"]["sandbox"], flush=True)
            assert episode["physicsTicksPerSecond"] == 120
            assert len(episode["samples"]) == route["ticks"]
            assert ticks is not None and len(ticks) == count
            assert interval == (60 if count == 2 else None)
            assert trace_verdict["coverageComplete"] and trace_verdict["result"] == expected
            assert geometry["result"] == "pass" and geometry["framesJudged"] == 46
PY
```
