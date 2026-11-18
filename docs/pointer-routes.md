# Pointer inputs in a route

Godot routes can put pointer inputs in the existing `expectrail.route/v0` `events`
array, alongside named actions. The [schema](../contracts/route.schema.json) and
[example](../contracts/examples/route-pointer.json) define the format. The
[tests](../tests/test_pointer_routes.py) exercise a button and a pointer-steered
paddle in a small fixture; this is not evidence of successful Breakout onboarding.

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

This is the route-contract half of #259's pointer/menu follow-up. `init` and
`route --auto` still use their existing action-map generation. Automatically
finding a start control, reporting pointer steering in `inspect`, generating
pointer sweeps, and rerunning Breakout at its pinned commit remain to be built
and measured. No draft check was approved by this change.
