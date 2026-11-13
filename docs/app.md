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

These are diagnostic, engine-record runs, as with the command's default. They make no model
calls and do not independently judge screenshots. Only run games you trust: this slice does
not offer isolated execution. The verifier still needs its usual Godot and machine tools
when it runs a real game. The app has not removed those requirements.

Jobs are stored at `~/.local/share/expectrail/app-jobs`. To choose another folder outside
both games, use `expectrail app --jobs-root /path/to/jobs`. The app only exposes jobs created
in its current session. It serves each finished report's `index.html` and copied PNG assets,
not project files, logs, arbitrary output files or jobs from another session. Reports cannot
run scripts. Existing report links to documentation are external links, opened only if chosen.

The opening token is removed from the address bar and stored for the page. API requests use
`X-Expectrail-Token`; they cannot authenticate with a URL or cookie. A port-specific, HttpOnly,
SameSite=Strict cookie carries the token for page reloads and report images. Every request
checks the exact loopback Host and the token. No CORS access is enabled.

If the connection fails after starting a job, it may still be running. Use **Retry status**
or **Cancel**. Reloading the page clears the selected job from the screen; it does not cancel
it. Stop the app with Ctrl+C to cancel unfinished jobs. A restart uses a new token and does
not list past jobs.

The evidence viewer has a named placeholder. The viewer, past runs, an installer, a trial
with a person unfamiliar with terminals, and tests on real games are later slices. This page
has not been looked at in a browser.
