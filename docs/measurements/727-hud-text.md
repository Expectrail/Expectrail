# Pause-menu text coverage on the bundled game (#727)

The public `hold-right-then-toggle-pause` probe runs 464 physics ticks. It releases right at
tick 250 and taps pause at ticks 310–314. The menu displays the authored coin-counter Label.
The stuck-counter defect suppresses the label update while leaving collection intact. In the
public screen diagnostic, 77 of 232 frames differed, starting at frame 155. The reported change
box at frame 166 was `[148, 34, 188, 66]` in the HUD region. The public record identifies no
observer reading for the row.
[Stuck-counter defect](../../bench/jit/public/coin-counter-stuck/defect.patch) ·
[Public screen evidence](../../bench/jit/public/menu-evidence-coin-counter-stuck.json)

The same probe has an engine-state result. In a separate 15-replay preflight the anonymous
visible integer was 5 on clean and comment-only, 10 on double count, and 0 on a stuck label,
three runs per arm, with five pickups each. The frozen player opened pause and read 0 with zero pickups.
That control leaves score-after-pickups unexercised. #744 covers an exact engine-state check
bound to the particular Label. Engine integers and coincident pixel changes cannot establish
which glyphs were rendered.
[Exact-score preflight](https://github.com/Expectrail/Expectrail/issues/744#issuecomment-7067680987)

## Current contract boundary

The gate test-spec schema rejects text equality. Current configured spatial bindings require
world-space node geometry, while the coin counter is a Godot Control Label in the pause UI.
The template and SAM-anchor pixel observers both refuse the bound `coins-counter` text role.
The current pixel-only offer also omits this pause probe. The standard do-nothing generator
refuses the `hud` and `label` classes. Given these constraints, the rendered-text clean,
public-defect, do-nothing and harmless checks were unrun. No rendered-text draft is qualified.
This finding preserves the distinction between an unavailable observation and an ordinary
counterexample for Q1 and Q3.
[Test-spec schema](../../contracts/test-spec.schema.json) · [Pixel observer bindings](../../expectrail/jit/pixel.py) · [Configured roles](../../harness/godot/expectrail_roles.gd)

## Reproduce the capability checks

Run from the checkout with the repository's Python dependencies. This checks the existing
route library, parser, control generator and committed screen record. It invokes no engines
or pixel observers.

```sh
python3 - <<'PY'
import json
from pathlib import Path

from expectrail.contracts import ContractError, validate
from expectrail.discovery.route_compiler import compile_route
from expectrail.jit import do_nothing, offer, pixel

profile = json.loads(Path("discovery/platformer.profile.json").read_text())
game = Path(profile["game"]["path"]).resolve()
report = Path("bench/jit/public/coin-counter-stuck/report.txt").read_text()
name = "hold-right-then-toggle-pause"
libraries = {
    setting: {probe["id"]: probe for probe in offer.library(
        profile["actions"], setting, report, profile=profile, game=game,
    )}
    for setting in (offer.MENU, offer.CONTROL, offer.PIXEL)
}
assert name in libraries[offer.MENU] and name in libraries[offer.CONTROL]
assert name not in libraries[offer.PIXEL]
probe = libraries[offer.CONTROL][name]
route = compile_route(probe["program"], name=name, description=probe["description"],
                      actions=offer.route_actions(profile, probe))
assert route["ticks"] == 464
print("Public menu route:", route["events"])

screen = json.loads(Path("bench/jit/public/menu-evidence-coin-counter-stuck.json").read_text())
row = next(row for row in screen["rows"] if row["probe"] == name)
assert row["observer"] is None and row["record"] is None
diff = row["screen"]
assert (diff["frames"], diff["of"], diff["firstFrame"], diff["atFrame"], diff["box"]) == (
    77, 232, 155, 166, [148, 34, 188, 66],
)
print("Screen diagnostic: 77 of 232 changed frames, with no observer reading")

for observer in ("visual-sensor", "sam-3.1-anchor"):
    proposed = {
        "id": "hud-capability", "statement": "The coin counter is visible.",
        "object": "coins-counter", "observer": observer, "probe": name,
        "predicate": {"type": "visible", "minFraction": 1, "minScore": 0.5},
    }
    parsed, reason = pixel.parse_candidate(
        proposed, pixel.BUNDLED_BINDINGS, {name}, pixel.proposed(observer),
    )
    assert parsed is None and reason and "(text)" in reason
    print(reason)

geometry = {
    "format": "expectrail.test-spec/v0", "id": "hud-capability",
    "instruction": "Observe the HUD.", "objects": {"counter": {"prompt": "coin counter"}},
    "assertion": {"type": "visible", "object": "counter"},
}
validate(geometry, "test-spec")
try:
    validate({**geometry, "assertion": {"type": "text-equals", "object": "counter",
                                       "expected": "5"}}, "test-spec")
except ContractError as error:
    assert str(error).startswith("test-spec: assertion:")
    print("Gate rejects text equality")
else:
    raise AssertionError("Gate unexpectedly accepts text equality")

for kind in ("hud", "label"):
    try:
        do_nothing.control(game, profile, kind)
    except do_nothing.NoControl as error:
        print(error)
    else:
        raise AssertionError(kind)
PY
```
