# Frozen on-screen compatibility proof (#263)

`kinematic-before.json` freezes observations and verdicts from the pre-fix anchored observer,
using the genuine recording in `tests/outside/recordings/kinematic-character/`, the public frame-111
recorded/tinted/hidden PNGs and trace row in `tests/fixtures/recorded-renderer/`. No model was called.

`kinematic-findings-before.json` freezes the exact complete findings.json bytes, with only the
clock and caller commit fixed before generation for reproducibility. Its fixture is a synthetic
constant-position replay made by repeating the same recorded image/engine row over the public
route, judged by the genuine recorded answers and existing policy. It is not the original full
capture, a new hosted run, or new vision evidence. The hidden fixture remains needs-review; no
missing recorded answer was filled in. The test requires byte equality, not just equal decisions.

The files were frozen on local prerequisite commit
`256734cb45397d82641272867b5b5017b30bc1ee`, before changing expectrail/anchored.py. Their purpose is
compatibility for wholly on-screen observations; clipping and defect detection have separate tests.
