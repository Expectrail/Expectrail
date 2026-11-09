# The games under test

## Godot: `platformer/`

`platformer/` is Godot's official 2D platformer demo, imported unmodified in its own commit so that
anyone can see exactly what we changed during the event.

| | |
| --- | --- |
| Source | https://github.com/godotengine/godot-demo-projects/tree/4.7-6ad6167/2d/platformer |
| Tag and commit | `4.7-6ad6167`, `6ad6167e0577fe3622c18546138f456b107ce93c` |
| Engine | Godot 4.7.2 stable (Compatibility renderer, OpenGL 3) |
| License | MIT, see [LICENSE-godot-demo-projects.md](LICENSE-godot-demo-projects.md) |

Seeded bugs are never committed to this directory. The harness copies the game into a work
directory and applies a seeded-bug patch there, so the clean game stays clean and every bug is a
small, reviewable diff (see `bugs/`).

## Unity: `unity-platformer/`

`unity-platformer/` is Platformio, an open-source 2D platformer: an endless run of levels built from
fixed structures and visual themes, with coins to collect, enemies to shoot and hazards to avoid. It
is the first Unity game Expectrail will test. Why we chose it over the other candidates is set out in
`docs/unity-game-choice.md` (pull request #193).

| | |
| --- | --- |
| Source | https://github.com/Javernaut/Platformio |
| Commit | `941a3add6b13404e672e05e17cadd85bceac5190` (August 3, 2026) |
| Engine | Unity 6000.3.21f1 (Unity 6.3 LTS), Input System as the only input handler |
| License | MIT for the code (`unity-platformer/LICENSE`), CC0 for Kenney's art and audio; the rest is in `NOTICE` |

Nothing in it is wired into the harness yet, and no bugs are seeded into it. As with the Godot game,
seeded bugs will be patches applied to a copy, never commits to this directory.

### How it was imported

The first commit copies the upstream tree with `git archive`, so only files tracked upstream come
across, and edits nothing. It leaves out:

- `.github/` (upstream's CI, which deploys a WebGL build to the author's GitHub Pages), `.idea/` and
  `Assembly-CSharp.csproj.DotSettings` (editor files);
- `Assets/TextureAtlasSlicer/`, an editor script with no licence that nothing in the game references;
- TextMesh Pro's EmojiOne sprite sheet and sprite asset (`Assets/TextMesh Pro/Sprites/` and
  `Assets/TextMesh Pro/Resources/Sprite Assets/`). Their attribution file points to EmojiOne's own
  terms instead of granting a licence, and no text in the game uses TextMesh Pro sprites.

The second commit changes only settings and metadata:

- `Assets/TextMesh Pro/Resources/TMP Settings.asset`: the default sprite asset pointed at EmojiOne and
  is now none (`{fileID: 0}`).
- `ProjectSettings/ProjectSettings.asset`: the author's Unity Cloud project ID, project name and
  organization are blanked. Every Unity cloud service was already off in `UnityConnectSettings.asset`.
- `Packages/manifest.json` and `Packages/packages-lock.json`: `com.unity.collab-proxy` (the Unity
  Version Control client) is removed. Nothing depends on it.
- The TextMesh Pro user guide PDF (`Assets/TextMesh Pro/Documentation/`) is removed.

The game's code, scenes and prefabs are untouched.

### Extenject

`Assets/Plugins/Zenject` is Extenject 9.2.0 as the author installed it from the Unity Asset Store,
which is why 294 of its `.meta` files say `licenseType: Store`. We kept it instead of swapping in the
copy from GitHub, because the two are the same code. Every file in the folder exists at the
MIT-licensed `9.2.0` tag of https://github.com/Mathijs-Bakker/Extenject (commit `c2e3350`). The 256 C#
files and the one prebuilt DLL match the tag byte for byte, except one C# file whose line endings
differ. All 308 `.meta` files carry the tag's GUIDs. The differences are metadata only:

- `Version.txt` says 9.2.0 where the tag's says 9.1.0, and `package.json` gives
  `com.mathijsbakker.extenject` 9.2.0 where the tag's gives `com.svermeulen.extenject` 0.0.1;
- `LICENSE.txt` adds a link to the licence;
- the `.meta` files record `licenseType: Store` where the tag's say `Pro`, and `package.json.meta`
  lacks the tag's blank last line.

Swapping in the tag's files would change those lines and one file's line endings, and nothing else.

### The Kenney Future font

Platformio's README puts Kenney's graphics, music and sound effects under CC0, and kenney.nl lists
Kenney's fonts as CC0 too. The font file itself, `Kenney Future.ttf`, says otherwise: it was built
on FontStruct in 2013, and its name table reads "Creative Commons Attribution Share Alike" with a link
to CC BY-SA 3.0. Until Kenney confirms CC0 for this file, we treat it and the TextMesh Pro font asset
made from it as CC BY-SA 3.0. They are redistributed unmodified with attribution in `NOTICE`. As we
read the licence, its share-alike term covers changes to the font, not a game that displays it.
