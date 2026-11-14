"""Run Muse Spark Open (open weights, on a partner's endpoint) on public material and record it.

Three things, on public material only (the approved specs, the seeded bugs, the scripted playtest):

1. Models: which model ids the key can see on the endpoint (``GET /models``).
2. Specs: each approved spec in ``specs/`` is drafted again from its one-line instruction, and the
   draft, unedited, is compared with the approved spec. The ground draft is also judged as drafted
   on the seeded bugs' traces (position log against the ground line, the verifier's SAM-off ground
   check), next to the approved spec. With ``MODEL_API_KEY`` set, Muse Spark on Meta's API drafts
   the same specs, for comparison.
3. Feedback: the scripted playtest (``agents/fixtures/feedback/playtest-transcript.json``, written
   by the team) is sorted and its bug reports drafted into checks, as ``agents.feedback --sorter
   open`` does.

    python3 -m agents.spark_open models
    python3 -m agents.spark_open run --seeded runs/seeded-check --out runs/spark-open
    python3 -m agents.spark_open publish runs/spark-open/results.json   # GitHub annotations
    python3 -m agents.spark_open collect --run <id>                    # bench/spark-open/<id>/

The workflow is ``.github/workflows/spark-open.yml``. Nothing here is estimated: token counts are
what the endpoint reported, and a call that failed is recorded as failed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

from agents import feedback
from agents.observations import from_trace_synthetic, with_reference_ground
from harness.run import REPO
from expectrail import approval, spec_writer
from expectrail.contracts import load
from expectrail.evaluator import evaluate

FORMAT = "expectrail.spark-open-run/v0"
SPECS_DIR = REPO / "specs"
GROUND_SPEC = "player-stays-above-ground"
PLAYTEST = REPO / "agents" / "fixtures" / "feedback" / "playtest-transcript.json"
SEEDED = ("clean", "physics-fall-through_v1", "physics-fall-through_v2", "sinking_v1", "sinking_v2",
          "missing-texture_v1", "missing-texture_v2", "layering_v1", "layering_v2")
OUT_DIR = REPO / "bench" / "spark-open"
PAYLOAD_TITLE = "Spark Open results"
CHUNK = 2000
MAX_CHUNKS = 5


def open_base() -> str:
    return os.environ.get("EXPECTRAIL_OPEN_API_BASE", spec_writer.OPEN_API_BASE).rstrip("/")


def open_model() -> str:
    return os.environ.get("EXPECTRAIL_OPEN_MODEL") or spec_writer.OPEN_MODEL


def _one_line(err: BaseException | str, limit: int = 300) -> str:
    return " ".join(str(err).split())[:limit]


def list_models(base: str, key: str, timeout: int = 60) -> list[str]:
    """Model ids the endpoint lists for this key (OpenAI-compatible GET /models)."""
    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read())
    except urllib.error.HTTPError as err:
        raise spec_writer.SpecDraftError(f"HTTP {err.code}: {err.read().decode(errors='replace')[:300]}") from err
    return sorted(str(m.get("id")) for m in doc.get("data") or [] if isinstance(m, dict) and m.get("id"))


def counting(transport, calls: list[dict], who: str):
    """Wrap a transport to keep what the endpoint said it served and the tokens it reported."""
    def wrapped(body: dict) -> dict:
        try:
            resp = transport(body)
        except Exception as err:
            calls.append({"by": who, "requested": body.get("model"), "error": _one_line(err)})
            raise
        usage = resp.get("usage") if isinstance(resp, dict) else None
        calls.append({"by": who, "requested": body.get("model"),
                      "served": resp.get("model") if isinstance(resp, dict) else None,
                      "promptTokens": (usage or {}).get("prompt_tokens"),
                      "completionTokens": (usage or {}).get("completion_tokens")})
        return resp
    return wrapped


def approved_specs(specs_dir: Path = SPECS_DIR) -> list[dict]:
    specs = []
    for path in sorted(specs_dir.glob("*.json")):
        spec = load(path, "test-spec")
        if approval.approved(spec):  # an approval that does not match the spec's content is none (#420)
            specs.append(spec)
    return specs


def _window(spec: dict) -> str:
    w = spec.get("window")
    return f"{w.get('fromFrame')}-{w.get('toFrame')}" if isinstance(w, dict) else "all frames"


def shape(spec: dict) -> dict:
    """The parts of a spec a reviewer compares: assertion, objects and their prompts, tolerance, window."""
    a = spec.get("assertion") or {}
    b = a.get("boundary") or {}
    return {"assertion": a.get("type"), "object": a.get("object"),
            "boundary": ({"relativeTo": b.get("relativeTo"), "edge": b.get("edge"), "side": b.get("side")}
                         if b else None),
            "tolerancePx": b.get("tolerancePx", a.get("tolerancePx")),
            "objects": {name: (obj or {}).get("prompt") for name, obj in (spec.get("objects") or {}).items()},
            "window": _window(spec)}


def compare(draft: dict, approved: dict) -> dict:
    d, a = shape(draft), shape(approved)
    return {"sameAssertion": d["assertion"] == a["assertion"] and d["boundary"] == a["boundary"],
            "sameObjectNames": sorted(d["objects"]) == sorted(a["objects"]) and d["object"] == a["object"],
            "sameTolerance": d["tolerancePx"] == a["tolerancePx"],
            "sameWindow": d["window"] == a["window"],
            "samePrompts": d["objects"] == a["objects"]}


def judge(spec: dict, trace: dict, level: list) -> str:
    """The verifier's SAM-off ground check on one trace; an evaluator error is reported by kind."""
    try:
        return evaluate(spec, from_trace_synthetic(with_reference_ground(trace, level)))["result"]
    except Exception as err:  # noqa: BLE001 — a draft the evaluator cannot read is a finding, not a crash
        return f"error: {type(err).__name__}"


def draft_all(specs: list[dict], model: str, transport, who: str) -> list[dict]:
    rows = []
    for approved in specs:
        row: dict = {"spec": approved["id"], "instruction": approved["instruction"], "by": who, "model": model}
        try:
            draft, problems = spec_writer.draft(approved["instruction"], spec_id=approved["id"], model=model,
                                                transport=transport)
        except Exception as err:  # noqa: BLE001
            draft, problems = None, [_one_line(err)]
        row.update(valid=draft is not None, problems=problems, draft=draft,
                   shape=shape(draft) if draft else None, approvedShape=shape(approved),
                   compare=compare(draft, approved) if draft else None)
        rows.append(row)
    return rows


def judge_ground(rows: list[dict], specs: list[dict], seeded: Path) -> list[dict]:
    clean = json.loads((seeded / "clean" / "trace.json").read_text(encoding="utf-8"))
    level = clean["levelSurfaces"]
    approved = next(s for s in specs if s["id"] == GROUND_SPEC)
    drafts = {r["by"]: r["draft"] for r in rows if r["spec"] == GROUND_SPEC}
    out = []
    for name in SEEDED:
        path = seeded / name / "trace.json"
        if not path.exists():
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        verdicts = {"approved": judge(approved, trace, level)}
        for who, draft in drafts.items():
            verdicts[who] = judge(draft, trace, level) if draft else "no draft"
        out.append({"run": name, **verdicts})
    return out


def sort_playtest(model: str, transport, host: str, out: Path) -> dict:
    resp = json.loads(PLAYTEST.read_text(encoding="utf-8"))
    turns = feedback.turns_from_response(resp)
    source = {"kind": "transcript", "file": PLAYTEST.name, "sha256": feedback.sha256_file(PLAYTEST),
              "durationMs": resp.get("audioDurationMs"), "consent": True,
              "transcriber": {"provenance": "fixture", "model": None, "mode": "DIARIZATION",
                              "sessionId": resp.get("sessionId"), "keywords": feedback.game_keywords()}}
    doc = feedback.intake(turns, out=out, intake_id="fb-playtest-spark-open", source=source, transport=transport,
                          classifier_label="model", model=model, endpoint=host)
    items = []
    for item in doc["items"]:
        draft = None
        if item.get("draft"):
            spec = json.loads((out / item["draft"]["path"]).read_text(encoding="utf-8"))
            draft = {"instruction": spec["instruction"], "shape": shape(spec)}
        items.append({k: item.get(k) for k in ("turn", "speaker", "text", "category", "decidedBy", "route",
                                                 "instruction", "draftProblems")} | {"draft": draft})
    return {"classifier": doc["classifier"], "items": items, "counts": doc["counts"]}


def run(seeded: Path | None, out: Path, meta: bool, key: str) -> dict:
    base, model = open_base(), open_model()
    host = feedback.host_of(base)
    calls: list[dict] = []
    doc: dict = {"format": FORMAT, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "endpoint": host, "model": model, "calls": calls}
    try:
        ids = list_models(base, key)
        doc["models"] = {"listed": len(ids), "muse": [i for i in ids if "muse" in i.lower() or "spark" in i.lower()],
                         "modelListed": model in ids}
    except Exception as err:  # noqa: BLE001 — some endpoints do not list; the calls below still say what served
        doc["models"] = {"error": _one_line(err)}
    specs = approved_specs()
    open_t = counting(spec_writer.open_transport(base, key), calls, "spark-open")
    rows = draft_all(specs, model, open_t, "spark-open")
    if meta and os.environ.get("MODEL_API_KEY"):
        rows += draft_all(specs, spec_writer.DEFAULT_MODEL,
                          counting(spec_writer.http_transport, calls, "muse-spark"), "muse-spark")
    doc["specs"] = rows
    doc["ground"] = judge_ground(rows, specs, seeded) if seeded else []
    fb_t = counting(feedback.openai_transport(base, key), calls, "spark-open")
    doc["feedback"] = sort_playtest(model, fb_t, host, out / "feedback")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- annotations

def summary_lines(doc: dict) -> list[tuple[str, str]]:
    m = doc.get("models") or {}
    lines = [("Spark Open models", (f"error {m['error']}" if "error" in m else
              f"{m['listed']} listed; Muse/Spark ids: {', '.join(m['muse']) or 'none'}; "
              f"{doc['model']} {'listed' if m['modelListed'] else 'not listed'}"))]
    for who in ("spark-open", "muse-spark"):
        rows = [r for r in doc["specs"] if r["by"] == who]
        if not rows:
            continue
        parts = []
        for r in rows:
            if not r["valid"]:
                parts.append(f"{r['spec']} needs review ({'; '.join(r['problems'])[:200]})")
                continue
            c, s = r["compare"], r["shape"]
            parts.append(f"{r['spec']} valid; assertion {'same' if c['sameAssertion'] else _assertion(s)}; "
                         f"names {'same' if c['sameObjectNames'] else s['objects']}; "
                         f"tolerance {s['tolerancePx']} vs {r['approvedShape']['tolerancePx']}; "
                         f"window {s['window']} vs {r['approvedShape']['window']}")
        lines.append((f"Specs drafted by {who} ({rows[0]['model']})", " | ".join(parts)))
    if doc.get("ground"):
        lines.append(("Ground draft on the seeded bugs", "; ".join(
            f"{g['run']}: " + ", ".join(f"{k} {v}" for k, v in g.items() if k != "run") for g in doc["ground"])))
    fb = doc["feedback"]
    weaken = [i for i in fb["items"] if i["category"] == "weaken-check"]
    lines.append(("Playtest sorted by spark-open", (
        f"classifier {fb['classifier']['provenance']}"
        + (f" (error {fb['classifier']['error']})" if fb["classifier"].get("error") else "") + "; "
        + "; ".join(f"{i['turn']} {i['category']} by {'+'.join(i['decidedBy'])} -> {i['route']}" for i in fb["items"])
        + f"; weaken-check to human-queue {sum(i['route'] == 'human-queue' for i in weaken)} of {len(weaken)}")))
    tok = {}
    for c in doc["calls"]:
        t = tok.setdefault(c["by"], {"calls": 0, "errors": 0, "in": 0, "out": 0, "served": set()})
        t["calls"] += 1
        if "error" in c:
            t["errors"] += 1
            continue
        t["in"] += c.get("promptTokens") or 0
        t["out"] += c.get("completionTokens") or 0
        if c.get("served"):
            t["served"].add(c["served"])
    lines.append(("Calls", "; ".join(f"{who}: {t['calls']} calls, {t['errors']} errors, {t['in']} tokens in, "
                                       f"{t['out']} out, served by {', '.join(sorted(t['served'])) or 'not said'}"
                                       for who, t in tok.items())))
    return lines


def payload_chunks(doc: dict) -> list[str]:
    raw = base64.b64encode(zlib.compress(json.dumps(doc, separators=(",", ":")).encode(), 9)).decode()
    return [raw[i:i + CHUNK] for i in range(0, len(raw), CHUNK)]


def unpack(chunks: list[str]) -> dict:
    return json.loads(zlib.decompress(base64.b64decode("".join(chunks))))


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def publish(doc: dict, write=print) -> None:
    for title, message in summary_lines(doc):
        write(f"::notice title={_escape(title).replace(',', '%2C').replace(':', '%3A')}::{_escape(message)}")
    chunks = payload_chunks(doc)
    if len(chunks) > MAX_CHUNKS:
        write(f"::warning::results too large for annotations ({len(chunks)} chunks); see the artifact")
        return
    for i, chunk in enumerate(chunks, 1):
        write(f"::notice title={PAYLOAD_TITLE} {i}/{len(chunks)}::{chunk}")


# ---------------------------------------------------------------- collect

def collect(run_id: int, fetch=None) -> dict:
    from agents.bench_collect import gh_json, run_annotations
    run_doc, notes = run_annotations(run_id, fetch=fetch or gh_json, prefix="spark-open")
    parts: dict[int, str] = {}
    total = None
    for note in notes:
        title = note.get("title") or ""
        if title.startswith(PAYLOAD_TITLE + " "):
            i, n = title[len(PAYLOAD_TITLE) + 1:].split("/")
            parts[int(i)], total = note["message"], int(n)
    if not total or sorted(parts) != list(range(1, total + 1)):
        raise SystemExit(f"run {run_id}: results annotations missing ({sorted(parts)} of {total})")
    doc = unpack([parts[i] for i in range(1, total + 1)])
    doc["run"] = run_id
    doc["runUrl"] = run_doc.get("html_url")
    doc["commit"] = run_doc.get("head_sha")
    return doc


def _px(value) -> str:
    return "none" if value is None else f"{value} px"


def _assertion(shape_: dict) -> str:
    b = shape_.get("boundary")
    return shape_["assertion"] + (f", {b['side']} the {b['relativeTo']}'s {b['edge']} edge" if b else "")


def _cell(value) -> str:
    return str(value).replace("|", "\\|")


def markdown(doc: dict) -> str:
    m = doc.get("models") or {}
    lines = ["# Muse Spark Open, live", "",
             "Written by `python3 -m agents.spark_open collect --run <id>` from the run's own annotations; do not "
             "edit by hand.",
             f"Run [{doc['run']}]({doc['runUrl']}), {doc['at'][:10]}, commit {str(doc['commit'])[:7]}. "
             f"Endpoint {doc['endpoint']}, model `{doc['model']}`.", ""]
    if "error" in m:
        lines += [f"Listing models failed: {m['error']}.", ""]
    else:
        lines += [f"The key lists {m['listed']} models; Muse or Spark ids: "
                  f"{', '.join(f'`{i}`' for i in m['muse']) or 'none'}.", ""]
    lines += ["## The approved checks, drafted again from one line", "",
              "Each approved spec in `specs/` drafted from its instruction alone, and compared with the approved "
              "spec, unedited.", "",
              "| Check | Drafted by | Valid | Assertion as approved | Object names as approved | Prompts | "
              "Tolerance (draft / approved) | Window (draft / approved) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in doc["specs"]:
        if not r["valid"]:
            lines.append(f"| {r['spec']} | {r['by']} | no: {_cell('; '.join(r['problems'])[:160])} | | | | | |")
            continue
        c, s, a = r["compare"], r["shape"], r["approvedShape"]
        prompts = ", ".join(f"{k}: \"{v}\"" for k, v in s["objects"].items())
        lines.append(f"| {r['spec']} | {r['by']} | yes | {'yes' if c['sameAssertion'] else 'no: ' + _assertion(s)} | "
                     f"{'yes' if c['sameObjectNames'] else 'no'} | {_cell(prompts)} | "
                     f"{_px(s['tolerancePx'])} / {_px(a['tolerancePx'])} | {s['window']} / {a['window']} |")
    approved_prompts = {}
    for r in doc["specs"]:
        approved_prompts.setdefault(r["spec"], r["approvedShape"]["objects"])
    lines += ["", "Approved prompts: " + "; ".join(
        f"{k}: " + ", ".join(f"{n} \"{p}\"" for n, p in v.items()) for k, v in approved_prompts.items()) + ".", ""]
    if doc.get("ground"):
        whos = [k for k in doc["ground"][0] if k != "run"]
        lines += ["## The ground draft, as drafted, on the seeded bugs", "",
                  "Judged the way the verifier judges the ground with SAM off: the engine's position log against "
                  "the ground line, on the smoke route. The position log names its objects `player` and `ground`, "
                  "so a draft that names them otherwise is needs-review here, where SAM would find them by prompt.",
                  "",
                  "| Seeded run | " + " | ".join(whos) + " |", "| --- |" + " --- |" * len(whos)]
        for g in doc["ground"]:
            lines.append(f"| {g['run']} | " + " | ".join(str(g[w]) for w in whos) + " |")
        lines.append("")
    fb = doc["feedback"]
    lines += ["## The scripted playtest, sorted", "",
              f"Classifier: {fb['classifier']['provenance']}"
              + (f", model `{fb['classifier']['model']}`" if fb["classifier"].get("model") else "")
              + (f", error: {fb['classifier']['error']}" if fb["classifier"].get("error") else "")
              + ". The fixed phrase rules always run too; \"decided by\" says which side decided.", "",
              "| Turn | Remark | Category | Decided by | Route | Check drafted |", "| --- | --- | --- | --- | --- | --- |"]
    for i in fb["items"]:
        drafted = (f"\"{i['draft']['instruction']}\"" if i.get("draft")
                   else ("; ".join(i.get("draftProblems") or []) or ""))
        lines.append(f"| {i['turn']} | {_cell(i['text'])} | {i['category']} | {'+'.join(i['decidedBy'])} | "
                     f"{i['route']} | {_cell(drafted)} |")
    lines += ["", "## Calls", "", "| By | Requested | Served | Tokens in | Tokens out | Error |",
              "| --- | --- | --- | --- | --- | --- |"]
    for c in doc["calls"]:
        lines.append(f"| {c['by']} | {c.get('requested')} | {c.get('served') or ''} | {c.get('promptTokens') or ''} | "
                     f"{c.get('completionTokens') or ''} | {_cell(c.get('error') or '')} |")
    return "\n".join(lines) + "\n"


def write(doc: dict, out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(markdown(doc), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models", help="list the model ids the key can see")
    r = sub.add_parser("run", help="draft the approved specs, judge the ground draft, sort the playtest")
    r.add_argument("--seeded", type=Path, help="harness.check_seeded output, for the ground verdicts")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--no-meta", action="store_true", help="skip the Muse Spark (Meta API) comparison")
    pub = sub.add_parser("publish", help="print GitHub annotations for a results.json")
    pub.add_argument("results", type=Path)
    c = sub.add_parser("collect", help="write bench/spark-open/ from a run's annotations")
    c.add_argument("--run", type=int, required=True)
    c.add_argument("--out", type=Path, help="default bench/spark-open/<run>")
    args = p.parse_args(argv)

    if args.cmd in ("models", "run"):
        key = next((os.environ[n] for n in spec_writer.OPEN_KEY_ENVS if os.environ.get(n)), None)
        if not key:
            print(f"error: set one of {', '.join(spec_writer.OPEN_KEY_ENVS)}", file=sys.stderr)
            return 1
        if args.cmd == "models":
            try:
                ids = list_models(open_base(), key)
            except spec_writer.SpecDraftError as err:
                print(f"error: {err}", file=sys.stderr)
                return 1
            print("\n".join(ids))
            model = open_model()
            print(f"{model}: {'listed' if model in ids else 'NOT listed'} ({len(ids)} models)", file=sys.stderr)
            return 0
        doc = run(args.seeded, args.out, meta=not args.no_meta, key=key)
        for title, message in summary_lines(doc):
            print(f"{title}: {message}")
        return 0
    if args.cmd == "publish":
        publish(json.loads(args.results.read_text(encoding="utf-8")))
        return 0
    doc = collect(args.run)
    args.out = args.out or OUT_DIR / str(args.run)
    write(doc, args.out)
    print(f"wrote {args.out / 'results.json'} and {args.out / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
