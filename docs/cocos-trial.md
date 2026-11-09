# COCOS 4 on a Linux CI runner: the trial

**Yes, with conditions:** COCOS 4 (engine 4.0.0-beta.1, COCOS CLI 0.2.0-beta.1) built a 2D project for
the web on a GitHub-hosted ubuntu-24.04 runner with no desktop, and the build ran in Chromium with
the web harness's own switches (run 42680755693). It did not build with no display at all. Two
approaches failed and the third worked, under these conditions:

- The build ran under Xvfb, a virtual X server with no desktop, as the game harness already runs
  Godot. With no X server, every build failed while loading the shader compiler.
- The CLI was run as `node dist/cli.js`, because the command `npm link` installs is not executable.
- The CLI's own TypeScript was put first on `PATH`; the runner's global TypeScript 7.0.2 failed the
  build's type check.

`cocos create --type 2d` makes an empty project with no scene, and an empty project cannot be built.
The project that built is the CLI's own 2D test fixture. No official COCOS 4 source says Linux is
supported, and the CLI's own CI does not test Linux.

Trial date: November 9, 2026. Workstream P12.

## What the official sources say

| Source | What it says |
| --- | --- |
| [github.com/cocos/cocos4](https://github.com/cocos/cocos4), README and LICENSE at `a56706c` (Nov 4, 2026) | COCOS 4 is the engine only; "the cross-platform framework and the core components of the editor will be converted to CLI tools". Licence MIT, "Copyright (c) 2025 SUD". Latest tag 4.0.0-beta.1. |
| [github.com/cocos/cocos-cli](https://github.com/cocos/cocos-cli), `readme.md`, `docs/en/quick-start.md`, `docs/en/commands.md` at tag 0.2.0-beta.1 (`886dff6`, Nov 3, 2026) | Prerequisites: Node.js 22.17.0 (the quick start says "or higher"), Git, Visual Studio for Windows, Xcode for macOS. Linux is not mentioned. Install: `npm install -g node-gyp`, `npm run init`, `npm install`, `npm run download-tools`, `npm run build`, `npm link`. Build: `cocos build --project <path> --platform web-mobile`; `--no-interactive` "for CI". Licence file MIT, "Copyright (c) 2025 SUD"; `package.json` says ISC. |
| cocos-cli `.github/workflows/pr-test.yml` | Its tests and E2E builds run on `windows-2022` and `macos-latest` only. |
| [cocos.com/en/cocos4](https://www.cocos.com/en/cocos4) | "Supports Web, iOS, Android, HarmonyOS, Windows, Mac." No licence, CLI or install instructions; its download button points to the cocos4 repository. |
| Press release, January 5, 2026 ([PR Newswire](https://www.prnewswire.com/news-releases/cocos-4-is-here-fully-open-source-302652264.html); read in the [PR Newswire Asia copy](https://technode.global/prnasia/cocos-4-is-here-fully-open-source/)) | "COCOS 4 is released under the standard MIT License." "Core editing functions will gradually transit to Headless Mode, accessible via CLI." Lists cocos/cocos4 and cocos/cocos-cli. |
| [Cocos Creator command-line publishing](https://docs.cocos.com/creator/manual/en/editor/publish/publish-in-command-line.html) | For Creator 3.x: "Cocos Creator still needs the GUI environment when running from the command line"; examples for Windows and macOS only. |

The CLI has no `--headless` flag. Its build is a Node program with no IDE and no window, which is
what "headless mode" means in practice. `npm run init` also clones
[cocos/cocos-engine-external](https://github.com/cocos/cocos-engine-external) at tag v4.0.0-10:
3.1 GB of prebuilt third-party libraries, including Linux and Emscripten builds, with no top-level
licence file.

No step needed an account, a login, a licence key or acceptance of terms.

## What ran

The trial was one workflow file, `.github/workflows/cocos-trial.yml`, on the branch
`scratch/cocos-trial`. That branch was made from main at `c169a5e` and holds only that file. The job
had `permissions: contents: read` and used no secrets. Its only actions were `actions/checkout` and
`actions/setup-python`, both pinned by full commit SHA. The last version is commit `77a2b72`;
the file's SHA-256 is `e6466ff942180dbf5320321813d6061d5e63c276304edaa9529dafa00b9dd8fc`. Every result went out as a workflow annotation and was read
back through the check-runs annotations API.

The runner was Ubuntu 24.04.5 LTS, kernel 7.0.0-1017-azure, with 4 CPUs, 15 GB of RAM and 86 GB
free. `DISPLAY` was empty, and no X server was running until the trial started one. It used Node
v22.23.4 from the runner's tool cache, npm 10.9.9 and git 2.56.0. Under Xvfb it used Xvfb
2:21.1.12-1ubuntu1.9 and Mesa 25.2.8-0ubuntu0.24.04.4.

The commands, in order. `$CLI` is the clone, and the job sets `NODE_OPTIONS=--max-old-space-size=8192`
as the CLI's CI does:

```bash
git clone --depth 1 -b 0.2.0-beta.1 https://github.com/cocos/cocos-cli "$CLI" && cd "$CLI"
npm install -g node-gyp
npm run init        # clones cocos4 at 4.0.0-beta.1 (b9f9e95) and cocos-engine-external at v4.0.0-10
COCOS_SKIP_POSTINSTALL_BUILD=true npm ci   # as the CLI's CI does; postinstall compiles the engine and downloads tools
npm run build
npm link
node dist/cli.js --no-interactive create --project "$P_EMPTY" --type 2d
cp -r tests/fixtures/projects/asset-operation "$P_FIXTURE"   # the project the CLI's build E2E test uses
sudo apt-get install -y xvfb xauth libgl1-mesa-dri
env PATH="$CLI/node_modules/.bin:$PATH" xvfb-run -a -s "-screen 0 1280x720x24" \
  node dist/cli.js --no-interactive build --project "$P_FIXTURE" --platform web-mobile
```

The CLI's CI uses `npm ci` with `COCOS_SKIP_POSTINSTALL_BUILD=true`, which this trial copied, not the
readme's `npm install`. With that flag the postinstall still compiles the engine and downloads the
tools, and `npm run build` then builds the CLI once.

After the build, a Python script served the build folder and opened it in Chromium with
Playwright 1.63.0 (`requirements-web.txt`). It used the exact `CHROMIUM_ARGS` from
`harness/web/run.py`, including `--disable-gpu`. It waited 10 seconds, then read the engine's
`cc` global, the canvas and the console.

## Results, run by run

| Run | What changed | Result |
| --- | --- | --- |
| 42675277015 | The official install, then the linked `cocos` command | Install and CLI build succeeded. `cocos` failed: `/opt/hostedtoolcache/node/22.23.4/x64/bin/cocos: Permission denied` (exit 126). |
| 42676936206 | `node dist/cli.js`, no X server (approach 1) | `cocos create` succeeded. Both builds failed after 8 to 11 s (exit 1): `ANGLE Display::initialize error 12289: Could not open the default X display.`, then `TypeError: Cannot read properties of null (reading 'getSupportedExtensions') at src/core/assets/effect-compiler/shdc-lib.js:1239`. |
| 42678902546 | No X server with `ANGLE_DEFAULT_PLATFORM=swiftshader`, then `=vulkan` (approach 2); then both builds under Xvfb (approach 3) | ANGLE failed with both settings: `ANGLE Display::initialize error 0: Internal Vulkan error (-3)`, then the same `getSupportedExtensions` TypeError. Under Xvfb the shader compiler worked. The empty project failed with `Build parameter startScene("") validation failed` (exit 34). The fixture failed its type check with `error TS5108: Option 'moduleResolution=node10' has been removed` (exit 38). |
| 42680755693 | Under Xvfb, with the CLI's `node_modules/.bin` first on `PATH` | The fixture built in 62 s (exit 0) to `build/web-mobile-test`: 50 files, 25 MB. In Chromium it ran: engine `4.0.0`, scene `scene-2d`, 474 frames in about 10 s, a 960 × 640 canvas, `WebGL 1.0 (OpenGL ES 2.0 Chromium)`, 212 colours with 25.6% of pixels off the background, 0 console errors, 0 page errors, 0 failed requests. The empty project still failed for lack of a scene (exit 34). |

The job's overall conclusion is failure in every run, including 42680755693, because the empty
project's build is expected to fail. The annotations are the record.

### Why each failure happened

- **The linked command is not executable.** `npm link` points `cocos` at `dist/cli.js`, which starts
  with `#!/usr/bin/env node` but is left at mode `-rw-r--r--`. `npm link` took 158 to 192 s, which
  suggests it re-ran the package's postinstall: that postinstall rebuilds `dist/` after npm has set
  the execute bit. The CLI's own E2E runner never uses the linked command. It runs
  `node dist/cli.js` (`e2e/helpers/cli-runner.ts`), and its release script sets the bit separately
  (`workflow/release.js`).
- **The shader compiler needs an X display.** `shdc-lib.js` creates a WebGL context through the `gl`
  (headless-gl 9.0.0-rc.10, ANGLE) package as soon as it is loaded, with no fallback. On Linux,
  ANGLE opens the X display. Asking ANGLE for SwiftShader or Vulkan instead did not help. The
  CLI's own offscreen scene rendering is a separate, opt-in path (`enableOffscreenRendering`) and is
  not involved.
- **The type check runs whatever `tsc` is on `PATH`.** On macOS and Linux,
  `static-compile-check.ts` runs a bare `tsc`. The runner's global `/usr/local/bin/tsc` is version
  7.0.2; the CLI depends on 5.9.3. The CLI's tests run under `npm run`, which puts the CLI's own
  `node_modules/.bin` first.
- **`cocos create` makes no scene.** It writes only `package.json` and two settings files. The CLI's
  code has a `TODO` for templates (`src/core/project-manager.ts`).

Two more errors appeared in every build on Linux but did not stop the 2D build:
`node_modules/@cocos/fbx-gltf-conv/bin/darwin/FBX-glTF-conv: Exec format error` (the macOS binary,
run on Linux, failing to import the engine's `primitives.fbx`), and
`spawn .../static/tools/cmft/cmftRelease64 ENOENT` (the skybox tool; `workflow/download-tools.js`
has tool lists for Windows and macOS only). A 3D project, or any project with FBX models or an
HDR skybox, would probably fail here.

## Time and disk

| Step | Wall time across the four full runs |
| --- | --- |
| `npm run init` | 164 to 180 s |
| `npm ci` (with the engine compile) | 143 to 171 s |
| `npm run build` | 44 to 61 s |
| `npm link` | 158 to 192 s |
| `apt-get install xvfb …` | 6 s |
| Building the fixture for web-mobile | 62 s |
| Loading it in Chromium | 11 s, of which 10 s is the deliberate wait |
| The whole job | 513 to 691 s |

The CLI's tree is 5.4 GB. Of that, `packages/engine` is 4.0 to 4.1 GB (3.1 GB of it
`native/external`), `node_modules` is 1.1 GB and `static/tools` is 213 MB. The npm cache was 276 MB.
Free space on `/` went from 86 GB to 80 GB. All of this except the project build depends only on the
CLI tag, so it can be cached.

## Other findings that matter for CI

- **Packages come from a mirror with TLS checks off.** The CLI's `.npmrc` sets
  `registry=https://registry.npmmirror.com` and `strict-ssl=false`. All 2,192 `resolved` URLs in its
  `package-lock.json` point to that mirror. The trial set `npm_config_strict_ssl=true`, and the
  install still worked. The lockfile's integrity hashes still apply.
- **Tools are downloaded over plain HTTP.** `workflow/download-tools.js` fetches tools from
  `http://download.cocos.com`, over HTTP, not HTTPS. On Linux it fetched only the three common
  tools.
- **The CLI reports errors to Cocos.** `src/cli.ts` starts Sentry with a fixed DSN at
  `sentry.cocos.org`, with `sampleRate` 0.5 and `tracesSampleRate` 0.2, and no setting turns it off.
  The trial runs had network access, so their errors may have been reported.
- **Everything is beta.** The engine tag is `4.0.0-beta.1` and the CLI tag is `0.2.0-beta.1`.

## GitHub rejected seven runs before they started

Runs 42671444332, 42672106283, 42672844896, 42673058230, 42673604571, 42673810119 and 42674376112
ended as failures about 50 s after they were created, with no job and no check run, so no annotation
says why. Smaller probe files started normally in the same period: runs 42672507792 and 42672663188
(job gated off, skipped), and 42673245859, 42673417425, 42673998412, 42674178725, 42674596996,
42674809247 and 42675007964. Dropping `actions/setup-node`, changing the default shell and renaming
two steps were each tried as the fix, and one probe seemed to confirm the step names. None of them was
the cause: run 42675277015 started and ran with a tree that is byte for byte the one rejected in run
42674376112. The rejections came from GitHub's side and were
intermittent, not caused by the workflow. The trial had already dropped `actions/setup-node` and
used the runner's Node 22, which the quick start's "22.17.0 or higher" allows.

## What it would take to add Cocos web builds to the web harness

A Cocos game would be a third adapter in `harness/adapters.py`, beside `godot` and `web`, registered
under its own name so that the shared verifier (`agents/domain_verifier.py`) and the fixer can take it.
Its `run` would copy the Cocos project, apply the patches, build it for the web, and replay the route
on the build in Chromium. Unlike the checkout page, which is patched and served as it is, every
candidate fix would need a new build: 62 s for this small project, on top of the CLI install.

**The build step.** The harness image already has Ubuntu 24.04, Xvfb and Mesa (for Godot). It would
also need Node 22 and the CLI at a pinned tag, installed as above and cached by tag (about 9 minutes
and 5.4 GB uncached). The CLI would run as `node dist/cli.js` under `xvfb-run`, with its
`node_modules/.bin` first on `PATH`. Egress to `sentry.cocos.org` should be blocked, and `strict-ssl`
turned back on. The adapter's ignored folders would be the ones the CLI's fixture ignores as
generated: `library/`, `temp/`, `local/`, `build/`, `native/`, `packages/`, `profiles/` and
`settings/v2/`. A web build is a static folder (`index.html`, `application.*.js`, `cocos-js/`,
`assets/`, `src/`).

**What the web harness already does.** `harness/web/run.py` takes another site folder with `--app`,
answers every request from that folder under a fixed origin, and lets nothing leave the machine.
The trial showed that the harness's `CHROMIUM_ARGS`, including `--disable-gpu`, give the game a
WebGL 1.0 context and a running engine, so no GPU switch has to change. Unknown file types would be
served as `application/octet-stream`, which is also how Python's own server served them in the
trial, with no failed request. The harness writes the app's name as `checkout` and its origin as
`checkout.test`; both would become per-app.

The rest is new work, because the web harness is built for a DOM form and a Cocos game is one
canvas:

1. **Steps.** Routes know `load`, `fill`, `select`, `check` and `click` on CSS selectors. A game route
   needs key presses and releases, clicks at canvas coordinates, and "wait N frames". That means a
   new route format version, changed in the contracts first, as `CONTRIBUTING.md` asks.
2. **A position log.** `LAYOUT_JS` reads DOM boxes, and for a game that is one box: the canvas. The
   engine is reachable from the page: the trial read `cc.ENGINE_VERSION`,
   `cc.director.getTotalFrames()` and the scene's name through `window.cc`. A Cocos route would read
   each named node's world position and size from `cc.director.getScene()` after every step and
   write them as `expectrail.observations/v0`, the counterpart of the Godot position log.
3. **Repeatable frames.** The game loop runs on `requestAnimationFrame` and wall-clock time: 474
   frames in about 10 s here, about 47 a second on software GL. Godot runs at fixed ticks under
   Movie Maker. Frames would have to be driven deterministically, for example with Playwright's
   clock control or a fixed engine step. Neither was tested. `harness.replay_check` (the same route
   twice, the same frame hashes) would decide it, and the adapter's `trace_state` would say which part
   of a trace row must agree.
4. **A game.** Expectrail would need a COCOS 4 project with at least one scene, since `cocos create`
   gives none: a port of the platformer or an MIT-licensed sample, with Cocos's MIT notice added to
   `NOTICE`. 2D only, until the FBX converter and `cmft` work on Linux.

## Loose ends

- The scratch branch `scratch/cocos-trial` was not deleted. `git push origin --delete scratch/cocos-trial`
  returned HTTP 403 through this session's git proxy, while every push to the branch had worked.
  The branch was never merged, holds only the trial workflow (which runs only on pushes to that
  branch), and points at `77a2b72`. Someone with access should delete it.
- The trial did not run `harness/web/run.py` itself on the build, only its Chromium switches, and it
  did not test a native target or the `start-mcp-server` command.
