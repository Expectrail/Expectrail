# Dodge engine data for stand-in tests — not vision evidence

Pinned public source: godot-demo-projects `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`,
`2d/dodge_the_creeps`, MIT; see tests/outside/projects.json. Captured locally November 16, 2026,
Godot 4.7.2, OpenGL3, llvmpipe LLVM 19.1.7. Bubblewrap 0.12.0 was required for all three captures;
only local Xvfb/display dependencies were bound read-only into the normal sandbox. No model ran.

`pinned-trace.json` and `broken-trace.json` preserve all real trace fields/values, formatted one
row per line. Harmless has exactly the same trace as pinned. `frame-aliases.json` contains the
three actual replay manifests, including original frame SHA-256s and capture provenance.
Unit tests generate **synthetic solid-colour PNGs**, assigning the same bytes only where the real
captures' hashes match. They are not screenshots. This reproduces question identity and counts
without checking in 900 screenshots. The CLI dry run in the handover used the real screenshots.

All returned boxes are from the engine, so positive verdicts are tautological stand-in plumbing
checks. They do not establish calibration, visual detection or an accept for the live observer.
The clipped-box stand-in stress exposes an edge-case risk; it is not a measured SAM false alarm.
Neither rules nor the approved spec are altered. No live Dodge recording is added to tests/outside/recordings/.
