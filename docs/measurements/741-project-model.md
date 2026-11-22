# Source-backed setup trial for #741

Can a saved project constraint and a replay together draft a more discriminating check, with evidence a developer can audit? This public Godot trial exercises the paired rail and movement obligation approved for first-user v1. It addresses Q1, Q3 and Q7 in the [evaluation plan](https://github.com/Expectrail/Expectrail/issues/282) and the scope agreed in [#741](https://github.com/Expectrail/Expectrail/issues/741).

## Reference and drafts

The [verification-owned fixture](../../bench/project-model/741/reference) binds three distinct scene-root children as the actor, contact mark and home mark. The adapter reads the saved actor position and rectangular collider from `main.tscn`. A center at y=80 and a collider height of 16 give a world-space band of y=72 through y=88. The pinned Godot 4.7.2 replay uses a 320×180 identity viewport at 60 ticks and 60 frames per second. The [out-and-back route](../../bench/project-model/741/out-and-back.json) sends right from tick 0 and left from tick 16. The actor touches the contact mark at tick 8 and the home mark at tick 25. These observations establish that the input exercises both legs. The source supplies the rail dimensions.

The [project-model record](../../contracts/examples/project-model.v1.json) stores the bound subject, world coordinates and units, source file digests and property locators, reference tree, engine binary and version, harness and profile digests, bindings, route, capture settings and observed tick references. The Godot adapter interprets the scene and collider. The common document can carry a source-backed band derived by another adapter.

The setup pair uses existing specs. `reference-rail` requires the actor's drawing box to stay within `[0, 72, 320, 88]` over the exercised window. `reference-movement` requires the actor to reach the contact mark in that same window. Return to the home mark is required evidence at authoring time. The movement draft evaluates the outbound reach. The model stays at authoring time, and each draft follows the existing human approval and verdict process.

## Public qualification

The fixture and [control patches](../../bench/project-model/741/controls) were committed before the candidate replays. The same frozen route and drafts were used with the clean reference and each committed control. Every assertion judged all 32 frames in all 15 replays.

| Arm | Broad viewport | Rail draft | Movement draft | Evidence |
| --- | --- | --- | --- | --- |
| Clean | 3/3 pass | 3/3 pass | 3/3 pass | Contact at frame 8 and return at frame 25 |
| Harmless comment | 3/3 pass | 3/3 pass | 3/3 pass | Same trace digest as the clean reference |
| Two pixels down | 3/3 pass | 3/3 fail | 3/3 fail | First box `[90, 74, 114, 90]` crosses the lower rail at frame 0 |
| Two pixels up | 3/3 pass | 3/3 fail | 3/3 pass | First box `[90, 70, 114, 86]` crosses the upper rail at frame 0 |
| Frozen actor with the same input | 3/3 pass | 3/3 pass | 3/3 fail | x stays at 100 and the contact mark is never reached |

There were zero indeterminate outcomes. The two-pixel upward defect isolates the rail from the movement assertion. The same-input freeze establishes that the movement assertion contributes coverage even when the frozen actor is inside the rail.

Three separately copied and replayed references produced byte-identical models and drafts. The canonical model SHA-256 was `59e3c445a68257bb7a9c24dfa731a3fb705d5f9ccf197fe1b6271104f74d124d`. The proof applied a control to a separate candidate before the last two derivations and verified that the pinned reference and drafts retained their original bytes after every arm. The reader returned `needs-review` when given the changed candidate tree or a reference identity with the two mark bindings exchanged.

The following trace digests identify the three matching repeats in each arm.

| Arm | Trace SHA-256 |
| --- | --- |
| Clean and harmless comment | `161d99e16cb2c39d0af94ed1a88082ed8aa7f4bd78fa720894f3d48dd9944120` |
| Two pixels down | `7a853c3adb52235e9c8897a7435df7a91c7e58600d6e51cd6cb6e4d09b67ec00` |
| Two pixels up | `aef3d052796324078078ced0e16ee464b1556e445a680d9a8473b666d5d8efc9` |
| Frozen actor | `581e48530fa4764b1cb1d7503d442eb03b0aec94c3f51aeae3af18002f302132` |

The controls were local engine-only diagnostics. Bubblewrap could not set up the user namespace in this environment, so the harness reported its automatic host fallback with an allowlisted environment. The [public cycle log](https://github.com/Expectrail/Expectrail/issues/721#issuecomment-7076354203) records the run and implementation status.

## Reproduce and review

With `EXPECTRAIL_GODOT` set to a pinned Godot 4.7.2 executable, run from the repository root.

```sh
trial_dir=$(mktemp -d)
PYTHONPATH=. python3 bench/project-model/741/qualify.py \
  --godot "$EXPECTRAIL_GODOT" --out "$trial_dir/trial"
```

This writes `qualification.json`, the replay and trace for each arm, and the three authoring outputs. The same authoring entry point can be run directly on a supported reference.

```sh
PYTHONPATH=. python3 -m expectrail.project_model_godot \
  --reference bench/project-model/741/reference \
  --route bench/project-model/741/out-and-back.json \
  --godot "$EXPECTRAIL_GODOT" --out "$trial_dir/authoring"
```

The command writes a new output directory outside the reference. For setup review, make a copy of the reference, add the route under `routes/`, set the profile's `routes` list to that path, and copy the two drafts into `checks/`. Run `expectrail onboard --project "$review_copy" --godot "$EXPECTRAIL_GODOT"` with a local display available. Keep the project-model file with the review evidence so the developer can inspect the source and exercised window alongside the two drafts. On a fresh wheel installation, this handoff produced a review page after a completed clean replay. The review manifest recorded both drafts as unapproved and their file digests matched the qualification outputs.

The trial supports one saved Godot text-scene layout and a complete out-and-back route on an untransformed viewport. Ambiguous bindings, unsupported source or capture transforms, incomplete evidence, or a changed authoring identity require review. Shipping the authoring command in the installed package requires the packaging owner to add its two modules to the wheel allowlist. Human approval remains open.
