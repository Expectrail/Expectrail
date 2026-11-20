# Proposed workflow: Sean installs it, nothing has been dispatched

The adjacent `531-live-repair-workflow.yml.txt` is complete proposed workflow
text, not an active workflow. No file under `.github/` was created or edited.
Sean must review the following before adding it on main.

- `workflow_dispatch` is the only trigger. There is no pull-request, fork,
  schedule, workflow-run or push trigger. `confirm` defaults false. The job's
  repository, event and main-ref conditions refuse another repository or ref.
- `contents: read` permits checkout. No write permission, id token, PR comment,
  deployment or repository mutation is needed. Artifact upload uses the action's
  run-scoped artifact mechanism, not an actions-write permission.
- `concurrency` serializes these runs and never cancels a paid run for a newer
  one. The existing ledger locks also serialize reservations across processes.
- Use a **dedicated self-hosted Linux runner**, labelled `expectrail-live`, with
  Python 3.12+, `python3 -m pip install -e ".[contracts]" pillow`, pinned Godot from `harness/get_godot.sh`,
  Xvfb/xauth, patch/git and functioning Bubblewrap. Restrict its runner group to
  this repository and trusted main workflows. Never let fork/PR code run on it.
  Set repository variable `EXPECTRAIL_GODOT_BINARY` to the installed binary’s
  absolute path; the workflow exports it as `EXPECTRAIL_GODOT` and checks its
  version against the repository pin before loading keys. Keep tool downloads
  outside checkout cleanup using `EXPECTRAIL_TOOLS` during provisioning.
  It needs outbound HTTPS only to the named OpenAI and Meta APIs for this run.
- Create the `live-repair` environment with deployment branches restricted to
  main, and store `EXPECTRAIL_OPENAI_FIXER_KEY` and
  `EXPECTRAIL_META_VISION_KEY` there. The former is an OpenAI key with access to
  the exact reviewed model; the latter is Meta's SAM Model API key. They must be
  separate keys. No key is created or supplied by this kit. No secret belongs in
  repository files, dispatch inputs, command arguments or artifacts. Only the
  run step binds them into the process environment. Protecting the environment
  and runner group is essential: YAML conditions alone cannot defend against a
  different malicious workflow an administrator permits to use those secrets.
- Set the repository variable `EXPECTRAIL_LEDGER_DIR` to a persistent, private
  runner directory outside every checkout. Provision mode 0700, writable by the
  runner. Keep `model-month.json`, `vision-month.json` and their lock files across
  runs. Use a dedicated service identity and back up this state. Do not reset or
  restore an older ledger to get more credit. The existing readers refuse corrupt
  files; the month changes in UTC. GitHub-hosted disks and evictable caches do
  **not** provide this durable shared month state, so this proposal uses neither.
- Every configurable cap is a dispatch input: invocation, aggregate fixer,
  per-worker vision and output tokens. The structured inputs also name the three
  disabled role caps and the two compiled $200 monthly limits. Other roles must
  stay zero; monthly limits must match the existing compiled policy. A person
  cannot raise them with dispatch text. Two separate $200 month ledgers are not
  a combined $200 allowance.
- The plan step validates inputs as data, prints the quote before loading keys,
  and checks the engine/sandbox. Input values enter quoted arguments or JSON
  parsing; none becomes shell code. The live step prepares only the public seeded
  fall-through project and handwritten report. There is no user-supplied patch,
  model, route, prompt, game repository or fixer choice in dispatch inputs.
- Checkout uses the event's main SHA, not an input ref, and drops Git credentials.
  The fixed model/endpoint/tier and existing CLI are selected in trusted code.
  Replace the action version tags with independently verified immutable SHAs if
  that is Sean's action-pinning policy; do not invent an unverified SHA.
- The default inputs quote **$10**: one $6 fixer envelope and two $2 SAM worker
  envelopes. The plan recalculates before execution if caps/attempts change.
  Output/retry limits, pre-send reservations and the gate still apply. The
  45-minute job timeout is a time bound, not the dollar-bound mechanism.
- Artifacts include the cap plan, report, real command output, jobs, traces,
  frames, findings, candidate patch, repair-run and invocation/budget records.
  The durable month ledgers stay outside the upload. Keep enough artifact quota
  for frames; retrieve the artifact before seven-day retention expires. An
  upload failure does not refund or undo a paid call. Needs-review still uploads
  evidence and must not cause an automatic retry.

Do not add a required environment reviewer if the intended operation is one
manual dispatch; that would add another deliberate approval step. Sean may
choose that stronger policy himself, but then the run sheet must say so.
No GitHub settings, environment, workflow or secret was changed here.
