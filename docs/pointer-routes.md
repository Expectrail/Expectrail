# Pointer inputs in a route

Godot routes can put pointer inputs in the existing `expectrail.route/v0` `events`
array, alongside named actions. The [schema](../contracts/route.schema.json) and
[example](../contracts/examples/route-pointer.json) define the format. The
[tests](../tests/test_pointer_routes.py) exercise a button and a pointer-steered
paddle in a small fixture. The later [Breakout trial](outside-trials/breakout-pointer/report.md) records config-only onboarding at the unchanged public pin.

```json
{"tick": 2, "pointer": {"position": [80, 30]}}
{"tick": 3, "pointer": {"position": [80, 30], "button": "left", "pressed": true}}
{"tick": 4, "pointer": {"position": [80, 30], "button": "left", "pressed": false}}
{"tick": 6, "pointer": {"position": [40, 120]}}
```

Each line above is an event object, to place in the array. Positions are pixels
in the game's root viewport: origin at its top left, x right, y down. They are
not world, window or desktop coordinates. The example fixture has a 320 × 180
viewport and a 640 × 360 window; callers use the viewport size. Points outside
that viewport are refused instead of clamped. Events name a physics tick and
are delivered before game physics. Events on the same tick retain their array
order. Button events also set the pointer position. Moves preserve the buttons
already held; positions and button state persist between route events. Supported
buttons are `left`, `right` and `middle`. Release each button explicitly.

The harness delivers ordinary mouse events, including GUI input, and moves the
viewport cursor for games that query its position. Headless replay sets the
window to the project's declared viewport size only for routes with pointer
input. Action-only routes keep their prior behavior. A captured replay should
use a dedicated display: a person moving the same window's pointer supplies
additional input, which is not part of the route. Subviewport targeting, wheel
scrolling and touch input are not implemented.

Normalized episodes retain pointer events in `inputs`. An action-triggered check
still requires that named action; a pointer click is not invented as a `shoot`
action. Action-pair discovery and action-hold symptom heuristics consider only
named actions. The current Unity adapter and trusted action-catalog report-route
path refuse pointers explicitly; neither silently replays a partial route. Web
routes use their separate, unchanged contract.

`inspect` now reports authored pointer-read hints and possible start controls without
running the project. `init` and `route --auto` use an opt-in disposable headless
probe when those hints require it. The engine reports visible/enabled buttons,
root-viewport boxes and actual `pressed` connections under the optional trace
[`inputProbe`](../contracts/examples/trace-input-probe.json) field. A start-labelled
control needs one matching start handler; ambiguous, disabled, truncated or
unconnected menu evidence is refused with the controls found. This is a conservative
heuristic for common GDScript scenes, not understanding arbitrary UI code or translated
labels. Unknown start logic needs a user-supplied route.

When there are no authored movement actions and a body script reads the pointer,
the draft clicks the measured start control and sweeps across the measured viewport.
Script hints alone do not prove movement. `route --auto` writes the route only after
three complete identical headless traces and observable bound-player movement;
a stationary pointer plan is refused. `init` writes a draft for review and does
not claim that it verified a game. A control-only input map is refused instead
of emitting a pause-only route. Reviewing a saved draft does not execute its game.

Ordinary action routes do not request a probe. Eight real rendered legacy replays
retain [identical trace bytes and decisions](menu-routes-evidence/parity-comparison.json).
The [menu/paddle fixture tests](../tests/test_menu_routes.py) have offline stand-ins
and real Godot tests. The [Breakout report](outside-trials/breakout-pointer/report.md)
separates raw draft engine diagnostics from the CLI's needs-review decisions.
No draft check was approved.
