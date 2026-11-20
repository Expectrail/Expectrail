# An audit of live workflow steps that may reach a capped model sender without its cap (#267)

## What changed
Since #267 every model role's sender holds against its own cap and sends nothing without one
(`EXPECTRAIL_SAM_USD_CAP` for vision, `EXPECTRAIL_{GLIMMER,MUSE,TRIAGE,SPEC}_USD_CAP` for the others).
Builder two found by `grep` on #267 that most workflows in the `spend` environment set none of these,
and asked which steps actually reach a sender. This answers that from the code, as far as a static
reading can, and keeps the answer from getting worse.

`python3 -m tools.spend_cap_audit` reads every job of `.github/workflows/` that runs in a protected
environment. For each step that holds a model key a role can use, it finds the Python the step starts
(`python -m`, a script path, a shell script, the `expectrail` command, `-c`, a here-document, a command
substitution) and follows the repository's imports from there, including imports inside functions and
module names given as strings for a child process. Senders are found by reading the code: calls to
`hold` or `require_cap` with a role, in a module that imports `expectrail.spend`, plus
`agents.sam_observations` for vision. A role whose sender is reachable, whose key the step holds, and
whose cap is not set at the workflow, job or step level, by `export`, or through `$GITHUB_ENV` in an
earlier step, is listed. A start it cannot follow (`python -m "$module"`, a script it cannot read) is
"cannot tell", never "no gap".

A cap counts as set only from outside the step's script: the workflow's, the job's or the step's
`env:` with a value that is not literally empty (a value such as `${{ inputs.cap }}` is known only at
run time and counts; the sender stops on an empty cap anyway), or an earlier step of the job surely
writing it to `$GITHUB_ENV`. That write is read as shell commands by a small lexer that keeps quoting
apart from operators: it counts from the next step only when it is `echo NAME=value >> $GITHUB_ENV`
(quoted or not) or `cat >> $GITHUB_ENV` with a here-document, and surely runs. A comment, an argument
or a here-document body never counts.

The script itself never sets a cap here (after the merge guard's second review). Whether a start runs
with a cap depends on the order of the step's commands: an `export` after the start, an `unset`,
`export -n`, `env -u`. The audit does not follow that order, so a step whose script, or a shell script
it runs, names a cap the step needs is "cannot tell" for that cap, even when `env:` also sets it. The
same holds for a start under `sudo`, `su`, `doas`, `runuser`, `exec -c`, or `env` with an option
(`-i`, `-u`), which change the environment the start sees. Within what it reads, then, a step is
listed whenever a start may run without a cap it needs. What it does not read: a variable name built at
run time (`unset "$NAME"`), and a program other than a shell script or our Python that changes the
environment before starting ours. Model keys are found by a looser text search, which over-reports in
the safe direction (it audits more steps).

It is an over-approximation and says so: "may reach" is not "sends". The repository's imports are
densely linked, so most entries will be steps that never send that role. The recorded list,
`tools/spend_cap_gaps.json`, gives each entry `unreviewed` or what a reader found (`not sent: why` or
`open: why`). One entry is reviewed here: `byo-smoke.yml` does not send spec, because `agents.byo_smoke`
calls `chat_completion` with role `LLM` and `expectrail.providers` holds spec only for role `SPEC`.

`python3 -m tools.spend_cap_audit --check` and `tests.test_spend_cap_audit` fail on a step the audit
lists that is not in the file, so a new live step that may start a sender without its cap is caught
when it is written, and on a step in the file the audit no longer lists, so the list only shrinks. The
comparison is by step, not by cap. Which caps a listed step may miss moves with any new import on main:
merging #602 added Muse to ten listed steps. Compared by cap, every such merge would turn the suite red
on pull requests that touch no workflow. `--check` prints that drift as notes, and the file records the
caps as last read.

Today's list: 48 steps in 38 jobs of 22 workflows. By cap: spec 46, vision 32, Muse 29, Glimmer 9,
triage 4. Five steps cannot be told: `fix-matrix.yml` judge-run (`python -m "$module"`), and the four
steps that export `EXPECTRAIL_SAM_USD_CAP` in their own script (`jit.yml` pixel-ask,
`outside-sam-probe.yml`, `run-it-record.yml`, `sam-probe.yml` sam-probe).

No workflow is changed. Which roles each workflow means to pay for, and from which budget, is for each
workflow's owner; vision's caps in workflows are #327's.

## What was run
- `python3 -m tools.spend_cap_audit --check` on the branch merged with main cb26728: 48 steps listed;
  they match the recorded list.
- `python3 -m unittest tests.test_spend_cap_audit`: 54 tests, OK (34 before the first review, 48
  before the second). The synthetic repositories cover each
  way of reaching a sender, each way of setting a cap, the cases that cannot be told, and the key filter.
  Four tests hold the audit's tables to `expectrail.spend.CAP_ENV`, `agents.sam_observations.KEY_ENV`,
  `agents.glimmer_client.KEY_ENVS` and `expectrail.providers.PROVIDER_DEFAULTS`.
- Five mutations of the audit, each caught by the tests: no string edges to child processes; a
  `$GITHUB_ENV` write counted in its own step; an empty cap counted as set; a module chosen at run time
  passed silently; the key filter removed.
- The review's probes (a comment, an argument, an unquoted same-step `$GITHUB_ENV` write, a comment
  in a here-document) and the rest of the class are tests in `CapsReadAsCommands` and
  `Synthetic.test_each_probe_is_a_gap`. With the old text search put back (and the new names aliased
  to it), 25 of those subtests fail and 4 error, so they catch it.
- The second review's probes are tests (`Synthetic.test_each_ordering_probe_is_not_passed`): an export
  after the start, on the same line after `;`, `unset`, `export -n` and `env -u` after an export; and,
  with the cap from `env:`, `unset`, `env -u`, `env -i`, `sudo` and `exec -c`. Three mutations, each
  caught: the script's exports counted again (6 failures, 1 error), the changed-environment check
  removed (3 failures, 1 error), and a followed shell script's text ignored (1 failure). The probe
  "`exit 0`, then `export`" starts nothing, so nothing in it can send and it is not listed (tested).
- Comparing by step: with new steps dropped from `compare`, its test fails.
- Full suite: see the pull request.
- Nothing was dispatched and nothing was spent.

## Not done
- Reviewing the 47 `unreviewed` entries, and setting caps where a step does send. Each fix sets the
  cap from that workflow's own budget input (as #618 did for `jit.yml`) and removes the entry.
- The audit is not a CI step of its own; it runs as part of the suite.

## Files
- `tools/spend_cap_audit.py`
- `tools/spend_cap_gaps.json`
- `tests/test_spend_cap_audit.py`
- `.gitignore`
- `docs/new-work/2026-11-18-spend-cap-audit.md`
