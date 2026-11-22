# macOS Local Interactive Runner

Use `play_local.sh` to play and inspect the bundled game on macOS.

> [!NOTE]
> The macOS verifier and the interactive launcher share the pinned engine installer, `get_godot_mac.sh`. Linux CI uses `harness/get_godot.sh`, Xvfb and Mesa software OpenGL for its deterministic replays.

---

### Quick Start

To launch and play the game locally on your Mac:

```sh
./harness/macos/play_local.sh
```

### What `play_local.sh` Does:
1. **Downloads the matching pinned Godot engine** (Godot 4.7.2 macOS universal binary) via `get_godot_mac.sh` into `tools/godot_mac/` in a checkout. Set `EXPECTRAIL_TOOLS` to keep the bundle under `godot_mac/` in another directory. An installed wheel uses the [user cache](../../docs/install.md#limits).
2. **Removes macOS Gatekeeper quarantine attributes** (`xattr -cr`) to prevent OS launch warnings or execution blocks.
3. **Pre-imports project assets headlessly** (`--headless --import`) so all sprite sheets, fonts, audio, and `AnimationPlayer` libraries are compiled cleanly before the window opens.
4. **Launches the native macOS window** with direct keyboard and gamepad input.

---

### In-Game Controls

| Action | Keyboard | Gamepad |
| :--- | :--- | :--- |
| **Move Left / Right** | `A` / `D` or Left / Right Arrows | Left Stick / D-Pad |
| **Jump** | `W` or Up Arrow *(supports double jump)* | Bottom button (`A` / `Cross`) |
| **Shoot** | `Space` or `Z` | Left button (`X` / `Square`) |
| **Pause & Coin Counter** | `Escape` | Start button |
| **Toggle Fullscreen** | `F11` or `Alt + Enter` | — |

---

### Playing with a Seeded Bug

Pass `--patch <patch-file>` (repeatable) to copy the game into `runs/local_play`, apply the patch, and launch it without touching the clean game:

```sh
# 1. Physics fall-through (player drops through the ground):
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v1.patch
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v2.patch

# 2. Missing coin textures (coins are invisible):
./harness/macos/play_local.sh --patch bugs/missing-texture/v1.patch
./harness/macos/play_local.sh --patch bugs/missing-texture/v2.patch

# 3. Layering bug (player is hidden behind the scenery/background):
./harness/macos/play_local.sh --patch bugs/layering/v1.patch
./harness/macos/play_local.sh --patch bugs/layering/v2.patch

# 4. Seeded bug + candidate fix applied together:
./harness/macos/play_local.sh --patch bugs/physics-fall-through/v1.patch --patch agents/fixtures/fix-collision-mask.patch
```

