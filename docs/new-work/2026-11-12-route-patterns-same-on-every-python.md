# A route pattern finds the same files on every Python (#307)

## What changed
The gate found route files with Python's `Path.glob`, and `Path.glob` does not mean the same thing
on every Python. On Python 3.12, the oldest the package says it supports, a pattern that ends in
`**` (for example `routes/**`) finds no file; on 3.13 it finds every file below. So the same request
was judged by different routes, and had a different `policyDigest`, depending on the Python that ran
it. On 3.12 `Path.glob` also refuses a pattern with `**` inside a longer part (`r**/x.json`) with a
`ValueError`. Nothing ran on 3.12 except the package job's own tests, so none of this showed. The
merge guard's note on #307 was the first sign: one property test counted 421 matches on 3.12 and
557 on 3.13.

- `expectrail.gate.verify.pattern_matches` is the gate's own matcher and `find_routes` uses it. It
  lists folders itself, part by part, with a work list instead of recursion. The rules are in
  `docs/ci-gate.md` ("A route pattern finds the same files on every machine").
- On Python 3.13 it finds exactly what `Path.glob` found, so no verdict on 3.13 changes. One
  intended difference that Linux cannot show: names are compared as written, so on a file system
  that ignores case `ROUTES/*.json` no longer finds `routes/smoke.json`.
- `request.pattern_reaches` compares one name with the gate's `segment_matches`, the function the
  matcher uses, instead of calling `fnmatch` itself. Its extra comparison without regard to case
  stays: it can only add a yes.
- The `package` job runs the whole suite on Python 3.12 before it downloads the engine, so the
  suite runs on both Pythons on every pull request.
- `docs/ci-gate.md` also says that a spec that is a link is counted by its name, never by what it
  leads to (the merge guard's suggestion on #321).

## What was run
- `python3.12 -m unittest tests.test_route_patterns` and the same on 3.13: 8 tests, OK on both. The
  module imports the standard library only, so it runs on 3.12 here, where `jsonschema` is not
  installed.
- `test_every_python_finds_the_same_files`: 39,526 generated patterns (1,556 find a file) over a tree
  with a link to a folder, a link to a file, a link to nothing, a loop and a link that leaves the
  checkout. One digest of every pattern and what it finds, recorded on 3.13; 3.12 gives the same.
- `test_the_same_as_path_glob_where_path_glob_can_be_asked`: on 3.13 all 39,526 are equal to
  `Path.glob`. On 3.12 the patterns `Path.glob` refuses or that end in `**` are left out of that
  comparison and held by the digest.
- With main's `find_routes` on Python 3.12, `test_a_pattern_that_ends_in_two_stars_finds_the_files_below`
  and `test_folders_nested_deeper_than_python_nests_calls` fail.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, on this tree: 2,130 tests, OK, 22
  skipped.
- The real sample with Godot 4.7.2 (`python3 -m expectrail.orchestrator sample`): accept, reject,
  accept, each as expected.
- OBAAF check: 0 new.

## Not done
- The whole suite on Python 3.12 was not run here: the 3.12 on this machine has no `jsonschema`
  and nothing can be installed. This pull request's `package` job is its first run. It may find
  other differences; they are fixed here if small and filed if not.
- Not run on a file system that ignores case, and not on Windows.
- A folder the gate cannot list counts as empty and no reason is given, as with `Path.glob`. A
  route file that is a link is still left out without a reason, as before. Both should be named in
  the reasons; that changes records and is a separate change.
- `expectrail/jit/bench.py` and `blind.py` still pin files with `Path.glob`. None of their patterns
  ends in `**` or has `**` inside a longer part.
- Unity's build copy and the web runner's copy still use their own walks (#324).

## Files
`expectrail/gate/verify.py`, `expectrail/orchestrator/request.py`, `tests/test_route_patterns.py`,
`tests/test_orchestrator.py`, `.github/workflows/ci.yml`, `docs/ci-gate.md`, `docs/orchestrator.md`
