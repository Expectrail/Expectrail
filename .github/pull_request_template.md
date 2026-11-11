<!-- Closes #N, or Part of #N. Agents label the pull request agent-pr; see AGENTS.md. -->
Part of #

## What was built

## What was run, and its result

<!-- A test, a CI run or a command with its output. "Not run" is an acceptable sentence; a guess presented as a result is not. -->

## What is left

## Anything only a person may do

<!-- Approving a check, held-out material, a secret or an environment, AGENTS.md or CODEOWNERS. Write "nothing" if nothing. -->

## Checklist

- [ ] `python3 -m unittest discover -s tests -t .` passes on this branch
- [ ] One row added to `docs/new-work.md`: the date, what changed, what was and was not run, the files
- [ ] No `approval` added or changed, nothing under `game/platformer` or `game/unity-platformer` edited
- [ ] No test deleted or skipped, or the reason is above with the line `Guard: test change intended (#issue)`
- [ ] A schema, its example, its writer and its reader change together
