# The wheel qualifies module names given as strings, and refuses what it cannot read (#614)

## What changed
#599 made the wheel builder rewrite `import` and `from ... import` of `harness` and `agents` to
`expectrail._bundle....`, and took `_bundle` off `sys.path`. A module named in a string was not
rewritten: `agents/observations.py` loaded its vision provider with
`importlib.import_module("agents.sam_observations")`, so in an installed copy it found no module, or a
foreign `agents` package's.

- `agents/observations.py` now imports its provider relatively,
  `importlib.import_module(".sam_observations", __package__)`, in both places. That resolves to the
  bundled module in the wheel and to `agents.sam_observations` in a clone.
- As the fallback, `setup.py`'s `qualify_imports` also rewrites a literal module name passed to
  `import_module`, `__import__`, `find_spec` or `run_module` (first argument or `name=`) when it names
  `harness` or `agents`. Relative names are left alone.
- What it cannot read stops the build with `ValueError` and the line: such a call whose module name is
  not a literal string, and any other string that is exactly a dotted harness/agents module name (for
  example `"-m", "agents.loop"`), since the builder cannot tell whether it is used as a module name.
  No packaged module has one today.
- `docs/install.md` says what the rewrite covers and what stops the build.
- `README.md`: the install block and its paragraph move below the logo and the `# Expectrail` title.
  The quickstart timer's rule (the first `sh` block is the install) is unchanged and still holds.

## What was run
- New tests first, on the branch before the fix: `python3 -m unittest tests.test_package`, 32 tests,
  9 failures and 2 errors, among them the installed copy's `_load_sam_provider()` with a foreign
  `agents` package on the path.
- With the fix: `tests.test_package`, OK.
- With the source fix reverted and only the builder rewrite: the installed-copy test and
  `ContentsTest` pass (9 tests, OK), so the fallback works alone.
- Mutations: no rewrite and the old source, caught by the installed-copy test and the wheel scan;
  the bare-string refusal turned off, caught by `test_what_it_cannot_read_stops_the_build`.
- The full suite on the branch merged with main at 2e014e1: `python3 -m unittest discover -s tests -t .`,
  4,929 tests, `OK (skipped=60)`.

## Not done
- Still Sean's on #249: applying `docs/proposals/249-wheel-sample.yml.txt` as a CI job and the
  container run in CI.
- Data paths such as `REPO / "harness" / "routes"` are not module names and are not touched.

## Files
- `setup.py`
- `agents/observations.py`
- `tests/test_package.py`
- `docs/install.md`
- `README.md`
- `docs/new-work/2026-11-18-wheel-string-imports.md`
