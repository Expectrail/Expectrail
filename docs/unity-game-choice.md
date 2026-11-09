# The first Unity game: Platformio

Recommendation, Nov 9, 2026: build the Unity milestone on
[Javernaut/Platformio](https://github.com/Javernaut/Platformio), pinned at commit `941a3ad`
(Aug 3, 2026). Three facts decide it:

- It is already on Unity 6.3 (`6000.3.21f1`), uses the new Input System only, and stores every
  scene, prefab and setting as text. Each of the four bug families is a one-line change to a text
  file, as on Godot.
- Its own code and art are cleanly licensed: MIT code and CC0 Kenney art. Its only randomness is
  `UnityEngine.Random`, which the harness can seed. Nothing in it waits on wall-clock time.
- The other two named candidates fail on licence or format. RedRunner's scenes, prefabs and
  settings are binary, and its input runs through Unity's Standard Assets, which carry no licence
  file. The multiplayer template's own notice says it is governed by the Asset Store EULA.

Platformio still needs three changes when it is imported, all licence clean-up and none of them in
the game's code. Extenject came in through the Asset Store and should be replaced with the same
version from GitHub, where it is MIT. An editor-only tool with no licence should be left out. The
TextMesh Pro sample emoji sheet should be dropped. These are set out under
[What the import would change](#what-the-import-would-change).

This is an evaluation only. No game is imported into this repository, and nothing here changes
`game/platformer`. The candidates were read as data from shallow clones; no script, build or
interpreter from inside them was run.

## Comparison

| | Platformio | RedRunner | 2D platformer template (multiplayer) |
| --- | --- | --- | --- |
| Repository, commit read | `Javernaut/Platformio` `941a3ad`, Aug 3, 2026 | `BayatGames/RedRunner` `2b675b5`, Jan 29, 2026 | `UnityTechnologies/2d_platformer_template_multiplayer` `5958c09`, Oct 8, 2026 |
| Code licence | MIT | MIT | MIT at the root, but `Assets/ThirdPartyNotice.txt` says Asset Store EULA |
| Art and audio | CC0 (Kenney), stated in the README and in two `License.txt` files | Art CC BY 4.0 (the credited itch.io page); sounds and two font families have no licence file | Unity's Platformer Microgame (Asset Store) |
| Third-party code in `Assets/` | Extenject 9.2.0 (MIT file, Asset Store copy); TextureAtlasSlicer (no licence, editor only); TextMesh Pro resources | Save Game Free (MIT upstream, no licence file in the folder) with `FullSerializer.dll`; Standard Assets CrossPlatformInput (no licence file) | Netcode for GameObjects, Unity Gaming Services, Vivox (packages) |
| Unity version | `6000.3.21f1` (6.3 LTS line) | `6000.2.6f2` (not 6.3) | `6000.3.25f1` |
| Asset serialization | Force Text (`m_SerializationMode: 2`) | Binary: 211 of 216 scenes, prefabs and assets, and the settings files | Force Text |
| Input | Input System 1.20.0 only (`activeInputHandler: 1`) | Legacy Input Manager (`Input.GetButtonDown`, `CrossPlatformInputManager`) | Input System 1.20.1 only |
| Render pipeline | Built-in | Built-in with Post Processing v2 | URP 17.3.0 |
| Fixed timestep | 0.02 s | 0.02 s (read from the binary file) | 0.02 s (stored as a rational) |
| Randomness | `UnityEngine.Random` only | `UnityEngine.Random` only | not decisive (rejected on licence) |
| Real-time timers | `Time.unscaledDeltaTime` in two fades; no `WaitForSecondsRealtime` | `WaitForSecondsRealtime(3f)` before the start screen, `(1.5f)` after a death | not checked further |
| Levels | 3 handmade level prefabs and 6 themes, picked at random in an endless loop | Procedural terrain | Handmade scenes, networked |
| Coins, enemies, shooting, hazards | All four | Coins and chests, hazards; "Fire" only plays an animation | Microgame set, networked |
| Size without `.git` | 25.5 MB | 122.6 MB | 59.6 MB |
| Largest binary | 0.69 MB (TextMesh Pro user guide PDF) | 89.07 MB (`Assets/Sounds/Enemies/Water.wav`) | 10.42 MB (`Assets/Audio/Music.wav`) |
| Verdict | **Choose** | Reject: binary assets, legacy input, uncleared Standard Assets | Reject: Asset Store EULA, needs a Unity cloud project |

The brief listed Platformio as last pushed in August 2024 at about 383 MB. Those are
[ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Fjavernaut%2Fplatformio) figures
from its last sync on Aug 15, 2024. The repository has had commits since: its head is
`941a3ad` "Upgrading Unity to 6000.3.21f1" of Aug 3, 2026. The 383 MB is GitHub's figure, which
includes history; the checked-out tree is 25.5 MB, and a depth-1 clone's `.git` is 5 MB.

## Platformio

### Licences

- `LICENSE`: "MIT License", "Copyright (c) 2023 Oleksandr Berezhnyi".
- `README.md`: "The source code for this project is licensed under the MIT license" and "All used
  graphical assets as well as music and SFX assets are licensed under the Creative Commons 0
  License by Kenney."
- `Assets/_Project/GameLoop/Music/License.txt` and `Assets/_Project/Home/Music/License.txt`
  (Kenney's Music Loops 1.1): "License: (Creative Commons Zero, CC0)" and "This content is free to
  use in personal, educational and commercial projects."
- Every art and sound file name matches a Kenney pack (`spritesheet_players.png`,
  `footstep_grass_000.ogg`, `coinGold.png`, `blueSheet.png` and so on). Kenney's font
  `Assets/_Project/UI/Components/Text/Kenney Future.ttf` has no licence file beside it. The README's
  CC0 sentence names graphics, music and SFX, not fonts, but Kenney publishes its fonts as CC0
  too.

Third-party folders under `Assets/`:

- **`Assets/Plugins/Zenject`** (Extenject 9.2.0, `package.json` name `com.mathijsbakker.extenject`).
  Its `LICENSE.txt` reads "The MIT License (MIT)", "Copyright (c) 2010-2015 Modest Tree Media".
  However, 300 of its `.meta` files carry `licenseType: Store`, which Unity writes for files
  imported from the Asset Store. The
  [Asset Store listing](https://assetstore.unity.com/packages/tools/utilities/extenject-dependency-injection-ioc-157735)
  gives its licence as "Standard Unity Asset Store EULA". The same project publishes version 9.2.0
  on [GitHub](https://github.com/Mathijs-Bakker/Extenject/releases), whose `License.md` reads "MIT
  License", "Copyright (c) 2016 Modest Tree Media Inc". The one prebuilt file,
  `Source/Usage/Zenject-usage.dll` (23 KB), is byte-identical to upstream's (SHA-256
  `ec0ab17fdf977413c4af2d146982672813bbad3b50f2d2615c644e35b883e8d7`). The C# sources are laid
  out differently from upstream's current main, so they cannot be checked byte for byte against
  it. Nothing in the game calls Extenject's legacy-input helpers (`UnityUtil.IsAltKeyDown` and
  similar, which use `Input.GetKey`). Those calls would throw with the Input System as the only
  input handler.
- **`Assets/TextureAtlasSlicer`**, an editor window that slices Kenney's XML sprite sheets. It has
  no licence file, and neither does its upstream repository (`toxicFork/Unity3D-TextureAtlasSlicer`,
  checked at `87d87f5`). Its README points to the Asset Store ("the Unity3D asset store", item
  36103), and its `.meta` files say `licenseType: Store`. The game does not need it to build or
  run.
- **`Assets/TextMesh Pro`**, the TextMesh Pro essential resources that Unity copies out of
  `com.unity.ugui`. That package is under the
  [Unity Companion License](https://unity.com/legal/licenses/unity-companion-license): use is
  "permitted as long as it is in connection with the authoring and/or distribution" of Unity
  content, and "This License, including the copyright notice associated with the Work, must be
  provided in all substantial portions". `Fonts/LiberationSans - OFL.txt`: "This Font Software is
  licensed under the SIL Open Font License, Version 1.1." `Sprites/EmojiOne Attribution.txt`
  says only: "Please visit their website to view the complete set of their emojis and review their
  licensing terms." The EmojiOne sprite asset is referenced only by `Resources/TMP Settings.asset`
  (`m_defaultSpriteAsset`).

Packages (`Packages/packages-lock.json`): 22 registry packages, all from
`https://packages.unity.com`, and no scoped registries. One is a preview,
`com.unity.vectorgraphics` 3.0.0-preview.7. Another is `com.unity.collab-proxy`, the Unity
Version Control client, which the game does not need.

### Engine settings

- `ProjectSettings/ProjectVersion.txt`: `m_EditorVersion: 6000.3.21f1`. The repository's GameCI
  workflow (`.github/workflows/main.yml`) still builds with `UNITY_VERSION: 6000.3.12f1` and carries
  a TODO to read the version from this file.
- `ProjectSettings/TimeManager.asset`: `Fixed Timestep: 0.02`, `Maximum Allowed Timestep: 0.33333334`.
- Render pipeline: built-in. In `GraphicsSettings.asset`, `m_CustomRenderPipeline: {fileID: 0}`;
  every quality level has `customRenderPipeline: {fileID: 0}`; there is no URP package.
- Input: `com.unity.inputsystem` 1.20.0, and `activeInputHandler: 1` in `ProjectSettings.asset` (the
  Input System only). There is one action asset,
  `Assets/_Project/Global/InputSystem/GlobalInputActions.inputactions`: Move is WASD or the
  arrows, Fire is F, Jump is Space. The player's `PlayerInput` component
  (`Assets/_Project/GameLoop/Character/Player/Player.prefab`) uses `m_NotificationBehavior: 0`
  (SendMessages to `OnMove`, `OnFire` and `OnJump`). `Assets/_Project/InputSystem.inputsettings.asset`
  has `m_UpdateMode: 1`, so input events are processed in the frame's Update. A search of the
  game's 42 scripts finds no `UnityEngine.Input`.
- 2D physics: `Physics2DSettings.asset` `m_SimulationMode: 0` (FixedUpdate), gravity -9.81.
- Serialization: `EditorSettings.asset` `m_SerializationMode: 2` (Force Text). Every scene and
  prefab is YAML.

### Randomness and level generation

The only random calls are `UnityEngine.Random.Range`:

- `Scripts/Platformio/DI/GlobalInstaller.cs:42`, `Utils.GetRandomItem`. `LevelGenerator` uses it to
  pick a level prefab and a theme, and `RandomizedSoundBank` uses it to pick sound variations.
- `Scripts/Platformio/Environment/Exit/RandomDonut.cs:40`, which picks the exit's sprite.

No game script uses `System.Random`, `Guid.NewGuid`, `DateTime`, `Environment.TickCount` or
`Stopwatch`. Levels are not procedural. The scene's installer
(`GameLoop/Resources/Installers/MainGameLoopSettingsInstaller.asset`, referenced from
`GameLoopScene.unity`) lists three handmade prefabs, `Level1` to `Level3`, and six themes.
`GameSession` swaps them in an endless loop. Level 1 has 5 enemies and 5 coins, level 2 has 3 and 6,
and level 3 has 7 and 15. Every level is a variant of `GameLoop/Level/BaseLevel.prefab` that
overrides only tile data, positions and names, so an edit to BaseLevel reaches all three. Because
level, theme, sound and exit picks share Unity's one random stream, a single seed fixes them all,
provided the calls happen in the same order. They do when the time step is locked.

### Timers

- `Scripts/Platformio/UI/Fader.cs:56` and `Sound/MusicPlayer.cs:37` use `Time.unscaledDeltaTime`.
  These are the screen fades between levels and after a death, and the music volume. Gameplay
  waits on the fade: after a death, `GameSession.ReloadCurrentLevel` fades out, resets the player,
  then fades in.
- `Level/LevelAnnouncement.cs:24` uses `WaitForSeconds` (scaled time). `Loop/PauseMenu.cs` sets
  `Time.timeScale` to 0 and back to 1.
- No `WaitForSecondsRealtime`, `Time.realtimeSinceStartup` or `Task.Delay`.
- Animators: the player and enemy prefabs both have `m_UpdateMode: 0` (Normal, scaled time). No
  scene or prefab uses UnscaledTime.

### Physics and movement

The player (`Player.prefab`) has a dynamic `Rigidbody2D` with `m_GravityScale: 4`,
`m_CollisionDetection: 1` (continuous), `m_Interpolate: 0` and `m_Constraints: 4` (rotation
frozen). Its body is a `CapsuleCollider2D` (`m_Offset` y -0.42004132). Its feet are a thin
`BoxCollider2D` (`m_Offset` y -0.95102316); both colliders end at local y = -1.0. Enemies
(`Character/Enemy/Enemy.prefab`) are kinematic bodies (`m_BodyType: 1`) with only trigger colliders.
They move at a fixed height, and `EnemyMovement.OnTriggerExit2D` turns them round when a thin
sensor at their front leaves something other than the player, such as the end of a platform.
Coins use a trigger `CircleCollider2D`. Projectiles are dynamic bodies that are destroyed on any
contact.

Movement is written in `Update`, not `FixedUpdate`. `PlayerController.Run` and `ClimbLadder`,
`EnemyMovement.Update` and `LaserProjectile.Update` all set `linearVelocity`, and the jump adds to
it in the `OnJump` input callback. The physics step still runs in FixedUpdate, so the run is
deterministic only if every physics tick has exactly one Update before it. Locking the frame time to
the fixed step gives that (see [deterministic replay](#what-deterministic-replay-would-need)).

Persistence: `Score/ScoreCounter.cs` keeps the best score in `PlayerPrefs`
(`key_last_max_score`). The main menu shows it.

The menu and player selection can be skipped. `DI/GameLoopSceneInstaller.cs` binds
`_playerAppearanceChoiceKeeper?.GetChoice() ?? fallbackPlayerAppearance`, so `GameLoopScene` (build
index 1) loads directly with the default character.

### Fit for the four bug families

Layer names (`TagManager.asset`): Ground 6, Climbing 7, Player 8, Background 9, Bouncing 10,
Enemies 11, Hazards 12, Bullets 13, Interactables 14. The collision matrix in `Physics2DSettings.asset`
decodes to this: Player collides with Ground, Climbing, Player, Bouncing, Enemies, Hazards and
Interactables, but not with Default or Background. Sorting layers, back to front: Default,
Platforms, Climbing, Hazards, Interactables, Enemies, Player, SecretOverlayPlatforms.

| Family | One-line seeded change (text) | What breaks |
| --- | --- | --- |
| Fall-through (collision layers) | `BaseLevel.prefab`, GameObject `PlatformsTilemap`: `m_Layer: 6` to `m_Layer: 0`. A second variant clears the Player/Ground bit in `Physics2DSettings.asset` `m_LayerCollisionMatrix`. | The player falls through the floor, as in Godot's fall-through bugs. The enemies' layer does not touch Default either, so their sensors should stop finding platform edges and they should walk straight off them (expected, not yet run). The matrix variant leaves the enemies alone. |
| Missing texture (sprite reference) | `Interactable/Coin/BronzeCoin.prefab` SpriteRenderer `m_Sprite: {fileID: 21300000, guid: f0c7b528077b1467f8c247e7cf76a743, type: 3}` to `{fileID: 0}`. A second variant changes the `m_Sprite` override in `GoldCoin.prefab` or `SilverCoin.prefab`. | Coins collide and score but are not drawn. Coins have no Animator, so nothing restores the sprite. The player's sprite comes from animation clips, so a player variant would edit a clip. |
| Layering (sorting order) | `Player.prefab` SpriteRenderer `m_SortingLayerID: 1604631805` (Player) to `0` (Default, behind Platforms). A second variant moves `PlatformsTilemap`'s TilemapRenderer from `-310998967` (Platforms) to SecretOverlayPlatforms. | The player is drawn behind the floor. The game also has a deliberate case: SecretOverlayPlatforms draws over the player to hide secrets. That gives the layering check a healthy build that must not be flagged. |
| Sinking (collider offset) | `BaseLevel.prefab`, `PlatformsTilemap`'s CompositeCollider2D `m_Offset: {x: 0, y: 0}` to `{x: 0, y: -0.3}`. A second variant uses the TilemapCollider2D offset. The player's own two colliders would have to move together, since either one alone holds the player up. | The floor's collision sits below its drawn tiles, so the player stands inside the ground. Enemies keep their fixed height. |

The trace fields map onto the game's own objects:

| Field | Source in Platformio |
| --- | --- |
| player | `PlayerController`'s `Rigidbody2D.position` |
| ground, levelSurfaces, levelArt | the Ground-layer tilemap (`PlatformsTilemap`): tile cells for `ground` and `levelArt`, collider paths (`CompositeCollider2D.GetPath`) for `levelSurfaces` |
| coins | live `ScorePickup` components |
| enemies | live `EnemyMovement` components (tag `Enemy`) |
| projectiles | live `LaserProjectile` components |
| onFloor | the feet `BoxCollider2D`'s `IsTouchingLayers(Ground)`, the same test the game uses to allow a jump |
| facing | the sign of the player's `transform.localScale.x` (`FlipSprite`) |

Unity's y axis points up and Godot's points down. The gameplay checks are written for y-down
(`agents/gameplay.py`: "y-down: y > floor + tol"), so the Unity recorder must either negate y or
declare the axis in the trace header.

### Size

The tree is 25.5 MB without `.git`, and nothing from `Library/`, `Temp/`, `Logs/`, `obj/` or
`UserSettings/` is committed. The largest files are text prefabs full of tile data: `Level3.prefab`
9.50 MB, `Level2.prefab` 2.81 MB, `LiberationSans SDF.asset` 2.26 MB and `Level1.prefab` 1.99 MB.
The largest binaries are the TextMesh Pro user guide PDF (0.69 MB), two music loops (0.43 and
0.42 MB), `LiberationSans.ttf` (0.35 MB) and a README screenshot (0.23 MB). The repository uses no
Git LFS: it has no `.gitattributes` and no pointer files. Its workflow nonetheless runs
`git lfs pull`.

## RedRunner

- `LICENSE`: "MIT License", "Copyright (c) 2017 Bayat Games".
- `README.md` credits: "Graphics: Free Platform Game Assets" (bayat.itch.io) and "Save System: Save
  Game Pro - Save Everything" (bayat.itch.io). The credited
  [art page](https://bayat.itch.io/platform-game-assets) lists "Creative Commons Attribution v4.0
  International" for the assets, so attribution would be owed.
- **Save Game Pro is not in the tree.** The README is the only file that names it. The folder is
  `Assets/SaveGameFree`, whose `Readme.txt` begins "Hi, thanks for downloading Save Game Free." and
  asks for "rating and writing your review at our product page". The folder has no licence file.
  Upstream `BayatGames/SaveGameFree` is "MIT License", "Copyright (c) 2025 Bayat Games". The
  folder also ships a prebuilt `Plugins/FullSerializer.dll` with no licence file, plus press-kit
  `.ai` files and documentation zips. The game uses it to save the coin count, scores and the audio
  setting to disk (`GameManager.cs:98-124, 206-207`), so state carries over between runs.
- **`Assets/Standard Assets/CrossPlatformInput`** is Unity's Standard Assets input layer. It has no
  licence file, and `Characters/RedCharacter.cs:301-316` reads movement, jump, guard and fire
  through `CrossPlatformInputManager`. `Standard Assets/Fonts/OpenSans/License!.txt` is "Apache
  License, Version 2.0". `Standard Assets/Fonts/Unipix.ttf`, `Fonts/baloo` and `Fonts/Quicksand`
  have no licence files. Nor does anything under `Assets/Sounds`.
- Unity `6000.2.6f2`, not the 6.3 line.
- **Binary serialization.** `file` reports 211 of the 216 scenes, prefabs, assets, controllers,
  animations and materials under `Assets/` as binary; the five text files are Standard Assets
  prefabs. Most of
  `ProjectSettings/` is binary too, including `EditorSettings.asset`, `TimeManager.asset`
  (`Fixed Timestep` decodes to 0.02), `TagManager.asset` and `Physics2DSettings.asset`. Seeded bugs
  and fixes could not be text diffs until every asset was re-serialized as text in the editor, and
  that would replace the whole tree.
- Input: no `com.unity.inputsystem` in `Packages/manifest.json`. The code uses the legacy Input
  Manager directly: `UIManager.cs:84-153` (`Input.GetButtonDown`, `Input.GetMouseButtonDown`,
  `Input.mousePosition`) and `RedCharacter.cs:330` (`Input.GetButtonDown ( "Roll" )`).
- Randomness: `UnityEngine.Random` only, which is seedable. The terrain is procedural
  (`TerrainGeneration/TerrainGenerator.cs:187, 306, 345`), as are chest coin bursts, camera shake
  and audio picks.
- Real time: `GameManager.cs:196` waits `WaitForSecondsRealtime(3f)` before showing the start
  screen, and `GameManager.cs:157` waits 1.5 s of real time after a death. Under a locked frame
  time those waits last a different number of frames on every machine, so the tick at which
  play can start would change from run to run.
- Movement: `RedCharacter.Update` sets `linearVelocity` (the same Update-versus-FixedUpdate point as
  Platformio).
- Mechanics: coins, chests and hazards (saw, spike, water, mace, eye). There is no projectile:
  "Fire" only triggers an animation (`RedCharacter.cs:316-327`), so the projectiles field would
  always be empty.
- Size: 122.6 MB without `.git`, of which `Assets/Sounds/Enemies/Water.wav` is 89.07 MB.
  `Logs/Packages-Update.log` is committed.

## 2D platformer template (multiplayer)

The brief named it `Unity-Technologies/2d_platformer_template_multiplayer`. That address refuses a
clone; the repository is `UnityTechnologies/2d_platformer_template_multiplayer`.

- `LICENSE`: "MIT License", "Copyright (c) 2025 Esteban Maldonado, Developer Advocate".
- `Assets/ThirdPartyNotice.txt`: "Asset is governed by the Asset Store EULA; however, the following
  components are governed by the licenses indicated below: LiberationSans".
- `Assets/PlatformerMicrogame_README.txt`: "2D Platformer Microgame - Version 5.0.0" and "Learn more
  about the project here: https://assetstore.unity.com/packages/templates/platformer-microgame-151055".
  The game is Unity's Platformer Microgame, an Asset Store template. It falls under the same
  exclusion as the Asset Store samples in the brief, whatever the root `LICENSE` says.
- `Assets/Blocks/MultiplayerSession/README.md`: "Make sure your Unity project is connected to a
  cloud project before use." The template depends on `com.unity.netcode.gameobjects` 2.13.3,
  `com.unity.services.multiplayer` 2.3.3 and `com.unity.services.vivox` 16.12.1. A cloud project
  needs a Unity account, and Expectrail's runs must not create one.
- For the record: `6000.3.25f1`, URP 17.3.0, Input System 1.20.1 (`activeInputHandler: 1`), Force
  Text, a fixed step stored as 2822399/141120000 s (0.02 s), and 59.6 MB without `.git`.

## Also looked at

A short GitHub search (through ecosyste.ms, since the session's API access covers only this
repository) found nothing that beats Platformio:

| Repository | Why not |
| --- | --- |
| `practical-works/unity2d-prototype` (MIT, 19 stars) | Ships `Assets/Plugins/Sirenix/Odin Inspector`, a commercial Asset Store product, and an Asset Store fullscreen editor plugin. Unity 2022.1.10f1, no Input System, last commit Mar 25, 2023. |
| `striderzz/2D-Platformer-Unity` (MIT, 6 stars) | A 7-script starter on Unity 2022.3.13f1 with no Input System; last commit May 17, 2024. |
| `trymorez/unity-2d-platformer` | ecosyste.ms shows no licence. |
| `roymasad/spiritdash` (MIT) | A 2.5D mobile runner for Unity 5.6 with ads and Google Play integration. |

## What the import would change

These are proposals only; this pull request changes nothing.

1. Replace `Assets/Plugins/Zenject` with Extenject 9.2.0 from its GitHub release (MIT), or add it as
   a UPM git package, and confirm the game compiles and the replay matches. Keep its `LICENSE`.
2. Leave out `Assets/TextureAtlasSlicer`. It has no licence, and the game does not need it to build
   or run.
3. Keep the TextMesh Pro essential resources under the Unity Companion License, and put its notice in
   `NOTICE`. Drop `Sprites/EmojiOne*`, `Resources/Sprite Assets/EmojiOne.asset` and the user guide
   PDF, and set `m_defaultSpriteAsset` in `TMP Settings.asset` to `{fileID: 0}`.
4. Drop the upstream `.github/workflows/main.yml`, which deploys to the author's Pages. Also drop
   `.idea/`, `Assembly-CSharp.csproj.DotSettings` and `com.unity.collab-proxy`.
5. Add the game to `NOTICE` and to the prior-work list in `docs/new-work.md`: Platformio (MIT,
   Oleksandr Berezhnyi), Kenney art and audio (CC0), Extenject (MIT), LiberationSans (OFL 1.1) and
   TextMesh Pro (Unity Companion License).

## What deterministic replay would need

Harness side, with no change to the game:

- **Lock time to the physics step.** Set `Time.captureDeltaTime` to `Time.fixedDeltaTime` (0.02 s),
  so each rendered frame is exactly one physics tick and the Update-written velocities land once
  per tick. Use the same float for both, so accumulated time never gives a frame zero or two ticks.
  The alternative is to run 2D physics in Script mode and step it once per frame.
- **Seed the random stream.** Call `UnityEngine.Random.InitState(seed)` from a
  `RuntimeInitializeOnLoadMethod(BeforeSceneLoad)` in the harness package, before `GameSession`
  picks the first level. Record the seed in `replay.json`. Level order is part of the run, so every
  route, held-out ones included, must name its seed.
- **Start at `GameLoopScene`** (build index 1), skipping the menu and player selection.
- **Inject input as a device.** Add a virtual `Keyboard` with `InputSystem.AddDevice<Keyboard>()`
  before the scene loads, and queue its key states for each route tick before that frame. Input
  events are processed in dynamic update (`m_UpdateMode: 1`), so they apply at the start of the
  tick's frame. Disable any real keyboard the X server exposes, so that `PlayerInput`'s
  control-scheme auto-switch cannot pick it up.
- **Isolate PlayerPrefs.** On Linux, Unity keeps them under `~/.config/unity3d/DefaultCompany/Platformio/`.
  Give each run an empty `HOME`, or delete `key_last_max_score` at start.
- **Check the unscaled fades in the first spike.** `Fader` and `MusicPlayer` advance by
  `Time.unscaledDeltaTime`. The expectation is that this follows the capture clock when
  `captureDeltaTime` is set, but that has to be measured. Run one route twice through a death and a
  level exit, and compare the traces and frames.

Game-side changes, only if the spike shows they are needed (each would be its own patch, not a
change to the imported tree):

- Move the velocity writes into `FixedUpdate` in `PlayerController` (`Run`, `ClimbLadder`),
  `EnemyMovement` and `LaserProjectile`.
- Advance `Fader` by `Time.deltaTime` while the game is not paused, if unscaled time turns out to
  follow the wall clock.
- Let `LevelGenerator` take a level index from a setting, if a fixed level turns out to be clearer
  for routes than a seed.

## Risks

- **A Unity licence for CI.** Building a Linux player with GameCI needs Unity licence secrets
  (`UNITY_LICENSE`, `UNITY_EMAIL`, `UNITY_PASSWORD`, as in Platformio's own workflow). A person
  has to provide them; Expectrail's agents must not create the account or enter the credentials.
  This holds for any Unity game.
- **Rendering on a GPU-less runner** is untested: the built-in pipeline in a Linux player under
  Xvfb with Mesa. As with Godot, frames from a different GPU will differ, so baselines must come
  from the same runner type.
- **Update-driven movement** depends on exactly one Update per physics tick. That holds under the
  time lock above but has to be shown over a long route.
- **The level loop is random.** Reaching the exit swaps in another random level, and losing the
  third life (`initialLives: 3`) goes back to the menu with `SceneManager.LoadScene(0)`. Routes
  must stay inside one level, or the recorder must follow the swap.
- **Extenject builds objects through reflection** at runtime. Build the Linux player with the Mono
  scripting backend first; IL2CPP stripping is guarded only by the `link.xml` in
  `Source/Usage`.
- **Large text levels.** `Level3.prefab` is 9.5 MB of tile data, too big for a fixer to read whole.
  Seed bugs in `BaseLevel.prefab` (110 KB), `Player.prefab` and the coin prefabs instead.
- **A small upstream.** One maintainer, 1 star and 1 fork. Pin the commit, and expect no help from
  upstream.
- **A preview package** (`com.unity.vectorgraphics` 3.0.0-preview.7) in an LTS project. Check what
  uses it before the first build.
