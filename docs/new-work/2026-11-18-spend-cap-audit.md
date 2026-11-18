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

How a script sets a cap is decided from its parsed commands, not from text (after the merge guard's
review): a small shell lexer keeps quoting apart from operators, and a cap counts only when a plain
`export NAME=value` (or `declare -x`, or `export NAME` after `NAME=value`) surely runs in the step's own
shell: at top level, not inside `if`, a loop, `case`, a `{ }` group, a subshell or a function, not after
`&&` or `||`, not in a pipeline or the background, and not with a redirection. A comment, an argument,
a here-document body, a prefix `NAME=value cmd` (it covers one command and the audit works per step), a
bare assignment without `export` (it does not reach a child process; `set -a` is not followed), and a
write to `$GITHUB_ENV` do not count in the step. A write to `$GITHUB_ENV` counts from the next step
only when it is `echo NAME=value >> $GITHUB_ENV` (quoted or not) or `cat >> $GITHUB_ENV` with a
here-document, and surely runs. A line the lexer cannot read, or nesting that does not balance, makes
the whole script set nothing. So the audit can only over-report a gap, which `--check` shows; it cannot
pass one. Model keys are still found by the old text search, where over-reporting is the safe
direction (it audits more steps).

It is an over-approximation and says so: "may reach" is not "sends". The repository's imports are
densely linked, so most entries will be steps that never send that role. The recorded list,
`tools/spend_cap_gaps.json`, gives each entry `unreviewed` or what a reader found (`not sent: why` or
`open: why`). One entry is reviewed here: `byo-smoke.yml` does not send spec, because `agents.byo_smoke`
calls `chat_completion` with role `LLM` and `expectrail.providers` holds spec only for role `SPEC`.

`python3 -m tools.spend_cap_audit --check` and `tests.test_spend_cap_audit` fail on a gap not in the
list, so a new live step that may reach a sender without its cap is caught when it is written, and on a
listed gap that is gone, so the list only shrinks.

Today's list: 48 steps in 38 jobs of 22 workflows. By cap: spec 46, vision 32, Muse 19, Glimmer 9,
triage 4. One step cannot be told (`fix-matrix.yml` judge-run, `python -m "$module"`).

No workflow is changed. Which roles each workflow means to pay for, and from which budget, is for each
workflow's owner; vision's caps in workflows are #327's.

## What was run
- `python3 -m tools.spend_cap_audit --check`: 48 steps listed; they match the recorded list.
- `python3 -m unittest tests.test_spend_cap_audit`: 48 tests, OK (34 before the review's changes). The synthetic repositories cover each
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
