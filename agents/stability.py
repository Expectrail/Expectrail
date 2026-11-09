"""Flaky-route detector: a failing route counts only when it fails the same way on repeated replays.

    python3 -m agents.stability --route harness/routes/smoke.json --out runs/stability \\
        [--patch bugs/physics-fall-through/v1.patch] [--runs 3] [--record-baseline]

Determinism is proven on one setup only (docs/harness.md). ``check`` replays one route k times
(default 3, the three-of-three rule advisory discovery uses) with a run function that has
``harness.run.run``'s contract: it returns the replay document and raises SystemExit when the
replay fails. Each replay is judged by the caller's judge, and the replays are compared by their
``frameSha256`` lists and the trace sha256 in replay.json.

- ``stable-fail``: every replay ran, all are identical, and every one failed. Result: fail.
- ``stable-pass``: every replay ran, all are identical, and every one passed. Result: pass.
- ``flaky``: the replays differ, or the judge's results differ, or some replays did not run while
  others did, or identical replays differ from this machine's baseline. Result: needs-review.
- ``undecided``: no replay ran, or every replay was identical and the judge could not decide on
  any of them. Result: needs-review.

A flaky route is never a pass and never a fail. The report (``expectrail.stability/v0``,
contracts/stability.schema.json) records a machine fingerprint: the CPU model from /proc/cpuinfo,
the Mesa version Godot printed in godot.log, and the engine version, renderer and device from
replay.json. replay.json itself is not changed: harness/run.py, which writes it, is pinned.
Hash-only baselines, one file per fingerprint, live in bench/baselines/ (see its README). Callers
compare against them; only this command line records them, with --record-baseline.

The command line judges each replay with the verifier's regression check (the ground spec) on the
position log against the clean level's ground line, as the verifier does with SAM off. It sends no
SAM images. It exits 0 when the route is stable (stable-fail or stable-pass) and 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from harness.run import REPO
from expectrail.contracts import canonical, validate

FORMAT = "expectrail.stability/v0"
BASELINE_FORMAT = "expectrail.stability-baseline/v0"
KIND = "stability"  # contracts/stability.schema.json; validated with the kind named (see docs/contracts.md)
STABILITY_RUNS = 3  # the same as advisory discovery's REPRO_RUNS (expectrail/discovery/run.py)
BASELINES = REPO / "bench" / "baselines"
RESULTS = ("fail", "needs-review", "pass")
CPUINFO = Path("/proc/cpuinfo")
# Godot's renderer line, e.g. "OpenGL API 4.5 (Core Profile) Mesa 25.2.8-0ubuntu0.24.04.4 - Compatibility".
MESA_RE = re.compile(r"OpenGL API [^\n]*?\bMesa (\d[^\s]*)")
# /proc/cpuinfo keys that name the CPU model, most common first. Case matters: x86 also has a
# lowercase "processor" key that holds a CPU number, not a model.
CPU_KEYS = ("model name", "Hardware", "Processor", "cpu model", "cpu")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CASE_FIELDS = ("route", "gameTree", "patchSha256", "fps", "captured")
HASH_FIELDS = ("frames", "frameListSha256", "traceSha256")

Run = Callable[..., dict]
Judge = Callable[[dict, Path], "str | dict[str, str]"]


# --- machine fingerprint ---------------------------------------------------------------------

def cpu_model(cpuinfo: Path = CPUINFO) -> str | None:
    """The CPU model: /proc/cpuinfo on Linux, sysctl on macOS, else what platform reports."""
    try:
        text = Path(cpuinfo).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for key in CPU_KEYS:
        m = re.search(rf"^{re.escape(key)}\s*:\s*(.+)$", text, re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or None


def mesa_version(run_dir: Path | None) -> str | None:
    """The Mesa version Godot printed when it started rendering, or None (a headless run starts no
    renderer, and a GPU driver that is not Mesa prints no Mesa version)."""
    if run_dir is None:
        return None
    try:
        log = (Path(run_dir) / "godot.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = MESA_RE.search(log)
    return m.group(1) if m else None


def fingerprint(replay: dict | None, run_dir: Path | None, cpuinfo: Path = CPUINFO) -> dict:
    """The machine type a replay ran on. The id (16 hex digits of the sha256 of the other fields)
    names the baseline file."""
    engine = (replay or {}).get("engine") or {}
    fields = {
        "cpu": cpu_model(cpuinfo),
        "arch": platform.machine() or None,
        "mesa": mesa_version(run_dir),
        "engine": engine.get("version"),
        "renderer": engine.get("renderer"),
        "device": engine.get("device"),
    }
    return {"id": hashlib.sha256(canonical(fields)).hexdigest()[:16], **fields}


# --- comparing and judging replays -------------------------------------------------------------

def replay_hashes(replay: dict) -> dict:
    """What two replays are compared by: the frame count, a digest of the frameSha256 list, and
    the trace's sha256."""
    frames = [str(h) for h in replay.get("frameSha256") or []]
    trace = (replay.get("trace") or {}).get("sha256")
    return {
        "frames": len(frames),
        "frameListSha256": hashlib.sha256("\n".join(frames).encode("utf-8")).hexdigest(),
        "traceSha256": trace if isinstance(trace, str) and SHA256_RE.fullmatch(trace) else None,
    }


def summarize(checks: dict[str, str]) -> str:
    """One result for a set of check results: any fail is a fail; anything undecided, or no check
    at all, is needs-review; otherwise pass."""
    values = list(checks.values())
    if "fail" in values:
        return "fail"
    if not values or any(v != "pass" for v in values):
        return "needs-review"
    return "pass"


def _normalize(got) -> tuple[str, dict[str, str] | None]:
    """A judge's answer as (result, checks). Anything that is not a known result is needs-review."""
    if isinstance(got, dict):
        checks = {str(k): (v if v in RESULTS else "needs-review") for k, v in got.items()}
        return summarize(checks), checks
    return (got if got in RESULTS else "needs-review"), None


def _judge(judge: Judge, replay: dict, run_dir: Path) -> tuple[str, dict | None, str | None]:
    try:
        result, checks = _normalize(judge(replay, run_dir))
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a judge that cannot answer is needs-review
        return "needs-review", None, f"judge: {type(exc).__name__}: {exc}"
    return result, checks, None


def _frames_differ(a: list, b: list) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def _shown(path: Path, base: Path) -> str:
    """A path for the report: relative to base or the repository, never an absolute path."""
    path = Path(path)
    for root in (base, REPO):
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
    return path.name


def _case(route_sha: str, replay: dict | None) -> dict:
    game = (replay or {}).get("game") or {}
    capture = (replay or {}).get("capture") or {}
    tree, patch = game.get("tree"), game.get("patchSha256")
    fields = {
        "route": route_sha,
        "gameTree": tree if isinstance(tree, str) and SHA256_RE.fullmatch(tree) else None,
        "patchSha256": patch if isinstance(patch, str) and SHA256_RE.fullmatch(patch) else None,
        "fps": capture.get("fps") if isinstance(capture.get("fps"), int) else None,
        "captured": bool((replay or {}).get("frameSha256")),
    }
    return {"key": hashlib.sha256(canonical(fields)).hexdigest(), **fields}


def _baseline_file(baselines: Path, fp: dict) -> Path:
    return Path(baselines) / f"{fp['id']}.json"


def _load_baseline(path: Path) -> dict | None:
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != BASELINE_FORMAT or not isinstance(doc.get("cases"), dict):
        raise SystemExit(f"{path}: not an {BASELINE_FORMAT} file")
    return doc


def _matches(entry: dict, hashes: dict) -> bool:
    return all(entry.get(k) == hashes.get(k) for k in HASH_FIELDS)


def _compare_baseline(baselines: Path | None, fp: dict, case: dict, hashes: dict | None,
                      identical: bool) -> dict:
    if baselines is None:
        return {"status": "off", "file": None}
    path = _baseline_file(baselines, fp)
    shown = _shown(path, REPO)
    if not identical or hashes is None:
        return {"status": "not-compared", "file": shown}
    doc = _load_baseline(path)
    entry = (doc or {}).get("cases", {}).get(case["key"])
    if entry is None:
        return {"status": "missing", "file": shown}
    return {"status": "match" if _matches(entry, hashes) else "differs", "file": shown}


def _tally(rows: list[dict]) -> str:
    done = [r for r in rows if r["frames"] is not None]
    parts = [f"{sum(r['result'] == res for r in done)} {word}"
             for res, word in (("fail", "failed"), ("pass", "passed"), ("needs-review", "undecided"))
             if any(r["result"] == res for r in done)]
    return ", ".join(parts) or "none judged"


def check(run: Run, route: Path, out: Path, *, judge: Judge, patches: list[Path] | None = None,
          runs: int = STABILITY_RUNS, first: tuple[dict, Path, object] | None = None,
          baselines: Path | None = None, cpuinfo: Path = CPUINFO) -> dict:
    """Replay ``route`` ``runs`` times and say whether it fails the same way every time.

    ``run(route, run_dir, patches=[...])`` has harness.run.run's contract. ``judge(replay, run_dir)``
    returns a result (fail, needs-review or pass) or a dict of named check results. ``first`` is a
    replay the caller already ran and judged, as (replay document, its directory, the judge's
    answer); it counts as replay 1, as discovery counts the run that found a failure. ``baselines``
    is the directory of baseline files to compare with (read only; None compares with nothing).
    Writes ``out/stability.json`` and returns it.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")
    route = Path(route)
    out.mkdir(parents=True, exist_ok=True)
    patches = list(patches or [])
    route_bytes = route.read_bytes()
    try:
        route_name = str(json.loads(route_bytes).get("name") or route.stem)
    except (ValueError, AttributeError):
        route_name = route.stem
    route_sha = hashlib.sha256(route_bytes).hexdigest()

    rows: list[dict] = []
    docs: list[dict | None] = []
    dirs: list[Path] = []

    def add(n: int, replay: dict | None, run_dir: Path, result: str, checks, error: str | None):
        hashes = replay_hashes(replay) if replay is not None else dict.fromkeys(HASH_FIELDS)
        rows.append({"run": n, "dir": _shown(run_dir, out), "result": result, "checks": checks, **hashes,
                     "framesDifferFromFirst": None, "error": error})
        docs.append(replay)
        dirs.append(run_dir)

    if first is not None:
        replay, run_dir, got = first
        result, checks = _normalize(got)
        add(1, replay, Path(run_dir), result, checks, None)
    for n in range(len(rows) + 1, runs + 1):
        run_dir = out / f"replay-{n:02d}"
        try:
            replay = run(route, run_dir, patches=patches)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - a replay that did not run is counted, never a pass
            add(n, None, run_dir, "needs-review", None, f"{type(exc).__name__}: {exc}")
            continue
        if not isinstance(replay, dict):
            add(n, None, run_dir, "needs-review", None, "the run function returned no replay document")
            continue
        add(n, replay, run_dir, *_judge(judge, replay, run_dir))

    done = [i for i, r in enumerate(rows) if r["frames"] is not None]
    crashed = len(rows) - len(done)
    if done:
        ref = docs[done[0]].get("frameSha256") or []
        for i in done:
            rows[i]["framesDifferFromFirst"] = _frames_differ(ref, docs[i].get("frameSha256") or [])
    distinct = len({tuple(rows[i][k] for k in HASH_FIELDS) for i in done})
    identical = crashed == 0 and distinct == 1
    outcomes = {canonical(rows[i]["checks"] if rows[i]["checks"] is not None else rows[i]["result"])
                for i in done}
    agree = len(outcomes) == 1
    ref_replay = docs[done[0]] if done else None
    fp = fingerprint(ref_replay, dirs[done[0]] if done else None, cpuinfo)
    case = _case(route_sha, ref_replay)
    hashes = {k: rows[done[0]][k] for k in HASH_FIELDS} if done else None
    baseline = _compare_baseline(baselines, fp, case, hashes, identical)

    if not done:
        status, reason = "undecided", f"none of the {runs} replays ran"
    elif crashed:
        status, reason = "flaky", (f"{crashed} of {runs} replays did not run and {len(done)} did "
                                   f"({_tally(rows)})")
    elif distinct > 1:
        status, reason = "flaky", (f"the {runs} replays are not identical ({distinct} different sets of "
                                   f"frame and trace hashes; {_tally(rows)})")
    elif not agree:
        status, reason = "flaky", f"the {runs} replays are identical but the judge's results differ ({_tally(rows)})"
    elif baseline["status"] == "differs":
        status, reason = "flaky", (f"the {runs} replays are identical to each other but differ from this "
                                   f"machine's baseline ({baseline['file']})")
    elif rows[done[0]]["result"] == "fail":
        status, reason = "stable-fail", f"failed {runs} of {runs} replays, all identical"
    elif rows[done[0]]["result"] == "pass":
        status, reason = "stable-pass", f"passed {runs} of {runs} replays, all identical"
    else:
        status = "undecided"
        errors = [rows[i]["error"] for i in done if rows[i]["error"]]
        reason = f"the {runs} replays are identical but the judge could not decide on any of them" + (
            f" ({errors[0]})" if errors else "")

    # Per check, for judges that return several: a check keeps its result only when every replay
    # ran, all are identical (and agree with the baseline) and the check said the same every time.
    names: list[str] = []
    for i in done:
        for name in rows[i]["checks"] or {}:
            if name not in names:
                names.append(name)
    checks = None
    if names:
        trusted = identical and baseline["status"] != "differs"
        checks = {}
        for name in names:
            seen = [(rows[i]["checks"] or {}).get(name) for i in done]
            same = trusted and len(set(seen)) == 1 and seen[0] is not None
            checks[name] = seen[0] if same else "needs-review"

    doc = {
        "format": FORMAT,
        "route": {"name": route_name, "sha256": route_sha},
        "case": case,
        "runs": runs,
        "status": status,
        "result": {"stable-fail": "fail", "stable-pass": "pass"}.get(status, "needs-review"),
        "reason": reason,
        "counts": {r: sum(rows[i]["result"] == r for i in done) for r in RESULTS} | {"crashed": crashed},
        "distinctReplays": distinct,
        "replaysIdentical": identical,
        "resultsAgree": agree,
        "checks": checks,
        "replays": rows,
        "fingerprint": fp,
        "baseline": baseline,
    }
    validate(doc, KIND)
    (out / "stability.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def record_baseline(report: dict, baselines: Path = BASELINES) -> Path:
    """Add this report's hashes to its machine's baseline file. Only identical replays are recorded,
    and an entry that already holds different hashes is never overwritten: remove it by hand if the
    change is expected. Nothing but digests is written: no route name, frame or trace."""
    if not report["replaysIdentical"]:
        raise SystemExit(f"not recorded: the replays are not identical ({report['reason']})")
    fp = report["fingerprint"]
    path = _baseline_file(baselines, fp)
    doc = _load_baseline(path) or {"format": BASELINE_FORMAT, "fingerprint": fp, "cases": {}}
    if doc["fingerprint"] != fp:
        raise SystemExit(f"{path}: holds another fingerprint than this machine's")
    first = report["replays"][0]
    hashes = {k: first[k] for k in HASH_FIELDS}
    key = report["case"]["key"]
    entry = doc["cases"].get(key)
    if entry is not None:
        if not _matches(entry, hashes):
            raise SystemExit(f"not recorded: {path} already holds different hashes for this case")
        return path
    doc["cases"][key] = {**{k: report["case"][k] for k in CASE_FIELDS}, **hashes,
                         "runs": report["runs"], "recorded": date.today().isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# --- the verifier's regression check, for callers that confirm a failing base ------------------

def ground_judge(out: Path, spec: dict | None = None) -> Judge:
    """A judge for the verifier's regression check, on the position log only.

    The ground spec (or the request's own copy of it, the same rule verify() uses) judged against
    the clean game's ground line, as the verifier judges it with SAM off. It sends no SAM image.
    The clean level's surfaces come from one short replay of the unpatched game, under ``out``.
    """
    from agents.patchutil import sha256_file
    from agents.verifier import REGRESSION_SPEC, _ground_observations, reference_surfaces
    from expectrail.contracts import load
    from expectrail.evaluator import evaluate

    reg = load(REGRESSION_SPEC, "test-spec")
    if spec is not None and spec.get("id") == reg["id"]:
        reg = spec
    reference = reference_surfaces(out)

    def judge(_replay: dict, run_dir: Path) -> str:
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        obs, _source = _ground_observations(reg, trace, sha256_file(run_dir / "replay.json"),
                                            run_dir / "frames", False, reference)
        return evaluate(reg, obs)["result"]

    return judge


def confirm_failing(request: dict, out: Path, *, runs: int = STABILITY_RUNS, run: Run | None = None,
                    baselines: Path | None = BASELINES) -> dict:
    """Replay a repair request's failing route on its failing base (the seed patch, no fix) ``runs``
    times and judge each replay with the regression check. Returns the stability report."""
    if run is None:
        from harness.run import run as harness_run

        run = harness_run
    failing = request["failing"][0]
    out.mkdir(parents=True, exist_ok=True)
    route = out / "route.json"
    route.write_text(json.dumps(failing["route"], indent=2) + "\n", encoding="utf-8")
    seed = request["base"].get("patch")
    patches = [seed if Path(seed).is_absolute() else REPO / seed] if seed else []
    judge = ground_judge(out, failing.get("spec"))
    return check(run, route, out, judge=judge, patches=[Path(p) for p in patches], runs=runs,
                 baselines=baselines)


def summary(report: dict, path: Path | None = None) -> dict:
    """The few fields a run record carries about a stability check."""
    doc = {k: report[k] for k in ("status", "result", "runs", "reason", "counts", "distinctReplays")}
    doc["fingerprint"] = report["fingerprint"]["id"]
    doc["baseline"] = report["baseline"]["status"]
    if path is not None:
        doc["path"] = str(path)
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("runs/stability"))
    p.add_argument("--patch", type=Path, action="append", default=[],
                   help="patch to apply (repeatable; order is seed then candidate)")
    p.add_argument("--runs", type=int, default=STABILITY_RUNS)
    p.add_argument("--baselines", type=Path, default=BASELINES,
                   help="directory of baseline files, one per machine fingerprint")
    p.add_argument("--record-baseline", action="store_true",
                   help="add this route's hashes to this machine's baseline (identical replays only)")
    args = p.parse_args(argv)
    from harness.run import run as harness_run

    report = check(harness_run, args.route, args.out, judge=ground_judge(args.out), patches=args.patch,
                   runs=args.runs, baselines=args.baselines)
    fp = report["fingerprint"]
    print(f"{report['status']}: {report['reason']}")
    print(f"machine {fp['id']}: cpu {fp['cpu']}, mesa {fp['mesa']}, engine {fp['engine']}, device {fp['device']}")
    print(f"baseline: {report['baseline']['status']}" + (f" ({report['baseline']['file']})"
                                                          if report["baseline"]["file"] else ""))
    if args.record_baseline:
        print(f"recorded: {record_baseline(report, args.baselines)}")
    return 0 if report["status"] in ("stable-fail", "stable-pass") else 1


if __name__ == "__main__":
    sys.exit(main())
