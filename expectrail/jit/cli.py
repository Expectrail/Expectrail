"""Command line for per-change check generation (docs/jit.md).

    python -m expectrail.jit.cli run --report-file report.txt --candidate fix.patch \
        [--base bugs/reported/air-jump.patch] --out runs/jit [--model spark|off] [--budget-usd 2]
    python -m expectrail.jit.cli report runs/jit/jit-run.json
    python -m expectrail.jit.cli gate-summary runs/jit/jit-run.json [--out generated-checks.json]

In CI the model call and the replays are separate steps, so the key and the change's code never meet:

    python -m expectrail.jit.cli propose --report-file r.txt --candidate c.patch --out runs/jit-proposal
    python -m expectrail.jit.cli run --report-file r.txt --candidate c.patch --out runs/jit \
        --proposal runs/jit-proposal/jit-proposal.json [--game path/to/the/reference/game]

Every step of one change takes the same ``--offer`` (expectrail/jit/offer.py): ``baseline``, the default,
is the generator as it was before issue #285's steps 3 and 4; ``signals-reach`` also offers the three
held-back signals and the reach probes; the evidence setting (``offer.EVIDENCE``) also gives the proposer step 5's
evidence, which ``measure`` makes (replays with frames, expectrail/jit/offer.py) and ``propose`` and
``revise`` read with ``--evidence``. A proposal is replayed only under the offer it was made with.
``measure``, ``propose``, ``revise`` and ``run`` also take the pixel setting (``offer.PIXEL``, #286), under which
the proposal carries pixel checks; ``revise`` replaces rejected trace checks only and carries the pixel
checks to the second round as they are.

**The observer for pixel checks** (``run`` under the pixel setting only; ``observer_from``). ``--observer``
names it: ``none`` (the default; every pixel check is then ``not-run``, with the reason) or
``sam-3.1-anchor`` (expectrail/jit/sam_observer.py). SAM is asked one of two ways, and one must be named:

- ``--sam-answers FILE``: SAM's recorded answers (an agents/sam_anchor.py answer file, answered by
  ``RecordedSamClient``, which answers only the exact question SAM was asked). The replay folder's build
  (``pixel-reference``, ``pixel-base``, ``pixel-candidate``) picks the recorded run: the run named
  ``<build>/<replay>`` if the file has one, else the run ``--sam-run BUILD=RUN`` names, else the run named
  as the build. No request is sent.
- ``--sam-live``: a live call (agents.sam_observations.MetaSamClient: the key in MODEL_API_KEY and the cap
  in EXPECTRAIL_SAM_USD_CAP), its images reserved against ``--budget-usd`` first. This spends money;
  nothing runs it unless the flag is given.

``--sam-box`` (``body``, the default: the engine's body box widened by ``--sam-pad`` game px; or ``WxH``
with ``--sam-lift``), ``--sam-every`` (every Nth frame and the last; 10 by default, at most 60) and
``--sam-first`` set how SAM is asked, and must be how a recording was asked: an observer that asks
otherwise than the recording stops at the first replay, and one that plans other frames than the
recording was asked about (another ``--sam-every`` or ``--sam-first``) is refused before it asks.

**Pixel checks across three jobs** (expectrail/jit/pixel_jobs.py), so SAM's key never meets the change's
code: ``run --observer sam-3.1-anchor --pixel-capture DIR`` replays and keeps the frames and asks nothing;
``pixel-ask --replays DIR --out answers.json --budget-usd X`` (``--sam-live``, or ``--sam-answers`` to
rehearse) asks SAM about them and runs no game; ``run --observer sam-3.1-anchor --sam-answers answers.json
--pixel-replays DIR`` judges the captured frames from those answers. ``--pixel-replays`` never takes
``--sam-live``. ``pixel-ask`` exits 0 once it has written the answer file (a stop is in its ``stopped``)
and 1 when it asked nothing. ``pixel-budget --record jit-run.json --budget-usd X`` prints what the asking
job may spend: the cap less the capture record's spend (expectrail/jit/pixel_jobs.py, ``budget_left``).

**The template sensor** (#262, expectrail/jit/template_observer.py): ``run --observer visual-sensor
--sensor-bank BANK`` judges pixel checks with no model and no request, over a template bank frozen
beforehand from a clean replay (agents/template_observations.py). It plans its frames as SAM does
(``--sam-every``, ``--sam-first``) and takes none of SAM's other arguments. It runs in the job that replays
the change, since it holds no key.

**The observer a proposal is for.** A run is judged by one observer, so ``propose`` and ``revise`` take
``--observer`` too (``sam-3.1-anchor``, the default, or ``visual-sensor``; the pixel setting only): the
proposer is offered pixel checks for that observer only, and the proposal records it. ``run --proposal``
replays a proposal only for the observer ``run`` is given and refuses one made for another; ``--observer
none`` judges no pixel checks, so it reads a proposal made for any observer (its pixel checks are
``not-run``), as jit.yml's first replay does.

``--withhold-candidate`` on ``propose``, ``revise`` and ``run`` gives the model no byte of the candidate
patch (issue #285, step 6): the checks then come from the report and the bug build alone, and a fix
cannot shape the checks that judge it. Every step of one change takes it or none does; a proposal made
one way is refused by a run made the other.

``run`` always exits 0 once it has written a record: a run that generated nothing is a result, and
nothing here accepts or rejects a change. Bad arguments exit 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.offer import ALL as ALL_OFFERS, DEFAULT as DEFAULT_OFFER, PIXEL, REPLAYABLE, REVISABLE
from expectrail.jit.offer import library as offered_library
from expectrail.jit.offer import attach_evidence, make_evidence, shows_evidence
from expectrail.jit.run import DEFAULT_BUDGET_USD, RECORD_NAME, from_base_alone, gate_summary, generate

PROFILE = Path(__file__).resolve().parents[2] / "discovery" / "platformer.profile.json"


def render(doc: dict) -> str:
    """The run as Markdown, for the job summary and the record folder."""
    lines = [f"# Generated checks: {doc['runId']}", "",
             "Report-only. A generated check never accepts or rejects a change (docs/jit.md).", ""]
    if doc["status"] != "complete":
        lines += [f"**No generated checks.** {doc['reason']}", ""]
    c = doc["counts"]
    lines += [f"- Proposed: {c['proposed']}, valid: {c['valid']}, catches: {c['strong']} strong, {c['weak']} weak",
              f"- Near-miss variants: {len(doc['variants'])}",
              f"- Spend: ${doc['spend']['usd']:.4f} of ${doc['spend']['capUsd']:.2f} "
              f"({doc['spend']['replays']} replays, {doc['spend']['promptTokens']} prompt and "
              f"{doc['spend']['completionTokens']} completion tokens; prices {doc['spend']['prices']['source']})"]
    base = from_base_alone(doc)
    if base["candidate"] == "withheld":
        lines.append(f"- The model was not shown the candidate (issue #285, step 6). Checks that pass on the clean game "
                     f"and fail on the bug build: {len(base['reproducing'])}, all derived from the report and the "
                     f"bug build alone")
    else:
        lines.append(f"- The model was shown the candidate. Checks that pass on the clean game and fail on the bug "
                     f"build: {len(base['reproducing'])}; none of them is derived without the candidate")
    if "pixelChecks" in doc:
        rows = doc["pixelChecks"]
        lines.append(f"- Pixel checks (#286): {len(rows)} proposed, {len(base.get('pixelReproducing', []))} pass on the clean "
                     f"game and fail on the bug build, "
                     f"{sum(1 for r in rows if r['outcome'] == 'catch')} fail on the candidate")
    lines.append("")
    if doc.get("pixelChecks"):
        lines += ["| Pixel check | Observer | Clean | Bug | Candidate | Result | Why |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in doc["pixelChecks"]:
            lines.append(f"| `{r['check']['id']}` | {r['check']['observer']} | {', '.join(r['clean']) or 'not run'} | "
                         f"{', '.join(r['bug']) or 'not run'} | {', '.join(r['candidate']) or 'not run'} | "
                         f"{r['status']}, {r['outcome']} | {(r['reason'] or '').replace('|', '/')} |")
        lines.append("")
    if doc["catches"]:
        lines += ["| Check | Strength | Says | Candidate | Base | Variants killed |", "| --- | --- | --- | --- | --- | --- |"]
        for k in doc["catches"]:
            lines.append(f"| `{k['specId']}` | {k['strength']} | {k['statement']} | {', '.join(k['candidate'])} | "
                         f"{', '.join(k['base']) if k['base'] is not None else 'not run'} | {len(k['killed'])} |")
        lines.append("")
    if doc["validity"]:
        lines += ["| Check | Valid | Reference | Outcome | Why not valid |", "| --- | --- | --- | --- | --- |"]
        for v in doc["validity"]:
            lines.append(f"| `{v['specId']}` | {'yes' if v['valid'] else 'no'} | {', '.join(v['reference']) or 'not run'} | "
                         f"{v['outcome']} | {'; '.join(v['reasons'])} |")
        lines.append("")
    return "\n".join(lines)


def diff_games(base: Path, head: Path) -> str:
    """A unified diff (``-p1`` paths relative to the game) from one game folder to another: text files
    only, in sorted order, so two jobs that diff the same two commits write the same bytes. Engine
    caches (``.godot``) are left out; a binary file that changed is named in a comment line."""
    import difflib

    import os

    def files(root: Path, linked: dict[str, str]) -> dict[str, Path]:
        # A symlink is never followed: a pull request's game is untrusted, and a link to, say,
        # /proc/self/environ would put whatever the reading process holds into the patch, which goes
        # to the model and into an artifact. A link (or anything under a linked folder) is named, not read.
        found: dict[str, Path] = {}
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if ".godot" in rel.parts:
                continue
            if any((root.joinpath(*rel.parts[:k])).is_symlink() for k in range(1, len(rel.parts) + 1)):
                linked[rel.as_posix()] = os.readlink(p) if p.is_symlink() else "(under a linked folder)"
                continue
            if p.is_file():
                found[rel.as_posix()] = p
        return found

    links_a: dict[str, str] = {}
    links_b: dict[str, str] = {}
    a, b = files(base, links_a), files(head, links_b)
    # Only links that were added, removed or pointed elsewhere are named; an unchanged link is no change.
    out: list[str] = [f"# symbolic link, not read: {rel}\n" for rel in sorted(set(links_a) | set(links_b))
                      if links_a.get(rel) != links_b.get(rel)]
    for rel in sorted(set(a) | set(b)):
        old = a[rel].read_bytes() if rel in a else b""
        new = b[rel].read_bytes() if rel in b else b""
        if old == new:
            continue
        try:
            old_t, new_t = old.decode("utf-8"), new.decode("utf-8")
        except UnicodeDecodeError:
            out.append(f"# binary file changed, not in this patch: {rel}\n")
            continue
        out += difflib.unified_diff(old_t.splitlines(keepends=True), new_t.splitlines(keepends=True),
                                    fromfile=f"a/{rel}" if rel in a else "/dev/null",
                                    tofile=f"b/{rel}" if rel in b else "/dev/null")
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n\\ No newline at end of file\n"
    return "".join(out)


def attach_measurements(probes: list[dict], path: Path | None, base: list[Path]) -> list[str]:
    """Put each probe's measurements on it for the prompt. Returns diagnostics: empty when they were
    attached; otherwise why not, and the proposal goes ahead without them (it is never refused)."""
    if path is None:
        return ["measurements: none given"]
    from expectrail.jit.measure import MeasurementsUnusable, load

    try:
        table = load(path, probe_ids={p["id"] for p in probes}, base_patches=base)
    except (MeasurementsUnusable, OSError) as exc:
        return [f"measurements: not used: {exc}"[:200]]
    for p in probes:
        if p["id"] in table:
            p["measured"] = table[p["id"]]
    return []


def _candidate(args) -> str:
    return "withheld" if getattr(args, "withhold_candidate", False) else "shown"


def _judged_by(args) -> str | None:
    """The observer that judges the pixel checks: ``propose`` and ``revise``'s ``--observer``, or ``run``'s
    (None for ``--observer none``: that run judges no pixel checks)."""
    name = getattr(args, "observer", SAM)
    return None if name == "none" else name


def _intent_settings(args) -> dict:
    # ``candidate`` only when it is withheld and ``observer`` only when it is not SAM, so the default call is
    # the one it always was. A model asked by a run that judges no pixel checks is offered SAM's, as before.
    observer = _judged_by(args) or SAM
    return {"offer": args.offer, **({"candidate": "withheld"} if _candidate(args) == "withheld" else {}),
            **({"observer": observer} if observer != SAM else {})}


SAM = "sam-3.1-anchor"
SENSOR = "visual-sensor"
OBSERVERS = ("none", SAM, SENSOR)
PROPOSAL_OBSERVERS = (SAM, SENSOR)   # expectrail/jit/pixel.py, PROPOSABLE
BUILDS = ("pixel-reference", "pixel-base", "pixel-candidate")   # the replay folders of expectrail/jit/run.py


class ObserverArgs(ValueError):
    """The observer arguments do not name one observer that can be built."""


def _box(text: str):
    if text == "body":
        return "body"
    try:
        w, h = (float(v) for v in text.lower().split("x"))
    except ValueError:
        raise ObserverArgs("--sam-box is 'body' or WIDTHxHEIGHT in game pixels") from None
    return (w, h)


def _sam_runs(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        build, sep, run = pair.partition("=")
        if not sep or build not in BUILDS or not run:
            raise ObserverArgs(f"--sam-run is BUILD=RUN with BUILD one of {', '.join(BUILDS)}: {pair[:60]!r}")
        if build in out:
            raise ObserverArgs(f"--sam-run names {build} twice")
        out[build] = run
    return out


def recorded_pick(runs: dict, names: dict[str, str]):
    """For a frame's path, the recorded run to answer from: ``<build>/<replay>`` if the recording has it,
    else the run ``names`` gives the build, else the build's own name (see the module docstring)."""
    def pick(png) -> str:
        run_dir = Path(png).parent.parent
        build = run_dir.parent.name
        exact = f"{build}/{run_dir.name}"
        return exact if exact in runs else names.get(build, build)
    return pick


def observer_from(args):
    """The observer ``run`` hands ``generate``: None, or a SamAnchorObserver over recorded or live answers.

    Fails closed: an observer named without the pixel setting, SAM named without saying how it is asked
    (or both ways), or a setting it cannot take, is refused with ObserverArgs and nothing runs."""
    name = getattr(args, "observer", "none")
    sam_args = [a for a in ("sam_answers", "sam_live", "sam_run") if getattr(args, a, None)]
    capture, stored = getattr(args, "pixel_capture", None), getattr(args, "pixel_replays", None)
    bank = getattr(args, "sensor_bank", None)
    if bank and name != SENSOR:
        raise ObserverArgs(f"--sensor-bank is the template bank of --observer {SENSOR}")
    if name == SENSOR:
        return _sensor_observer(args, sam_args, capture or stored)
    if name == "none":
        if sam_args:
            raise ObserverArgs("--sam-answers, --sam-live and --sam-run need --observer sam-3.1-anchor")
        if capture or stored:
            raise ObserverArgs("--pixel-capture and --pixel-replays need --observer sam-3.1-anchor")
        return None
    if args.offer != PIXEL:
        raise ObserverArgs(f"--observer is for pixel checks, which only the {PIXEL} setting offers")
    if capture and stored:
        raise ObserverArgs("--pixel-capture and --pixel-replays are different jobs: give one")
    if capture:
        # The capture job runs the change's code: it asks nobody, so it is given no way to ask.
        if sam_args:
            raise ObserverArgs("--pixel-capture asks nothing: it takes no --sam-answers, --sam-live or --sam-run")
        return _sam_observer(args, None)
    if stored and not args.sam_answers:
        raise ObserverArgs("--pixel-replays judges captured frames from the answers pixel-ask wrote: it needs "
                           "--sam-answers, never --sam-live (the key would meet the change's code)")
    return _sam_observer(args, *_sam_client(args))


def _sensor_observer(args, sam_args, jobs):
    """The template sensor (#262) over ``--sensor-bank``: it asks no one, so it takes nothing of SAM's but the
    frame plan, and runs in the job that replays the change (no capture or asking job)."""
    if args.offer != PIXEL:
        raise ObserverArgs(f"--observer is for pixel checks, which only the {PIXEL} setting offers")
    if not args.sensor_bank:
        raise ObserverArgs(f"--observer {SENSOR} needs --sensor-bank FILE (a template bank frozen from a clean replay)")
    if sam_args:
        raise ObserverArgs(f"--observer {SENSOR} asks no one: it takes no --sam-answers, --sam-live or --sam-run")
    if jobs:
        raise ObserverArgs(f"--observer {SENSOR} holds no key, so it judges in the job that replays: it takes no "
                           "--pixel-capture or --pixel-replays")
    if (args.sam_box, args.sam_pad, args.sam_lift) != ("body", 4.0, 0.0):
        raise ObserverArgs(f"--observer {SENSOR} searches near the engine's body box: it takes no --sam-box, "
                           "--sam-pad or --sam-lift")
    from expectrail.jit.template_observer import TemplateSensorObserver

    try:
        return TemplateSensorObserver(args.sensor_bank, every=args.sam_every, first=args.sam_first)
    except ValueError as exc:
        raise ObserverArgs(str(exc)) from exc


def _sam_client(args) -> tuple:
    """(client,) from exactly one of ``--sam-answers`` (recorded) and ``--sam-live`` (None: built on first use)."""
    if bool(args.sam_answers) == bool(args.sam_live):
        raise ObserverArgs("--observer sam-3.1-anchor needs exactly one of --sam-answers FILE (recorded answers) "
                           "or --sam-live (a live call that spends money)")
    if args.sam_run and not args.sam_answers:
        raise ObserverArgs("--sam-run picks runs of recorded answers: it needs --sam-answers")
    from expectrail.jit.sam_observer import RecordedSamClient

    client = None
    if args.sam_answers:
        try:
            client = RecordedSamClient(args.sam_answers, "")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ObserverArgs(f"--sam-answers cannot be read as an answer file ({type(exc).__name__})") from exc
        client.pick = recorded_pick(client.runs, _sam_runs(args.sam_run))
    return (client,)


def _sam_observer(args, client):
    from expectrail.jit.sam_observer import SamAnchorObserver

    try:
        return SamAnchorObserver(client, box=_box(args.sam_box), pad=args.sam_pad, lift=args.sam_lift,
                                 every=args.sam_every, first=args.sam_first)
    except ValueError as exc:
        raise ObserverArgs(str(exc)) from exc


def _add_sam_setting(parser) -> None:
    parser.add_argument("--sam-box", default="body", help="body (the engine's body box), or WIDTHxHEIGHT in game px")
    parser.add_argument("--sam-pad", type=float, default=4.0, help="game px the body box is widened by")
    parser.add_argument("--sam-lift", type=float, default=0.0, help="with a sized box: game px above the origin")
    parser.add_argument("--sam-first", type=int, help="ask about the first N frames only")
    parser.add_argument("--sam-every", type=int, default=10,
                        help="ask about every Nth frame and the last (default 10, at most 60); the same in every job")


def _pixel_jobs_kwargs(args) -> dict:
    """What ``run`` hands ``generate`` for the capture or the judging job (expectrail/jit/pixel_jobs.py)."""
    if getattr(args, "pixel_capture", None):
        return {"pixel_capture": args.pixel_capture}
    if getattr(args, "pixel_replays", None):
        from expectrail.jit.pixel_jobs import StoredReplays

        return {"frame_runner": StoredReplays(args.pixel_replays)}
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="expectrail.jit.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--profile", type=Path, default=PROFILE)
    r.add_argument("--report-file", type=Path, required=True)
    r.add_argument("--candidate", type=Path, required=True)
    r.add_argument("--base", type=Path, action="append", default=[])
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--model", choices=("spark", "off"), default="spark")
    r.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--variant-limit", type=int, default=8)
    r.add_argument("--spark-usd-per-mtok-in", type=float)
    r.add_argument("--spark-usd-per-mtok-out", type=float)
    r.add_argument("--run-id")
    r.add_argument("--proposal", type=Path, help="replay a saved proposal instead of calling the model")
    r.add_argument("--game", type=Path, help="the reference game (default: game/platformer in this checkout)")
    r.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    r.add_argument("--offer", choices=REPLAYABLE, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    r.add_argument("--observer", choices=OBSERVERS, default="none",
                   help="who judges pixel checks (the pixel setting only); none leaves them not run")
    r.add_argument("--sam-answers", type=Path, help="SAM's recorded answers (agents/sam_anchor.py answer file)")
    r.add_argument("--sam-run", action="append", default=[], metavar="BUILD=RUN",
                   help="the recorded run that answers for a build's replays")
    r.add_argument("--sam-live", action="store_true", help="ask SAM live: spends money (key and cap from the environment)")
    r.add_argument("--sensor-bank", type=Path, help=f"the template bank of --observer {SENSOR} (frozen from a clean replay)")
    _add_sam_setting(r)
    r.add_argument("--pixel-capture", type=Path, metavar="DIR",
                   help="replay the pixel checks' probes with frames and keep them in DIR for pixel-ask; ask nothing")
    r.add_argument("--pixel-replays", type=Path, metavar="DIR",
                   help="judge pixel checks on the frames captured in DIR (with --sam-answers from pixel-ask)")
    pa = sub.add_parser("pixel-ask", help="ask SAM about the frames a --pixel-capture run kept (no game is run)")
    pa.add_argument("--replays", type=Path, required=True, help="the --pixel-capture folder")
    pa.add_argument("--out", type=Path, required=True, help="the answer file to write")
    pa.add_argument("--budget-usd", type=float, required=True, help="the most the images may cost; checked first")
    pa.add_argument("--sam-answers", type=Path, help="answer from a recorded answer file instead (sends nothing)")
    pa.add_argument("--sam-run", action="append", default=[], metavar="BUILD=RUN",
                    help="the recorded run that answers for a build's replays")
    pa.add_argument("--sam-live", action="store_true", help="ask SAM live: spends money (key and cap from the environment)")
    _add_sam_setting(pa)
    pb = sub.add_parser("pixel-budget", help="print what pixel-ask may spend: the cap less the capture record's spend")
    pb.add_argument("--record", type=Path, required=True, help="the capture run's jit-run.json")
    pb.add_argument("--budget-usd", type=float, required=True, help="the change's cap")
    pp = sub.add_parser("propose")
    pp.add_argument("--profile", type=Path, default=PROFILE)
    pp.add_argument("--report-file", type=Path, required=True)
    pp.add_argument("--candidate", type=Path, required=True)
    pp.add_argument("--out", type=Path, required=True)
    pp.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    pp.add_argument("--spark-usd-per-mtok-in", type=float)
    pp.add_argument("--spark-usd-per-mtok-out", type=float)
    pp.add_argument("--base", type=Path, action="append", default=[],
                    help="the bug's patches, read only to check the measurements were taken against them")
    pp.add_argument("--measurements", type=Path, help="jit-measurements.json from the measure command")
    pp.add_argument("--evidence", type=Path,
                    help="the evidence file the measure command wrote; read only under the evidence setting")
    pp.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    pp.add_argument("--observer", choices=PROPOSAL_OBSERVERS, default=SAM,
                    help="the observer that will judge the pixel checks (the pixel setting only); the same as run's")
    pp.add_argument("--offer", choices=ALL_OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    rv = sub.add_parser("revise")
    rv.add_argument("--profile", type=Path, default=PROFILE)
    rv.add_argument("--report-file", type=Path, required=True)
    rv.add_argument("--candidate", type=Path, required=True)
    rv.add_argument("--proposal", type=Path, required=True, help="the first proposal")
    rv.add_argument("--record", type=Path, required=True, help="the first replay's jit-run.json")
    rv.add_argument("--out", type=Path, required=True)
    rv.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    rv.add_argument("--spark-usd-per-mtok-in", type=float)
    rv.add_argument("--spark-usd-per-mtok-out", type=float)
    rv.add_argument("--base", type=Path, action="append", default=[])
    rv.add_argument("--measurements", type=Path)
    rv.add_argument("--evidence", type=Path,
                    help="the evidence file the measure command wrote; read only under the evidence setting")
    rv.add_argument("--github-output", type=Path, help="append revised=true|false here (a workflow's GITHUB_OUTPUT)")
    rv.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    rv.add_argument("--observer", choices=PROPOSAL_OBSERVERS, default=SAM,
                    help="the observer that will judge the pixel checks (the pixel setting only); the same as run's")
    rv.add_argument("--offer", choices=REVISABLE, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    ms = sub.add_parser("measure")
    ms.add_argument("--profile", type=Path, default=PROFILE)
    ms.add_argument("--base", type=Path, action="append", default=[])
    ms.add_argument("--out", type=Path, required=True)
    ms.add_argument("--game", type=Path, help="the reference game (default: game/platformer in this checkout)")
    ms.add_argument("--offer", choices=ALL_OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    ms.add_argument("--report-file", type=Path,
                    help="the bug report; with --offer signals-reach it only orders the reach probes")
    ms.add_argument("--evidence-jobs", type=int, default=1,
                    help="replays at once for the evidence (the evidence setting only)")
    bp = sub.add_parser("bench-pins", help="print the pins a bench registration records")
    bc = sub.add_parser("bench-check", help="exit 1 unless the bench registration is signed and its pins hold")
    bc.add_argument("--prereg", type=Path)
    bs = sub.add_parser("bench-score")
    bs.add_argument("--records", type=Path, required=True, help="a folder with <case>/jit-run.json per case")
    bs.add_argument("--prereg", type=Path)
    bs.add_argument("--cases", type=Path)
    bs.add_argument("--out", type=Path, required=True)
    del bp
    dg = sub.add_parser("diff-games")
    dg.add_argument("base", type=Path)
    dg.add_argument("head", type=Path)
    dg.add_argument("--out", type=Path, required=True)
    for name in ("report", "gate-summary"):
        s = sub.add_parser(name)
        s.add_argument("record", type=Path)
        if name == "gate-summary":
            s.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "diff-games":
        text = diff_games(args.base, args.head)
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps({"bytes": len(text.encode("utf-8")), "empty": not text.strip()}))
        return 0
    if args.cmd == "measure":
        from expectrail.jit.measure import measure

        profile = load_strict(args.profile, "mechanics-profile")
        report = args.report_file.read_text(encoding="utf-8", errors="replace") if args.report_file else ""
        if not 1 <= args.evidence_jobs <= 8:
            ap.error("--evidence-jobs is between 1 and 8")
        probes = offered_library(profile["actions"], args.offer, report)
        doc = measure(profile, args.base, args.out, probes=probes, game=args.game)
        made = None
        if shows_evidence(args.offer) and args.base:
            # Under this setting the evidence is part of what is offered: a run that cannot make it
            # stops here instead of proposing as if it had been offered.
            made = make_evidence(profile, probes, args.base, args.out, game=args.game,
                                 jobs=args.evidence_jobs)["totals"]
        print(json.dumps({"probes": len(doc["probes"]), "bugBuild": bool(args.base), "evidence": made}))
        return 0
    if args.cmd in ("bench-pins", "bench-check", "bench-score"):
        from expectrail.jit import bench

        if args.cmd == "bench-pins":
            print(json.dumps(bench.pins(), indent=1, sort_keys=True))
            return 0
        prereg = json.loads((args.prereg or bench.PREREG).read_text(encoding="utf-8"))
        if args.cmd == "bench-check":
            problems = bench.check_registration(prereg)
            for p in problems:
                print(f"::error::{p}")
            print(json.dumps({"ok": not problems, "problems": len(problems)}))
            return 1 if problems else 0
        doc = bench.score(bench.load_cases(args.cases or bench.CASES), args.records, prereg["bar"])
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "jit-bench.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        (args.out / "jit-bench.md").write_text(bench.render(doc), encoding="utf-8")
        print(json.dumps({"verdict": doc["verdict"], **doc["totals"]}))
        return 0
    if args.cmd == "revise":
        from expectrail.jit.intent import IntentUnavailable, revise_to_file, spark_intent

        profile = load_strict(args.profile, "mechanics-profile")
        if args.budget_usd < 0:
            ap.error("budget must not be negative")
        if args.observer != SAM and args.offer != PIXEL:
            ap.error(f"--observer is for pixel checks, which only the {PIXEL} setting offers")
        prices = {k: v for k, v in (("sparkUsdPerMTokIn", args.spark_usd_per_mtok_in),
                                    ("sparkUsdPerMTokOut", args.spark_usd_per_mtok_out)) if v is not None}
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        probes = offered_library(profile["actions"], args.offer, report)
        notes = attach_measurements(probes, args.measurements, args.base)
        notes += attach_evidence(probes, args.evidence, args.base, args.offer)
        try:
            doc = revise_to_file(spark_intent(**_intent_settings(args)), report,
                                 args.candidate.read_bytes().decode("utf-8", errors="replace"), profile, probes,
                                 args.proposal, args.record, args.out, budget_usd=args.budget_usd, prices=prices,
                                 notes=notes)
            revised, skipped = doc["revision"]["revised"], doc["revision"]["skipped"]
        except (IntentUnavailable, ValueError, KeyError, OSError) as exc:
            # The first round's record stands; nothing here can turn into a pass or a catch.
            revised, skipped = False, " ".join(str(exc).split())[:200]
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as fh:
                fh.write(f"revised={'true' if revised else 'false'}\n")
        print(json.dumps({"revised": revised, "skipped": skipped}))
        return 0
    if args.cmd == "propose":
        from expectrail.jit.intent import propose_to_file, spark_intent

        profile = load_strict(args.profile, "mechanics-profile")
        if args.budget_usd < 0:
            ap.error("budget must not be negative")
        if args.observer != SAM and args.offer != PIXEL:
            ap.error(f"--observer is for pixel checks, which only the {PIXEL} setting offers")
        prices = {k: v for k, v in (("sparkUsdPerMTokIn", args.spark_usd_per_mtok_in),
                                    ("sparkUsdPerMTokOut", args.spark_usd_per_mtok_out)) if v is not None}
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        probes = offered_library(profile["actions"], args.offer, report)
        notes = attach_measurements(probes, args.measurements, args.base)
        measured = not notes
        notes += attach_evidence(probes, args.evidence, args.base, args.offer)
        doc = propose_to_file(spark_intent(**_intent_settings(args)), report,
                              args.candidate.read_bytes().decode("utf-8", errors="replace"), profile,
                              probes, args.out, budget_usd=args.budget_usd, prices=prices, notes=notes)
        print(json.dumps({"error": doc["error"], "candidates": len(doc["candidates"]), "probes": len(doc["probes"]),
                          "measured": measured,
                          "evidence": any("differs" in p for p in probes)}))
        return 0

    if args.cmd == "pixel-budget":
        from expectrail.jit.pixel_jobs import budget_left

        left, why = budget_left(args.record, args.budget_usd)
        if why:
            print(f"pixel-budget: {why}", file=sys.stderr)
        print(f"{left:.4f}")
        return 0

    if args.cmd == "pixel-ask":
        from expectrail.jit import pixel_jobs
        from expectrail.jit.run import DEFAULT_PRICES

        try:
            observer = _sam_observer(args, *_sam_client(args))
        except ObserverArgs as exc:
            ap.error(str(exc))
        try:
            doc = pixel_jobs.ask(args.replays, observer, args.budget_usd, DEFAULT_PRICES["samUsdPerImage"])
        except pixel_jobs.pixel.PixelError as exc:
            print(json.dumps({"asked": False, "reason": " ".join(str(exc).split())[:300]}))
            return 1
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"asked": True, "runs": len(doc["runs"]), **doc["stats"], "stopped": doc["stopped"]}))
        if doc["stopped"]:
            print(f"pixel-ask stopped: {doc['stopped']}", file=sys.stderr)
        return 0

    if args.cmd == "run":
        if args.budget_usd < 0 or args.reps < 1 or args.variant_limit < 0:
            ap.error("budget, reps and variant limit must not be negative (reps at least 1)")
        try:
            observer = observer_from(args)
        except ObserverArgs as exc:
            ap.error(str(exc))
        intent = None
        if args.proposal is not None:
            from expectrail.jit.intent import IntentUnavailable, from_proposal

            try:
                intent = from_proposal(args.proposal, offer=args.offer, candidate=_candidate(args),
                                       observer=_judged_by(args))
            except IntentUnavailable as exc:
                reason = str(exc)

                def intent(*_a, _reason=reason):
                    raise IntentUnavailable(_reason)
                intent.model, intent.system, intent.offer = None, "", args.offer
                intent.candidate, intent.observer = _candidate(args), _judged_by(args) or SAM
        elif args.model == "spark":
            from expectrail.jit.intent import spark_intent

            intent = spark_intent(**_intent_settings(args))
        prices = {}
        if args.spark_usd_per_mtok_in is not None:
            prices["sparkUsdPerMTokIn"] = args.spark_usd_per_mtok_in
        if args.spark_usd_per_mtok_out is not None:
            prices["sparkUsdPerMTokOut"] = args.spark_usd_per_mtok_out
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        doc = generate(args.profile, report, args.candidate, args.base, args.out, intent=intent,
                       budget_usd=args.budget_usd, prices=prices, reps=args.reps, variant_limit=args.variant_limit,
                       run_id=args.run_id, game=args.game, offer=args.offer,
                       candidate_to_model=_candidate(args), observer=observer,
                       **_pixel_jobs_kwargs(args))
        (args.out / "jit-report.md").write_text(render(doc) + "\n", encoding="utf-8")
        print(json.dumps({"status": doc["status"], "reason": doc["reason"], "counts": doc["counts"],
                          "spendUsd": doc["spend"]["usd"], "record": str(args.out / RECORD_NAME)}))
        return 0
    doc = load_strict(args.record, "jit-run")
    if args.cmd == "report":
        print(render(doc))
    else:
        text = json.dumps(gate_summary(doc), indent=1)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
