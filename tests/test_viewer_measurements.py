"""The viewer compares recorded measurements and still has readable evidence without scripts."""
import base64
import copy
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail import viewer
from tests.test_ci_gate import make_repo
from tests.test_exact_score import ROUTE, judge, observation_frames, score_spec, score_trace
from tests.test_gate_intent import FlakyBase
from tests.test_viewer import Base, embedded

SAMPLES = Path(__file__).resolve().parents[1] / "docs/viewer-samples"


class StaticContent(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.text, self.images = [], []
        self.script = False
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script = True
        if tag == "img":
            self.images.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "script":
            self.script = False

    def handle_data(self, text):
        if not self.script:
            self.text.append(text)


class MeasurementTest(unittest.TestCase):
    def test_published_reject_distinguishes_first_difference_from_first_failure_offline(self):
        page = (SAMPLES / "fall-through-bug.html").read_text()
        payload = embedded(page)
        content = StaticContent(page)
        words = " ".join(content.text)
        self.assertIn("First measured difference at frame 0", words)
        self.assertIn("First failing frame: 5", words)
        self.assertIn("Bound: 20 px", words)
        v = payload["views"][0]
        self.assertEqual(len(content.images), 2)
        for image, side in zip(content.images, ("before", "after"), strict=True):
            frame = next(f for f in v["frames"][side] if f["frame"] == 0)
            self.assertEqual(image["alt"], f"{side.capitalize()} the change, frame 0")
            source = image["srcset"]
            self.assertTrue(source.startswith("data:image/png;base64,"))
            self.assertEqual(hashlib.sha256(base64.b64decode(source.split(",", 1)[1], validate=True)).hexdigest(),
                             frame["sha256"])
        self.assertIn(payload["reproduce"], words)

    def test_clean_sample_has_only_after_measurements_and_no_image(self):
        page = (SAMPLES / "clean.html").read_text()
        content = StaticContent(page)
        words = " ".join(content.text)
        self.assertIn("No paired engine measurements", words)
        self.assertIn("No frames were kept for this check", words)
        self.assertNotIn("First measured difference at", words)
        self.assertFalse(content.images)
        self.assertEqual(embedded(page)["decision"], "accept")

    def test_gaps_incomparable_values_and_a_missing_image_do_not_move_the_difference(self):
        payload = embedded((SAMPLES / "fall-through-bug.html").read_text())
        v = payload["views"][0]
        for side, points in (
            ("before", [(0, 0, "ok"), (1, None, "absent"), (2, None, "not-applicable"), (4, 0, "ok")]),
            ("after", [(0, 0, "ok"), (1, 9, "ok"), (2, None, "missing"), (4, -1, "ok")]),
        ):
            v["series"][side]["points"] = [dict(frame=f, value=n, state=s) for f, n, s in points]
        v["frames"]["after"] = []
        with tempfile.TemporaryDirectory() as tmp:
            page = viewer.write(Path(tmp), payload["record"], [v])
            for file in (page, page.with_name("evidence.html")):
                content = StaticContent(file.read_text())
                words = " ".join(content.text)
                self.assertIn("First measured difference at frame 4", words)
                self.assertIn("No after frame 4", words)
                for label in ("Not observed", "Object missing", "Not exercised"):
                    self.assertIn(label, words)
                self.assertFalse(content.images)  # no local frame files here
        v["series"]["after"]["unit"] = "tiles"
        self.assertNotIn("First measured difference at", " ".join(StaticContent(viewer.render(payload)).text))
        v["series"]["after"]["unit"] = "px"
        v["series"]["after"]["points"][-1]["value"] = 0
        self.assertIn("No difference in the paired engine measurements", " ".join(StaticContent(viewer.render(payload)).text))

    def test_earlier_finding_opens_both_exports_without_moving_the_measured_difference(self):
        payload = embedded((SAMPLES / "fall-through-bug.html").read_text())
        view = payload["views"][0]
        view["firstFrame"] = 0
        for finding in payload["record"]["findings"]:
            if finding["id"] == view["findingId"]:
                finding["frame"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "frames").mkdir()
            for side, later in (("before", 2), ("after", 7)):
                view["series"][side]["points"] = [
                    dict(frame=0, state="ok", value=0), dict(frame=20, state="ok", value=later)]
                frame = next(f for f in view["frames"][side] if f["frame"] == 0)
                image = base64.b64decode(frame["path"].split(",", 1)[1], validate=True)
                frame["path"] = f"frames/{side}-finding-00000000.png"
                (folder / frame["path"]).write_bytes(image)
                view["frames"][side] = [frame]
            page = viewer.write(folder, payload["record"], [view])
            for file in (page, page.with_name(viewer.EXPORT_NAME)):
                with self.subTest(file=file.name):
                    content = StaticContent(file.read_text())
                    words = " ".join(content.text)
                    self.assertIn("First measured difference at frame 20.", words)
                    self.assertIn("Before: 2 px · After: 7 px", words)
                    self.assertIn("Compare before and after at frame 0", words)
                    self.assertIn("Step through frame 0", words)
                    self.assertEqual([im["alt"] for im in content.images],
                                     ["Before the change, frame 0", "After the change, frame 0"])

    def test_needs_review_with_no_engine_data_cannot_claim_a_visual_divergence_as_engine_evidence(self):
        payload = embedded((SAMPLES / "fall-through-bug.html").read_text())
        v = payload["views"][0]
        v["visualSeries"], v["series"] = v["series"], {}
        payload.update(state="observation-failure", decision="needs-review")
        words = " ".join(StaticContent(viewer.render(payload)).text)
        self.assertIn("Needs review", words)
        self.assertIn("Vision measurements", words)
        self.assertIn("No paired engine measurements", words)
        self.assertNotIn("First measured difference at", words)

    def test_observer_policy_and_returned_verdicts_in_both_exports(self):
        for sample, before, after in (
            ("clean", "No applicable public checks.", "Engine 1/1 · Vision 1/1"),
            ("fall-through-bug", "Engine 1/1 · Vision 1/1", "Engine 1/1 · Vision 0/1"),
        ):
            payload = embedded((SAMPLES / f"{sample}.html").read_text())
            with tempfile.TemporaryDirectory() as tmp:
                page = viewer.write(Path(tmp), payload["record"], payload["views"])
                for file in (page, page.with_name(viewer.EXPORT_NAME)):
                    with self.subTest(sample=sample, export=file.name):
                        html = file.read_text()
                        words = " ".join(StaticContent(html).text)
                        self.assertNotIn("two observers on every check", words)
                        self.assertIn("sam-recorded (sam-3.1,", words)
                        self.assertIn(f"Before public check verdicts {before}", words)
                        self.assertIn(f"After public check verdicts {after}", words)
                        self.assertEqual(embedded(html)["decision"], payload["decision"])

    def test_observer_counts_distinguish_an_unanswered_check_from_a_review_verdict(self):
        record = embedded((SAMPLES / "fall-through-bug.html").read_text())["record"]
        row = record["checks"][0]
        def check(engine, visual, outcome):
            return dict(row, after=outcome, observed={"before": row["observed"]["before"],
                                                      "after": {"engine": engine, "visual": visual}})
        record["checks"] = [
            check("replay-error", "not-asked", "replay-error"),
            check("needs-review", "no-answer", "needs-review"),
            check("pass", "needs-review", "needs-review"),
            check("not-applicable", "not-asked", "not-applicable"),
        ]
        words = dict(viewer._observer_rows(record))
        self.assertEqual(words["After public check verdicts"], "Engine 2/3 · Vision 1/3")
        record.pop("observers")
        for check_row in record["checks"]:
            check_row.pop("observed")
        words = dict(viewer._observer_rows(record))
        self.assertEqual(words["After public check verdicts"], "Engine 2/3 · Vision 0/3")

    def test_untested_visual_position_pairs_on_the_public_route(self):
        record = embedded((SAMPLES / "fall-through-bug.html").read_text())["record"]
        row = record["anchor"]["routes"][0]
        words = " ".join(viewer.not_tested(record))
        self.assertIn("compared 0 of 13 sampled frame pairs", words)
        self.assertIn(row["reason"], words)

        row.update({"in": 1, "out": 1, "moved": 1, "noBase": 1, "noAnswer": 1, "notAsked": 1})
        self.assertIn("compared 2 of 6 sampled frame pairs", " ".join(viewer.not_tested(record)))
        row.update({"moved": 0, "noBase": 0, "noAnswer": 0, "notAsked": 0})
        self.assertNotIn("sampled frame pairs", " ".join(viewer.not_tested(record)))

        record["anchor"] = {"status": "not-asked", "stopped": "No base.", "routes": []}
        self.assertIn("was not run. No base.", " ".join(viewer.not_tested(record)))
        del record["anchor"]
        self.assertNotIn("sampled frame pairs", " ".join(viewer.not_tested(record)))

    def test_replay_scope_distinguishes_zero_from_an_unknown_count(self):
        payload = embedded((SAMPLES / "clean.html").read_text())
        record = payload["record"]
        record["isolation"] = dict(record["isolation"], replays=0, sandboxed=0)
        self.assertIn("zero completed replays", " ".join(viewer.not_tested(record)))
        self.assertNotIn("only the public routes were replayed", " ".join(viewer.not_tested(record)))
        del record["isolation"]
        self.assertIn("number of completed replays was not recorded", " ".join(viewer.not_tested(record)))

    def test_before_commit_and_tree_are_reported_independently(self):
        paired = embedded((SAMPLES / "fall-through-bug.html").read_text())
        tree = paired["record"]["game"]["baseTree"][:16]
        self.assertEqual(dict(viewer._facts(paired))["Base"], f"commit ID unavailable, game tree {tree}")
        head_only = embedded((SAMPLES / "clean.html").read_text())
        self.assertEqual(dict(viewer._facts(head_only))["Base"], "No Before replay recorded.")
        paired["record"]["pullRequest"] = {"baseSha": "a" * 40}
        self.assertEqual(dict(viewer._facts(paired))["Base"], f"commit {'a' * 40}, game tree {tree}")

    def test_frame_sources_must_be_local_or_an_embedded_png(self):
        payload = embedded((SAMPLES / "fall-through-bug.html").read_text())
        v = payload["views"][0]
        for side in ("before", "after"):
            v["frames"][side] = [{"frame": 0, "path": "https://invalid.example/other.png"}]
        for mode in ("single file", "folder"):
            if mode == "folder":
                del payload["export"]
            with self.subTest(mode=mode):
                content = StaticContent(viewer.render(payload))
                self.assertFalse(content.images)
                self.assertIn("No before frame 0", " ".join(content.text))
                self.assertIn("No after frame 0", " ".join(content.text))


class TerminalScoreTest(unittest.TestCase):
    def test_static_measurements_show_only_the_terminal_engine_verdict(self):
        spec = score_spec()
        for value, exercised, expected in ((5, True, "pass"), (10, True, "fail"), (0, True, "fail"),
                                          (0, False, "needs-review")):
            with self.subTest(value=value, exercised=exercised):
                seen = observation_frames(0, 1, 2, 3)
                verdict = judge(score_trace(value, exercised=exercised))
                self.assertEqual(verdict["result"], expected)
                measured = viewer.check_series(spec, {"engineObservations": seen}, verdict)
                self.assertIsNone(measured["series"])
                row = dict(spec=spec["id"], route=ROUTE, before=None, after=expected,
                           comparison="ADDED", findingId=None)
                view, = viewer.build_views({"checks": [row], "findings": []}, {},
                                           {(spec["id"], ROUTE): {"after": measured}}, None)
                for single in (False, True):
                    page = viewer._measurements(view, None, False, single, 0)
                    words = " ".join(StaticContent(page).text)
                    self.assertIn("after the change: Engine Label check for tick 3 (expected 5)", words)
                    self.assertIn(f"Engine verdict: {expected}. {verdict['reason']}", words)
                    self.assertIn("Rendered digits were not checked", words)
                    self.assertNotIn("Object missing", words)
        self.assertIsNone(viewer.series(spec, seen))

    def test_incomplete_and_unbound_score_evidence_stays_distinct(self):
        spec = score_spec()
        partial = observation_frames(0, 1, 3)
        verdict = judge(score_trace(10), frames=(0, 1, 3))
        result = viewer.check_series(spec, {"engineObservations": partial}, verdict)
        self.assertIsNone(result["series"])
        self.assertIn("Engine verdict: needs-review", result["note"])
        self.assertIn(verdict["reason"], result["note"])
        for check, seen, recorded in ((score_spec(minFrames=2), partial, verdict),
                                      (spec, observation_frames(0, 1, 2, 3), verdict),
                                      (spec, None, verdict), (spec, partial, None)):
            result = viewer.check_series(check, {"engineObservations": seen}, recorded)
            self.assertIsNone(result["series"])
            self.assertIn("Terminal score unavailable", result["note"])
            self.assertNotIn("read 10", result["note"])


class RepeatedRunTest(Base):
    def test_render_shows_the_gate_repeats_in_order_for_each_export(self):
        with mock.patch("tests.test_viewer.FakeReplay", FlakyBase):
            doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base", bug=True), intent="fix")
        self.assertEqual(doc["decision"], "needs-review")
        for name in ("index.html", viewer.EXPORT_NAME):
            page = (self.tmp / "out" / "viewer" / name).read_text()
            self.assertIn("<h1>Needs review: repeated runs disagree</h1>", page)
            self.assertIn("<caption>Repeated runs that disagree</caption>", page)
            self.assertIn("<td>smoke</td><td>fail, pass, pass</td><td>pass, pass, pass</td>", page)
            self.assertEqual(embedded(page)["decision"], doc["decision"])
        published = viewer.render_published(doc, doc["decision"])
        self.assertIn("<h1>needs-review</h1>", published)
        self.assertIn("<td>fail, pass, pass</td>", published)

    def test_disagreement_requires_both_a_pass_and_a_failure_on_the_same_side(self):
        row = {"spec": "score", "route": "smoke", "base": ["fail"] * 3, "head": ["pass"] * 3}
        record = {"repair": {"rows": [row]}}
        self.assertEqual(viewer._disagreeing_repeats(record), [])
        row["head"] = ["pass", "replay-error", "needs-review"]
        self.assertEqual(viewer._disagreeing_repeats(record), [])
        row["head"] = ["pass", "fail", "needs-review"]
        self.assertEqual(viewer._disagreeing_repeats(record), [row])
        self.assertEqual(viewer._disagreeing_repeats({}), [])


class RepairedFrameTest(Base):
    def test_gate_keeps_exact_first_difference_on_a_repair_in_both_viewers(self):
        record = self.gate(make_repo(self.tmp / "fixed"), make_repo(self.tmp / "faulty", bug=True))
        self.assertEqual(record["findings"], [])
        folder = self.tmp / "out/viewer"
        for name in ("index.html", viewer.EXPORT_NAME):
            payload = embedded((folder / name).read_text())
            self.assertTrue(payload["views"])
            for view in payload["views"]:
                self.assertEqual(view["comparison"], "REPAIRED")
                self.assertIsNone(view["findingId"])
                self.assertIsNone(view["firstFrame"])
                first, _ = viewer._first_difference(view)
                self.assertIsNotNone(first)
                for side, arm in (("before", "base"), ("after", "head")):
                    frames = view["frames"][side]
                    self.assertEqual([frame["frame"] for frame in frames], [first])
                    capture = self.tmp / "out-work" / arm / view["route"] / "frames" / f"f{first:08d}.png"
                    self.assertEqual(frames[0]["sha256"], hashlib.sha256(capture.read_bytes()).hexdigest())
                    if name == viewer.EXPORT_NAME:
                        data = base64.b64decode(frames[0]["path"].split(",", 1)[1], validate=True)
                    else:
                        data = (folder / frames[0]["path"]).read_bytes()
                    self.assertEqual(data, capture.read_bytes())
            self.assertNotIn(str(self.tmp), str(payload["views"]))

    def test_missing_unreadable_or_linked_capture_never_substitutes_a_neighbor(self):
        captures = self.tmp / "frames"
        captures.mkdir()
        valid = b"\x89PNG\r\n\x1a\n" + b"adjacent"
        (captures / "f00000019.png").write_bytes(valid)
        (captures / "f00000021.png").write_bytes(valid)
        target = self.tmp / "viewer"
        frame = captures / "f00000020.png"
        def kept(folder=captures):
            return viewer._repair_frame(folder, 20, target, "after-repair-0")
        self.assertEqual(kept(), [])
        frame.symlink_to(captures / "f00000021.png")
        self.assertEqual(kept(), [])
        frame.unlink()
        frame.write_bytes(b"invalid")
        self.assertEqual(kept(), [])
        frame.write_bytes(valid)
        link = self.tmp / "linked"
        link.symlink_to(captures, target_is_directory=True)
        self.assertEqual(kept(link), [])
        with mock.patch.object(viewer, "MAX_EXPORT_FRAME_BYTES", 1):
            self.assertEqual(kept(), [])
        self.assertFalse(target.exists())

    def test_existing_finding_keeps_its_share_of_both_frame_limits(self):
        self.gate(make_repo(self.tmp / "h", bug=True), make_repo(self.tmp / "b"))
        folder = self.tmp / "out/viewer"
        payload = embedded((folder / "index.html").read_text())
        finding = payload["views"][0]
        repaired = dict(copy.deepcopy(finding), comparison="REPAIRED", findingId=None, firstFrame=None)
        payload["views"] = [repaired, finding]
        first = finding["frames"]["after"][0]
        with mock.patch.object(viewer, "MAX_EXPORT_FRAME_BYTES", (folder / first["path"]).stat().st_size):
            exported = embedded(viewer.export(folder, payload).read_text())["views"]
            self.assertEqual(exported[0]["frames"], {"after": [], "before": []})
            self.assertEqual(exported[1]["frames"]["after"][0]["sha256"], first["sha256"])

        record = payload["record"]
        check = record["checks"][0]
        record["findings"] = [f for f in record["findings"] if f["id"] == check["findingId"]]
        record["checks"] = [dict(check, comparison="REPAIRED", findingId=None), check]
        timelines = {(check["spec"], check["route"]): {
            side: {"series": finding["series"][side], "_frames_dir": self.tmp / "out-work" / arm / check["route"] / "frames"}
            for side, arm in (("before", "base"), ("after", "head"))}}
        frames = {check["findingId"]: {side: (tl["_frames_dir"], finding["firstFrame"])
                                        for side, tl in timelines[check["spec"], check["route"]].items()}}
        with mock.patch.object(viewer, "MAX_FRAMED_FINDINGS", 1):
            rows = viewer.build_views(record, frames, timelines, self.tmp / "limited")
        self.assertEqual(rows[0]["frames"], {"after": [], "before": []})
        self.assertTrue(rows[1]["frames"]["before"])
