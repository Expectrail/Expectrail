"""The CI gate's review page: one self-contained HTML file in the evidence artifact.

The page opens from disk with no server and no network: no scripts, no external fonts or styles.
Every string is escaped and key-like strings are redacted. A frame is copied in only from the
replay that made it, with its SHA256 printed beside it. Held-out routes appear as counts only.
The words for each comparison are the review's (docs/review.md).
"""
from __future__ import annotations

import hashlib
import html
import shutil
from pathlib import Path

from expectrail.diagnostics import redact
from expectrail.gate import record as rec

REVIEW_DOC = "https://github.com/Expectrail/Expectrail/blob/main/docs/review.md"
GATE_DOC = "https://github.com/Expectrail/Expectrail/blob/main/docs/ci-gate.md"
MAX_FRAMED_FINDINGS = 20
DECISION_MEANS = {
    "accept": "Every approved check passes on every route after this change. Accepted means this change "
              "passed these checks on these routes, not that the game is correct.",
    "reject": "At least one check fails after this change.",
    "needs-review": "Some evidence is missing or could not be decided, so the gate does not accept. A person "
                    "should look.",
}
ADAPTER = {"godot": "Godot"}
WORD = {"pass": "pass", "fail": "fail", "needs-review": "needs review", "replay-error": "replay error",
        None: "not run"}
TONE = {"accept": "good", "reject": "bad", "needs-review": "warn", "REPAIRED": "good", "PRESERVED": "quiet",
        "REGRESSION": "bad", "UNRESOLVED": "bad", "INCONCLUSIVE": "warn"}
CSS = """
body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:#14161a;background:#fafaf7}
main{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:18px;margin:28px 0 8px}
.badge{display:inline-block;padding:2px 10px;border-radius:4px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.good{background:#dff3e4;color:#14532d}.bad{background:#fde2e1;color:#7f1d1d}.warn{background:#fdf1d6;color:#78350f}
.quiet{background:#eceee9;color:#3f4540}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #dcdcd5;padding:6px 8px;text-align:left;vertical-align:top}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
.frames{display:flex;gap:14px;flex-wrap:wrap}figure{margin:0;flex:1 1 320px}figure img{width:100%;border:1px solid #c9c9c0}
figcaption{font-size:13px;color:#4b5049}.hole{padding:40px 12px;border:1px dashed #b9b9b0;color:#4b5049;text-align:center}
.meta td:first-child{width:220px;color:#4b5049}
"""



def esc(value) -> str:
    return html.escape(redact("" if value is None else str(value)), quote=True)


def _badge(word: str) -> str:
    return f'<span class="badge {TONE.get(word, "quiet")}">{esc(word)}</span>'


def _copy_frame(frames_dir: Path | None, index: int | None, assets: Path, name: str) -> dict | None:
    if frames_dir is None or index is None:
        return None
    src = Path(frames_dir) / f"f{int(index):08d}.png"
    if not src.is_file() or src.is_symlink():
        return None
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / f"{name}.png"
    shutil.copyfile(src, target)
    return {"path": f"assets/{target.name}", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "frame": int(index)}


def _figure(title: str, frame: dict | None, missing: str) -> str:
    if frame is None:
        return f'<figure><figcaption><b>{esc(title)}</b></figcaption><div class="hole">{esc(missing)}</div></figure>'
    return (f'<figure><img src="{esc(frame["path"])}" alt="{esc(title)}, frame {esc(frame["frame"])}">'
            f'<figcaption><b>{esc(title)}</b>, frame {esc(frame["frame"])}, sha256 '
            f'<code>{esc(frame["sha256"][:16])}</code></figcaption></figure>')


def _generated_section(gen: dict | None) -> list[str]:
    """Generated checks (docs/jit.md): advisory, shown apart from the checks that decide."""
    if not gen or gen["status"] == "not-run":
        return []
    out = ["<h2>Generated checks (advisory)</h2>",
           "<p>Checks generated for this change from its bug report and patch. They never accept or reject: "
           "the decision above comes from the approved checks alone. A check is valid when it passed on the "
           "clean game 3 of 3 times and failed 3 of 3 on a near-miss version of this change; it catches when "
           "it also fails 3 of 3 on this change. A strong catch also fails on the build the bug report "
           "describes.</p>"]
    if gen["status"] == "nothing-generated":
        out.append(f"<p>No generated checks: {esc(gen['reason'] or '')}</p>")
        return out
    out.append(f"<p>{gen['proposed']} proposed, {gen['valid']} valid, {gen['strong']} strong and "
               f"{gen['weak']} weak catches.</p>")
    if gen["catches"]:
        out.append("<table><tr><th>Generated check</th><th>Strength</th><th>Says</th></tr>"
                   + "".join(f"<tr><td><code>{esc(c['specId'])}</code></td><td>{_badge(c['strength'].upper())}</td>"
                             f"<td>{esc(c['statement'])}</td></tr>" for c in gen["catches"]) + "</table>")
    return out


def write_page(out: Path, record: dict, frames: dict[str, dict]) -> Path:
    """Write out/review/index.html for ``record``. ``frames`` maps a finding id to
    {"after": (frames_dir, index), "before": (frames_dir, index)} from the replays that made them."""
    review = out / "review"
    review.mkdir(parents=True, exist_ok=True)
    assets = review / "assets"
    decision = record["decision"]
    pr = record["pullRequest"]
    parts = [
        "<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Expectrail gate: {esc(decision)}</title><style>{CSS}</style></head><body><main>",
        f"<h1>Expectrail gate {_badge(decision)}</h1>",
        f"<p>{esc(DECISION_MEANS[decision])}</p>",
    ]
    if decision == "needs-review" and rec.unverified_fix(record):
        parts.append("<p><strong>No check reproduced the reported bug, so this fix is not verified.</strong> "
                     f"No check failed before the change {rec.REPAIR_RUNS} times of {rec.REPAIR_RUNS} and passed "
                     "after it, so the checks passing now says nothing about the bug. Add a check that fails on the "
                     "bug, or let Expectrail propose one.</p>")
    if record["reasons"]:
        parts.append("<ul>" + "".join(f"<li>{esc(r)}</li>" for r in record["reasons"]) + "</ul>")
    counts, held = record["counts"], record["heldOut"]
    meta = [
        ("Pull request", f"#{pr['number']}" if pr else "none (not a pull request run)"),
        ("Head commit", pr["headSha"] if pr else "unknown"),
        ("Base commit", (pr or {}).get("baseSha") or "not replayed"),
        ("Game", f"{record['game']['path']} (tree {(record['game']['headTree'] or 'unknown')[:16]})"),
        ("Checks from", "the base commit: this change cannot edit the checks that judge it"
         if record["checksFrom"] == "base" else "the head commit: the checks are the pull request's own"),
        ("Spec and route files this change edits",
         f"{record['checksChanged']['specs']} spec, {record['checksChanged']['routes']} route"),
        ("Public checks", f"{counts['checks']}: {counts['passed']} pass, {counts['failed']} fail, "
                          f"{counts['needsReview']} need review"),
        ("Held-out routes", "not used" if held["status"] == "not-used" else
         "could not be judged" if held["status"] == "unavailable" else
         f"{held['routes']} routes, {held['checks']} checks: {held['passed']} pass, {held['failed']} fail, "
         f"{held['needsReview']} need review (counts only)"),
        ("Declared as", rec.repair_words(record)),
        ("Replays in the sandbox", rec.isolation_words(record.get("isolation"))),
        ("Draft specs not used", str(record["drafts"])),
        ("Replayed by", f"the {ADAPTER.get(record['adapter'], record['adapter'])} harness"),
        ("Judged on", rec.observers_words(record)),
        ("Expectrail", f"{record['expectrail']['version']}"
                       + (f" at {record['expectrail']['commit']}" if record["expectrail"]["commit"] else "")),
        ("Written", record["createdAt"]),
    ]
    parts.append('<h2>Run</h2><table class="meta">'
                 + "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in meta) + "</table>")

    parts.append("<h2>Findings</h2>")
    if not record["findings"]:
        parts.append("<p>None: every check passes after this change.</p>")
    for n, finding in enumerate(record["findings"]):
        fid = finding["id"]
        parts.append(f'<h3 id="f-{esc(fid)}"><code>{esc(fid)}</code> {esc(finding["spec"])} on '
                     f'{esc(finding["route"])} {_badge(finding["comparison"])}</h3>')
        parts.append(f"<p>Before: {esc(WORD[finding['before']])}. After: {esc(WORD[finding['after']])}. "
                     f"{esc(finding['reason'])}</p>")
        if n < MAX_FRAMED_FINDINGS and finding["frame"] is not None:
            got = frames.get(fid) or {}
            after = _copy_frame(*(got.get("after") or (None, None)), assets, f"{fid}-after")
            before = _copy_frame(*(got.get("before") or (None, None)), assets, f"{fid}-before")
            parts.append('<div class="frames">'
                         + _figure("Before the change", before, "No frame from the base commit")
                         + _figure("After the change", after, "No frame was recorded") + "</div>")

    parts.append("<h2>Every check</h2><table><tr><th>Spec</th><th>Route</th><th>Before</th><th>After</th>"
                 "<th>Comparison</th><th>Finding</th></tr>")
    for check in record["checks"]:
        fid = check["findingId"]
        link = f'<a href="#f-{esc(fid)}"><code>{esc(fid)}</code></a>' if fid else ""
        parts.append(f"<tr><td>{esc(check['spec'])}</td><td>{esc(check['route'])}</td>"
                     f"<td>{esc(WORD[check['before']])}</td><td>{esc(WORD[check['after']])}</td>"
                     f"<td>{_badge(check['comparison'])}</td><td>{link}</td></tr>")
    parts.append("</table>")
    parts += _generated_section(record.get("generatedChecks"))
    parts.append(f'<h2>Reading this page</h2><p>The comparisons use the review\'s words: '
                 f'<a href="{REVIEW_DOC}">docs/review.md</a>. How the gate works and its limits: '
                 f'<a href="{GATE_DOC}">docs/ci-gate.md</a>. A finding id is the first 12 hex digits of '
                 f"sha256(spec, route, kind), so the same failure keeps its id across pushes.</p>")
    parts.append("</main></body></html>\n")
    page = review / "index.html"
    page.write_text("\n".join(parts), encoding="utf-8")
    return page
