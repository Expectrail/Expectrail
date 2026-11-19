# A candidate is applied as the tree it names, whichever `patch` the machine has (#659)

## What changed
macOS's `patch` (and GNU `patch` under POSIXLY_CORRECT) leaves a zero-byte file where a patch deletes
one (`+++ /dev/null`). Three repair tests on macOS returned `reject` because the verifier judged a tree
that still held the deleted file (#378).

- `harness/patching.py` (new): `apply(work, patch)` is the one way a seed, candidate or repair reaches
  a game copy. It reads the patch's headers and counts each hunk's lines from its `@@` header, so a
  removed line that reads `--- x` is not taken for a file. After `patch -p1 --forward --batch` exits 0:
  - a file the patch deletes and that is left with zero bytes is removed;
  - a deleted file still there with content, or as anything but a file, stops the application;
  - a file the patch edits or creates must be there afterwards, even when the edit empties it. No
    global `-E`, which would delete a file a candidate meant to empty.
- An empty patch changes nothing, as `patch` treats it (`agents.matrix` gives an offline fixer one).
- What it cannot check is refused before `patch` runs: a non-empty patch naming no file, an absolute path or one with
  `..`, a rename, a copy, a binary change, `/dev/null` to `/dev/null`, a hunk with more lines than its
  header. A hunk cut short is left to `patch`, which accepts it (`agents/fixtures/out-of-glob.patch`
  is one).
- Errors are `PatchNotApplied`, a `CalledProcessError` whose message names the file, so `runit`,
  `repair` and the proposal writer, which already stop on a failed `patch`, stop on it too.
- Callers moved onto it: `agents.patchutil.apply_patch` / `apply_patches` (used by `expectrail.runit`,
  `expectrail.repair`, `agents.assurance.proposal`), `harness.run.apply_patches` (every replay copy),
  `expectrail.gate.known_bench._patch` and `expectrail.orchestrator.sample.checkout`.
- Left as they are, on purpose, and listed in a test: `expectrail/jit/blind.py` (pinned by blind set
  3's registration) and `harness/web/run.py` (it applies the private web patches, which this change
  cannot be tested against).
- `setup.py` ships `harness.patching` in the wheel.

## What was run
- Reproduced first, on Linux (GNU patch 2.7.6), main b3c74d2: the three tests #378 names pass with
  default `patch` and all three error under `POSIXLY_CORRECT=1`.
- `python3 -m unittest tests.test_patching`: 23 tests, OK. They include the three controls with the
  machine's own `patch` (delete, empty by edit, both in one patch), a game copy inside another Git
  checkout, GNU `patch` in POSIX mode on deletions only (the raw program leaves `BUG` empty; `apply`
  removes it), and the three repair tests from #378 run with deletions applied that way: all pass.
- Every tracked `*.patch` and `*.diff` outside `fresh-*` (103 files) reads with the new parser; none
  is refused.
- The full suite on main b3c74d2 plus this change, without the engine: `python3 -m unittest discover -s tests
  -t .` ran 5,260 tests, OK, 66 skipped (711 s). The first run of it found two callers this change
  had broken (an empty offline patch in `agents.matrix`, and the mutation bench's rehearsal pair);
  both pass now that an empty patch changes nothing.
- Native macOS: not run here. The `macOS suite` workflow runs these tests on push to main and on
  dispatch.

## Not done
- A native macOS record of the patch executable's version and the file state after each control.
- `harness/web/run.py` and `expectrail/jit/blind.py` still call `patch` directly.

## Files
- `harness/patching.py` (new), `tests/test_patching.py` (new)
- `agents/patchutil.py`, `harness/run.py`, `expectrail/gate/known_bench.py`,
  `expectrail/orchestrator/sample.py`, `setup.py`
- `docs/new-work/2026-11-19-patch-deletes.md`
