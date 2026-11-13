# `--jobs-root` after the command, and a usage error that shows the `expectrail` command list (#383)

## What changed
Found by the nightly platform test (#383): `expectrail verify ... --jobs-root DIR` exited 5 with
"unrecognized arguments", because the orchestrator took `--jobs-root` only before the command, while
`expectrail app` takes it only after. The usage it printed was the orchestrator's: it listed the
worker's internal `_work` command and left out `app` and `doctor`.

- `verify`, `status`, `cancel`, `report` and `sample` take `--jobs-root` after the command too. Before
  the command still works. The same folder in both places is fine; two different folders is a usage
  error (exit 5, "given twice"), never a silent choice of one.
- A command line the top-level parser cannot read now shows the `expectrail` command list (the same
  text as `expectrail --help`) when it came through `expectrail`. A subcommand's error still shows that
  command's own options.
- The command list in usage and help says `COMMAND`, not `{verify,...,_work}`; `_work` appears in no
  help or usage text. The `expectrail` list now explains where `--jobs-root` goes.
- `expectrail` with no command or an unknown one now also says "Nothing was run.", as every other usage
  error does.
- `docs/orchestrator.md` and `docs/install.md` say where `--jobs-root` goes.

## What was run
- `python3 -m unittest tests.test_orchestrator tests.test_package`: OK. New tests: `CliTest` (the
  folder after the command for status, verify, report and cancel; a folder only before the command is
  not dropped; two different folders are refused) and `CommandTest` (a usage error through `expectrail`
  shows its command list with `app` and `doctor` and without `_work`; `status JOB --jobs-root DIR` is
  read). No Godot and no model ran.
- The full suite: see the pull request.

## Not done
- Not run from an installed wheel; the package job in CI runs the installed command.

## Files
- `expectrail/orchestrator/cli.py`
- `expectrail/cli.py`
- `tests/test_orchestrator.py`
- `tests/test_package.py`
- `docs/orchestrator.md`
- `docs/install.md`
- `docs/new-work/2026-11-13-jobs-root-after-command.md`
