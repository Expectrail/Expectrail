"""``expectrail doctor``: does this machine have what a verification needs?

    expectrail doctor [--json] [--isolated] [--no-fetch]

One list (``checks``) of what a run needs, each piece checked the way a run uses it:

    python    Python 3.12 or later
    godot     the engine, found as a replay finds it (fetched on first use), at the pinned version
    display   a virtual display for the engine to draw on (xvfb-run, on Linux)
    opengl    the engine draws one frame of an empty project and names the device it drew with
    disk      free space where the engine and a run's frames are written
    sandbox   bubblewrap, by the probe a replay uses (needed only for the isolated class)
    patch     for `expectrail sample` and seeded bugs
    curl, unzip   to fetch the engine, when it is not here yet
    vision-key    required MODEL_API_KEY, presence only; its value is never returned
    vision-cap    required EXPECTRAIL_SAM_USD_CAP, a finite nonnegative USD amount

The engine's preflight (``expectrail.orchestrator.engines.GodotGate._tools``) asks this module for the
pieces every run needs (``for_run``), by the same functions, so `doctor` and a real run cannot
disagree about them: when `doctor` passes, the preflight's tool check passes.

Exit code: 0 when nothing required is missing; 3 when something is (as `sample`: it checks the
install, it is not a verdict on a change); 5 for a usage error. `doctor` never prints a verdict.

``--json`` prints one ``expectrail.doctor/v1`` document (contracts/doctor.v1.schema.json).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from expectrail import __version__, resources

FORMAT = "expectrail.doctor/v1"
SCHEMA = resources.ROOT / "contracts" / "doctor.v1.schema.json"
MIN_PYTHON = (3, 12)
# The engine is 140 MB unpacked, and one replay's 120 frames were 24 MB on the bundled game (measured
# on one machine, November 12, 2026). A verification replays each route on the head and the base
# and keeps the frames. This is room for a few routes, not a measured need.
MIN_FREE_BYTES = 1024 ** 3
EXIT_OK, EXIT_MISSING, EXIT_USAGE = 0, 3, 5
VISION_KEYS = ("MODEL_API_KEY",)
NO_KEY = "Without MODEL_API_KEY or EXPECTRAIL_SAM_USD_CAP, verification sends nothing and ends needs-review."
APT = "sudo apt-get install"


@dataclass
class Check:
    id: str
    what: str          # what is needed, in a few words
    status: str        # ok, missing; for the vision key: present, absent; skipped when it could not be tried
    required: bool     # missing and required: `doctor` exits non-zero
    found: str         # what was found, or what is wrong
    fix: str | None    # what to do about it; None when nothing is wrong
    run: bool = False  # every run needs it: the engine's preflight asks for these


def _ok(id: str, what: str, found: str, *, required: bool = True, run: bool = False) -> Check:
    return Check(id, what, "ok", required, found, None, run)


def _missing(id: str, what: str, found: str, fix: str, *, required: bool = True, run: bool = False) -> Check:
    return Check(id, what, "missing", required, found, fix, run)


def _clip(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def python() -> Check:
    have = ".".join(map(str, sys.version_info[:3]))
    want = ".".join(map(str, MIN_PYTHON))
    if sys.version_info[:2] >= MIN_PYTHON:
        return _ok("python", f"Python {want} or later", f"Python {have}")
    return _missing("python", f"Python {want} or later", f"Python {have}",
                    f"run Expectrail with Python {want} or later (no recorded run is below it)")


def pinned() -> str:
    from harness.run import GODOT_VERSION

    return GODOT_VERSION


def _where_godot_would_be() -> Path | None:
    """Where the engine is when it is already here, without fetching it (harness.run.find_godot and
    harness/get_godot.sh name the same places)."""
    from harness.run import REPO, tools_dir

    named = os.environ.get("EXPECTRAIL_GODOT")
    if named:
        return Path(named)
    if sys.platform == "darwin":
        return REPO / "tools" / "godot_mac" / "Godot.app" / "Contents" / "MacOS" / "Godot"
    return tools_dir() / "godot" / f"Godot_v{pinned()}_linux.x86_64"


def godot(fetch: bool = True) -> tuple[Check, Path | None]:
    """The engine as a replay finds it, and that it is the pinned version. ``fetch=False`` only
    looks: an engine that is not here yet is then missing."""
    what = f"Godot {pinned()}"
    lacking = [name for name in ("curl", "unzip") if shutil.which(name) is None]
    refetch = ((f"{APT} {' '.join(lacking)}, then" if lacking else
                "allow a download from github.com (a proxy or a firewall may be stopping it), then")
               + " run `expectrail doctor` again; or set EXPECTRAIL_GODOT to a Godot " + pinned() + " binary")
    try:
        if fetch:
            from harness.run import find_godot

            path = Path(find_godot())
        else:
            path = _where_godot_would_be()
        if path is None or not path.is_file():
            raise FileNotFoundError(str(path))
    except Exception as exc:  # noqa: BLE001 - whatever stops Godot being found is the same finding
        if not fetch:
            return _missing("godot", what, "Godot is not here yet (it is fetched on first use, and --no-fetch was given)",
                            "run `expectrail doctor` without --no-fetch, or set EXPECTRAIL_GODOT to a Godot "
                            + pinned() + " binary", run=True), None
        # The fetch script's own last line says which step failed. Only its own words are shown.
        said = [line for line in str(getattr(exc, "stderr", "") or "").splitlines() if line.startswith("get_godot: ")]
        return _missing("godot", what, f"Godot could not be found or downloaded ({type(exc).__name__})"
                        + (f": {_clip(said[-1][len('get_godot: '):], 240)}" if said else ""), refetch, run=True), None
    try:
        said = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _missing("godot", what, f"the Godot binary at {path} could not be run ({type(exc).__name__})",
                        "unset EXPECTRAIL_GODOT so the pinned engine is fetched, or point it at a Godot "
                        + pinned() + " binary this machine can run", run=True), None
    want = pinned().replace("-", ".")
    version = said.splitlines()[-1] if said else ""
    if not (version == want or version.startswith(want + ".")):
        return _missing("godot", what, f"the Godot at {path} says it is {_clip(version, 60) or 'nothing'}, not {pinned()}",
                        "unset EXPECTRAIL_GODOT so the pinned engine is fetched, or point it at Godot " + pinned()
                        + ": recorded results are for that version", run=True), None
    return _ok("godot", what, f"Godot {version} at {path}", run=True), path


def display() -> Check:
    what = "a virtual display (xvfb-run)"
    if not sys.platform.startswith("linux"):
        return Check("display", what, "skipped", False, "not Linux: the engine uses this system's own display; not checked",
                     None, True)
    if shutil.which("xvfb-run") is None:
        return _missing("display", what, "xvfb-run is not installed", f"{APT} xvfb", run=True)
    return _ok("display", what, f"xvfb-run at {shutil.which('xvfb-run')}", run=True)


PROBE_PROJECT = '[application]\nconfig/name="expectrail-doctor"\nrun/main_scene="res://probe.tscn"\n'
PROBE_SCENE = '[gd_scene format=3]\n\n[node name="Probe" type="Node"]\n'


def opengl(engine: Path | None, shown: Check) -> Check:
    """The real thing: the engine draws one frame of an empty project, started as a replay starts it
    (harness.run.godot_cmd and game_env), and names the device it drew with."""
    what = "OpenGL the engine can draw with (Mesa's software renderer)"
    mesa = f"{APT} libgl1-mesa-dri libglx-mesa0"
    if engine is None or shown.status == "missing":
        return Check("opengl", what, "skipped", True, "not tried: it needs Godot and a display, and one is missing above",
                     "fix what is missing above, then run `expectrail doctor` again", True)
    from harness.run import game_env, godot_cmd

    try:
        with tempfile.TemporaryDirectory(prefix="expectrail-doctor-") as tmp:
            Path(tmp, "project.godot").write_text(PROBE_PROJECT, encoding="utf-8")
            Path(tmp, "probe.tscn").write_text(PROBE_SCENE, encoding="utf-8")
            done = subprocess.run(godot_cmd(engine, False) + ["--path", tmp, "--audio-driver", "Dummy",
                                                               "--rendering-driver", "opengl3", "--quit"],
                                  capture_output=True, text=True, timeout=120, env=game_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _missing("opengl", what, f"the engine could not draw a frame ({type(exc).__name__})", mesa, run=True)
    device = re.search(r"Using Device: (.+)", done.stdout + done.stderr)
    if done.returncode != 0 or not device:
        return _missing("opengl", what, f"the engine drew no frame (exit {done.returncode}, no device named)", mesa, run=True)
    name = _clip(device.group(1), 80)
    if "llvmpipe" not in name.lower():
        return _ok("opengl", what, f"the engine drew a frame with {name}; this is not Mesa's software renderer, "
                                   "which every recorded run used, so frames may differ from those", run=True)
    return _ok("opengl", what, f"the engine drew a frame with {name}", run=True)


def _existing(path: Path) -> Path:
    path = Path(path).absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def disk() -> Check:
    from harness.run import tools_dir

    what = f"{MIN_FREE_BYTES // 1024 ** 2} MB free for the engine and a run's frames"
    places = {"the engine's folder": _existing(tools_dir()), "the temporary folder": _existing(Path(tempfile.gettempdir()))}
    low, shown = [], []
    for label, place in places.items():
        try:
            free = shutil.disk_usage(place).free
        except OSError as exc:
            low.append(f"{label} ({place}) could not be measured ({type(exc).__name__})")
            continue
        shown.append(f"{free // 1024 ** 2} MB free in {label} ({place})")
        if free < MIN_FREE_BYTES:
            low.append(f"{free // 1024 ** 2} MB free in {label} ({place})")
    if low:
        return _missing("disk", what, "; ".join(low),
                        "free some space there, or name other folders with EXPECTRAIL_TOOLS and TMPDIR", run=True)
    return _ok("disk", what, "; ".join(shown), run=True)


def sandbox(isolated: bool) -> Check:
    """bubblewrap, by the probe a replay uses. Required only when the isolated class is asked for."""
    from harness import sandbox as box

    what = "the replay sandbox (bubblewrap)"
    tool, why = box.probe(True)
    if tool is not None:
        return _ok("sandbox", what, f"bubblewrap {tool.version} at {tool.path} started a sandbox", required=isolated)
    fix = (f"{APT} bubblewrap (Linux; the kernel must allow unprivileged user namespaces). Without it replays "
           "run outside the sandbox, and the isolated class and `require-sandbox` refuse to run")
    return _missing("sandbox", what, _clip(why or "the sandbox could not be started"), fix, required=isolated)


def program(name: str, why: str, *, required: bool, package: str | None = None) -> Check:
    what = f"`{name}` ({why})"
    path = shutil.which(name)
    if path:
        return _ok(name, what, f"{name} at {path}", required=required)
    return _missing(name, what, f"{name} is not installed", f"{APT} {package or name}", required=required)


def vision_key(env: dict | None = None) -> Check:
    """Report presence only; never return or print the key's value."""
    env = os.environ if env is None else env
    what = "a key for a visual observer (MODEL_API_KEY)"
    if str(env.get("MODEL_API_KEY") or "").strip():
        return _ok("vision-key", what, "MODEL_API_KEY is present (value withheld)")
    return _missing("vision-key", what, "MODEL_API_KEY is missing. " + NO_KEY,
                    "set MODEL_API_KEY in the verifier's environment to its vision model key; never put it in a file")


def vision_cap(env: dict | None = None) -> Check:
    env = os.environ if env is None else env
    raw = str(env.get("EXPECTRAIL_SAM_USD_CAP") or "").strip()
    try:
        cap = float(raw)
    except ValueError:
        cap = float("nan")
    what = "a vision spend cap (EXPECTRAIL_SAM_USD_CAP)"
    if 0 <= cap < float("inf"):
        return _ok("vision-cap", what, f"EXPECTRAIL_SAM_USD_CAP is ${cap:g} per run")
    return _missing("vision-cap", what, "EXPECTRAIL_SAM_USD_CAP is missing or invalid. " + NO_KEY,
                    "set EXPECTRAIL_SAM_USD_CAP to the most this run may spend in US dollars (a finite amount, 0 or more)")


def vision_checks(env: dict | None = None) -> list[Check]:
    return [vision_key(env), vision_cap(env)]


def for_run() -> list[Check]:
    """What every run needs, checked as a run uses it. The engine's preflight calls this."""
    engine, path = godot(True)
    shown = display()
    return [engine, shown, opengl(path, shown), disk()]


def checks(*, isolated: bool = False, fetch: bool = True, env: dict | None = None) -> list[Check]:
    """Every piece `doctor` reports, in the order it prints them."""
    engine, path = godot(fetch)
    shown = display()
    here = engine.status == "ok"
    fetching = "to fetch the engine; it is already here" if here else "to fetch the engine"
    return [python(), engine, shown, opengl(path, shown), disk(), sandbox(isolated),
            program("patch", "`expectrail sample` and seeded bugs put a patch on a copy of the game", required=True),
            program("curl", fetching, required=False), program("unzip", fetching, required=False),
            *vision_checks(env)]


def missing(found: list[Check]) -> list[Check]:
    """The required pieces that are not ok. `doctor` exits non-zero, and the preflight stops a job,
    exactly when this is not empty for the pieces each asks about."""
    return [c for c in found if c.required and c.status != "ok"]


def document(found: list[Check]) -> dict:
    return {"format": FORMAT, "expectrail": __version__, "ok": not missing(found),
            "checks": [{"id": c.id, "what": _clip(c.what, 200), "status": c.status, "required": c.required,
                        "found": _clip(c.found, 1000), "fix": None if c.fix is None else _clip(c.fix, 600)}
                       for c in found]}


def problems(doc) -> list[str]:
    """Why a document is not a valid expectrail.doctor/v1 record ([] when it is). ``ok`` must follow
    from the checks: a reader does not take the summary's word for it."""
    from expectrail.gate import record as rec

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"doctor: the schema could not be read ({type(exc).__name__})"]
    found = [f"doctor: {e}" for e in rec.errors(doc, schema)]
    if found:
        return found
    ids = [c["id"] for c in doc["checks"]]
    if len(set(ids)) != len(ids):
        found.append("doctor: a check is listed twice")
    for c in doc["checks"]:
        if (c["status"] in ("ok", "present", "absent")) != (c["fix"] is None):
            found.append(f"doctor: {c['id']}: a fix is given exactly when something is missing or was not tried")
    want = not any(c["required"] and c["status"] != "ok" for c in doc["checks"])
    if doc["ok"] != want:
        found.append("doctor: `ok` does not follow from the checks")
    return found


WORD = {"ok": "ok", "missing": "MISSING", "skipped": "not tried", "present": "present", "absent": "absent"}


def text(found: list[Check]) -> str:
    lines = [f"expectrail doctor ({__version__}): what a verification needs on this machine", ""]
    for c in found:
        word = WORD[c.status] if c.required or c.status != "missing" else "missing"
        lines.append(f"  {word:<9} {c.what}")
        lines.append(f"            {c.found}")
        if c.fix:
            lines.append(f"            fix: {c.fix}")
    lines.append("")
    bad = missing(found)
    optional = [c for c in found if not c.required and c.status == "missing"]
    if bad:
        lines.append(f"{len(bad)} required piece{'s' if len(bad) != 1 else ''} missing ({', '.join(c.id for c in bad)}): "
                     "fix that before running `expectrail sample` or a verification here.")
    else:
        lines.append("Everything a verification needs is here." + (
            f" Not required and missing: {', '.join(c.id for c in optional)}." if optional else ""))
    lines.append("This checks the machine. It is not a verdict on any change.")
    return "\n".join(lines)


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def main(argv: list[str] | None = None, *, prog: str = "expectrail doctor") -> int:
    p = _Parser(prog=prog, description="Check that this machine has what a verification needs.")
    p.add_argument("--json", action="store_true", help="print one expectrail.doctor/v1 document")
    p.add_argument("--isolated", action="store_true",
                   help="also require the replay sandbox, as the isolated execution class does")
    p.add_argument("--no-fetch", action="store_true", help="only look for the engine; do not download it")
    try:
        args = p.parse_args(argv)
    except _Usage as exc:
        print(f"{prog}: {exc}\n{p.format_usage().strip()}", file=sys.stderr)
        return EXIT_USAGE
    found = checks(isolated=args.isolated, fetch=not args.no_fetch)
    print(json.dumps(document(found), indent=2) if args.json else text(found))
    return EXIT_MISSING if missing(found) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
