# Configured Godot role boxes (#259)

For a replay with `expectrail.project/v1` bindings, `trace.json` declares
`capabilities.roleBoxes: true` and records `roleObjects` on every physics tick.
The existing unconfigured trace format and observation path are unchanged.
The contract is [trace.schema.json](../contracts/trace.schema.json); the small
[example](../contracts/examples/trace-role-boxes.json) is synthetic.

Each instance records:

- `role`: the config binding's name, including custom names;
- `id`: its scene-relative path (literal `#` doubled), with a generation suffix for replacement instances;
- `worldBox`: its measured axis-aligned bounds in world pixels, y down;
- `box`: the same geometry's bounds in captured-frame pixels, before clipping;
- `visible`: the engine's visibility-in-tree state for its measured drawing;
- `boundsSource`: `drawing`, or an explicit `collision` fallback.

The recorder resolves bindings every tick. A group can name several instances;
`player` must be unique. A short node name must be unique even when one match is
at the scene root. Full node paths disambiguate. Spawned instances appear on the
first recorded tick they exist; freed instances disappear. Hidden instances retain
their bounds and have `visible=false`. A binding never found during the route, an
ambiguous binding, or a present object without supported measurable bounds stops
the replay with a named setup error and no trace.

Drawing bounds cover `Sprite2D`'s current rect, `AnimatedSprite2D`'s current frame,
and `Polygon2D` vertices, with node transforms. Hidden components do not enlarge a
visible object; a fully hidden object retains its measured bounds with `visible=false`. They exclude other bound roots and
nested physics bodies/areas. With no supported drawing, enabled collision shapes
and polygons provide the explicitly labelled fallback. A shape uses its bounding
rectangle. These are geometry bounds, not an opaque-pixel outline. Visibility in
this record does not prove alpha, occlusion, shader output, or pixels on screen.
Vision is still needed for an accept. Custom drawing, tile layers bound as an object,
and separate canvases/viewports are not supported as role geometry; unsupported
bindings refuse rather than invent a box. Ground need not be a bound role: the
existing measured ground line remains available.

Camera2D updates after physics. A tick's screen box uses the following tick's
camera, matching the existing trace reader; the last tick keeps its own camera.
The recorder transforms the actual measured vertices, so rotation does not expand
a world AABB a second time. The trace includes the viewport size. In headless
configured replays the recorder sets the window to the game's declared size;
otherwise Godot can leave it at 64 by 64. Configured replays also import their
staged assets, including `.import` mappings absent from a source checkout.

`agents.observations` uses the measured role boxes for configured engine
observations and the existing engine-agreement filter. Observations omit hidden
and fully offscreen objects. Agreement references retain their engine placements;
a placement alone cannot create a visual detection. A configured trace predating
`roleObjects` still loads, but cannot supply these observations: no bundled coin
size or player-foot offset is substituted. An absent measurement is not a pass.
Unconfigured old traces retain their existing reader.

Configured reference-ground comparisons use the measured player drawing's columns
against trusted surface polygons, with no bundled width, feet or grass offset.
They do not calibrate an arbitrary game's relationship between art and collision.
The old bundled ground comparison is unchanged.

Evidence is in [test_role_boxes.py](../tests/test_role_boxes.py): offline contract,
reader and agreement tests, and real headless Godot tests on config-lane and
crate-run. The latter skip with a named Godot prerequisite when it is unavailable.
The handover includes before/after unconfigured bundled traces and their hashes.
