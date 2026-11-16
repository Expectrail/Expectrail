# Verify two versions in the local app

With Expectrail installed, start it once:

```sh
expectrail app
```

In a repository checkout, use `python3 -m expectrail.app` instead. Python 3.12 or newer is
required. Open the full address it prints. Keep that process running while using the page.
The address is on `127.0.0.1`, with a free port and a new token each time. Do not share it.
The app serves its own page without downloading scripts, styles or fonts.

1. Paste the full paths to **Before** and **After**, two Godot project folders. Each has
   `project.godot` and its own [project config](project-config.md), `expectrail.project.json`.
   Git references are not supported in this screen.
2. The config's `routes` and `approvedContracts` lists choose the policy. The base config
   chooses what judges both copies. A config produced by `expectrail init` is a draft and
   cannot give an accept until its bindings are reviewed. Only a person may approve checks.
3. Select **Check folders**. The page lists usable route names, approved check IDs and draft
   warnings. The setup doctor probes the installed engine and display with an empty project;
   it runs neither your selected game nor a model. Missing engine, display or drawing support
   now shows its reason and fix for live vision as well as recorded vision. Invalid or absent
   configs name what to fix.
   **Older projects without a config** retains the explicit path inputs for existing checkouts.
4. Select **Verify**. The app and `expectrail verify --project AFTER --base BEFORE` prepare
   the same kind of request and use the same worker. The job snapshots both games and the
   selected policy bytes outside your source folders. The page shows phases; **Cancel** asks
   the orchestrator to stop the job and its processes. [Offline parity tests](../tests/test_app_projects.py).
5. Read the result and its reasons. **Accept** and **Reject** are the verifier's decisions
   under the checks used. **Needs review** is not an accept. **Failed**, **Cancelled** and
   **Could not be carried out** give no verdict. An unfinished job gives no verdict either.
   When the job has an existing report, the page links to it. Missing tools are reported by
   the verifier, with its suggested fix.

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
The box starts unchecked. The app asks for the attempt limit and dollar cap. The checkbox requests Muse
and has no fixture picker. Muse still has no enforceable per-request dollar bound, so that live path
stops with needs-review and `fixer-bound-unavailable`. Use the [CLI fixture example](../README.md#verify-then-repair)
to try the loop without a model. The separate `expectrail repair JOB --agent llm-patch` selector
does not change this checkbox or verification's auto-fix agent. Its live path still requires the
reviewed model, keys and enforced caps; no live repair was run in this audit.
[App and budget tests](../tests/test_auto_fix.py), [remaining close-out steps](p0-closeout-audit.md).
