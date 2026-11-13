# Verify two versions in the local app

With Expectrail installed, start it once:

```sh
expectrail app
```

In a repository checkout, use `python3 -m expectrail.app` instead. Python 3.12 or newer is
required. Open the full address it prints. Keep that process running while using the page.
The address is on `127.0.0.1`, with a free port and a new token each time. Do not share it.
The app serves its own page without downloading scripts, styles or fonts.

1. Paste the full paths to **Before** and **After**, two folders with the same layout. Git
   references are not supported in this slice.
2. Open **Where your game, routes and checks are** if needed. The game folder defaults to
   `.` (the folder containing `project.godot`), the routes to `routes/*.json`, and the checks
   folder to `specs`. These paths are relative to each version's folder.
3. Select **Check folders**. The page reports whether it found a Godot project, usable
   routes and approved checks, and gives next steps for missing inputs. Checking folders
   does not run Godot or check the machine's tools. If you have no routes or checks, ask
   your game developer to provide them. Only a person may approve checks.
4. Select **Verify**. The routes and approved checks from **Before** judge both versions,
   exactly as with `expectrail verify --base BEFORE --head AFTER`. The page shows the job's
   recorded phases. **Cancel** asks the orchestrator to stop the job and its processes.
5. Read the result and its reasons. **Accept** and **Reject** are the verifier's decisions
   under the checks used. **Needs review** is not an accept. **Failed**, **Cancelled** and
   **Could not be carried out** give no verdict. An unfinished job gives no verdict either.
   When the job has an existing report, the page links to it. Missing tools are reported by
   the verifier, with its suggested fix.

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

An installer, a trial with a person unfamiliar with terminals, and tests of this app on real
games are not done in this slice. This page was not looked at in a browser.
