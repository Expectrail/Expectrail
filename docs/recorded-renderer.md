# Recorded answers and rendering environments (#515)

A recorded answer still requires the exact PNG SHA-256, question kind and prompt. There is no
approximate match, environment override or live fallback. An exact image can be answered even
when the environments differ; provenance does not invalidate identical bytes.

New recordings carry optional `renderingEnvironments`: the capture's `replay.json` engine name,
engine version, renderer and device string (including its reported LLVM/driver version). These
are the environments of captures that supplied answers, not the GPU of the judge reading them.
Several environments can occur in one recording. A null entry means some answers have no
capture metadata. Missing fields are unknown, never inferred from the local machine.

The [schema](../contracts/vision-recording.v1.schema.json),
[example](../contracts/examples/vision-recording.json), writer and reader are updated together.
Old recordings without this optional field remain readable. The checked-in kinematic-character
recording has only its known original capture provenance added; no answers changed.

When an image is absent and all known recording environments differ from its capture, a missing
answer now says, for example:

> recorded under llvmpipe LLVM 20.1.2; this replay used llvmpipe LLVM 19.1.7; no exact image answer (not-recorded)

The local app, outside judge, Run it findings/status and recorded-bank observer preserve this
explanation. It describes a measured environment difference, not proof that the renderer caused
every missing image. A missing question for an already-known image is not blamed on the renderer.
Unknown provenance or a compatible environment in a mixed bank does not establish a mismatch.
Arbitrary model/provider error bodies remain redacted. The anchored observer is wrapped with
`recorded.with_recorded_diagnostics`; its decision rules are unchanged.

## Measurements before choosing a tolerance

Reproduce offline (Pillow and NumPy, no engine, model or network):

```sh
python3 -m tools.recorded_renderer --out /tmp/recorded-renderer.json
```

The following table is generated from [the machine-readable measurements](measurements/recorded-renderer.json).
[Fixtures and provenance](../tests/fixtures/recorded-renderer/README.md) include the two capture manifests,
the four actual PNGs, their hashes and the trace row. The existing model answer gives the original
player's box, [481,321,497,337), in frame pixels. Distance is Euclidean distance from each changed
pixel centre to the nearest original player pixel centre. RGBA channels are compared as integers.

| Comparison | Changed pixels | Largest channel difference (0–255) | Distance from player, min–max px |
| --- | ---: | ---: | ---: |
| Renderer: 179 identical frames | 0 | 0 | no changed pixels |
| renderer-frame-111 | 2 | 1 | 261.017–266.0 |
| hidden-player | 256 | 209 | 0.0–0.0 |
| moved-right-3px | 298 | 209 | 0.0–3.0 |
| resized-16-to-20px | 362 | 209 | 0.0–2.828 |
| tinted-player | 256 | 36 | 0.0–0.0 |
| red-minus-one-whole-player | 256 | 1 | 0.0–0.0 |
| two-player-pixels-one-level | 2 | 1 | 0.0–0.0 |

The renderer comparison covers the two saved 180-frame captures. Of these, 179 PNG hashes are
identical; only frame 111 differs. The 2 changed pixels are at (220,318), red 47→46, and (215,324),
green 74→73. Both captures report Godot 4.7.2 and OpenGL3; the device strings report LLVM 20.1.2
and 19.1.7. This establishes image differences alongside renderer differences, not a controlled
causal isolation of driver versions.

Hidden and tinted are real captures from the public outside run. Moved and resized are controlled
composites of the original sprite over the real hidden background: 3 pixels right, and 16×16 to
20×20 by nearest-neighbour resizing about the same centre. The last two rows are deliberate subtle
recolour probes, including two interior player pixels changed by one channel level. These are
synthetic pixel changes, not additional game replay or model judgments.

## Decision: retain exact matching

The large visual changes are far above renderer drift in changed-pixel count. But the sparse
recolour overlaps it exactly: 2 pixels, largest channel difference 1. A global bound that admits
that renderer drift also admits this player recolour. The spatial distances separate these
particular fixtures. They do not validate a general matching rule: a recorded box is not a
complete mask of every check's visual evidence, and this one frame says nothing about renderer
variation at a player edge or about other objects/checks. No opt-in tolerance is added.

Offline re-judging of the saved real captures gives a passing engine+vision check on the original
capture (120/120 questions answered). The newer capture gives needs-review (111/112 answered
before stopping at frame 111), with the explanation above. This is a single-check replay of saved
evidence, not a new full verification or a new engine run. The full capture scripts/results are
in the handover. The unchanged project therefore still cannot be accepted on both renderer builds
from this recording. A renderer-matched recording or a separately demonstrated safe spatial
policy remains a decision for Sean; no new answer was recorded or fabricated here.
