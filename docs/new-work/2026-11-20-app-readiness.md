# Check Before’s verification setup in the local app (#692)

## What changed

Verify now explains which route or approved check the Before project needs before asking the developer to acknowledge its renderer warning. The local app uses the same readiness rules as configured CLI verification. On submission, the server checks the routes and specs from the snapshot of Before that would judge the change. A refusal removes the unused snapshot before a job or worker starts. A readiness refusal identifies that verification did not start. A lost submission reply keeps the existing guidance to check Past runs.

## What was run

- On main `89dff2e8`, the new HTTP regression received 201 when Before had no usable route, no approved check, or only a named draft. After retained the usable route and approved check in all three cases.
- The source-edit regression first returned HTTP 201 when the check list was empty during the copy of Before. With the snapshot check, the server returned HTTP 400, identified the missing approved check, and retained zero jobs or snapshots.
- An initial full-suite run found one compatibility failure. A renderer inspection could describe a ready project without the new readiness field. The browser now preserves its renderer warning for that response, and the existing regression passed unchanged.
- `python3 -m unittest tests.test_recorded_renderer_drift.AppBrowserTest tests.test_app_projects tests.test_project_unready tests.test_app tests.test_app_screens` ran 57 tests in 38.503 seconds, all passing. This includes a ready Before, a candidate dropping the check, a draft config with an approved check, and a lost submission reply.
- After the required historical commit fetch, `python3 -m unittest discover -s tests -t .` ran 5,590 tests in 544.628 seconds, 78 skipped, zero failures or errors.
- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,256 files with zero errors or warnings.

## Chromium rehearsal on public game copies

On main `89dff2e8`, Verify started one job on the prepared Breakout draft with one route and zero approved checks. On the changed code, the same click showed the missing Before check and said “Verification did not start.” Both 108-file project folders retained the digest `08f93d2acd3c6a1ffc0808df9a5445cf04afaf1ca80497c1e4b84e1ebaa6c316`. The digest covers the sorted relative paths and SHA-256 of every file. Each browser case below preserved every source file in both folders.

| Before project | Job submissions | Jobs created | What the developer saw |
| --- | ---: | ---: | --- |
| Breakout draft with no approved check | 0 | 0 | Name an existing approved check and review the draft bindings. |
| Kinematic-character with the check listed only in After | 0 | 0 | Before must name an approved check. |
| Kinematic-character with no usable route | 0 | 0 | List a usable route in the Before config. |
| Kinematic-character naming a draft check | 0 | 0 | The named check needs human approval. |
| Kinematic-character with a usable route and approved check | 1 | 1 | Verification reached the worker and ended in needs-review during the sandbox preflight on this host. |

In a separate race test, the browser inspected a ready Before folder, then the test removed its check reference just before submission. The app sent one request, created zero jobs and reported “Verification did not start.” The test restored the config afterward. These were automated rehearsals.

## Not done

An unaided developer session on their own game remains open.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `expectrail/project_job.py`
- `tests/test_app_projects.py`
- `docs/new-work/2026-11-20-app-readiness.md`
