"""Run it, played by a visitor in a real browser, against the local stub (#265).

    python3 -m tools.runit_smoke                     real runs: needs Godot, as `expectrail.runit run` does
    python3 -m tools.runit_smoke --require-sandbox   real runs, every replay in the sandbox (needs bubblewrap)
    python3 -m tools.runit_smoke --stand-in          stand-in replays and stand-in recordings, no Godot

It starts ``tools.runit_stub`` on a free port of 127.0.0.1, opens ``/run-it/#local`` in Chromium, and does
what a visitor does, checking each time that the page says what the published ``status.json`` says and
no more:

1. **One run at a time.** While the first run is held, a second visitor starts another sample and must
   be told "Busy".
2. **Each sample the page offers.** Click "Run it", wait for the result, and compare the verdict shown
   (title and colour) with the one ``status.json`` allows. Only an accept with every vision question
   answered from the recording may be green. Also compared: the vision line and its recording date, the
   receipt line, the request id, that the run ended as the sample is expected to, and that the
   evidence viewer is shown.
3. **The quota.** The stub allows each visitor as many runs as there are samples, so one more click
   must say the quota is spent, when it resets, and show the most recent run labelled as earlier.
4. **The latest runs.** After a reload, each sample's card names its latest run and its verdict.
5. **Switched off.** With the service closed, nothing can be started, the page says so, and the latest
   run of a sample still opens, labelled earlier.

A sample whose button the page does not enable (the recorded fix, until a repair is recorded) is
listed as "not offered" and not run. Nothing here talks to GitHub, a model or any address but the stub.
Exit 0 when every check holds, 1 when one does not, 2 when the smoke could not run at all.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "expectrail.run-it-smoke/v1"

# The page's own words for the end of a run that published nothing (docs/run-it/run-it.js).
TERMINAL_MESSAGES = ("The run failed", "Cancelled", "No answer from this run", "Lost contact", "Could not reach",
                     "Run it answered", "Busy", "Today's quota", "Run it has started", "Run it stopped",
                     "Run it is switched off", "Run it could not", "That is not one", "Run it did not",
                     "Run it refused")

READ_PAGE = """() => {
  const $ = (id) => document.getElementById(id);
  const facts = {};
  document.querySelectorAll('#facts dt').forEach((dt) => {
    facts[dt.textContent] = dt.nextElementSibling ? dt.nextElementSibling.textContent : null;
  });
  const viewer = $('viewer');
  const note = $('evidence-note');
  return {
    panelShown: !$('run').hidden,
    when: $('run-when').textContent,
    title: $('run-title').textContent,
    message: $('run-message').textContent,
    resultShown: !$('result').hidden,
    verdict: $('verdict-title').textContent,
    tone: $('verdict').getAttribute('data-tone'),
    facts: facts,
    viewerShown: !viewer.hidden && (viewer.getAttribute('srcdoc') || '').length > 0,
    evidenceNote: note.hidden ? null : note.textContent,
    standInBanner: !$('standin').hidden,
  };
}"""

SETTLED = """(terminal) => {
  const $ = (id) => document.getElementById(id);
  const message = $('run-message').textContent;
  if (terminal.some((t) => message.startsWith(t))) return true;
  if ($('result').hidden || !$('verdict-title').textContent) return false;
  const viewer = $('viewer');
  return (!viewer.hidden && (viewer.getAttribute('srcdoc') || '').length > 0) || !$('evidence-note').hidden
    || $('verdict-title').textContent === 'Cannot tell';
}"""


def evidence_headline(page, timeout_s: float = 20.0) -> str | None:
    """The headline the evidence viewer shows inside its sandboxed frame, once it has drawn; None if never."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for frame in page.frames:
            if frame is page.main_frame or frame.url != "about:srcdoc":
                continue
            try:
                text = frame.evaluate("() => document.body ? document.body.innerText : ''")
            except Exception:   # noqa: BLE001 - the frame is being replaced; try again
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines and lines[0] == "Expectrail evidence viewer" and len(lines) > 1:
                return lines[1]
        time.sleep(0.25)
    return None


def expected_verdict(status: dict) -> tuple[str, str]:
    """The (title, tone) the page may show for a published status.json: the page's rule, restated."""
    vision = status.get("vision") or {}
    if status.get("phase") == "cancelled":
        return "Cancelled: no verdict", "review"
    if status.get("phase") != "completed" or status.get("decision") is None:
        return "The run failed: no verdict", "review"
    decision = status.get("decision")
    if decision == "reject":
        return "Rejected", "fail"
    if decision == "needs-review":
        return "Needs review", "review"
    if decision == "accept":
        answered, asked = vision.get("answered"), vision.get("asked")
        if (vision.get("recorded") is True and vision.get("notRecorded") == 0 and isinstance(answered, int)
                and answered > 0 and answered == asked):
            return "Accepted", "pass"
        return "Needs review", "review"
    return "Cannot tell", "review"


def compare(status: dict, page: dict, *, label: str, earlier: bool, evidence: bool) -> list[str]:
    """What the page shows for a published run that it should not, as sentences (empty: it agrees).

    ``earlier``: the page should be showing this run as an earlier one, not as the visitor's own.
    ``evidence``: the folder holds the viewer's one-file export, so the page should show it."""
    problems = []
    title, tone = expected_verdict(status)
    if not page.get("resultShown"):
        return [f"{label}: the page shows no result (message: {page.get('message')!r})"]
    if page.get("verdict") != title or page.get("tone") != tone:
        problems.append(f"{label}: the page shows {page.get('verdict')!r} ({page.get('tone')}), status.json allows "
                        f"{title!r} ({tone}) for decision {status.get('decision')!r}")
    when = page.get("when") or ""
    if earlier and not when.startswith("Earlier run, from "):
        problems.append(f"{label}: an earlier run is labelled {when!r}, not as earlier with its time")
    if not earlier and when != "Your run":
        problems.append(f"{label}: the visitor's own run is labelled {when!r}")
    facts = page.get("facts") or {}
    vision = status.get("vision") or {}
    line = facts.get("Vision") or ""
    if vision.get("recorded") is True:
        lead = f"Vision answers recorded on {vision.get('recordedAt')} "
        if not line.startswith(lead):
            problems.append(f"{label}: the vision line does not start {lead.strip()!r}: {line!r}")
        counts = f"{vision.get('answered')} of {vision.get('asked')} questions answered from the recording"
        if counts not in line:
            problems.append(f"{label}: the vision line does not say {counts!r}: {line!r}")
    elif line.startswith("Vision answers recorded"):
        problems.append(f"{label}: the vision line claims a recording that status.json does not have: {line!r}")
    receipt = (status.get("receipt") or {}).get("why") or "not signed"
    if facts.get("Receipt") != receipt:
        problems.append(f"{label}: the receipt line is {facts.get('Receipt')!r}, status.json says {receipt!r}")
    if facts.get("Request") != status.get("requestId"):
        problems.append(f"{label}: the request line is {facts.get('Request')!r}, not {status.get('requestId')!r}")
    expected_end = "ended as this sample is expected to end" if status.get("asExpected") else "did not end as"
    if expected_end not in (facts.get("This sample") or ""):
        problems.append(f"{label}: the sample line does not match asExpected={status.get('asExpected')!r}: "
                        f"{facts.get('This sample')!r}")
    if evidence and not page.get("viewerShown"):
        problems.append(f"{label}: the evidence viewer is not shown ({page.get('evidenceNote')!r})")
    elif evidence:
        headline = page.get("evidenceHeadline")
        decision = status.get("decision")
        if headline is None:
            problems.append(f"{label}: the evidence frame never drew the viewer")
        elif headline.startswith("Accepted") != (decision == "accept") or \
                headline.startswith("Rejected") != (decision == "reject"):
            problems.append(f"{label}: the evidence viewer's headline {headline!r} does not agree with decision "
                            f"{decision!r}")
    return problems


def read(page) -> dict:
    """What the page shows now, with the evidence viewer's headline once its frame has drawn."""
    reading = page.evaluate(READ_PAGE)
    reading["evidenceHeadline"] = evidence_headline(page) if reading["viewerShown"] else None
    return reading


class Gate:
    """Holds the first run until the busy check is done, so that check never races a fast run."""

    def __init__(self, runner, timeout: float = 120.0):
        self.runner, self.timeout = runner, timeout
        self.started, self.release = threading.Event(), threading.Event()
        self._first = True

    def __call__(self, sample: str, out: Path, request_id: str) -> None:
        if self._first:
            self._first = False
            self.started.set()
            self.release.wait(self.timeout)
        self.runner(sample, out, request_id)


def smoke(*, stand_in: bool, require_sandbox: bool = False, only: list[str] | None = None,
          run_timeout_s: float = 20 * 60, screenshots: Path | None = None, docs: Path | None = None,
          log=print) -> dict:
    """Play the visitor; ``docs`` serves another copy of the site (tests use it to break the page)."""
    from playwright.sync_api import sync_playwright
    from harness.web.run import CHROMIUM_ARGS, game_env
    from tools import runit_stub

    runner, root = (runit_stub.stand_in_runner(recorded=True) if stand_in
                    else runit_stub.real_runner(require_sandbox))
    gate = Gate(runner)
    results = Path(tempfile.mkdtemp(prefix="expectrail-smoke-results-"))
    manifest = json.loads(((docs or ROOT / "docs") / "run-it" / "samples.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in manifest["samples"]]
    unknown = sorted(set(only or []) - set(ids))
    if unknown:
        raise SystemExit(f"not a sample in docs/run-it/samples.json: {', '.join(unknown)}")
    limits = runit_stub.Limits(per_visitor=1, daily_cap=40, breaker=3)
    service = runit_stub.Service(results, gate, root, limits=limits, stand_in=stand_in)
    service.log = lambda message: log(f"stub: {message}")
    server = runit_stub.serve(service, 0, docs=docs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/run-it/#local"
    doc = {"format": FORMAT, "standIn": stand_in, "requireSandbox": require_sandbox, "url": url,
           "runs": [], "notOffered": [], "checks": [], "problems": []}

    def check(name: str, problems: list[str]) -> None:
        doc["checks"].append({"check": name, "held": not problems})
        doc["problems"].extend(problems)
        log(f"{'held' if not problems else 'FAILED'}: {name}" + "".join(f"\n  {p}" for p in problems))

    def status_of(request_id: str) -> dict | None:
        path = results / request_id / "status.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def shot(page, name: str) -> None:
        if screenshots is None:
            return
        screenshots.mkdir(parents=True, exist_ok=True)
        for width, height, tag in ((1280, 900, "desktop"), (390, 844, "phone")):
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=str(screenshots / f"{name}-{tag}.png"), full_page=True)
            # Chromium leaves a frame outside the viewport unpainted in a full-page shot, so the
            # evidence gets a shot of its own, scrolled into view.
            if page.is_visible("#viewer"):
                page.locator("#viewer").scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                page.screenshot(path=str(screenshots / f"{name}-{tag}-evidence.png"))
        page.set_viewport_size({"width": 1280, "height": 900})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=CHROMIUM_ARGS, env=game_env())
            context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US",
                                          timezone_id="UTC", reduced_motion="reduce")
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            # A refusal (429, 409, 503) and a missing latest.json (404) are answers the page handles, and
            # Chromium logs each as "Failed to load resource"; anything else logged as an error counts.
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
            page.goto(url)
            page.wait_for_selector('#service[data-open="yes"]', timeout=30_000)
            page.wait_for_selector("button[data-run]", timeout=30_000)
            offered = page.eval_on_selector_all(
                "button[data-run]", "bs => bs.filter(b => !b.disabled).map(b => b.getAttribute('data-run'))")
            doc["notOffered"] = [i for i in ids if i not in offered]
            chosen = [i for i in offered if not only or i in only]
            if not chosen:
                check("the page offers a sample to run", ["no sample the page offers was chosen"])
                return doc
            limits.per_visitor = len(chosen)
            banner = page.evaluate("() => !document.getElementById('standin').hidden")
            check("the stand-in banner is shown exactly when the runs are stand-ins",
                  [] if banner == stand_in else [f"banner shown: {banner}, stand-in runs: {stand_in}"])

            # 1 and 2: the runs, with a second visitor turned away while the first is held.
            busy_checked = False
            for n, sample in enumerate(chosen):
                before = set(p.name for p in results.iterdir())
                page.click(f'button[data-run="{sample}"]')
                if not busy_checked:
                    busy_checked = True
                    problems = []
                    if not gate.started.wait(60):
                        problems.append("the first run never reached the runner")
                    other = [s for s in offered if s != sample][:1] or [sample]
                    second = browser.new_context(locale="en-US", timezone_id="UTC").new_page()
                    second.goto(url)
                    second.wait_for_selector(f'button[data-run="{other[0]}"]:not([disabled])', timeout=30_000)
                    second.click(f'button[data-run="{other[0]}"]')
                    second.wait_for_function(SETTLED, arg=list(TERMINAL_MESSAGES), timeout=30_000)
                    message = second.evaluate("() => document.getElementById('run-message').textContent")
                    if not message.startswith("Busy:"):
                        problems.append(f"a second visitor during a run was told {message!r}, not Busy")
                    second.context.close()
                    gate.release.set()
                    check("a second visitor is told Busy while a run is going", problems)
                page.wait_for_function(SETTLED, arg=list(TERMINAL_MESSAGES), timeout=run_timeout_s * 1000)
                reading = read(page)
                new = sorted(set(p.name for p in results.iterdir()) - before - {"latest.json"})
                status = status_of(new[0]) if len(new) == 1 else None
                row = {"sample": sample, "requestId": new[0] if len(new) == 1 else None,
                       "pageVerdict": reading["verdict"], "pageTone": reading["tone"],
                       "decision": status and status.get("decision"), "asExpected": status and status.get("asExpected"),
                       "vision": status and {k: status["vision"].get(k) for k in ("recorded", "recordedAt", "answered", "asked")},
                       "evidenceShown": reading["viewerShown"], "evidenceHeadline": reading["evidenceHeadline"]}
                doc["runs"].append(row)
                if status is None:
                    check(f"{sample}: the run is published and the page shows it",
                          [f"{sample}: nothing was published; the page says {reading['message']!r}"])
                    continue
                problems = compare(status, reading, label=sample, earlier=False,
                                   evidence=(results / new[0] / "viewer" / "evidence.html").is_file())
                if status.get("asExpected") is not True:
                    problems.append(f"{sample}: decided {status.get('decision')!r}, not as the sample is expected to end")
                check(f"{sample}: the page shows what status.json says ({reading['verdict']})", problems)
                shot(page, f"run-{n + 1}-{sample}")

            published = {r["sample"]: r["requestId"] for r in doc["runs"] if r["requestId"]}

            # 3: the quota, with the earlier run in its place.
            first = chosen[0]
            if first in published:
                page.click(f'button[data-run="{first}"]')
                page.wait_for_function(SETTLED, arg=list(TERMINAL_MESSAGES), timeout=30_000)
                reading = read(page)
                problems = []
                if not reading["message"].startswith("Today's quota is spent.") or "resets at" not in reading["message"]:
                    problems.append(f"one run over the quota says {reading['message']!r}")
                if "most recent finished run of this sample" not in reading["message"]:
                    problems.append("the quota refusal does not offer the most recent run instead")
                else:
                    page.wait_for_function(SETTLED, arg=[], timeout=30_000)
                    reading = read(page)
                    problems += compare(status_of(published[first]), reading, label=f"{first} (after the quota)",
                                        earlier=True, evidence=True)
                check("the quota refusal says when it resets and shows the earlier run, labelled earlier", problems)
                shot(page, "quota")

            # 4: the latest run of each sample, after a reload.
            page.goto("about:blank")
            page.goto(url)
            page.wait_for_selector('#service[data-open]', timeout=30_000)
            problems = []
            for sample, request_id in published.items():
                title, _ = expected_verdict(status_of(request_id))
                selector = f'[data-latest="{sample}"]'
                try:
                    page.wait_for_function(
                        "([sel, t]) => (document.querySelector(sel) || {}).textContent?.includes(t)",
                        arg=[selector, f": {title}."], timeout=15_000)
                except Exception:   # noqa: BLE001 - reported below with what the card says
                    pass
                line = page.text_content(selector) or ""
                if not line.startswith("Latest run, ") or not line.endswith(f": {title}."):
                    problems.append(f"{sample}: the card says {line!r}, not its latest run and {title!r}")
            check("each card names its latest run and its verdict", problems)

            # 5: switched off, the earlier runs still open.
            service.open = False
            page.goto("about:blank")
            page.goto(url)
            page.wait_for_selector('#service[data-open="no"]', timeout=30_000)
            problems = []
            enabled = page.eval_on_selector_all("button[data-run]", "bs => bs.filter(b => !b.disabled).length")
            if enabled:
                problems.append(f"{enabled} Run it buttons are enabled while the service is switched off")
            service_line = page.text_content("#service") or ""
            if "not starting runs" not in service_line:
                problems.append(f"the service line says {service_line!r}")
            if first in published:
                page.wait_for_selector(f'button[data-show="{first}"]:not([hidden])', timeout=15_000)
                page.click(f'button[data-show="{first}"]')
                page.wait_for_function(SETTLED, arg=[], timeout=30_000)
                problems += compare(status_of(published[first]), read(page),
                                    label=f"{first} (switched off)", earlier=True, evidence=True)
            check("switched off, nothing starts and the latest run still opens, labelled earlier", problems)
            shot(page, "switched-off")

            check("the page logged no script errors", [f"script error: {e}" for e in errors])
            browser.close()
    finally:
        gate.release.set()
        server.shutdown()
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.runit_smoke", description=__doc__.split("\n\n")[0])
    parser.add_argument("--stand-in", action="store_true", help="stand-in replays and recordings, no Godot")
    parser.add_argument("--require-sandbox", action="store_true", help="real runs: every replay in the sandbox")
    parser.add_argument("--sample", action="append", default=None, help="only this sample (repeatable)")
    parser.add_argument("--run-timeout", type=float, default=20 * 60, help="seconds to wait for one run")
    parser.add_argument("--json", type=Path, default=None, help="also write the result here")
    parser.add_argument("--screenshots", type=Path, default=None, help="save desktop and phone screenshots here")
    args = parser.parse_args(argv)
    if args.stand_in and args.require_sandbox:
        parser.error("--require-sandbox is for real runs")
    started = time.monotonic()
    try:
        doc = smoke(stand_in=args.stand_in, require_sandbox=args.require_sandbox, only=args.sample,
                    run_timeout_s=args.run_timeout, screenshots=args.screenshots)
    except SystemExit:
        raise
    except Exception as exc:   # noqa: BLE001 - the smoke could not run; say so, never "held"
        print(f"Run it smoke could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    doc["seconds"] = round(time.monotonic() - started, 1)
    held = sum(1 for c in doc["checks"] if c["held"])
    kind = "stand-in runs" if args.stand_in else "real runs"
    print(f"Run it smoke ({kind}): {len(doc['runs'])} runs, {held} of {len(doc['checks'])} checks held, "
          f"{len(doc['problems'])} problems, {doc['seconds']} s"
          + (f"; not offered by the page: {', '.join(doc['notOffered'])}" if doc["notOffered"] else ""))
    for row in doc["runs"]:
        print(f"  {row['sample']}: page {row['pageVerdict']!r}, status.json {row['decision']}, "
              f"as expected {row['asExpected']}, evidence viewer {row['evidenceHeadline']!r}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return 0 if doc["checks"] and not doc["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
