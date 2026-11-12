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
- On Python 3.13 it finds what `Path.glob` found wherever every folder can be listed, so no verdict
  there changes. Two differences:
  - Names are compared as written, so on a file system that ignores case `ROUTES/*.json` no longer
    finds `routes/smoke.json`. Linux cannot show it.
  - A folder that can be entered and not listed (the merge guard's first review). `Path.glob` goes
    to a plain name without listing, and so does the matcher: a route named in full is found there,
    as on main. Where a part with `*`, `?`, `[` or `**` needed the listing, main found nothing and
    said nothing; the gate now adds the reason "cannot list the folder ... while looking for
    routes". After `**`, a plain name is also tried in such a folder, which `Path.glob` does not do,
    so the matcher can find one file more there, with that reason beside it.
- `request.pattern_reaches` compares one name with the gate's `segment_matches`, the function the
  matcher uses, instead of calling `fnmatch` itself. Its extra comparison without regard to case
  stays: it can only add a yes.
- The `package` job runs the whole suite on Python 3.12 before it downloads the engine, so the
  suite runs on both Pythons on every pull request.
- `docs/ci-gate.md` also says that a spec that is a link is counted by its name, never by what it
  leads to (the merge guard's suggestion on #321).

## What was run
- `python3.12 -m unittest tests.test_route_patterns` and the same on 3.13: 11 tests, OK on both, none
  skipped. The module imports the standard library only, so it runs on 3.12 here, where `jsonschema`
  is not installed. The three tests of a folder that cannot be listed make the refusal with a
  stand-in for the listing call, so they run as any user. With a real folder of mode 0111 they were
  run by hand as a user that is not root, on both Pythons, before the stand-in replaced the skip
  they needed as root: OK, and on 3.13 each plain-name pattern gave what `Path.glob` gives.
- The review's own case through `read_checks`, as a user that is not root, Python 3.13: routes
  `['coins', 'smoke']`, no problem, digest `f439c3e96bcd`, the three values the review gives for
  main. With `routes/*.json` in place of the full name: `['coins']` and the reason "cannot list the
  folder routes while looking for routes (head)".
- `test_every_python_finds_the_same_files`: 39,526 generated patterns (1,556 find a file) over a tree
  with a link to a folder, a link to a file, a link to nothing, a loop and a link that leaves the
  checkout. One digest of every pattern and what it finds, recorded on 3.13; 3.12 gives the same.
- `test_the_same_as_path_glob_where_path_glob_can_be_asked`: on 3.13 all 39,526 are equal to
  `Path.glob`. On 3.12 the patterns `Path.glob` refuses or that end in `**` are left out of that
  comparison and held by the digest.
- With main's `find_routes` on Python 3.12, `test_a_pattern_that_ends_in_two_stars_finds_the_files_below`
  and `test_folders_nested_deeper_than_python_nests_calls` fail.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, merged with main at 1dce492, as root: 2,216 tests, OK, 29
  skipped.
- The real sample with Godot 4.7.2 (`python3 -m expectrail.orchestrator sample`): accept, reject,
  accept, each as expected.
- OBAAF check: 0 new.

## Not done
- The whole suite on Python 3.12 was not run here: the 3.12 on this machine has no `jsonschema`
  and nothing can be installed. This pull request's `package` job is its first run. It may find
  other differences; they are fixed here if small and filed if not.
- Not run on a file system that ignores case, and not on Windows.
- A reason about a check file does not change the decision: with a route file that is not JSON, not
  a valid route or over the size cap, or a spec file that is not a valid spec, beside checks that
  pass, the gate still says accept and adds the reason after "all 2 checks pass" (run here on
  main's code with the gate tests' stand-in replay, five cases). The new "cannot list" reason is
  the same. That is #340; it needs a field in the record, so it is its own change.
- A route file that is a link is still left out without a reason, as before (#340).
- `expectrail/jit/bench.py` and `blind.py` still pin files with `Path.glob`. None of their patterns
  ends in `**` or has `**` inside a longer part.
- Unity's build copy and the web runner's copy still use their own walks (#324).

## Files
`expectrail/gate/verify.py`, `expectrail/orchestrator/request.py`, `tests/test_route_patterns.py`,
`tests/test_orchestrator.py`, `.github/workflows/ci.yml`, `docs/ci-gate.md`, `docs/orchestrator.md`
