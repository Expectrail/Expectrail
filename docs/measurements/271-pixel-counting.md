# The six rules on the public pixel checks (#271, #286)

Offline, from the committed records under `bench/jit/stand-in/`; no replay, observer or model.
These checks were written by hand, not by a model, and no trusted certificate is supplied, so rule 5
never holds and nothing counts. The page shows which rules each check meets from its own runs.
Pixel rows reach the gate decision only as authenticated evidence (rule 5); this is not a rate.

Made by `python3 -m expectrail.jit.counting pixel-bench --records bench/jit/stand-in --out <page>`.

| Record | Check | Predicate | Rules met | Counting | Why advisory |
| --- | --- | --- | --- | --- | --- |
| bullet-behind-scenery-sensor | `jit-px-bullet-visible-shoot-left-every12` | visible on bullet | 1, 3, 4 | no | no independent near miss killed (the candidate does not pass 3 of 3); trusted producer/replayer and input binding not authenticated; provenance incomplete |
| bullet-behind-scenery-sensor | `jit-px-bullet-visible-move-fire-right` | visible on bullet | 1, 3, 4 | no | no independent near miss killed (the candidate does not pass 3 of 3); trusted producer/replayer and input binding not authenticated; provenance incomplete |
| bullet-behind-scenery-visible | `jit-px-bullet-visible-shoot-left-every12` | visible on bullet | 3 | no | base-only reproduction/clean 3-of-3 missing; no independent near miss killed (the candidate does not pass 3 of 3); a run not judged, no single observer setting, or an unstable candidate; trusted producer/replayer and input binding not authenticated; provenance incomplete |
| bullet-behind-scenery-visible | `jit-px-bullet-visible-move-fire-left` | visible on bullet | 3 | no | base-only reproduction/clean 3-of-3 missing; no independent near miss killed (the candidate does not pass 3 of 3); a run not judged, no single observer setting, or an unstable candidate; trusted producer/replayer and input binding not authenticated; provenance incomplete |
| bullet-behind-scenery-visible | `jit-px-bullet-visible-move-fire-right` | visible on bullet | 3 | no | base-only reproduction/clean 3-of-3 missing; no independent near miss killed (the candidate does not pass 3 of 3); a run not judged, no single observer setting, or an unstable candidate; trusted producer/replayer and input binding not authenticated; provenance incomplete |
| enemy-walks-backwards-faces-motion | `jit-px-enemy-faces-motion-hold-right` | faces-motion on enemy | 1, 3, 4 | no | no independent near miss killed (the candidate does not pass 3 of 3); trusted producer/replayer and input binding not authenticated; provenance incomplete |
| enemy-walks-backwards-faces-motion | `jit-px-enemy-faces-motion-reverse` | faces-motion on enemy | 1, 3, 4 | no | no independent near miss killed (the candidate does not pass 3 of 3); trusted producer/replayer and input binding not authenticated; provenance incomplete |
| enemy-walks-backwards-faces-motion | `jit-px-enemy-faces-motion-move-fire-right` | faces-motion on enemy | 1, 3, 4 | no | no independent near miss killed (the candidate does not pass 3 of 3); trusted producer/replayer and input binding not authenticated; provenance incomplete |

Total: 3 records with pixel checks; 8 pixel checks; 0 counting; 8 advisory.
