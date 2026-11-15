"""The viewer compares recorded measurements and still has readable evidence without scripts."""
import base64
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from expectrail import viewer
from tests.test_viewer import embedded

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
