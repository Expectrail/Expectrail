# Where the ball first shows a broken rebound

In the public Breakout game, a ball can pass the launch check and still fall through the paddle. A four-event pointer route puts the paddle under the descending ball. On the clean game it rebounds from the paddle at frame 76, then from the right wall at frame 85. The existing sweep misses the paddle. It gives a useful control for a legal miss. [Contact route](route.json) · [Registered sweep](../../../../tests/outside/breakout-pointer/routes/pointer-auto.json) · [Game source and licence](https://github.com/mike0697/Breakout/tree/0ac7aed444ea593a023d9b666c211d7ab8acd51e)

## Compare the first different Ball frames

Each generated frame is a 360 × 640 PNG. The paths below are relative to the temporary output directory created by the reproduction command. The engine recorded one physics tick per frame. Screen and world boxes agreed for the Ball and Paddle on this route. Coordinates increase to the right and down.

| Surface | Clean game | Collider control | What to inspect |
| --- | --- | --- | --- |
| Paddle, frame 76 | `clean/1/frames/f00000076.png` | `paddle-contact-layer/1/frames/f00000076.png` | The Ball drawing's bottom reaches y=605.998 in clean play and y=609.037 when the Ball cannot collide with the paddle. At frame 77 the edges are y=600.436 and y=615.466. Only the clean ball is moving up. |
| Right wall, frame 85 | `clean/1/frames/f00000085.png` | `right-wall-disabled/1/frames/f00000085.png` | The Ball drawing's right edge reaches x=360.277 in clean play and x=363.977 with the wall disabled. At frame 86 the edges are x=356.508 and x=367.719. Only the clean ball is moving left. |

The SHA-256 prefixes for the four recorded PNGs are `253a6b138a47ab9a`, `c996ced085adf328`, `ec8e288a29c1b719`, `d13941c1e3d3e4fc`, in table order.

The paddle collider's top is at y=606. At frame 76 its horizontal span is x=286–334 and the clean Ball spans x=322.274–330.274. On the registered sweep, the same frame puts the ball at x=323.107–331.107 and the paddle collider at x=10.822–58.822. The Ball passing below the paddle on that sweep is legal. [Paddle scene](https://github.com/mike0697/Breakout/blob/0ac7aed444ea593a023d9b666c211d7ab8acd51e/scenes/paddle.tscn)

The wall's inner face is x=360.25. A strict limit at x=360 or even at x=360.25 would flag the clean rebound. Disabling the wall also changes the paddle's approach at frame 17, before the Ball reaches either surface. Frame 85 is the first difference in the **Ball** on that control. Direction on the following frame and the collider controls support the contact interpretation. The recorder has no collider-hit event here. [Wall scene](https://github.com/mike0697/Breakout/blob/0ac7aed444ea593a023d9b666c211d7ab8acd51e/scenes/walls.tscn)

## What the controls establish

The route uses seed 1 at 60 ticks per second. It keeps the original Start events at ticks 12–14, moves the pointer to (310, 512) at tick 17 and ends after 100 ticks. Compare these drawings on the same route and game pin.

| Game version | Result to look for |
| --- | --- |
| Clean and comment-only | Same Ball and Paddle traces and frames. Both rebounds are visible. |
| Paddle on layer 8 | The Ball's mask is 7. The paddle looks the same but the Ball drops through it. |
| Right-wall collider disabled | The Ball rebounds from the paddle, then travels through the right edge. |
| Ball physics disabled | The Ball stays at its initial position through both windows. It satisfies simple containment while demonstrating neither rebound. |

All three traces and all 100 PNGs repeated byte for byte within each of the five versions. The clean and harmless versions also matched each other. The frozen Ball held its starting drawing box, [212, 196, 220, 204], for every tick. Its first difference from the moving clean Ball was at frame 14. Three replays of the original 407-tick sweep also matched each other. [Original menu and route](../../../../tests/outside/breakout-pointer/routes/pointer-auto.json)

| Version | Trace SHA-256 prefix | First different Ball frame | First different pixel frame |
| --- | --- | --- | --- |
| Clean / harmless | `ea26a31992cf` | None | None |
| Paddle on layer 8 | `df41c8755fae` | 76 | 76 |
| Right wall disabled | `3b990874ab41` | 85 | 17 |
| Ball physics disabled | `66c3d21a4d7d` | 14 | 14 |

These are rendered engine diagnostics on prepared game copies. Each prospective check still needs evidence that its surface was reached. A missing or ambiguous Ball binding, or an unexercised contact, warrants needs-review. Local Bubblewrap refused the uid map. No independent vision judgement or developer onboarding time was measured.

## Reproduce

Run from the Expectrail checkout on Linux with the pinned Godot 4.7.2 and Xvfb available. Each replay below gets its own virtual display. Use a fresh temporary folder and copy only the pinned game's tracked files.

```bash
trial=$(mktemp -d)
repo=$PWD
route="$repo/docs/outside-trials/breakout-pointer/contact-rehearsal/route.json"
changes="$repo/docs/outside-trials/breakout-pointer/contact-rehearsal/changes"
git clone --quiet https://github.com/mike0697/Breakout.git "$trial/upstream"
mkdir "$trial/game"
git -C "$trial/upstream" archive 0ac7aed444ea593a023d9b666c211d7ab8acd51e | tar -x -C "$trial/game"
cp tests/outside/breakout-pointer/expectrail.project.json "$trial/game/"

for arm in clean harmless paddle-contact-layer right-wall-disabled ball-never-moves; do
  patch_args=()
  if [ "$arm" = harmless ]; then
    patch_args=(--patch "$repo/tests/outside/breakout/changes/harmless.patch")
  elif [ "$arm" != clean ]; then
    patch_args=(--patch "$changes/$arm.patch")
  fi
  for repeat in 1 2 3; do
    env -u DISPLAY python3 -m harness.run --sandbox auto --game "$trial/game" \
      --route "$route" --out "$trial/$arm/$repeat" "${patch_args[@]}"
  done
done
```

Inspect `frames/f00000076.png` and `frames/f00000085.png` beside the Ball's `roleObjects[].worldBox` in the corresponding `trace.json`. Each `replay.json` identifies the engine, isolation mode and hashes of the trace and frames. Repeat with the registered sweep to inspect the legal miss. [Recorded run](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7052345859)
