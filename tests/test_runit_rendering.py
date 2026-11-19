"""A Run it result names the rendering environment its frames were drawn in (#265, with #515).

Sample recordings answer by exact image bytes. One LLVM step on the runner changes a few pixels
(#515), so a run then gets needs-review. These tests hold that the published result says which
environment drew the frames, beside the recording's, and that a recording which names none says so
in plain words. Provenance never supplies an answer and never changes a verdict.

No engine, model or network: the stand-in replay of tests/test_two_observers.py and the renderer
fixtures of tests/test_recorded_renderer.py.
"""
import contextlib
import copy
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.sam_observations import SamError
from expectrail import recorded, runit
from expectrail.gate import record as rec
from tests import test_runit as runit_tests
from tests import test_two_observers as observers_tests
from tools import runit_published, runit_smoke

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures/recorded-renderer"
RECORDING = ROOT / "tests/outside/recordings/kinematic-character/vision-recording.json"
OLD = json.loads((FIXTURES / "recorded-replay.json").read_text())["engine"]
NEW = json.loads((FIXTURES / "replayed-replay.json").read_text())["engine"]
POINT = [(488, 329)]
SCHEMA = json.loads((ROOT / runit.RESULT_SCHEMA).read_text(encoding="utf-8"))


class ClientTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "frames").mkdir()
        self.png = self.root / "frames" / "f00000111.png"
        self.doc = recorded.read_recording(RECORDING)
        self.legacy = copy.deepcopy(self.doc)
        self.legacy.pop("renderingEnvironments")

    def capture(self, image="recorded.png", environment=OLD):
        shutil.copyfile(FIXTURES / image, self.png)
        replay = self.root / "replay.json"
        if environment is None:
            replay.unlink(missing_ok=True)
        else:
            replay.write_text(json.dumps({"format": "expectrail.replay/v0", "engine": environment}))
        return self.png

    def test_a_recording_that_names_no_environment_says_so_and_names_this_replays(self):
        client = recorded.RecordedClient(self.legacy)
        with self.assertRaises(SamError) as caught:
            client.segment_at(self.capture("replayed.png", NEW), POINT)
        said = str(caught.exception)
        self.assertEqual(caught.exception.kind, "not-recorded")
        self.assertIn("the recording does not name the rendering environment it was made in", said)
        self.assertIn("llvmpipe (LLVM 19.1.7", said)
        # The kind comes first: readers that cut a long reason short still see it (release gate).
        self.assertIn("not-recorded", said[:60])
        self.assertNotIn("recorded under", said)   # it never guesses the recording's environment
        self.assertEqual(client.last_missing_reason, said)
        self.assertLessEqual(len(said), 300)

    def test_a_long_environment_keeps_the_reason_short(self):
        client = recorded.RecordedClient(self.legacy)
        with self.assertRaises(SamError) as caught:
            client.segment_at(self.capture("replayed.png", dict(NEW, device="x" * 160, renderer="y" * 160)), POINT)
        self.assertLessEqual(len(str(caught.exception)), 300)
        self.assertTrue(str(caught.exception).startswith("no exact image answer (not-recorded): "))

    def test_without_this_replays_environment_the_reason_stays_the_plain_one(self):
        client = recorded.RecordedClient(self.legacy)
        with self.assertRaises(SamError) as caught:
            client.segment_at(self.capture("replayed.png", None), POINT)
        self.assertIn("does not hold this frame and question", str(caught.exception))

    def test_a_known_frame_with_another_question_is_not_blamed_on_the_environment(self):
        with self.assertRaises(SamError) as caught:
            recorded.RecordedClient(self.legacy).segment_at(self.capture(environment=NEW), [(0, 0)])
        self.assertIn("does not hold this frame and question", str(caught.exception))

    def test_rendering_compares_this_replay_with_the_recording(self):
        cases = (
            (self.doc, OLD, "match", [OLD]),
            (self.doc, NEW, "mismatch", [OLD]),
            (self.legacy, NEW, "unknown", None),
            (self.doc, None, "unavailable", [OLD]),
            (self.doc, {"name": "godot", "version": OLD["version"]}, "unavailable", [OLD]),
        )
        for doc, environment, status, recording in cases:
            with self.subTest(status=status, environment=environment):
                client = recorded.RecordedClient(doc)
                # The same recorded image in every case: provenance never decides whether it is answered.
                found = client.segment_at(self.capture(environment=environment), POINT)
                self.assertEqual(len(found), 1)
                rendering = client.rendering()
                self.assertEqual(rendering["status"], status)
                self.assertEqual(rendering["recording"], recording)
                complete = environment and all(environment.get(k) for k in ("name", "version", "renderer", "device"))
                if environment is None:
                    self.assertEqual(rendering["thisRun"], [])
                elif complete:
                    self.assertEqual(rendering["thisRun"], [environment])

    def test_one_frame_drawn_elsewhere_makes_the_whole_run_a_mismatch(self):
        client = recorded.RecordedClient(self.doc)
        client.segment_at(self.capture(environment=OLD), POINT)
        client.segment_at(self.capture(environment=NEW), POINT)
        self.assertEqual(client.rendering()["status"], "mismatch")
        self.assertCountEqual(client.rendering()["thisRun"], [OLD, NEW])

    def test_one_frame_with_no_environment_makes_a_match_unavailable(self):
        client = recorded.RecordedClient(self.doc)
        client.segment_at(self.capture(environment=OLD), POINT)
        client.segment_at(self.capture(environment=None), POINT)
        self.assertEqual(client.rendering()["status"], "unavailable")

    def test_nothing_asked_is_unavailable(self):
        self.assertEqual(recorded.RecordedClient(self.doc).rendering(),
                         {"thisRun": [], "recording": [OLD], "status": "unavailable"})

    def test_a_partly_named_recording_cannot_be_compared(self):
        doc = copy.deepcopy(self.doc)
        doc["renderingEnvironments"] = [OLD, None]
        client = recorded.RecordedClient(doc)
        client.segment_at(self.capture(environment=OLD), POINT)
        self.assertEqual(client.rendering(), {"thisRun": [OLD], "recording": [OLD, None], "status": "unknown"})

    def test_sentence(self):
        said = recorded.rendering_sentence({"thisRun": [NEW], "recording": None, "status": "unknown"})
        self.assertIn("does not name", said)
        self.assertIn("19.1.7", said)
        said = recorded.rendering_sentence({"thisRun": [NEW], "recording": [OLD], "status": "mismatch"})
        self.assertIn("20.1.2", said)
        self.assertIn("19.1.7", said)
        self.assertIn("same as the recording",
                      recorded.rendering_sentence({"thisRun": [OLD], "recording": [OLD], "status": "match"}))
        self.assertIn("not reported",
                      recorded.rendering_sentence({"thisRun": [], "recording": [OLD], "status": "unavailable"}))


class RunItTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = runit_tests.make_root(self.tmp / "repo")
        self.game = observers_tests.Game()
        self.environment = OLD
        self.drift = False
        self.n = 0

    def replay(self, route, project, out, frames):
        got = self.game.replay(route, project, out, frames)
        if self.environment is not None:
            (out / "replay.json").write_text(json.dumps({"format": "expectrail.replay/v0", "engine": self.environment}))
        if self.drift and got["framesDir"] is not None:
            from tests.test_sam import png_bytes
            (Path(got["framesDir"]) / "f00000011.png").write_bytes(png_bytes(64, 64, 515))
        return got

    def record(self):
        target = self.repo / "docs/run-it/vision/clean.json"
        with contextlib.redirect_stdout(io.StringIO()):
            runit.record("clean", target, root=self.repo, client=self.game.observer()._client,
                         replay=self.replay, run_id="offline", recorded_at="2026-11-15")
        return target

    def run_clean(self):
        self.n += 1
        out = self.tmp / f"out{self.n}"
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("live model")):
            doc = runit.run("clean", out, root=self.repo, replay=self.replay, request_id=f"r-{self.n}")
        self.assertEqual(rec.errors(doc, SCHEMA), [])
        self.assertEqual(runit.check(out, sample_id="clean", request_id=f"r-{self.n}", root=self.repo), [])
        self.assertEqual(json.loads((out / "status.json").read_text()), doc)
        return doc

    def test_a_run_on_the_recordings_environment_says_match_and_accepts(self):
        self.record()
        doc = self.run_clean()
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual(doc["vision"]["rendering"], {"thisRun": [OLD], "recording": [OLD], "status": "match"})

    def test_drift_under_a_recording_with_no_environment_is_needs_review_and_says_why(self):
        target = self.record()
        legacy = json.loads(target.read_text())
        legacy.pop("renderingEnvironments")
        target.write_text(json.dumps(legacy))
        self.environment, self.drift = NEW, True
        doc = self.run_clean()
        self.assertEqual(doc["decision"], "needs-review")
        v = doc["vision"]
        self.assertGreater(v["notRecorded"], 0)
        self.assertEqual(v["rendering"], {"thisRun": [NEW], "recording": None, "status": "unknown"})
        self.assertIn("does not name the rendering environment", v["why"])
        self.assertIn("19.1.7", v["why"])

    def test_a_drifted_runner_is_named_against_the_recordings(self):
        self.record()
        self.environment, self.drift = NEW, True
        doc = self.run_clean()
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["vision"]["rendering"]["status"], "mismatch")
        self.assertIn("recorded under llvmpipe LLVM 20.1.2", doc["vision"]["why"])

    def test_the_same_bytes_from_another_environment_are_still_answered_exactly(self):
        self.record()
        self.environment = NEW
        doc = self.run_clean()
        self.assertEqual((doc["decision"], doc["vision"]["notRecorded"]), ("accept", 0))
        self.assertEqual(doc["vision"]["rendering"]["status"], "mismatch")

    def test_a_long_reason_is_cut_to_the_schemas_cap(self):
        self.record()
        long = dict(NEW, device="x" * 160, renderer="y" * 160)
        target = self.repo / "docs/run-it/vision/clean.json"
        legacy = json.loads(target.read_text())
        legacy.pop("renderingEnvironments")
        target.write_text(json.dumps(legacy))
        self.environment, self.drift = long, True
        doc = self.run_clean()
        self.assertLessEqual(len(doc["vision"]["why"]), 300)

    def test_a_result_with_a_malformed_rendering_block_is_refused(self):
        self.record()
        doc = self.run_clean()
        for bad in ({"thisRun": [OLD], "recording": [OLD], "status": "close enough"},
                    {"thisRun": [dict(OLD, extra="1")], "recording": None, "status": "unknown"},
                    {"thisRun": [OLD] * 9, "recording": None, "status": "unknown"},
                    {"thisRun": [dict(OLD, device="\n")], "recording": None, "status": "unknown"},
                    {"thisRun": [OLD], "status": "match"}):
            with self.subTest(bad=bad):
                broken = copy.deepcopy(doc)
                broken["vision"]["rendering"] = bad
                self.assertTrue(rec.errors(broken, SCHEMA))

    def test_a_result_from_before_this_field_still_reads(self):
        example = json.loads((ROOT / "contracts/examples/run-it-result.json").read_text())
        self.assertEqual(rec.errors(example, SCHEMA), [])
        self.assertIn("rendering", example["vision"])
        example["vision"].pop("rendering")
        self.assertEqual(rec.errors(example, SCHEMA), [])
        for name in ("builder1-recorded-bug", "builder1-recorded-clean", "builder1-recorded-repair"):
            earlier = json.loads((ROOT / "docs/run-it/earlier" / name / "status.json").read_text())
            self.assertEqual(rec.errors(earlier, SCHEMA), [], name)


class PageCompareTest(unittest.TestCase):
    def status(self, rendering):
        from tests.test_runit_smoke import STATUS
        status = copy.deepcopy(STATUS)
        if rendering is not None:
            status["vision"]["rendering"] = rendering
        return status

    def page(self, line):
        from tests.test_runit_smoke import PAGE
        page = copy.deepcopy(PAGE)
        if line is not None:
            page["facts"]["Rendering"] = line
        return page

    def compare(self, status, page):
        return runit_smoke.compare(status, page, label="clean", earlier=False, evidence=True)

    def test_the_rendering_line_must_say_what_status_json_says(self):
        for status_word, rendering in (
                ("match", {"thisRun": [OLD], "recording": [OLD], "status": "match"}),
                ("mismatch", {"thisRun": [NEW], "recording": [OLD], "status": "mismatch"}),
                ("unknown", {"thisRun": [NEW], "recording": None, "status": "unknown"}),
                ("unavailable", {"thisRun": [], "recording": [OLD], "status": "unavailable"})):
            with self.subTest(status=status_word):
                right = recorded.rendering_sentence(rendering)
                self.assertEqual(self.compare(self.status(rendering), self.page(right)), [])
                self.assertTrue(self.compare(self.status(rendering), self.page(None)))
                wrong = "Drawn with the same rendering environment as the recording."
                if status_word != "match":
                    self.assertTrue(self.compare(self.status(rendering), self.page(wrong)))

    def test_no_rendering_block_means_no_line(self):
        self.assertEqual(self.compare(self.status(None), self.page(None)), [])
        self.assertTrue(self.compare(self.status(None), self.page("Drawn with something.")))


class NightlyNoteTest(unittest.TestCase):
    def test_the_nightly_reports_the_rendering_environment_and_says_when_it_is_absent(self):
        rendering = {"thisRun": [NEW], "recording": None, "status": "unknown"}
        note = runit_published.rendering_note({"rendering": rendering})
        self.assertTrue(note.startswith("; rendering unknown: Drawn with Mesa - llvmpipe (LLVM 19.1.7"), note)
        self.assertEqual(runit_published.rendering_note({}), "; rendering environment not in this result")


NODE = shutil.which("node")
PAGE_JS = ROOT / "docs/run-it/run-it.js"


@unittest.skipIf(NODE is None, "Node is not installed (the ubuntu-24.04 runners have it)")
class PageWordsTest(unittest.TestCase):
    """The page's own renderingLine, run under Node, says exactly what rendering_sentence says."""

    def page_lines(self, cases):
        source = PAGE_JS.read_text(encoding="utf-8")
        start, end = source.index("  var ENV_KEYS"), source.index("  // status.json, read defensively")
        is_obj = next(line for line in source.splitlines() if "function isObj(" in line)
        script = (is_obj + "\n" + source[start:end] + "\nconst cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
                  "\nprocess.stdout.write(JSON.stringify(cases.map(renderingLine)));")
        proc = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_every_status_has_the_same_words_on_the_page(self):
        partial = {"name": "godot", "version": None, "renderer": "opengl3", "device": None}
        good = [{"thisRun": [OLD], "recording": [OLD], "status": "match"},
                {"thisRun": [OLD, NEW], "recording": [OLD], "status": "mismatch"},
                {"thisRun": [NEW], "recording": None, "status": "unknown"},
                {"thisRun": [OLD], "recording": [OLD, None], "status": "unknown"},
                {"thisRun": [], "recording": None, "status": "unknown"},
                {"thisRun": [], "recording": [OLD], "status": "unavailable"},
                {"thisRun": [partial], "recording": [OLD], "status": "unavailable"}]
        self.assertEqual(self.page_lines(good), [recorded.rendering_sentence(r) for r in good])

    def test_anything_malformed_shows_no_line(self):
        bad = [None, "match", {"thisRun": [OLD], "recording": [OLD], "status": "close enough"},
               {"thisRun": [dict(OLD, extra="1")], "recording": None, "status": "unknown"},
               {"thisRun": [OLD] * 9, "recording": None, "status": "unknown"},
               {"thisRun": [dict(OLD, device="<b>\n")], "recording": None, "status": "unknown"},
               {"thisRun": [OLD], "recording": "OLD", "status": "match"},
               {"thisRun": [None], "recording": None, "status": "unknown"},
               {"thisRun": [NEW], "recording": None, "status": "mismatch"}]
        self.assertEqual(self.page_lines(bad), [None] * len(bad))

    def test_the_line_is_a_fact_after_vision_and_never_touches_the_verdict(self):
        source = PAGE_JS.read_text(encoding="utf-8")
        start = source.index("function verdictOf")
        verdict = source[start:source.index("\n  }\n", start)]
        self.assertIn('status.decision === "accept"', verdict)
        self.assertNotIn("rendering", verdict.lower())
        show = source[source.index("function showResult"):]
        self.assertLess(show.index('fact(facts, "Vision"'), show.index('fact(facts, "Rendering"'))


if __name__ == "__main__":
    unittest.main()
