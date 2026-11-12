# A route that is a link, or outside the checkout, is named and counted (#340)

## What changed
Two kinds of file a route pattern can name were left out of the routes and nothing said so: a link
to a file, and a file reached through a link that leaves the checkout. A change was then judged on
fewer routes than the job named, with no reason and no trace in the digest. (A spec that is a link
has been named and refused since #321.)

- `expectrail.gate.verify.match_routes` gives back the route files, the links to a file and the
  files outside the checkout, from the one walk; `find_routes` is its first list, as before.
- `read_checks` hands a link to the reader, which refuses it with the reason it gives for a spec,
  and never opens a file outside the checkout. Both are in `problems` and in the digest by name
  and refusal. A link to nothing or to a folder is still no route file.
- With the rule of the first part of #340, either one means the result is never accept.
- `docs/harness.md` says what the merge guard found on #339: an action that shares its first key
  with another is released with it.
- Corrections to what #337's log says: its line that after `**` a plain name is tried in a folder
  that cannot be listed "which `Path.glob` does not do" is wrong; on Python 3.13 `Path.glob` does
  (the merge guard's run). The comment in `read_checks` that said such a folder makes the result
  needs-review is reworded; it became true with the first part of #340.

## What was run
- `tests.test_route_patterns` on Python 3.12 and 3.13: 12 tests, OK on both.
- `tests.test_orchestrator` and `tests.test_ci_gate`: OK.
- Full suite and the real sample: see the pull request.

## Not done
- A link to nothing where a route would be is not named: it is no file, as for specs.
- A pipe or a device a pattern names is passed over (it is not a file).
- A route that names an action the project does not have is still not stopped.

## Files
`expectrail/gate/verify.py`, `tests/test_route_patterns.py`, `tests/test_orchestrator.py`,
`docs/ci-gate.md`, `docs/orchestrator.md`, `docs/harness.md`
