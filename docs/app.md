# Verify two versions in the local app

With Expectrail installed, start it once:

```sh
expectrail app
```

In a repository checkout, use `python3 -m expectrail.app` instead. Python 3.12 or newer is
required. Open the full address it prints. Keep that process running while using the page.
The address is on `127.0.0.1`, with a free port and a new token each time. Do not share it.
The app serves its own page without downloading scripts, styles or fonts.

1. For **Before** and **After**, paste the full path to each Godot project folder or its
   `project.godot` file. Either input selects the containing project, including its routes
   and checks. To verify, each also needs its own [project config](project-config.md), `expectrail.project.json`.
   Git references are not supported in this screen.
2. The config's `routes` and `approvedContracts` lists choose the policy. The base config
   chooses what judges both copies. A config produced by `expectrail init` is a draft and
   cannot give an accept until its bindings are reviewed. Only a person may approve checks.
3. Select **Check folders**. The page lists usable route names, approved check IDs and draft
   warnings. The setup doctor probes the installed engine and display with an empty project;
   it runs neither your selected game nor a model. Missing engine, display or drawing support
   now shows its reason and fix for live vision as well as recorded vision. When a config is missing, the app reads the saved Godot scenes
   and shows the starting scene, possible player nodes, images and any binding that still
   needs a choice. Choose a proposed node in
   **Before player** or **After player**. Each selection shows the image path, source sprite,
   available dimensions and atlas regions or whole-image reference for that node. You can
   switch players independently on either side. Editing a folder clears its preview.
   Check folders shows a separate result for Before and After. An existing
   pending draft is checked against the project and its saved route before preview. For a
   menu game, the preview reads the saved inputs without starting the game. If the draft
   selects a player, the preview names it and shows its image candidates. Replay the route
   to see whether those inputs reach gameplay.
   Previewing leaves both folders untouched.
   **Save draft setup…** shows a confirmation for the selected side, folder and player. If
   route discovery needs a live control measurement, confirming starts a disposable copy
   of the game headless, including its project scripts. Only confirm for a trusted project.
   With **Require the replay sandbox** selected, setup refuses this probe. Cancelling the
   confirmation leaves the project untouched. An input-map-only setup can save directly
   from the authored files without starting the game.

   Saving uses the same draft and first route as `expectrail init --player NODE`. When
   the binding needs a decision, the app writes `expectrail.project.draft.json` beside
   `project.godot` and a content-addressed route under `routes/`. Complete the listed
   bindings and save the reviewed config object as `expectrail.project.json`. When the
   binding is complete, the config is saved at that filename with `draft: true`. In both
   cases review the route in gameplay and choose checks for human approval. A changed
   folder, an existing setup file or an unsupported route stops the save. The app gives
   the reason and the **Check folders** action lets you start a new review.

   **Older projects without a config** uses folder paths for Before and After, with explicit
   game, route and check paths relative to each folder.
4. Select **Verify**. The app and `expectrail verify --project AFTER --base BEFORE` prepare
   the same kind of request and use the same worker. The job snapshots both games and the
   selected policy bytes outside your source folders. The page shows phases; **Cancel** asks
   the orchestrator to stop the job and its processes. [Offline parity tests](../tests/test_app_projects.py).
5. Read the result and its reasons. **Accept** and **Reject** are the verifier's decisions
   under the checks used. **Needs review** is not an accept. **Failed**, **Cancelled** and
   **Could not be carried out** give no verdict. An unfinished job gives no verdict either.
   When the job has an existing report, the page links to it. Missing tools are reported by
   the verifier, with its suggested fix.

### Local project selection API

All four endpoints require the app token. The desktop dialog takes its selection from the person at
the computer. `POST /api/projects/choose` takes an empty JSON object and returns a folder path,
or `null` on Cancel. A graphical desktop and Python Tk are required for the dialog.
`GET /api/projects/recent` lists up to six folders from previous choices and configured jobs,
newest first. These paths stay in the local app's job store.

`POST /api/projects/check` takes an absolute `before` or `after` path, or both. Each supplied field
gets its own folder and problem. With After alone the app can suggest a sibling named
`<game>-before` or the same project inside another registered Git worktree. With both folders
it checks whether After contains Before's starting scene at the expected location.

For a local Git checkout, `POST /api/projects/previous` takes only `after` and returns the
corresponding folder in a temporary copy of the first parent of HEAD, plus the full commit ID.
It reads local Git objects. Repositories containing symlinks or submodules cannot supply this
copy. Opening another previous copy or closing the app releases the temporary folder.

### Local player preview API

The page sends an authenticated `POST /api/inspect` with `projectConfig: true` and
`folder` for each side. This field accepts a directory or its regular `project.godot` file.
A missing `expectrail.project.json` still returns HTTP 400 with
`state: "could-not-be-carried-out"` and the existing human-readable `detail`. For a
project with player candidates and no saved draft, the same response includes a `setupPreview` object.
Its `players` array supplies the options, `selectedPlayer` is null and `imageSuggestions`
is empty. The page sends the chosen node to the same endpoint, for example:

```json
{"projectConfig":true,"side":"before","folder":"/path/to/breakout","player":"Paddle"}
```

The HTTP 400 response still blocks verification. Its `setupPreview` describes the selected
node. For example, the Paddle report contains this suggestion in `imageSuggestions`:

```json
{
  "sprite": "Paddle/AnimatedSprite2D",
  "property": "sprite_frames",
  "image": "res://break assets/paddle/sp_paddle_long_strip2.png",
  "imageSize": [94, 18],
  "regions": [[0, 0, 47, 18], [47, 0, 47, 18]]
}
```

`entryScene` names the starting scene, `players` now contains the chosen node and
`selectedPlayer` names it. Each region is `[x, y, width, height]`. A whole-image reference
has `regions: null`, and an unread image size is null. `unresolvedBindings` lists inspection
problems or choices that need human review. Invalid selections return a detail without
`setupPreview`. A saved draft retains its recorded selection and route checks. Selecting a
player reads the folder. A selected-player request with `side` set to `before` or `after`
also supplies a `saveReview`. Its `folder`, `setupFile` and `runsProject` describe the
proposed save. A blocked review gives a reason without a save ID.

After the developer confirms, the browser posts `side`, `folder`, `player` and the
single-use `review` ID to the authenticated `/api/setup/save` endpoint. The server checks
the review against that side's current selection and the project bytes, then builds and
publishes the draft without overwriting a setup. A successful HTTP 201 response names
the actual `setupFile` and `route`. Each new side inspection invalidates its previous
review. Saving creates no verification job or approval.

### Try kinematic-character with saved vision answers

The example is an ordinary configured project, not a verification preset. Get the
[pinned Godot demos](https://github.com/godotengine/godot-demo-projects/archive/b761b4cd5718a7118f2c95eb55f181d0a5f004f1.zip)
and extract them. To prepare a new copy once, use:

```sh
python3 -m expectrail.app_kinematic /path/to/demos/2d/kinematic_character /path/to/example-before
```

The destination must not exist. This copies the game, the existing approved check unchanged,
the walk route, published recording and calibration, and the [example config](../contracts/examples/project-recorded.json).
It does not run a game, approve a check or ask a model. Copy that prepared folder to
`example-after` and make your change there. Choose those two configured folders in the app,
then **Check folders** and **Verify**. No special checkbox or worker is used. The same pair
can be verified with `expectrail verify --project /path/to/example-after --base /path/to/example-before`.
Past runs names the immutable verification copies in the job store.

Saved answers match exact PNG bytes and questions. The unchanged game is **not guaranteed an
accept from the current recording**: a real replay on November 15 differed from the original
capture at frame 111 by two pixels. Its point question `(488, 329)` is recorded for the old PNG,
but not for the new hash. The [reproducible image probe](../tests/test_app_projects.py) and
[request details](../tests/fixtures/recorded-pixel-mismatch/question.json) name the missing answer.
It stays needs-review. No approximate-image substitution or live fallback was added; Sean must
decide whether to record that image. An engine failure can still reject. Godot, a display and
the other usual local tools are required for an actual replay; recorded vision uses no key.

The result says which observers judged, from the job's own status or findings. With `both`,
the engine's record and the vision model judge every check. If that rule records no visual
observer, the page says the model was unavailable. An absent observers block or `engine-only`
means an engine diagnostic: Expectrail's rule is that an accept needs vision too. This app
does not select or change the verifier's observer rule. A needs-review diagnostic naming
`MODEL_API_KEY` or `EXPECTRAIL_SAM_USD_CAP` explains the provider key or spending cap to set
before starting the app again. No key is entered on this page.

Only run games you trust: this slice does not offer isolated execution. The verifier still
needs its usual Godot and machine tools when it runs a real game. The app has not removed those requirements.

Jobs are stored at `~/.local/share/expectrail/app-jobs`. To choose another folder outside
both games, use `expectrail app --jobs-root /path/to/jobs`.

**Past runs** lists jobs in this store, newest first, with their folders, recorded result and
creation time in UTC. **Open run** shows that job's result; **Refresh past runs** reads it again.
A running job has no verdict. Opening an unfinished job owned by this session resumes status
updates and its Cancel button. Finish or cancel the current job before opening another.

Only jobs created in the current app session can open reports or the **Evidence viewer**.
Older jobs show their result but no file links. Finished jobs link to the existing viewer,
including its offline evidence export and copied frames. When no gate viewer exists, the
existing viewer renderer shows the job's status without inventing evidence. Report pages
cannot run scripts; viewer pages allow only the viewer's own script by its SHA-256 hash.
File reads refuse symbolic links and traversal and expose only the named HTML pages and
PNG assets, not project files, logs or arbitrary output files. Existing report links to
documentation are external links, opened only if chosen.

The opening token is removed from the address bar and stored for the page. API requests use
`X-Expectrail-Token`; they cannot authenticate with a URL or cookie. A port-specific, HttpOnly,
SameSite=Strict cookie carries the token for page reloads, reports and viewer frames. Every request
checks the exact loopback Host and the token. No CORS access is enabled.

If the connection fails after starting a job, it may still be running. Use **Retry status**
or **Cancel**. Reloading the page clears the selected job from the screen; it does not cancel
it. Stop the app with Ctrl+C to cancel unfinished jobs. A restart uses a new token and
lists the same stored jobs without granting access to their report or viewer files.

An installer and a trial with a person unfamiliar with terminals remain open. Browser and
real-replay evidence for this slice is named in its work log; automated use is not a first-user trial.

## Auto-fix checkbox

Before selecting **Verify**, open the repair controls by checking **Try to fix the game if verification rejects it**.
The box starts unchecked. The app asks for the fixer, attempt limit and dollar cap before launch.
Choose **llm-patch (bounded provider requests)** only after the person starting the app has set the
reviewed provider/model, invocation cap, aggregate fixer cap, vision cap and durable month ledgers.
No key is entered in the page. Unknown or unpriced models, missing caps and provider violations
still stop for review. There is no silent model fallback. **Muse** stays refused with
`fixer-bound-unavailable`; selecting it does not create a bound.

The same explicit selection is `expectrail verify ... --auto-fix --auto-fix-agent llm-patch
--auto-fix-usd-cap 6 --auto-fix-attempts 1`. The old CLI default remains Muse. The separate
`expectrail repair JOB --agent llm-patch` uses the same existing loop after a reject.
A repair's candidate may accept, reject or need review; the original rejected job stays rejected.
Nothing merges the patch. The [operator steps and evidence](repair-remaining.md) distinguish
fixture tests, real engine diagnostics and the live run Sean has not performed.
