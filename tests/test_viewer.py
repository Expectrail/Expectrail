"""The evidence viewer (#264, expectrail/viewer.py): the state it shows for every kind of result, that
it never shows an empty or disagreeing result as success, that its timeline agrees with the
evaluator or is left out, that it fetches nothing, that held-out routes never reach it, and the job
viewer `expectrail report` writes. No Godot: the gate tests' stand-in replay."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail import evaluator, viewer
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from expectrail.orchestrator import cli as ocli
from expectrail.orchestrator import engines
from expectrail.orchestrator import request as req
from expectrail.orchestrator import runner
from expectrail.orchestrator import store as st
from tests.test_ci_gate import FIXTURES, SECRET_NAMES, SPEC, FakeReplay, make_heldout, make_repo

REPO = Path(__file__).resolve().parent.parent


def spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def obs(name: str) -> dict:
    trace = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return gv.observations(trace, "a" * 64)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="viewer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def gate(self, head: Path, base: Path | None = None, name: str = "out", **kw) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                               out=self.tmp / name, work=self.tmp / f"{name}-work", base=base,
                               pr={"number": 7, "headSha": "1" * 40, "baseSha": "2" * 40 if base else None},
                               replay=FakeReplay(), **kw)

    def page(self, name: str = "out") -> str:
        return (self.tmp / name / "viewer" / "index.html").read_text(encoding="utf-8")


def banner_state(page: str) -> str:
    return re.search(r'class="banner [a-z]+" role="status" data-state="([a-z-]+)"', page).group(1)


# --- the state shown -----------------------------------------------------------------------------

class StateTest(Base):
    def record(self, **over) -> dict:
        doc = json.loads((REPO / "contracts" / "examples" / "findings.json").read_text(encoding="utf-8"))
        doc.update(over)
        return doc

    def test_each_record_maps_to_its_own_state(self):
        reject = self.gate(make_repo(self.tmp / "h1", bug=True), make_repo(self.tmp / "b1"), "r")
        accept = self.gate(make_repo(self.tmp / "h2"), make_repo(self.tmp / "b2"), "a")
        crash = self.gate(make_repo(self.tmp / "h3", crash=True), make_repo(self.tmp / "b3"), "c")
        self.assertEqual(viewer.state_of(reject)[0], "behaviour-failure")
        self.assertEqual(viewer.state_of(accept)[0], "accept")
        self.assertEqual(viewer.state_of(crash)[:2], ("replay-failure", "needs-review"))
        for name, state in (("r", "behaviour-failure"), ("a", "accept"), ("c", "replay-failure")):
            self.assertEqual(banner_state(self.page(name)), state)

    def test_a_check_that_could_not_be_decided_is_an_observation_failure(self):
        doc = self.gate(make_repo(self.tmp / "h"), make_repo(self.tmp / "b"), rule=rec.BOTH, visual=None)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(viewer.state_of(doc)[0], "observation-failure")
        self.assertNotIn("Accepted", self.page())

    def test_an_empty_result_is_never_success(self):
        head = make_repo(self.tmp / "h")
        for f in (head / "specs").iterdir():
            f.unlink()
        doc = self.gate(head)
        self.assertEqual(doc["counts"]["checks"], 0)
        self.assertEqual(viewer.state_of(doc)[0], "nothing-checked")
        page = self.page()
        self.assertEqual(banner_state(page), "nothing-checked")
        self.assertNotIn(">Accepted<", page)
        # Even a record that claims accept with no checks is not shown as accepted.
        forged = copy.deepcopy(doc)
        forged["decision"] = "accept"
        self.assertEqual(viewer.state_of(forged)[0], "nothing-checked")
        self.assertEqual(viewer.state_of(None)[0], "nothing-checked")

    def test_a_record_saying_accept_over_a_failing_check_is_not_accepted(self):
        doc = self.gate(make_repo(self.tmp / "h", bug=True))
        forged = dict(doc, decision="accept")
        self.assertEqual(viewer.state_of(forged)[:2], ("needs-review", "needs-review"))

    def test_the_jobs_decision_wins_and_a_disagreement_is_never_an_accept(self):
        doc = self.gate(make_repo(self.tmp / "h"))
        self.assertEqual(doc["decision"], "accept")
        status = {"phase": "completed", "decision": "needs-review", "reasons": ["the evidence names another tree"],
                  "diagnostics": []}
        state, decision, reasons = viewer.state_of(doc, status)
        self.assertEqual((state, decision), ("needs-review", "needs-review"))
        self.assertTrue(any("differ" in r for r in reasons))
        # The other way round too: the kinder one is never picked.
        bad = self.gate(make_repo(self.tmp / "h2", bug=True), name="o2")
        self.assertEqual(viewer.state_of(bad, dict(status, decision="accept"))[0], "needs-review")

    def test_job_phases_without_a_record(self):
        self.assertEqual(viewer.state_of(None, {"phase": "executing"})[0], "running")
        self.assertEqual(viewer.state_of(None, {"phase": "cancelled", "reasons": []})[0], "cancelled")
        self.assertEqual(viewer.state_of(None, {"phase": "failed", "reasons": ["WORKER_LOST"]})[0],
                         "infrastructure-failure")
        done = {"phase": "completed", "decision": "needs-review", "reasons": [], "diagnostics": [{"code": "INPUT_INVALID"}]}
        self.assertEqual(viewer.state_of(None, done)[0], "unsupported-project")
        tool = dict(done, diagnostics=[{"code": "TOOL_MISSING"}])
        self.assertEqual(viewer.state_of(None, tool)[0], "infrastructure-failure")
        lying = dict(done, decision="accept", diagnostics=[])
        self.assertEqual(viewer.state_of(None, lying)[:2], ("needs-review", "needs-review"))

    def test_every_state_has_words_and_none_but_accept_is_good(self):
        for state, (title, tone, means) in viewer.STATES.items():
            self.assertTrue(title and means, state)
            self.assertEqual(tone == "good", state == "accept", state)


# --- the timeline ---------------------------------------------------------------------------------

class SeriesTest(unittest.TestCase):
    def test_the_first_failing_frame_is_the_evaluators(self):
        s, o = spec(), obs("trace-fallthrough.json")
        verdict = evaluator.evaluate(s, o)
        series = viewer.series(s, o)
        self.assertEqual(verdict["result"], "fail")
        over = [p["frame"] for p in series["points"] if p["state"] == "over"]
        self.assertEqual(over[0], verdict["firstFrame"])
        self.assertEqual(over[:len(verdict["evidence"])], [e["frame"] for e in verdict["evidence"]])
        self.assertTrue(viewer.series_agrees(series, verdict))
        self.assertEqual(series["limit"], 20)

    def test_a_pass_has_no_failing_frame(self):
        s, o = spec(), obs("trace-fixed.json")
        verdict = evaluator.evaluate(s, o)
        self.assertEqual(verdict["result"], "pass")
        series = viewer.series(s, o)
        self.assertFalse([p for p in series["points"] if p["state"] == "over"])
        self.assertTrue(viewer.series_agrees(series, verdict))

    def test_a_timeline_that_disagrees_or_has_no_verdict_is_left_out(self):
        s, o = spec(), obs("trace-fallthrough.json")
        run = {"engineObservations": o}
        verdict = dict(evaluator.evaluate(s, o), firstFrame=999)
        got = viewer.check_series(s, run, verdict)
        self.assertIsNone(got["series"])
        self.assertIn("does not agree", got["note"])
        self.assertIsNone(viewer.check_series(s, run, dict(verdict, result="pass", firstFrame=None))["series"])
        self.assertIsNone(viewer.check_series(s, run, None)["series"])
        broken = viewer.check_series(s, {"engineObservations": None}, verdict)
        self.assertIsNone(broken["series"])
        self.assertIn("could not be measured", broken["note"])

    def test_other_kinds_agree_with_the_evaluator(self):
        o = obs("trace-fallthrough.json")
        base = spec()
        kinds = [
            {"type": "visible", "object": "player"},
            {"type": "inside-region", "object": "player", "region": {"box": [0, 0, 1600, 700]}, "tolerancePx": 5},
            {"type": "inside-region", "object": "player", "region": {"relativeTo": "ground", "marginPx": 400}},
            {"type": "reaches", "object": "player", "goal": "ground", "distancePx": 0},
            {"type": "never-crosses", "object": "player", "boundary": {"value": 700, "side": "above", "tolerancePx": 0}},
        ]
        for assertion in kinds:
            s = dict(base, assertion=assertion)
            verdict = evaluator.evaluate(s, o)
            series = viewer.series(s, o)
            self.assertTrue(viewer.series_agrees(series, verdict), (assertion, verdict["result"]))
        self.assertIsNone(viewer.series(dict(base, assertion={"type": "something-new", "object": "player"}), o))


# --- the folder the gate writes -------------------------------------------------------------------

class GateViewerTest(Base):
    def test_a_failing_run_opens_at_its_first_failure_with_frames_on_both_sides(self):
        doc = self.gate(make_repo(self.tmp / "h", bug=True), make_repo(self.tmp / "b"))
        folder = self.tmp / "out" / "viewer"
        views = json.loads((folder / "views.json").read_text(encoding="utf-8"))
        framed = [v for v in views if v["findingId"]]
        self.assertEqual(len(framed), len(doc["findings"]))
        first = framed[0]
        self.assertEqual(first["firstFrame"], min(f["frame"] for f in doc["findings"]))
        for side in ("after", "before"):
            frames = [f["frame"] for f in first["frames"][side]]
            self.assertIn(first["firstFrame"], frames, side)
            self.assertEqual(len(frames), viewer.FRAMES_AROUND * 2 + 1, side)
            for f in first["frames"][side]:
                self.assertRegex(f["path"], viewer.FRAME_NAME)
                self.assertTrue((folder / f["path"]).is_file())
            self.assertIsNotNone(first["series"][side], side)

    def test_the_page_fetches_nothing_and_escapes_what_it_embeds(self):
        doc = self.gate(make_repo(self.tmp / "h", bug=True))
        doc = copy.deepcopy(doc)
        doc["findings"][0]["reason"] = '</script><img src="https://example.invalid/x.png"><!--'
        page = viewer.render({"format": viewer.FORMAT, "state": "behaviour-failure", "decision": "reject",
                              "reasons": ["<b>x</b>"], "record": doc, "views": [], "job": None,
                              "reproduce": None})
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("default-src 'none'", page)
        self.assertEqual(page.count("</script>"), 2)   # the data block's own and the script's own
        self.assertNotIn("<img src=\"https://", page)
        self.assertNotIn("<b>x</b>", page)
        for url in re.findall(r'(?:src|href)="([^"]+)"', page):
            self.assertFalse(url.startswith(("http:", "https:", "//")), url)
        data = re.search(r'<script type="application/json" id="evidence">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(data)["record"]["findings"][0]["reason"], doc["findings"][0]["reason"])

    def test_held_out_routes_never_reach_the_viewer(self):
        self.gate(make_repo(self.tmp / "h", bug=True), make_repo(self.tmp / "b"),
                  heldout=make_heldout(self.tmp / "held"))
        folder = self.tmp / "out" / "viewer"
        for path in folder.rglob("*"):
            text = path.name + (path.read_text(encoding="utf-8") if path.suffix in (".html", ".json") else "")
            for name in SECRET_NAMES:
                self.assertNotIn(name, text, path)
        self.assertIn("counts only", self.page())

    def test_frame_paths_read_back_are_checked(self):
        self.gate(make_repo(self.tmp / "h", bug=True))
        folder = self.tmp / "out" / "viewer"
        views = json.loads((folder / "views.json").read_text(encoding="utf-8"))
        views[0]["frames"]["after"] += [{"frame": 1, "path": "../../../etc/passwd"},
                                         {"frame": 2, "path": "/etc/passwd"},
                                         {"frame": 3, "path": "frames/after-x-00000003.png"}]  # not on disk
        (folder / "views.json").write_text(json.dumps(views), encoding="utf-8")
        kept = viewer.read_views(folder)
        paths = [f["path"] for f in kept[0]["frames"]["after"]]
        self.assertTrue(paths)
        self.assertTrue(all(viewer.FRAME_NAME.fullmatch(p) and (folder / p).is_file() for p in paths))
        (folder / "views.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(viewer.read_views(folder), [])

    def test_a_viewer_that_fails_does_not_change_the_decision(self):
        from unittest import mock

        with mock.patch.object(viewer, "write_gate", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stdout(io.StringIO()) as log:
                doc = gv.run_gate(repo=make_repo(self.tmp / "h", bug=True), game="game/platformer",
                                  routes=["routes/*.json"], specs="specs", out=self.tmp / "o",
                                  work=self.tmp / "w", replay=FakeReplay())
        self.assertEqual(doc["decision"], "reject")
        self.assertIn("evidence viewer was not written", log.getvalue())
        self.assertTrue((self.tmp / "o" / "findings.json").is_file())


# --- the job viewer `expectrail report` writes ----------------------------------------------------

class JobViewerTest(Base):
    def setUp(self):
        super().setUp()
        self.store = st.JobStore(self.tmp / "jobs", lease_seconds=0.6)

    def job(self, head: Path, base: Path | None = None) -> str:
        status, _ = self.store.create(req.build(adapter="godot", head=head, base=base, game="game/platformer",
                                                routes=["routes/*.json"], specs="specs"))
        return status["id"]

    def report(self, job: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = ocli.main(["--jobs-root", str(self.store.root), "--lease-seconds", "0.6", "report", job])
        return code, out.getvalue()

    def test_a_rejected_job_gets_a_viewer_with_frames_and_a_reproduction_command(self):
        job = self.job(make_repo(self.tmp / "h", bug=True), make_repo(self.tmp / "b"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, job, engines={"godot": engines.GodotGate(replay=FakeReplay())})
        self.assertEqual(status["decision"], "reject")
        code, out = self.report(job)
        self.assertEqual(code, 1)
        page_path = self.store.paths(job).root / "viewer" / "index.html"
        self.assertIn(f"viewer: {page_path}", out)
        page = page_path.read_text(encoding="utf-8")
        self.assertEqual(banner_state(page), "behaviour-failure")
        self.assertIn("expectrail verify --adapter godot --head", page)
        frames = list((page_path.parent / "frames").glob("*.png"))
        self.assertTrue(frames)
        self.assertIn(job, page)

    def test_jobs_with_no_result_get_their_own_page_and_keep_their_exit_codes(self):
        bad = self.job(make_repo(self.tmp / "h"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, bad, engines={"godot": engines.GodotGate(replay=FakeReplay())})
        self.assertEqual(status["decision"], "accept")
        self.assertEqual(self.report(bad)[0], 0)
        self.assertEqual(banner_state((self.store.paths(bad).root / "viewer" / "index.html").read_text()), "accept")

        missing = self.store.create(req.build(adapter="godot", head=self.tmp / "h", game="game/missing",
                                              routes=["routes/*.json"], specs="specs"))[0]["id"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runner.work(self.store, missing, engines={"godot": engines.GodotGate(replay=FakeReplay())})
        self.assertEqual(self.report(missing)[0], 2)
        page = (self.store.paths(missing).root / "viewer" / "index.html").read_text()
        self.assertEqual(banner_state(page), "unsupported-project")
        self.assertIn("INPUT_INVALID", page)

        gone = self.job(make_repo(self.tmp / "h2"))
        self.store.cancel(gone)
        self.assertEqual(self.report(gone)[0], ocli.EXIT_CANCELLED)
        self.assertEqual(banner_state((self.store.paths(gone).root / "viewer" / "index.html").read_text()), "cancelled")

    def test_report_json_is_still_the_status_alone(self):
        job = self.job(make_repo(self.tmp / "h"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runner.work(self.store, job, engines={"godot": engines.GodotGate(replay=FakeReplay())})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ocli.main(["--jobs-root", str(self.store.root), "report", job, "--json"])
        self.assertEqual(json.loads(out.getvalue()), self.store.status(job))


if __name__ == "__main__":
    unittest.main()
