"""The evidence viewer (#264): one self-contained folder that answers, without opening JSON, what
failed, where and when, expected against measured, how sure, and how to reproduce it.

    <folder>/index.html     the viewer: inline style and script, the evidence embedded as data
    <folder>/views.json     the same views, for a later viewer (the job viewer) to read again
    <folder>/frames/*.png   captured frames around each finding, from the replays that made them
    <folder>/evidence.html  the same page as one file, frames embedded, to keep or send (``export``)

It opens from disk (file://) as well as from a web site: the evidence is embedded in the page, so
nothing is fetched, and a Content-Security-Policy forbids every request but the page's own frames.
The site's "Run it" (#265) and the local app (#370) open the same folder.

Rules this file holds:
- the decision shown is the verifier's. With a job, the job's decision is the one shown; when the
  job and its evidence disagree, nothing is shown as accepted. An empty result (no check ran, no
  evidence) is never shown as success;
- every state the job model has gets its own words (``STATES``): a failing behaviour, an observer
  that could not decide, a replay that did not finish, a project Expectrail cannot verify, a run
  that could not be carried out, nothing checked, cancelled, still running;
- the timeline is measured from the same observations the evaluator judged, and it is shown only
  when it agrees with the evaluator's verdict (``series_agrees``); otherwise it is left out and the
  page says so. It decides nothing;
- held-out routes appear as counts only: nothing from the held-out replays reaches this folder.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import os
import re
import shlex
import shutil
from pathlib import Path

from expectrail.diagnostics import redact
from expectrail.gate import record as rec

FORMAT = "expectrail.viewer/v0"
FRAMES_AROUND = 6            # frames either side of a finding's first failing frame
MAX_FRAMED_FINDINGS = 5      # findings that get frames; every finding is listed
MAX_VIEWS = 200              # checks that get a timeline
MAX_POINTS = 4000            # points in one timeline
MAX_VIEWS_BYTES = 8 * 1024 * 1024
MAX_EXPORT_FRAME_BYTES = 32 * 1024 * 1024   # frames embedded in evidence.html, before base64
EXPORT_NAME = "evidence.html"
FRAME_NAME = re.compile(r"frames/(after|before)-[0-9a-z-]{1,80}-\d{8}\.png")

# state -> (title, tone, what it means). The title never says more than the verifier decided.
STATES = {
    "accept": ("Accepted", "good",
               "Every approved check passed on every route after this change. That is these checks on these "
               "routes, not proof that the game is correct."),
    "behaviour-failure": ("Rejected: a check fails after this change", "bad",
                          "At least one approved check ran to the end and failed. The earliest failure is shown first."),
    "observation-failure": ("Needs review: an observer could not decide", "warn",
                            "At least one check could not be decided from what was observed (an object not found, "
                            "frames missing, or the visual observer gave no answer). Nothing here is a pass."),
    "replay-failure": ("Needs review: a replay did not run to the end", "warn",
                       "The game did not finish at least one route, so those checks have no result. This can be "
                       "the change or an unstable replay; run it again to tell."),
    "unsupported-project": ("Not verified: Expectrail cannot verify this project or request", "warn",
                            "Nothing was replayed. The request or the project is not one this verifier can run."),
    "infrastructure-failure": ("Not verified: the run could not be carried out", "warn",
                               "Something the run needs failed (a tool, a provider, a time limit, the worker). "
                               "This says nothing about the change. Run it again once the cause is fixed."),
    "nothing-checked": ("Not verified: no check ran", "warn",
                        "No approved check was judged, so there is nothing to accept. An empty result is not a pass."),
    "needs-review": ("Needs review", "warn",
                     "Some evidence is missing or could not be decided, so this is not an accept. A person should look."),
    "cancelled": ("Cancelled: there is no result", "quiet", "The job was cancelled before it finished."),
    "running": ("Running: there is no result yet", "quiet", "The job has not finished."),
}
UNSUPPORTED_CODES = ("INPUT_INVALID", "PATCH_SCOPE_BLOCKED")
WORD = {"pass": "pass", "fail": "fail", "needs-review": "needs review", "replay-error": "did not finish",
        "not-applicable": "not applicable", None: "not run"}


# --- what the page says ---------------------------------------------------------------------------

def state_of(record: dict | None, status: dict | None = None) -> tuple[str, str | None, list[str]]:
    """(state, decision, reasons) for a record, a job status, or both.

    With a status, the job's phase and decision come first: a job that is not completed has no
    decision, and a completed job's decision is the one shown. When the job's decision and its
    record's differ, the result is needs-review: a viewer never picks the kinder one."""
    reasons: list[str] = []
    if status is not None:
        phase = status.get("phase")
        if phase == "cancelled":
            return "cancelled", None, list(status.get("reasons") or [])
        if phase == "failed":
            return "infrastructure-failure", None, list(status.get("reasons") or [])
        if phase != "completed":
            return "running", None, []
        decision = status.get("decision")
        reasons = list(status.get("reasons") or [])
        if record is None:
            codes = [d.get("code") for d in status.get("diagnostics") or []]
            if any(c in UNSUPPORTED_CODES for c in codes):
                return "unsupported-project", "needs-review", reasons
            if decision == "accept":
                return "needs-review", "needs-review", reasons + [
                    "the job says accept but its evidence is missing, so nothing here is accepted"]
            return "infrastructure-failure", "needs-review", reasons or ["the job wrote no evidence"]
        if decision != record["decision"]:
            return "needs-review", "needs-review", reasons + [
                f"the job's decision ({decision}) and its evidence's ({record['decision']}) differ, so nothing "
                "here is accepted"]
    if record is None:
        return "nothing-checked", None, reasons or ["there is no evidence to show"]
    decision = record["decision"]
    reasons = reasons or list(record.get("reasons") or [])
    afters = [c["after"] for c in record.get("checks") or [] if c["after"] != "not-applicable"]
    if decision == "reject":
        return "behaviour-failure", decision, reasons
    if not afters or not record["counts"]["checks"]:
        return "nothing-checked", "needs-review", reasons
    if decision == "accept":
        if all(a == "pass" for a in afters):
            return "accept", decision, reasons
        return "needs-review", "needs-review", reasons + ["the record says accept but not every check passed"]
    if "replay-error" in afters:
        return "replay-failure", decision, reasons
    if "needs-review" in afters:
        return "observation-failure", decision, reasons
    return "needs-review", decision, reasons


def not_tested(record: dict | None) -> list[str]:
    """What this run did not test, in plain words."""
    if record is None:
        return ["nothing: no check ran"]
    out = []
    held = record["heldOut"]
    if held["status"] == "not-used":
        out.append("no held-out routes: only the public routes were replayed")
    elif held["status"] == "unavailable":
        out.append("the held-out routes could not be judged")
    if not any(c["before"] is not None for c in record["checks"]):
        out.append("the build before the change: nothing was compared with it")
    if rec.rule_of(record) == rec.ENGINE_ONLY:
        out.append("the frames by a visual observer: only the engine's record judged")
    elif (record.get("observers") or {}).get("visual") is None:
        out.append("the frames by a visual observer: none was asked, so nothing is accepted")
    if record.get("drafts"):
        out.append(f"{record['drafts']} draft spec{'s' if record['drafts'] != 1 else ''} (not approved, not used)")
    if record.get("checkProblems"):
        out.append(f"{record['checkProblems']} spec or route file{'s' if record['checkProblems'] != 1 else ''} "
                   "that could not be used")
    iso = record.get("isolation")
    if iso is None or iso["sandboxed"] != iso["replays"]:
        out.append("in the replay sandbox: " + rec.isolation_words(iso))
    out.append("anything outside these routes, these checks and this game build")
    return out


def reproduce(request: dict | None, *, sample: str | None = None) -> str | None:
    """The command that runs the same verification again, from the job's request. Only public
    inputs: the request never names held-out material."""
    if sample is not None:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", sample):
            raise ValueError("a public sample must have a plain sample id")
        return f"python3 -m expectrail.runit run --sample {sample} --out {sample}-run"
    if not request:
        return None
    p = request["project"]
    cmd = ["expectrail", "verify", "--adapter", p["adapter"], "--head", request["head"]["checkout"]]
    if request.get("base"):
        cmd += ["--base", request["base"]["checkout"]]
    cmd += ["--game", p["game"], "--routes", " ".join(p["routes"]), "--specs", p["specs"]]
    if request["head"].get("commit"):
        cmd += ["--head-commit", request["head"]["commit"]]
    if request.get("base") and request["base"].get("commit"):
        cmd += ["--base-commit", request["base"]["commit"]]
    return " ".join(shlex.quote(str(c)) for c in cmd)


# --- the timeline: one check's measured value against its limit, frame by frame -------------------

def series(spec: dict, observations: dict, *, end_frame: int | None = None) -> dict | None:
    """What the check measures in each frame of its window, from the observations the evaluator
    judged, by the evaluator's own rules (expectrail.evaluator). Each point: the frame, the value,
    and a state: ``ok``, ``over`` (past the limit: a failing frame), ``missing`` (an object the
    check needs was not found), ``not-applicable`` (nothing to compare against in that frame),
    ``short`` / ``reached`` for a goal. It decides nothing; ``series_agrees`` holds it to the verdict."""
    from expectrail import evaluator as ev

    assertion = spec["assertion"]
    kind = assertion["type"]
    scores = {name: obj.get("minScore", ev.DEFAULT_MIN_SCORE) for name, obj in spec["objects"].items()}

    def pick(frame, name):
        return ev._best(frame["objects"].get(name), scores.get(name, ev.DEFAULT_MIN_SCORE))

    head = {"kind": kind, "object": assertion["object"], "limit": None, "unit": "px", "label": ""}
    points = []
    for frame in ev._frames(spec, observations):
        n = frame["frame"]
        obj = pick(frame, assertion["object"])
        point = {"frame": n, "value": None, "state": "missing", "boxes": {}}
        if obj is not None:
            point["boxes"][assertion["object"]] = list(obj["box"])
        if kind == "visible":
            head.update(limit=None, unit="", label=f"{assertion['object']} found (1) or not (0)")
            point.update(value=1 if obj else 0, state="ok" if obj else "over")
        elif obj is None:
            pass
        elif kind == "inside-region":
            region = assertion["region"]
            tol = assertion.get("tolerancePx", 0)
            head.update(limit=tol, label=f"px of {assertion['object']} outside its region")
            if "box" in region:
                box = region["box"]
            else:
                ref = pick(frame, region["relativeTo"])
                if ref is None:
                    points.append(point)
                    continue
                m = region.get("marginPx", 0)
                box = [ref["box"][0] - m, ref["box"][1] - m, ref["box"][2] + m, ref["box"][3] + m]
            b = obj["box"]
            out = max(box[0] - b[0], box[1] - b[1], b[2] - box[2], b[3] - box[3])
            point["boxes"]["region"] = list(box)
            point.update(value=out, state="over" if out > tol else "ok")
        elif kind == "never-crosses":
            bnd = assertion["boundary"]
            index, sign = ev.SIDE[bnd["side"]]
            tol = bnd.get("tolerancePx", 0)
            head.update(limit=tol, label=f"px of {assertion['object']} past the boundary ({bnd['side']})")
            if "relativeTo" in bnd:
                refs = [d for d in frame["objects"].get(bnd["relativeTo"]) or []
                        if d.get("score", 0) >= scores.get(bnd["relativeTo"], ev.DEFAULT_MIN_SCORE)]
                if not refs:
                    points.append(point)
                    continue
                if bnd.get("requireOverlap", True):
                    other = "x" if bnd["side"] in ("above", "below") else "y"
                    refs = [d for d in refs if ev._overlap(obj["box"], d["box"], other)]
                    if not refs:
                        point.update(state="not-applicable")
                        points.append(point)
                        continue
                ref = min(refs, key=lambda d: abs(d["box"][ev.EDGE[bnd["edge"]]] - obj["box"][index]))
                value = ref["box"][ev.EDGE[bnd["edge"]]]
                point["boxes"][bnd["relativeTo"]] = list(ref["box"])
            else:
                value = bnd["value"]
            past = sign * (obj["box"][index] - value)
            point["line"] = {"axis": "y" if bnd["side"] in ("above", "below") else "x", "at": value}
            point.update(value=past, state="over" if past > tol else "ok")
        elif kind == "reaches":
            goal = pick(frame, assertion["goal"])
            head.update(limit=assertion.get("distancePx", 0), label=f"px from {assertion['object']} to {assertion['goal']}")
            if goal is None:
                points.append(point)
                continue
            point["boxes"][assertion["goal"]] = list(goal["box"])
            d = ev._distance(obj["box"], goal["box"])
            point.update(value=d, state="reached" if d <= head["limit"] else "short")
            if point["state"] == "reached":
                points.append(point)
                break
        else:
            return None
        points.append(point)
    # An absent frame was not observed, unlike an observed frame with no object.
    # Include leading/trailing gaps when the check or the engine supplies the window.
    window = spec.get("window") or {}
    lo = window.get("fromFrame", 0)
    hi = window.get("toFrame", end_frame if end_frame is not None else
                    max((p["frame"] for p in points), default=lo - 1))
    if end_frame is not None:
        hi = min(hi, end_frame)
    if kind == "reaches" and points and points[-1]["state"] == "reached":
        hi = min(hi, points[-1]["frame"])  # the existential check stops at its witness
    by_frame = {p["frame"]: p for p in points}
    points = [by_frame.get(n, {"frame": n, "value": None, "state": "absent", "boxes": {}})
              for n in range(lo, min(hi + 1, lo + MAX_POINTS))]
    return {**head, "points": points, "truncated": hi - lo + 1 > MAX_POINTS}


def series_agrees(s: dict | None, verdict: dict | None) -> bool:
    """Whether a timeline says what the verdict says: its first failing frame is the verdict's
    first failing frame, and a pass has no failing frame. Anything else is not shown."""
    if s is None or not isinstance(verdict, dict):
        return False
    if verdict.get("result") == "needs-review":
        return True  # measurements can be shown without claiming sufficient exercised coverage
    over = [p["frame"] for p in s["points"] if p["state"] == "over"]
    if s["kind"] == "reaches":
        reached = any(p["state"] == "reached" for p in s["points"])
        return (verdict.get("result") == "pass") == reached
    if verdict.get("result") == "fail":
        return bool(over) and over[0] == verdict.get("firstFrame")
    if verdict.get("result") == "pass":
        return not over
    return True   # needs-review: the timeline shows what was and was not observed


def _measured_series(spec, observations, verdict, source, end_frame=None) -> dict:
    try:
        s = series(spec, observations, end_frame=end_frame)
    except Exception as exc:  # noqa: BLE001 - a timeline that cannot be measured is left out, never guessed
        return {"series": None, "note": f"no timeline: it could not be measured ({type(exc).__name__})"}
    if s is None:
        return {"series": None, "note": "no timeline for this kind of check yet"}
    if not series_agrees(s, verdict):
        return {"series": None, "note": "no timeline: it does not agree with the evaluator's verdict, so it is left out"}
    s["source"] = source
    s["coverage"] = verdict.get("coverage")
    coverage = s["coverage"] or {}
    note = (f"Coverage: {coverage['status']}. {verdict.get('reason', '')}"
            if coverage.get("status") not in (None, "exercised") else None)
    return {"series": s, "note": note}


def check_series(spec: dict, run: dict, verdict: dict | None) -> dict:
    """Keep the public check's context until write_gate can read its saved visual evidence.

    _spec and _end_frame are internal only; build_views does not export them."""
    count = ((verdict or {}).get("coverage") or {}).get("framesExpected")
    end = (spec.get("window", {}).get("fromFrame", 0) + count - 1) if count else None
    return {**_measured_series(spec, run.get("engineObservations"), verdict, "the engine's record", end),
            "_spec": spec, "_end_frame": end}


def visual_series(out: Path, spec: dict | None, check: dict, side: str, spec_sha: str,
                  end_frame: int | None = None) -> dict:
    """Read only this public row's saved visual answer and verdict, bound by their digests."""
    from expectrail.contracts import digest, validate

    said = (check.get("observed") or {}).get(side) or {}
    if said.get("visual") not in rec.VISUAL_VERDICTS:
        return {"series": None, "note": "no visual timeline: vision " +
                ("did not run" if said.get("visual") == "not-asked" else "gave no usable observations")}
    try:
        if not spec or digest(spec) != spec_sha:
            raise ValueError("the check does not match the record")
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", check[k]) for k in ("spec", "route")):
            raise ValueError("not a public check path")
        arm = {"after": "head", "before": "base"}[side]
        def read(kind):
            path = Path(out) / kind / arm / check["route"] / (check["spec"] + ".visual.json")
            parent = Path(out)
            for part in ("", *path.relative_to(out).parts):
                parent = parent / part
                if parent.is_symlink():
                    raise ValueError("a visual evidence path is a link")
            return rec.read_json(path, MAX_VIEWS_BYTES, "visual evidence")
        observed, verdict = read("observations"), read("verdicts")
        validate(observed, "observations")
        validate(verdict, "verdict")
        sha = digest(observed)
        if (sha != said["visualAnswerSha256"] or verdict["observations"]["sha256"] != sha
                or verdict["spec"] != {"id": check["spec"], "sha256": spec_sha}
                or not (verdict["result"] == said["visual"] or
                        (verdict["result"] == "pass" and said["visual"] == "needs-review"))):
            raise ValueError("the visual evidence does not match the record")
        return _measured_series(spec, observed, verdict, "the visual observer's record", end_frame)
    except Exception as exc:  # presentation must omit unreadable or unbound evidence, never guess it
        return {"series": None, "note": f"no visual timeline: its recorded evidence could not be verified ({type(exc).__name__})"}


# --- writing the folder ---------------------------------------------------------------------------

def _scrub(value):
    """Every string redacted the way the review page redacts it."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _copy_frames(frames_dir, around: int | None, folder: Path, label: str) -> list[dict]:
    if frames_dir is None or around is None:
        return []
    # The captured frames nearest the first failing one, FRAMES_AROUND on each side, whatever the
    # capture rate: a harness that captures every other frame still gives thirteen frames to step through.
    try:
        have = sorted(int(m.group(1)) for m in (re.fullmatch(r"f(\d{8})\.png", p.name)
                                                for p in Path(frames_dir).iterdir()) if m)
    except OSError:
        return []
    before = [n for n in have if n < around][-FRAMES_AROUND:]
    after = [n for n in have if n >= around][:FRAMES_AROUND + 1]
    got = []
    for n in before + after:
        src = Path(frames_dir) / f"f{n:08d}.png"
        if not src.is_file() or src.is_symlink():
            continue
        name = f"frames/{label}-{n:08d}.png"
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        got.append({"frame": n, "path": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return got


def build_views(record: dict, frames: dict[str, dict], timelines: dict[tuple[str, str], dict],
                folder: Path) -> list[dict]:
    """One view per check: its result on both sides, its timeline on both sides, and for the first
    findings the frames around the first failing frame. ``frames`` is the review page's map (a
    finding id to {"after": (dir, frame), "before": (dir, frame)}); ``timelines`` maps (spec, route)
    to {"after": check_series(...), "before": ...}."""
    findings = {f["id"]: f for f in record["findings"]}
    order = sorted(record["findings"], key=lambda f: (f["frame"] is None, f["frame"] or 0, f["id"]))
    framed = {f["id"] for f in order[:MAX_FRAMED_FINDINGS]}
    views = []
    for check in record["checks"][:MAX_VIEWS]:
        fid = check["findingId"]
        finding = findings.get(fid) if fid else None
        first = finding["frame"] if finding else None
        got = frames.get(fid) or {} if fid in framed else {}
        tl = timelines.get((check["spec"], check["route"])) or {}
        view = {"spec": check["spec"], "route": check["route"], "before": check["before"], "after": check["after"],
                "comparison": check["comparison"], "findingId": fid, "firstFrame": first,
                "reason": finding["reason"] if finding else None, "frames": {}, "series": {}, "notes": [],
                "observed": check.get("observed"), "visualSeries": {}, "visualNotes": []}
        for side in ("after", "before"):
            src = got.get(side) or (None, None)
            view["frames"][side] = _copy_frames(src[0], first, folder, f"{side}-{fid or 'x'}") if fid else []
            one = tl.get(side) or {}
            view["series"][side] = one.get("series")
            if one.get("note"):
                view["notes"].append(f"{'after' if side == 'after' else 'before'} the change: {one['note']}")
            visual = one.get("visual") or {}
            view["visualSeries"][side] = visual.get("series")
            if visual.get("note"):
                view["visualNotes"].append(f"{side} the change: {visual['note']}")
        views.append(view)
    return views


def write(folder: Path, record: dict | None, views: list[dict] | None = None, *, status: dict | None = None,
          request: dict | None = None, sample: str | None = None) -> Path:
    """Write ``folder``/index.html (and views.json) for a record, a job status, or both."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    views = list(views or [])
    (folder / "views.json").write_text(json.dumps(views) + "\n", encoding="utf-8")
    state, decision, reasons = state_of(record, status)
    payload = _scrub({
        "format": FORMAT, "state": state, "decision": decision, "reasons": reasons,
        "record": record, "views": views,
        "job": None if status is None else {k: status.get(k) for k in (
            "id", "phase", "decision", "reasons", "diagnostics", "evidenceGrade", "executionClass", "inputs",
            "history", "finishedAt")},
        "reproduce": reproduce(request, sample=sample), "sample": sample,
    })
    page = folder / "index.html"
    page.write_text(render(payload), encoding="utf-8")
    export(folder, payload)
    return page


def export(folder: Path, payload: dict) -> Path:
    """``folder``/evidence.html: the page as one file that opens offline, every frame embedded as a
    data: URI. Only the folder's own frame files are read (the name ``FRAME_NAME`` allows, a regular
    file, not a link) and only when their bytes still have the sha256 the view recorded. A frame that
    fails either test, or that would pass ``MAX_EXPORT_FRAME_BYTES``, is left out, and the page says
    how many were left out and why. The decision, the state and the reasons are the payload's,
    unchanged: the export carries the same evidence, it never says more."""
    folder = Path(folder)
    out = copy.deepcopy(payload)
    embedded, left_out, budget = 0, {"over the size cap": 0, "missing or changed on disk": 0}, MAX_EXPORT_FRAME_BYTES
    for view in out.get("views") or []:
        frames = view.get("frames") if isinstance(view, dict) else None
        if not isinstance(frames, dict):
            continue
        for side in ("after", "before"):
            kept = []
            for f in frames.get(side) or []:
                data = _frame_bytes(folder, f)
                if data is None:
                    left_out["missing or changed on disk"] += 1
                    continue
                if len(data) > budget:
                    left_out["over the size cap"] += 1
                    continue
                budget -= len(data)
                kept.append(dict(f, path="data:image/png;base64," + base64.b64encode(data).decode("ascii")))
                embedded += 1
            frames[side] = kept
    out["export"] = {"framesEmbedded": embedded,
                     "framesLeftOut": {k: v for k, v in left_out.items() if v}}
    target = folder / EXPORT_NAME
    target.write_text(render(out), encoding="utf-8")
    return target


def _frame_bytes(folder: Path, f) -> bytes | None:
    if not isinstance(f, dict):
        return None
    path = f.get("path")
    if not isinstance(path, str) or not FRAME_NAME.fullmatch(path):
        return None
    src = folder / path
    if src.is_symlink() or not src.is_file():
        return None
    try:
        if src.stat().st_size > MAX_EXPORT_FRAME_BYTES:
            return None
        data = src.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    want = f.get("sha256")
    if not isinstance(want, str) or hashlib.sha256(data).hexdigest() != want:
        return None
    return data


def write_gate(out: Path, record: dict, frames: dict[str, dict], timelines: dict[tuple[str, str], dict]) -> Path:
    """The gate's viewer, beside its review page: out/viewer/."""
    folder = Path(out) / "viewer"
    shutil.rmtree(folder, ignore_errors=True)
    enriched = {}
    specs = {s["id"]: s["sha256"] for s in record["specs"]}
    for check in record["checks"][:MAX_VIEWS]:  # only public rows; no private paths are enumerated
        key = (check["spec"], check["route"])
        enriched[key] = {}
        for side in ("before", "after"):
            one = (timelines.get(key) or {}).get(side) or {}
            enriched[key][side] = dict(one, visual=visual_series(
                out, one.get("_spec"), check, side, specs.get(check["spec"]), one.get("_end_frame")))
    return write(folder, record, build_views(record, frames, enriched, folder))


def read_views(folder: Path) -> list[dict]:
    """A gate viewer's views, read as data: capped, strict JSON, and every frame path checked to be
    one of the folder's own frame files. Anything else is dropped, never trusted."""
    try:
        doc = rec.read_json(Path(folder) / "views.json", MAX_VIEWS_BYTES, "views.json")
    except rec.RecordError:
        return []
    if not isinstance(doc, list):
        return []
    out = []
    for view in doc[:MAX_VIEWS]:
        if not isinstance(view, dict) or not isinstance(view.get("frames"), dict):
            continue
        for side in ("after", "before"):
            kept = []
            for f in view["frames"].get(side) or []:
                path = f.get("path") if isinstance(f, dict) else None
                if isinstance(path, str) and FRAME_NAME.fullmatch(path) and (Path(folder) / path).is_file() \
                        and not (Path(folder) / path).is_symlink():
                    kept.append(f)
            view["frames"][side] = kept
        out.append(view)
    return out


def write_job(store, job_id: str, *, sample: str | None = None) -> Path:
    """The job's viewer: <job>/viewer/, from its status, its request and, when it completed with
    evidence, its findings record and the gate's viewer frames. This is the folder `expectrail
    report` names, the site and the local app open."""
    status = store.status(job_id)
    paths = store.paths(job_id)
    folder = paths.root / "viewer"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    record, views = None, []
    if status["phase"] == "completed" and status.get("output"):
        out = paths.output
        try:
            record = rec.read_record(out / "findings.json")
        except rec.RecordError:
            record = None
        gate_viewer = out / "viewer"
        if record is not None and gate_viewer.is_dir():
            views = read_views(gate_viewer)
            for view in views:
                for side in ("after", "before"):
                    for f in view["frames"][side]:
                        target = folder / f["path"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(gate_viewer / f["path"], target)
    try:
        request = store.request(job_id)
    except Exception:  # noqa: BLE001 - no request, no reproduction command; the rest still shows
        request = None
    return write(folder, record, views, status=status, request=request, sample=sample)


# --- the page -------------------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape(redact("" if value is None else str(value)), quote=True)


CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "base-uri 'none'; form-action 'none'")

CSS = """
:root{--bg:#fafaf7;--fg:#14161a;--muted:#4b5049;--line:#dcdcd5;--card:#fff;
--good-bg:#dff3e4;--good:#14532d;--bad-bg:#fde2e1;--bad:#7f1d1d;--warn-bg:#fdf1d6;--warn:#78350f;--quiet-bg:#eceee9;--quiet:#3f4540;
--over:#c0362c;--ok:#2f6f4f;--gap:#9a9a90;--limit:#7a5a00;--cursor:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#131512;--fg:#e8e8e3;--muted:#a7aca3;--line:#33362f;--card:#1b1d19;
--good-bg:#173823;--good:#b7ebc6;--bad-bg:#4a1d1b;--bad:#ffc9c4;--warn-bg:#47360f;--warn:#fde3a7;--quiet-bg:#2a2d27;--quiet:#d0d4cc;
--over:#ff7a6e;--ok:#7fd4a4;--gap:#77776f;--limit:#e0b44a;--cursor:#7aa2ff}}
*{box-sizing:border-box}
body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:var(--fg);background:var(--bg)}
main{max-width:1180px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}h3{font-size:15px;margin:16px 0 6px}
a{color:var(--cursor)}
.banner{border-radius:8px;padding:14px 16px;margin:8px 0 16px}
.good{background:var(--good-bg);color:var(--good)}.bad{background:var(--bad-bg);color:var(--bad)}
.warn{background:var(--warn-bg);color:var(--warn)}.quiet{background:var(--quiet-bg);color:var(--quiet)}
.badge{display:inline-block;padding:1px 8px;border-radius:4px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.facts td:first-child{width:34%;color:var(--muted)}
td{overflow-wrap:anywhere}
.scroll{overflow-x:auto}
code,pre{font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--card);border:1px solid var(--line);padding:10px;overflow-x:auto;white-space:pre-wrap;word-break:break-all}
.findings{list-style:none;padding:0;margin:0}.findings li{margin:0 0 6px}
.findings button{font:inherit;text-align:left;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
.findings button[aria-pressed=true]{outline:2px solid var(--cursor)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:640px){.pair{grid-template-columns:1fr}}
figure{margin:0}figcaption{font-size:13px;color:var(--muted);margin-top:4px}
.stage{position:relative;background:#000;border:1px solid var(--line);min-height:80px}
.stage img{display:block;width:100%;height:auto}
.stage svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.hole{padding:40px 12px;color:#ddd;text-align:center;font-size:14px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.controls button,.controls label{font:inherit;font-size:14px}
.controls button{padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
.controls input[type=range]{flex:1 1 200px}
.timeline svg{width:100%;height:120px;display:block;background:var(--card);border:1px solid var(--line)}
.legend{font-size:12px;color:var(--muted)}
.keys{font-size:13px;color:var(--muted)}kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-radius:3px;padding:0 4px}
.muted{color:var(--muted)}
"""

# The interactive part. It reads the embedded evidence, writes only with textContent and attributes,
# and never fetches anything.
SCRIPT = r"""
(function(){
"use strict";
var data = JSON.parse(document.getElementById("evidence").textContent);
var root = document.getElementById("inspector");
if (!root) return;
var views = (data.views || []).filter(function(v){ return v && typeof v === "object"; });
var findings = views.filter(function(v){ return v.findingId; });
findings.sort(function(a, b){
  var fa = typeof a.firstFrame === "number" ? a.firstFrame : Infinity;
  var fb = typeof b.firstFrame === "number" ? b.firstFrame : Infinity;
  return fa - fb || String(a.findingId).localeCompare(String(b.findingId));
});
var shown = findings.length ? findings : views;
var state = {i: 0, frame: 0, overlays: true, observer: "engine"};
function el(tag, attrs, text){
  var e = document.createElement(tag);
  for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
function svg(tag, attrs){
  var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
  return e;
}
function framesOf(v){
  var set = {};
  ["after", "before"].forEach(function(side){
    ((v.frames || {})[side] || []).forEach(function(f){ if (typeof f.frame === "number") set[f.frame] = 1; });
    [v.series, v.visualSeries].forEach(function(series){
      var s = (series || {})[side];
      if (s && s.points) s.points.forEach(function(p){ if (typeof p.frame === "number") set[p.frame] = 1; });
    });
  });
  return Object.keys(set).map(Number).sort(function(a, b){ return a - b; });
}
function framedOf(v){
  var set = {};
  ["after", "before"].forEach(function(side){
    ((v.frames || {})[side] || []).forEach(function(f){ if (typeof f.frame === "number") set[f.frame] = 1; });
  });
  return Object.keys(set).map(Number).sort(function(a, b){ return a - b; });
}
function pointAt(s, n){
  if (!s || !s.points) return null;
  for (var i = 0; i < s.points.length; i++) if (s.points[i].frame === n) return s.points[i];
  return null;
}
var COLORS = ["#ffd400", "#00e0ff", "#ff5cf0", "#7dff6a"];
function stage(v, side, n){
  var fig = el("figure");
  var box = el("div", {"class": "stage"});
  var f = ((v.frames || {})[side] || []).filter(function(x){ return x.frame === n; })[0];
  var label = side === "after" ? "After the change" : "Before the change";
  if (!f) {
    box.appendChild(el("div", {"class": "hole"}, "No " + (side === "after" ? "after" : "before") + " frame " + n + " in this evidence"));
    fig.appendChild(box);
    fig.appendChild(el("figcaption", null, label + ", frame " + n));
    return fig;
  }
  var img = el("img", {src: f.path, alt: label + ", frame " + n});
  box.appendChild(img);
  var selected = ((state.observer === "vision" ? v.visualSeries : v.series) || {})[side];
  var p = pointAt(selected, n);
  if (state.overlays && p) {
    var o = svg("svg", {"aria-hidden": "true", preserveAspectRatio: "none"});
    function draw(){
      var w = img.naturalWidth || 1, h = img.naturalHeight || 1;
      o.setAttribute("viewBox", "0 0 " + w + " " + h);
      var names = Object.keys(p.boxes || {});
      names.forEach(function(name, k){
        var b = p.boxes[name];
        if (!b || b.length !== 4) return;
        o.appendChild(svg("rect", {x: b[0], y: b[1], width: Math.max(0, b[2] - b[0]), height: Math.max(0, b[3] - b[1]),
          fill: "none", stroke: COLORS[k % COLORS.length], "stroke-width": Math.max(2, w / 400)}));
        var t = svg("text", {x: b[0] + 4, y: Math.max(14, b[1] - 4), fill: COLORS[k % COLORS.length], "font-size": Math.max(14, w / 60)});
        t.textContent = name;
        o.appendChild(t);
      });
      if (p.line && typeof p.line.at === "number") {
        var a = p.line.axis === "x"
          ? {x1: p.line.at, x2: p.line.at, y1: 0, y2: h}
          : {x1: 0, x2: w, y1: p.line.at, y2: p.line.at};
        a.stroke = "#ff3b30"; a["stroke-width"] = Math.max(2, w / 500); a["stroke-dasharray"] = "8 6";
        o.appendChild(svg("line", a));
      }
    }
    if (img.complete) draw(); else img.addEventListener("load", draw);
    box.appendChild(o);
  }
  fig.appendChild(box);
  var cap = label + ", frame " + n + ", sha256 " + String(f.sha256 || "").slice(0, 16);
  if (p && p.value !== null && p.value !== undefined) cap += ". Measured " + p.value + (selected.unit || "") + " (" + p.state + ")";
  else if (p) cap += ". " + p.state;
  fig.appendChild(el("figcaption", null, cap));
  return fig;
}
function timeline(v, side, n, visual){
  var s = ((visual ? v.visualSeries : v.series) || {})[side];
  var observer = visual ? "Vision" : "Engine";
  var wrap = el("div", {"class": "timeline"});
  wrap.appendChild(el("h3", null, observer + ", " + (side === "after" ? "after the change" : "before the change") + ": " + (s ? s.label + ", measured from " + (s.source || "the observations") : "no timeline")));
  if (!s || !s.points || !s.points.length) {
    var why = ((visual ? v.visualNotes : v.notes) || []).filter(function(t){ return t.indexOf(side) === 0; })[0];
    var said = (v.observed || {})[side];
    var missing = visual && said ? (said.visual === "not-asked" ? "Vision did not run for this check." :
      "Visual measurements are not included in this export. Recorded visual result: " + said.visual + ".") : "No measurements for this side.";
    wrap.appendChild(el("p", {"class": "muted"}, why || missing));
    return wrap;
  }
  var pts = s.points, W = 1000, H = 120, pad = 8;
  var lo = pts[0].frame, hi = pts[pts.length - 1].frame;
  var vals = pts.filter(function(p){ return typeof p.value === "number"; }).map(function(p){ return p.value; });
  if (typeof s.limit === "number") vals.push(s.limit);
  var vmin = Math.min.apply(null, vals.concat([0])), vmax = Math.max.apply(null, vals.concat([1]));
  if (vmax === vmin) vmax = vmin + 1;
  function X(f){ return pad + (hi === lo ? 0.5 : (f - lo) / (hi - lo)) * (W - 2 * pad); }
  function Y(val){ return H - pad - (val - vmin) / (vmax - vmin) * (H - 2 * pad - 14); }
  var g = svg("svg", {viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", role: "img",
    "aria-label": s.label + ", frames " + lo + " to " + hi});
  pts.forEach(function(p){
    if (p.state === "absent") {
      g.appendChild(svg("rect", {x: X(p.frame) - 2, y: pad, width: Math.max(4, (W - 2 * pad) / Math.max(1, hi - lo)),
        height: H - 2 * pad, fill: "var(--gap)", opacity: 0.25}));
    }
    if (p.state === "missing" || p.state === "not-applicable") {
      g.appendChild(svg("rect", {x: X(p.frame) - 2, y: H - pad - 10, width: 4, height: 10,
        fill: p.state === "missing" ? "var(--gap)" : "var(--line)"}));
    }
  });
  if (typeof s.limit === "number") {
    g.appendChild(svg("line", {x1: pad, x2: W - pad, y1: Y(s.limit), y2: Y(s.limit), stroke: "var(--limit)",
      "stroke-dasharray": "6 4", "stroke-width": 1.5}));
  }
  var d = "", pen = false;
  pts.forEach(function(p){
    if (typeof p.value !== "number") { pen = false; return; }
    d += (pen ? " L" : " M") + X(p.frame).toFixed(1) + " " + Y(p.value).toFixed(1); pen = true;
  });
  if (d) g.appendChild(svg("path", {d: d, fill: "none", stroke: "var(--ok)", "stroke-width": 1.5}));
  pts.forEach(function(p){
    if (p.state === "over") g.appendChild(svg("circle", {cx: X(p.frame), cy: Y(p.value), r: 3.5, fill: "var(--over)"}));
  });
  g.appendChild(svg("line", {x1: X(n), x2: X(n), y1: 0, y2: H, stroke: "var(--cursor)", "stroke-width": 2}));
  wrap.appendChild(g);
  g.style.cursor = "pointer";
  g.addEventListener("click", function(e){
    var r = g.getBoundingClientRect();
    var f = lo + Math.round((e.clientX - r.left) / r.width * (hi - lo));
    var all = framesOf(v), best = all[0];
    all.forEach(function(x){ if (Math.abs(x - f) < Math.abs(best - f)) best = x; });
    state.frame = best; draw();
  });
  var over = pts.filter(function(p){ return p.state === "over"; }).length;
  var miss = pts.filter(function(p){ return p.state === "missing"; }).length;
  var na = pts.filter(function(p){ return p.state === "not-applicable"; }).length;
  var absent = pts.filter(function(p){ return p.state === "absent"; }).length;
  var leg = "Frames " + lo + " to " + hi + ". " + (typeof s.limit === "number" ? "Dashed line: the tolerance, " + s.limit + s.unit + ". " : "") +
    over + " past the limit (red), " + miss + " with an object not found (grey marks), " + na + " not exercised: nothing to compare (light marks), " +
    absent + " not observed (grey bands and gaps in the line)." +
    (s.truncated ? " Only the first points are shown." : "") + " Blue line: the frame shown above.";
  wrap.appendChild(el("p", {"class": "legend"}, leg));
  if (s.coverage) wrap.appendChild(el("p", {"class": "legend"}, "Recorded coverage: " + s.coverage.status +
    "; observed " + s.coverage.framesObserved + " of " + s.coverage.framesExpected + " window frames."));
  return wrap;
}
function draw(){
  root.textContent = "";
  if (!shown.length) { root.appendChild(el("p", null, "There is nothing to inspect: no check has evidence in this folder.")); return; }
  var v = shown[state.i];
  var all = framesOf(v);
  if (all.length && all.indexOf(state.frame) < 0) {
    var best = all[0]; all.forEach(function(x){ if (Math.abs(x - state.frame) < Math.abs(best - state.frame)) best = x; });
    state.frame = best;
  }
  var title = el("h3", null, v.spec + " on " + v.route + ": " + v.comparison);
  root.appendChild(title);
  if (v.reason) root.appendChild(el("p", null, v.reason));
  var c = el("div", {"class": "controls"});
  function btn(text, label, fn){ var b = el("button", {type: "button", "aria-label": label}, text); b.addEventListener("click", fn); c.appendChild(b); return b; }
  btn("← Frame", "previous frame", function(){ step(-1); });
  var range = el("input", {type: "range", min: 0, max: Math.max(0, all.length - 1), value: Math.max(0, all.indexOf(state.frame)), "aria-label": "frame"});
  range.addEventListener("input", function(){ state.frame = all[Number(range.value)]; draw(); document.querySelector("#inspector input[type=range]").focus(); });
  c.appendChild(range);
  btn("Frame →", "next frame", function(){ step(1); });
  c.appendChild(el("span", {"aria-live": "polite"}, "Frame " + state.frame + (v.firstFrame === state.frame ? " (first failing frame)" : "")));
  var ov = btn(state.overlays ? "Hide overlays" : "Show overlays", "toggle overlays", function(){ state.overlays = !state.overlays; draw(); });
  ov.setAttribute("aria-pressed", String(state.overlays));
  if (v.visualSeries && (v.visualSeries.before || v.visualSeries.after)) {
    btn("Overlays: " + state.observer, "toggle measurement source", function(){
      state.observer = state.observer === "engine" ? "vision" : "engine"; draw();
    });
  }
  if (typeof v.firstFrame === "number") btn("First failure", "go to the first failing frame", function(){ state.frame = v.firstFrame; draw(); });
  root.appendChild(c);
  var framed = framedOf(v);
  if (framed.length) {
    var pair = el("div", {"class": "pair"});
    pair.appendChild(stage(v, "before", state.frame));
    pair.appendChild(stage(v, "after", state.frame));
    root.appendChild(pair);
    if (framed.indexOf(state.frame) < 0) root.appendChild(el("p", {"class": "muted"}, "Frames are kept for frames " + framed[0] + " to " + framed[framed.length - 1] + " around the first failure; this frame has measurements only."));
  } else {
    root.appendChild(el("p", {"class": "muted"}, "No frames were kept for this check."));
  }
  root.appendChild(timeline(v, "after", state.frame));
  root.appendChild(timeline(v, "before", state.frame));
  root.appendChild(timeline(v, "after", state.frame, true));
  root.appendChild(timeline(v, "before", state.frame, true));
  (v.notes || []).forEach(function(t){ root.appendChild(el("p", {"class": "muted"}, t)); });
  (v.visualNotes || []).forEach(function(t){ root.appendChild(el("p", {"class": "muted"}, t)); });
  document.querySelectorAll("[data-view]").forEach(function(b){ b.setAttribute("aria-pressed", String(Number(b.getAttribute("data-view")) === state.i)); });
}
function step(d){
  var all = framesOf(shown[state.i]); if (!all.length) return;
  var k = all.indexOf(state.frame); k = Math.min(all.length - 1, Math.max(0, (k < 0 ? 0 : k) + d));
  state.frame = all[k]; draw();
}
function pick(i){
  if (!shown.length) { draw(); return; }
  state.i = Math.max(0, Math.min(shown.length - 1, i));
  var v = shown[state.i];
  state.observer = ((v.observed || {}).after || {}).visual === "fail" ? "vision" : "engine";
  var all = framesOf(v);
  state.frame = typeof v.firstFrame === "number" ? v.firstFrame : (all[0] || 0);
  draw();
}
document.querySelectorAll("[data-view]").forEach(function(b){
  b.addEventListener("click", function(){
    var id = b.getAttribute("data-finding");
    for (var i = 0; i < shown.length; i++) if (shown[i].findingId === id) { pick(i); break; }
    root.scrollIntoView({block: "start"});
  });
});
document.addEventListener("keydown", function(e){
  if (!shown.length) return;
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  var t = e.target && e.target.tagName;
  if (t === "INPUT" && e.target.type !== "range") return;
  if (t === "TEXTAREA" || t === "SELECT") return;
  if (e.key === "ArrowRight") { step(e.shiftKey ? 5 : 1); e.preventDefault(); }
  else if (e.key === "ArrowLeft") { step(e.shiftKey ? -5 : -1); e.preventDefault(); }
  else if (e.key === "Home") { var a = framesOf(shown[state.i]); if (a.length) { state.frame = a[0]; draw(); } e.preventDefault(); }
  else if (e.key === "End") { var b = framesOf(shown[state.i]); if (b.length) { state.frame = b[b.length - 1]; draw(); } e.preventDefault(); }
  else if (e.key === "o" || e.key === "O") { state.overlays = !state.overlays; draw(); }
  else if (e.key === "n" || e.key === "j") { pick(state.i + 1); }
  else if (e.key === "p" || e.key === "k") { pick(state.i - 1); }
  else if (e.key === "f" || e.key === "F") { var v = shown[state.i]; if (typeof v.firstFrame === "number") { state.frame = v.firstFrame; draw(); } }
});
pick(0);
})();
"""


def _json_for_script(payload: dict) -> str:
    """JSON that cannot end its <script> element or open a comment inside it."""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    # JSON escapes preserve the exact image bytes while avoiding key-shaped
    # word boundaries in random base64. Ordinary evidence text stays scannable.
    text = re.sub(r'data:image/png;base64,[A-Za-z0-9+/=]+',
                  lambda m: m[0].replace('+', r'\u002b').replace('/', r'\u002f'), text)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _facts(payload: dict) -> list[tuple[str, str]]:
    record, job = payload["record"], payload["job"]
    facts = []
    if job:
        facts.append(("Job", f"{job['id']}: {job['phase']}"))
        facts.append(("Evidence grade", job.get("evidenceGrade") or "none (no evidence)"))
        if job.get("finishedAt"):
            facts.append(("Finished", job["finishedAt"]))
    if record:
        pr = record.get("pullRequest") or {}
        game = record["game"]
        facts += [
            ("Head", f"commit {pr.get('headSha') or 'unknown'}, game tree {(game.get('headTree') or 'unknown')[:16]}"),
            ("Base", f"commit {pr.get('baseSha') or 'not replayed'}, game tree {(game.get('baseTree') or 'not replayed')[:16]}"),
            ("Game", game["path"]),
            ("Policy", f"{len(record['specs'])} approved spec{'s' if len(record['specs']) != 1 else ''} from the "
                       f"{'base commit (the change cannot edit the checks that judge it)' if record['checksFrom'] == 'base' else 'head commit'}"
                       + (f"; policy digest {job['inputs']['policyDigest'][:16]}" if job and (job.get('inputs') or {}).get('policyDigest') else "")),
            ("Judged on", rec.observers_words(record)),
            ("Public checks", f"{record['counts']['checks']}: {record['counts']['passed']} pass, "
                              f"{record['counts']['failed']} fail, {record['counts']['needsReview']} need review"),
            ("Held-out routes", "not used" if record["heldOut"]["status"] == "not-used" else
             "could not be judged" if record["heldOut"]["status"] == "unavailable" else
             f"{record['heldOut']['routes']} routes, {record['heldOut']['checks']} checks: {record['heldOut']['passed']} pass, "
             f"{record['heldOut']['failed']} fail, {record['heldOut']['needsReview']} need review (counts only)"),
            ("Declared as", rec.repair_words(record)),
            ("Replays in the sandbox", rec.isolation_words(record.get("isolation"))),
            ("Expectrail", record["expectrail"]["version"]
             + (f" at {record['expectrail']['commit']}" if record["expectrail"].get("commit") else "")),
        ]
    return facts


def vision_words(record: dict | None, job: dict | None) -> str | None:
    """Say what did not run without changing the structured decision (including rejects)."""
    said = [((c.get("observed") or {}).get("after") or {}).get("visual")
            for c in (record or {}).get("checks", []) if c["after"] != "not-applicable"]
    if any(d.get("code") == "PROVIDER_FAILED" for d in (job or {}).get("diagnostics") or []):
        if any(s in rec.VISUAL_VERDICTS for s in said):
            return "Vision did not complete (PROVIDER_FAILED). Some recorded visual answers are available."
        if "no-answer" in said:
            return "Vision returned no usable answer (PROVIDER_FAILED). This is not a visual pass."
        return "Vision did not run (PROVIDER_FAILED) on the after-change checks. An engine failure still rejects."
    n = said.count("not-asked")
    if n:
        return f"Vision did not run on {n} after-change check{'s' if n != 1 else ''}. An engine failure still rejects."
    return None


def render(payload: dict) -> str:
    state = payload["state"]
    title, tone, means = STATES[state]
    record, job = payload["record"], payload["job"]
    parts = [
        "<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        f"<title>Expectrail evidence: {esc(title)}</title><style>{CSS}</style></head><body><main>",
        '<p class="muted">Expectrail evidence viewer</p>',
        f'<div class="banner {tone}" role="status" data-state="{esc(state)}"><h1>{esc(title)}</h1>'
        f"<p>{esc(means)}</p></div>",
    ]
    exported = payload.get("export")
    if exported is None:
        parts.append(f'<p class="muted"><a href="{EXPORT_NAME}" download>Download this evidence as one file</a> '
                     "(frames included; it opens offline).</p>")
    else:
        gone = exported.get("framesLeftOut") or {}
        note = (f"Offline copy: {exported.get('framesEmbedded', 0)} frames embedded in this file.")
        if gone:
            note += " Left out: " + "; ".join(f"{n} {why}" for why, n in gone.items()) + "."
        parts.append(f'<p class="muted" data-export="1">{esc(note)}</p>')
    if payload["reasons"]:
        parts.append("<h2>Why</h2><ul>" + "".join(f"<li>{esc(r)}</li>" for r in payload["reasons"]) + "</ul>")
    if job and job.get("diagnostics"):
        parts.append("<ul>" + "".join(f"<li><code>{esc(d.get('code'))}</code> ({esc(d.get('stage'))}): "
                                      f"{esc(d.get('detail'))} Fix: {esc(d.get('fix'))}</li>"
                                      for d in job["diagnostics"]) + "</ul>")
    vision = vision_words(record, job)
    if vision:
        parts.append(f'<h2>Vision</h2><p>{esc(vision)}</p>')
    findings = sorted((record or {}).get("findings") or [],
                      key=lambda f: (f["frame"] is None, f["frame"] or 0, f["id"]))
    if findings:
        parts.append("<h2>Findings, earliest first</h2><ul class=\"findings\">")
        for n, f in enumerate(findings):
            when = f"from frame {f['frame']}" if f["frame"] is not None else "no frame"
            parts.append(f'<li><button type="button" data-view="{n}" data-finding="{esc(f["id"])}">'
                         f'<code>{esc(f["id"])}</code> <b>{esc(f["spec"])}</b> on <b>{esc(f["route"])}</b>, {esc(when)}: '
                         f'{esc(f["comparison"])}. Before: {esc(WORD.get(f["before"], f["before"]))}; after: '
                         f'{esc(WORD.get(f["after"], f["after"]))}. {esc(f["reason"])}</button></li>')
        parts.append("</ul>")
    if record is not None:
        parts.append('<h2>Inspect</h2><p class="keys">Keys: <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step a frame '
                     "(<kbd>Shift</kbd> for five), <kbd>Home</kbd> <kbd>End</kbd>, <kbd>f</kbd> first failure, "
                     "<kbd>o</kbd> overlays on or off, <kbd>n</kbd> <kbd>p</kbd> next or previous finding.</p>"
                     '<section id="inspector" aria-label="frames and timeline"><noscript>The frame inspector needs '
                     "scripts; everything else on this page reads without them.</noscript></section>")
    facts = _facts(payload)
    if facts:
        parts.append('<h2>Run</h2><div class="scroll"><table class="facts">'
                     + "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in facts) + "</table></div>")
    parts.append("<h2>Not tested</h2><ul>" + "".join(f"<li>{esc(t)}</li>" for t in not_tested(record)) + "</ul>")
    if record and record["checks"]:
        parts.append('<h2>Every check</h2><div class="scroll"><table><tr><th>Spec</th><th>Route</th><th>Before</th>'
                     "<th>After</th><th>Comparison</th></tr>"
                     + "".join(f"<tr><td>{esc(c['spec'])}</td><td>{esc(c['route'])}</td>"
                               f"<td>{esc(WORD.get(c['before'], c['before']))}</td><td>{esc(WORD.get(c['after'], c['after']))}</td>"
                               f"<td>{esc(c['comparison'])}</td></tr>" for c in record["checks"])
                     + "</table></div>")
    parts.append("<h2>Reproduce</h2>")
    if payload["reproduce"]:
        words = ("Run this public sample with its recorded vision answers (no model call):" if payload.get("sample") else
                 "The same verification, run again from the same checkouts (the paths are the machine's that ran it):")
        parts.append(f"<p>{words}</p><pre>{esc(payload['reproduce'])}</pre>")
    else:
        parts.append("<p>No reproduction command: this folder was written without the job's request.</p>")
    parts.append("<p class=\"muted\">The decision on this page is the verifier's. The timeline is measured from the "
                 "same observations the evaluator judged and is shown only when it agrees with the evaluator; it "
                 "decides nothing. Held-out routes appear as counts only.</p>")
    parts.append(f'<script type="application/json" id="evidence">{_json_for_script(payload)}</script>')
    parts.append(f"<script>{SCRIPT}</script>")
    parts.append("</main></body></html>\n")
    return "\n".join(parts)
