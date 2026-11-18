"""The ``expectrail`` command: one name in front of what is built.

    expectrail verify --head . --game game/platformer --routes 'routes/*.json' --specs specs [--base ../base]
    expectrail status JOB | cancel JOB | report JOB
    expectrail sample              three real verifications of the bundled game: as it is, broken, repaired
    expectrail doctor [--json]     does this machine have what a verification needs?
    expectrail trust-check RECEIPT --trust-store FILE [--repo OWNER/NAME] [--expect-head SHA] ...
    expectrail trust-check RECEIPT --attested-by OWNER/NAME/.github/workflows/FILE.yml --repo OWNER/NAME ...
                                   does this receipt clear this change? (needs the `trust` extra)
    expectrail --version

`verify`, `status`, `cancel`, `report` and `sample` are the orchestrator's own commands
(``expectrail.orchestrator.cli``): the same functions, the same options and the same exit codes as
``python3 -m expectrail.orchestrator``. Nothing is implemented twice here.

`doctor` is ``expectrail.doctor``: it checks the machine, exits 0 or 3, and is not a verdict.

`trust-check` is ``expectrail.receipt``: 0 clearance, 1 no clearance, 5 when nothing could be checked.
It needs ``cryptography`` and ``jsonschema`` (``pip install 'expectrail[trust]'``); a copy without them
says so and checks nothing.

Commands that are planned and not built say so, name the issue, and exit 5 (the command could not
be carried out). They never print a verdict. A command line that cannot be read (a missing or
unknown option) exits 5 too, never 2: 2 is needs-review.
"""
from __future__ import annotations

import sys

from expectrail import __version__, resources

ORCHESTRATOR = ("verify", "status", "cancel", "report", "sample", "ingest")
# name -> (what it will do, the issue that builds it)
PLANNED: dict[str, tuple[str, int]] = {}
# What `trust-check` needs beyond the standard library: the `trust` extra in pyproject.toml.
TRUST_PACKAGES = ("cryptography", "jsonschema")
EXIT_USAGE = 5


def usage() -> str:
    lines = ["usage: expectrail COMMAND [--jobs-root DIR] ...", "", "commands:"]
    lines += [f"  {name:<12} {text}" for name, text in (
        ("verify", "verify a change and say accept, reject or needs review"),
        ("status", "show a job's status"),
        ("cancel", "cancel a job and stop what it started"),
        ("report", "show a finished job's result and where its evidence is"),
        ("sample", "three real verifications of the bundled game: as it is, broken, repaired"),
        ("repair", "propose and verify a fix for a rejected job"),
        ("onboard", "build an offline binding review page from an init draft"),
        ("inspect", "list the player, inputs, cameras and ground in a Godot project; --at-tick N measures them in a replay"),
        ("init", "propose a draft project config and first input route"),
        ("route", "make a first route from a Godot input map and check three identical replays"),
        ("app", "open the local browser app"),
        ("trust-check", "check a receipt against a trust store: clearance or not, and what it establishes"),
        ("doctor", "check that this machine has what a verification needs, and name the fix for what is missing"))]
    lines += [f"  {name:<12} not built yet (#{issue}): {text}" for name, (text, issue) in PLANNED.items()]
    lines += ["", "  --version    print the version and where this copy's files are",
              "", "  --jobs-root DIR  where jobs are kept (default: $EXPECTRAIL_JOBS, else runs/jobs); after the",
              "                   command, or before it for every command but app, doctor and trust-check",
              "", "`expectrail COMMAND --help` shows a command's options."]
    return "\n".join(lines)


# Explicit no-spend profile used by Dockerfile.sample. Ordinary verify and the legacy
# no-vision quickstart retain their existing rules and outcomes.
SAMPLE_RECORDINGS_ENV = 'EXPECTRAIL_VLM_SAMPLE_RECORDINGS'


def _sample_profile():
    import os
    value = os.environ.get(SAMPLE_RECORDINGS_ENV, '0')
    if value not in ('0', '1'):
        raise ValueError(SAMPLE_RECORDINGS_ENV + ' must be 0 or 1')
    return value == '1'


def _sample_observer():
    from pathlib import Path
    from expectrail.recorded import read_recording, RecordedBankObserver
    base = (resources.ROOT / 'sample-vision' if resources.INSTALLED else
            resources.ROOT / 'docs/run-it/vision')
    names = ('clean', 'fall-through-bug', 'fall-through-repair')
    return RecordedBankObserver([read_recording(Path(base) / (name + '.json')) for name in names])


def _recorded_sample(argv):
    """Use the existing sample runner and gate with exact saved vision, never a live client."""
    import argparse
    import json
    from expectrail.orchestrator import cli, engines, sample, store
    p = cli.Parser(prog='expectrail sample')
    p.full_usage = usage()
    p.add_argument('--jobs-root')
    p.add_argument('--lease-seconds', type=float, default=store.DEFAULT_LEASE_SECONDS, help=argparse.SUPPRESS)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--json', action='store_true')
    # Keep global options before or after sample; argparse rejects conflicting repetitions below.
    args = p.parse_args(argv)
    roots = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '--jobs-root']
    roots += [arg.split('=', 1)[1] for arg in argv if arg.startswith('--jobs-root=')]
    from pathlib import Path
    if len({Path(root) for root in roots}) > 1:
        raise cli.UsageError('--jobs-root was given twice with different folders; give it once')
    visual = _sample_observer()
    if not args.json:
        print('Expectrail sample: real Godot replays; exact saved vision answers; no live model fallback.')
        for doc in visual.recordings:
            print('Vision recorded ' + doc['recordedAt'] + ', run ' + doc['run'] + ': ' + doc['sample'])
    results = sample.run(cli._store(args), timeout_seconds=args.timeout,
                         engines={'godot': engines.GodotGate(visual=visual)},
                         on_case=None if args.json else lambda r: print(sample.line(r), flush=True))
    if args.json:
        print(json.dumps(results, indent=2))
    return 0 if all(r['asExpected'] for r in results) else 3


def _sample_doctor(argv):
    """Doctor for the explicit bundled-recordings profile; arbitrary projects stay unchanged."""
    import json
    from pathlib import Path
    from expectrail import doctor
    p = doctor._Parser(prog='expectrail doctor')
    p.add_argument('--json', action='store_true')
    p.add_argument('--isolated', action='store_true')
    p.add_argument('--no-fetch', action='store_true')
    p.add_argument('--project', type=Path)
    args = p.parse_args(argv)
    # A real project, explicit or in the current directory, is never substituted by a sample.
    if args.project is not None or (Path.cwd() / 'project.godot').is_file() or (Path.cwd() / 'expectrail.project.json').is_file():
        return doctor.main(argv)
    found = doctor.checks(isolated=args.isolated, fetch=not args.no_fetch)
    try:
        visual = _sample_observer()
        details = '; '.join(d['sample'] + ': recorded ' + d['recordedAt'] + ', run ' + d['run'] for d in visual.recordings)
        record = doctor.Check('sample-recordings', 'exact saved vision for the bundled sample', 'ok', True,
                              details + '; no live fallback; this does not establish vision for your project', None)
    except (ValueError, OSError) as exc:
        record = doctor.Check('sample-recordings', 'exact saved vision for the bundled sample', 'missing', True,
                              'sample recordings unavailable: ' + str(exc), 'Reinstall the wheel with its original sample recordings.')
    found.append(record)
    for check in found:
        if check.id in ('vision-key', 'vision-cap'):
            check.required = False
            check.found += '; not required for the explicitly selected recorded sample; required for live vision'
    print(json.dumps(doctor.document(found), indent=2) if args.json else doctor.text(found))
    return doctor.EXIT_MISSING if doctor.missing(found) else doctor.EXIT_OK


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
    for at, word in enumerate(args):
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
    if command == "repair":
        from expectrail import repair

        return repair.main(args[:at] + args[at + 1:])
    if command == "onboard" and args[0] == command:
        from expectrail import onboard

        return onboard.main(args[1:])
    if command in ("init", "inspect") and args[0] == command:
        from expectrail import onboarding

        return onboarding.main(command, args[1:])
    if command == "route":
        if args[0] != "route":
            print("expectrail: put route options after `route`. Nothing was run.", file=sys.stderr)
            return EXIT_USAGE
        from expectrail import route

        return route.main(args[1:])
    if command == "app":
        if args[0] != "app":
            print("expectrail: put app options after `app`. Nothing was run.", file=sys.stderr)
            return EXIT_USAGE
        from expectrail import app

        return app.main(args[1:])
    if command == "trust-check":
        if args[0] != "trust-check":
            print("expectrail: `trust-check` takes no option before it. Nothing was checked.", file=sys.stderr)
            return EXIT_USAGE
        try:
            from expectrail import receipt
        except ModuleNotFoundError as exc:
            missing = (exc.name or "").split(".")[0]
            if missing not in TRUST_PACKAGES:
                raise
            print(f"expectrail: `trust-check` needs the `{missing}` package, which this copy does not have. "
                  "Install it with: pip install 'expectrail[trust]' (or, in a clone, pip install "
                  "cryptography jsonschema). Nothing was checked.", file=sys.stderr)
            return EXIT_USAGE
        return receipt.trust_check_main(args[1:])
    if command in ('doctor', 'sample'):
        try:
            enabled = _sample_profile()
            if enabled:
                if command == 'doctor':
                    if args[0] != command:
                        print('expectrail: put doctor options after doctor. Nothing was checked.', file=sys.stderr)
                        return EXIT_USAGE
                    return _sample_doctor(args[1:])
                return _recorded_sample(args[:at] + args[at + 1:])
        except (ValueError, OSError) as exc:
            print('expectrail: ' + str(exc) + '\nNothing was run.', file=sys.stderr)
            return EXIT_USAGE
        except Exception as exc:
            from expectrail import doctor
            from expectrail.orchestrator import cli
            if not isinstance(exc, (doctor._Usage, cli.UsageError)):
                raise
            print('expectrail: ' + str(exc) + '\nNothing was run.', file=sys.stderr)
            return EXIT_USAGE
    if command == "doctor":
        if args[0] != "doctor":
            print("expectrail: `doctor` takes no option before it. Nothing was checked.", file=sys.stderr)
            return EXIT_USAGE
        from expectrail import doctor

        return doctor.main(args[1:])
    if command not in ORCHESTRATOR:
        shown = f"no command named {command!r}" if command else "no command given"
        print(f"expectrail: {shown}. Nothing was run.\n\n{usage()}", file=sys.stderr)
        return EXIT_USAGE
    from expectrail.orchestrator import cli as orchestrator

    return orchestrator.main(args, prog="expectrail", usage=usage())


if __name__ == "__main__":
    sys.exit(main())
