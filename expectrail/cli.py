"""The ``expectrail`` command: one name in front of what is built.

    expectrail verify --head . --game game/platformer --routes 'routes/*.json' --specs specs [--base ../base]
    expectrail status JOB | cancel JOB | report JOB
    expectrail sample              three real verifications of the bundled game: as it is, broken, repaired
    expectrail --version

`verify`, `status`, `cancel`, `report` and `sample` are the orchestrator's own commands
(``expectrail.orchestrator.cli``): the same functions, the same options and the same exit codes as
``python3 -m expectrail.orchestrator``. Nothing is implemented twice here.

Commands that are planned and not built say so, name the issue, and exit 5 (the command could not
be carried out). They never print a verdict.
"""
from __future__ import annotations

import sys

from expectrail import __version__, resources

ORCHESTRATOR = ("verify", "status", "cancel", "report", "sample")
# name -> (what it will do, the issue that builds it)
PLANNED = {
    "doctor": ("check that this machine has what a verification needs", 249),
    "trust-check": ("check a receipt against a trust store", 255),
    "repair": ("run the fix loop on a failing check", 249),
}
EXIT_USAGE = 5


def usage() -> str:
    lines = ["usage: expectrail [--jobs-root DIR] COMMAND ...", "", "commands:"]
    lines += [f"  {name:<12} {text}" for name, text in (
        ("verify", "verify a change and say accept, reject or needs review"),
        ("status", "show a job's status"),
        ("cancel", "cancel a job and stop what it started"),
        ("report", "show a finished job's result and where its evidence is"),
        ("sample", "three real verifications of the bundled game: as it is, broken, repaired"))]
    lines += [f"  {name:<12} not built yet (#{issue}): {text}" for name, (text, issue) in PLANNED.items()]
    lines += ["", "  --version    print the version and where this copy's files are",
              "", "`expectrail COMMAND --help` shows a command's options."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if args else EXIT_USAGE
    if args[0] in ("--version", "-V"):
        kind = "installed package" if resources.INSTALLED else "clone"
        print(f"expectrail {__version__} ({kind}; files at {resources.ROOT})")
        return 0
    # The command is the first word that is not an option (or an option's value): `--jobs-root DIR`
    # may come first, as with the orchestrator's own command line.
    words, skip = [], False
    for word in args:
        if skip:
            skip = False
        elif word in ("--jobs-root", "--lease-seconds"):
            skip = True
        elif not word.startswith("-"):
            words.append(word)
            break
    command = words[0] if words else None
    if command in PLANNED:
        text, issue = PLANNED[command]
        print(f"expectrail: `{command}` is not built yet (#{issue}): it will {text}. Nothing was run.", file=sys.stderr)
        return EXIT_USAGE
    if command not in ORCHESTRATOR:
        shown = f"no command named {command!r}" if command else "no command given"
        print(f"expectrail: {shown}.\n\n{usage()}", file=sys.stderr)
        return EXIT_USAGE
    from expectrail.orchestrator import cli as orchestrator

    return orchestrator.main(args, prog="expectrail")


if __name__ == "__main__":
    sys.exit(main())
