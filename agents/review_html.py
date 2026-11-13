"""Render a review (change-evidence.json) as one self-contained HTML page.

    python3 -m agents.review_html runs/review/change-evidence.json [--out folder]

The page opens from disk with no server and no network: no scripts, no external fonts or styles.
Every string from the record is escaped and key-like strings are redacted. Frames are shown only
when the file's SHA256 still matches the record; a missing or changed frame is said to be missing,
never replaced by another image. Private routes appear as counts only. The review's status comes
first and the verifier's decision is shown on its own: neither overrides the other.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import shutil
import sys
from pathlib import Path

from expectrail.change_evidence import load_record, pre_repair_rule
from expectrail.diagnostics import redact

STATUS_TONE = {"REPAIR DEMONSTRATED": "good", "REJECTED": "bad", "NO REPAIR DEMONSTRATED": "warn",
               "INCONCLUSIVE": "warn"}
STATUS_MEANS = {
    "REPAIR DEMONSTRATED": "A requested check failed on the game before the change and passes after it, "
                           "three times of three on each side, every required check passes, and the verifier accepted.",
    "REJECTED": "The change fails a required check, or the verifier rejected it.",
    "NO REPAIR DEMONSTRATED": "Every check passes after the change, but no requested check was failing "
                              "before it, so nothing here shows a repair.",
    "INCONCLUSIVE": "Some evidence is missing or could not be compared, so no repair is claimed.",
}
LABEL_MEANS = {
    "SAMPLE": "recorded observations, not new replays",
    "FRESH LIVE": "both runs replayed now, with the private routes",
    "RECORDED LIVE": "an archived live run",
    "MIXED OR INCOMPLETE": "some evidence is missing, a fallback, or from different sources",
}
ORIGIN = {"muse": "Muse Code", "fixture": "a fixture patch", "developer": "a developer"}
COMPARISON_TONE = {"REPAIRED": "good", "PRESERVED": "quiet", "REGRESSION": "bad", "UNRESOLVED": "bad",
                   "INCONCLUSIVE": "warn"}


def esc(value) -> str:
    """Escape for HTML text and attributes, after redacting key-like strings."""
    return html.escape(redact("" if value is None else str(value)), quote=True)


def _word(result: str | None) -> str:
    return {"pass": "pass", "fail": "fail", "needs-review": "needs review"}.get(result or "", "missing")


def _short(sha: str | None) -> str:
    return sha[:12] if sha else "none"


def _frame(arm_name: str, arm: dict | None, run_id: str, src_dir: Path, out: Path) -> tuple[str, str | None]:
    """(figure html, warning or None). Copies the frame into out/assets when out is elsewhere."""
    title = "Before the change" if arm_name == "base" else "After the change"
    frame = (arm or {}).get("frame")
    if not frame:
        note = ("No frame: this arm was not replayed" if arm is None
                else "No frame: a sample review runs on recorded observations" if arm.get("replaySha256") is None
                else "No frame was recorded for this arm")
        return (f'<figure class="frame missing"><figcaption><b>{title}</b></figcaption>'
                f'<div class="hole">{esc(note)}</div></figure>'), None
    src = src_dir / frame["path"]
    if not src.is_file():
        return (f'<figure class="frame missing"><figcaption><b>{title}</b></figcaption>'
                f'<div class="hole">Frame {esc(frame["frame"])} is missing from the review folder</div></figure>'), \
            f"the {arm_name} frame file is missing"
    if hashlib.sha256(src.read_bytes()).hexdigest() != frame["sha256"]:
        return (f'<figure class="frame missing"><figcaption><b>{title}</b></figcaption>'
                f'<div class="hole">Frame {esc(frame["frame"])} changed after it was recorded, so it is not shown'
                f'</div></figure>'), f"the {arm_name} frame does not match its recorded SHA256"
    if out.resolve() != src_dir.resolve():
        (out / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / frame["path"])
    caption = (f'<b>{title}</b><span>run {esc(run_id)}, {"failing base" if arm_name == "base" else "candidate"}, '
               f'frame {esc(frame["frame"])}, replay {esc(_short(arm.get("replaySha256")))}</span>')
    return (f'<figure class="frame"><img src="{esc(frame["path"])}" alt="{esc(title)}, frame {esc(frame["frame"])}">'
            f'<figcaption>{caption}</figcaption></figure>'), None


def _runs_line(record: dict) -> str:
    """How many times each claimed repair was replayed, from the record's ``repair`` block (#284)."""
    if pre_repair_rule(record):
        return ("This review was recorded before reviews replayed a claimed repair: each check was judged once "
                "on each side, which the gate's rule today does not count as a demonstration.")
    repair = record["repair"]
    if not repair["rows"]:
        return "No requested check went from failing to passing, so nothing was replayed again."
    parts = [f'<code>{esc(r["spec"])}</code> before {esc(", ".join(_word(x) for x in r["base"]))}; '
             f'after {esc(", ".join(_word(x) for x in r["head"]))}: '
             f'{"counts" if r["counts"] else "does not count"}' for r in repair["rows"]]
    return (f'A claimed repair counts only when the check fails before the change and passes after it '
            f'{repair["runs"]} times of {repair["runs"]}. ' + "; ".join(parts) + ".")


def build(record: dict, src_dir: Path, out: Path, recorded: str | None = None) -> str:
    status, label = record["status"], record["evidenceLabel"]
    as_written = label
    if recorded and label == "FRESH LIVE":
        label = "RECORDED LIVE"  # fresh when it ran; shown again later, it is a recorded live run
    reasons = record.get("reasons") or []
    verification = record.get("verification")
    warnings: list[str] = []

    rows = []
    for r in record["rows"]:
        tone = COMPARISON_TONE.get(r["comparison"], "quiet")
        mismatch = f'<div class="small">judged differently: {esc(", ".join(r["mismatch"]))}</div>' if r.get("mismatch") else ""
        rows.append(
            f'<tr><td><code>{esc(r["spec"])}</code>{mismatch}</td>'
            f'<td>{"requested" if r["primary"] else "guard"}</td>'
            f'<td class="r-{esc(r["before"] or "missing")}">{_word(r["before"])}</td>'
            f'<td class="r-{esc(r["after"] or "missing")}">{_word(r["after"])}</td>'
            f'<td><span class="pill {tone}">{esc(r["comparison"])}</span></td></tr>')
    table = ("".join(rows) if rows
             else '<tr><td colspan="5" class="small">No checks were paired: an arm did not finish.</td></tr>')

    figures = []
    for arm_name in ("base", "candidate"):
        fig, warning = _frame(arm_name, record["arms"].get(arm_name), record["runId"], src_dir, out)
        figures.append(fig)
        if warning:
            warnings.append(warning)

    runs_line = _runs_line(record)

    private = record["private"]
    private_line = (f'{private["checks"]} check{"s" if private["checks"] != 1 else ""} on the private routes: '
                    f'{private["passed"]} passed, {private["failed"]} failed, {private["needsReview"]} need review '
                    f'(source: {esc(private["source"] or "none")}). Route names and frames stay private.')

    stages = "".join(
        f'<li><b>{esc(s["stage"])}</b> {esc(s["status"])}'
        + (f', {esc(s["reason"])}' if s.get("reason") else "")
        + (", reused the verification" if s.get("reused") else "") + "</li>"
        for s in record["stages"])
    diagnostics = "".join(
        f'<li><b>{esc(d["code"])}</b> in {esc(d["stage"])}: {esc(d["detail"])}<div class="small">'
        f'What to do: {esc(d["fix"])}</div></li>' for d in record["diagnostics"]) or "<li>None</li>"
    warning_html = "".join(f'<p class="warning">{esc(w)}</p>' for w in warnings)
    reason_html = (f'<p class="reason">{esc(reasons[0])}</p>' if reasons else "")
    more_reasons = "".join(f"<li>{esc(r)}</li>" for r in reasons[1:])
    decision = verification["decision"] if verification else "not reached"
    arms = record["arms"]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Expectrail review</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1b; --quiet:#6b6a64; --line:#e3e0d8; --card:#ffffff;
  --good:#1f7a4d; --good-bg:#e5f4e4; --bad:#b3261e; --bad-bg:#fbebeb; --warn:#8a5a00; --warn-bg:#f9eeda; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --fg:#ecebe6; --quiet:#a3a19a; --line:#34332f;
  --card:#1e1e1b; --good:#7fd1a2; --good-bg:#16301f; --bad:#f2a49e; --bad-bg:#3a1a18; --warn:#f0c470; --warn-bg:#352a12; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:15px; font-weight:600; color:var(--quiet); margin:0 0 8px; letter-spacing:.02em; }}
h2 {{ font-size:16px; margin:32px 0 8px; }}
.status {{ font-size:30px; font-weight:700; margin:0; }}
.status.good {{ color:var(--good); }} .status.bad {{ color:var(--bad); }} .status.warn {{ color:var(--warn); }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }}
.chip {{ border:1px solid var(--line); border-radius:999px; padding:2px 10px; font-size:13px; background:var(--card); }}
.reason {{ font-size:16px; margin:8px 0; }}
.small {{ font-size:13px; color:var(--quiet); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ text-align:left; padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--quiet); font-weight:600; }}
td code {{ overflow-wrap:normal; word-break:normal; }}
.r-fail {{ color:var(--bad); }} .r-pass {{ color:var(--good); }}
@media (max-width:520px) {{ th, td {{ padding:6px 4px; }} .card {{ padding:12px; }} .status {{ font-size:24px; }}
  table {{ font-size:13px; }} }}
.pill {{ border-radius:6px; padding:1px 8px; font-size:12px; font-weight:600; white-space:nowrap; }}
.pill.good {{ background:var(--good-bg); color:var(--good); }} .pill.bad {{ background:var(--bad-bg); color:var(--bad); }}
.pill.warn {{ background:var(--warn-bg); color:var(--warn); }} .pill.quiet {{ color:var(--quiet); border:1px solid var(--line); }}
.frames {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
.frame {{ margin:0; }} .frame img {{ width:100%; border-radius:8px; border:1px solid var(--line); image-rendering:pixelated; }}
.frame figcaption {{ display:flex; flex-direction:column; font-size:13px; margin-top:6px; }}
.frame figcaption span {{ color:var(--quiet); }}
.hole {{ aspect-ratio:16/9; display:flex; align-items:center; justify-content:center; text-align:center; padding:16px;
  border:1px dashed var(--line); border-radius:8px; color:var(--quiet); font-size:14px; }}
.warning {{ background:var(--warn-bg); color:var(--warn); border-radius:8px; padding:8px 12px; }}
code {{ font:13px ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }}
ul {{ padding-left:20px; }} li {{ margin:4px 0; }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; font-size:13px; margin:0; }}
dt {{ color:var(--quiet); }} dd {{ margin:0; overflow-wrap:anywhere; }}
.table-wrap {{ overflow-x:auto; }}
</style></head>
<body><main>
<h1>Expectrail review: the same checks before and after a change</h1>
<p class="status {STATUS_TONE.get(status, 'warn')}">{esc(status)}</p>
<p>{esc(STATUS_MEANS.get(status, ""))}</p>
{reason_html}
<div class="meta">
<span class="chip">Evidence: {esc(label)}, {esc(LABEL_MEANS.get(label, ""))}{f" (the run labelled it {esc(as_written)})" if label != as_written else ""}</span>
<span class="chip">Candidate from {esc(ORIGIN.get(record["candidate"]["origin"], record["candidate"]["origin"]))}</span>
<span class="chip">Verifier decision: {esc(decision)}</span>
</div>
{f'<p class="warning">Recorded evidence: {esc(recorded)}. This page shows that run as it wrote its record; nothing was run again.</p>' if recorded else ""}
{warning_html}
{f"<ul>{more_reasons}</ul>" if more_reasons else ""}

<h2>Each check, before and after the change</h2>
<div class="card table-wrap"><table>
<thead><tr><th>Check</th><th>Role</th><th>Before</th><th>After</th><th>Result</th></tr></thead>
<tbody>{table}</tbody></table>
<p class="small">{runs_line}</p>
<p class="small">Before is the game with the reported bug and no fix; after is the same game with the candidate.
A requested check is one the repair request names as failing; only those can show a repair.
Guards must pass after the change. The verifier also checked the clean game, separately.</p></div>

<h2>The first failing frame, before and after</h2>
<div class="frames">{"".join(figures)}</div>

<h2>Private routes</h2>
<p>{private_line}</p>

<h2>How the review ran</h2>
<div class="card"><ul>{stages}</ul></div>

<h2>Diagnostics</h2>
<ul>{diagnostics}</ul>

<h2>Identities</h2>
<div class="card"><dl>
<dt>Review run</dt><dd><code>{esc(record["runId"])}</code> ({esc(record["mode"])} mode)</dd>
<dt>Repair request</dt><dd><code>{esc(record["request"]["id"])}</code>, SHA256 <code>{esc(record["request"]["sha256"])}</code></dd>
<dt>Candidate patch</dt><dd><code>{esc(record["candidate"]["patchSha256"] or "none")}</code></dd>
<dt>Verification file</dt><dd><code>{esc((verification or {}).get("fileSha256") or "none")}</code></dd>
<dt>Failing base</dt><dd>{esc((arms.get("base") or {}).get("provenance") or "not run")}, observed by {esc((arms.get("base") or {}).get("observationBackend") or "nothing")}, replay <code>{esc(_short((arms.get("base") or {}).get("replaySha256")))}</code></dd>
<dt>Candidate</dt><dd>{esc((arms.get("candidate") or {}).get("provenance") or "not run")}, observed by {esc((arms.get("candidate") or {}).get("observationBackend") or "nothing")}, replay <code>{esc(_short((arms.get("candidate") or {}).get("replaySha256")))}</code></dd>
<dt>Run it again</dt><dd><code>{esc(record["rerun"])}</code></dd>
</dl></div>

<p class="small">This page shows evidence for these checks on this route. It is not proof that the game is correct,
and no status here approves a merge or a release. Generated from change-evidence.json.</p>
</main></body></html>
"""


def render(record_path: Path, out: Path, *, recorded: str | None = None, name: str = "review.html") -> Path:
    """Write out/<name> from a change-evidence record; returns its path. ``recorded`` names the run
    a republished record came from: the page says so and shows a fresh live label as recorded."""
    record_path = Path(record_path)
    record = load_record(record_path)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / name
    target.write_text(build(record, record_path.parent, out, recorded), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("record", type=Path, help="a change-evidence.json")
    p.add_argument("--out", type=Path, help="folder for review.html (default: the record's folder)")
    p.add_argument("--recorded", help="the run a republished record came from, e.g. 'fix matrix run 123, demo run 1'")
    p.add_argument("--name", default="review.html", help="the page's file name")
    args = p.parse_args(argv)
    print(render(args.record, args.out or args.record.parent, recorded=args.recorded, name=args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
