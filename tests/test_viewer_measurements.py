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
