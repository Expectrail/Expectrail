""""Run it" (#265, slice 1): the samples manifest, the recorded vision answers, the offline run and
the publishing job's check.

No live Godot and no live model. Replays are the stand-ins of tests/test_two_observers.py (a position
log and real PNG frames). The recordings are made from the scripted stand-in model that answers in
SAM 3.1's wire format: they are not recordings of the live model. The real orchestrator, the real
gate under the two-observer rule, the real viewer and the real record reader judge them.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from agents.sam_observations import MetaSamClient, SamError
from expectrail import recorded, runit
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from tests.test_two_observers import SPEC, Game

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "run-it.yml"
# The seeded bug of the stand-in game: a file whose presence makes the stand-in replay sink.
BUG_PATCH = """--- a/BUG
+++ b/BUG
@@ -0,0 +1 @@
+1
"""


def make_root(root: Path) -> Path:
    """A copy of what a run reads: the manifest, its schemas, the game, the route, the check, the bug."""
    for rel in (runit.MANIFEST, runit.SAMPLES_SCHEMA, runit.RESULT_SCHEMA, "contracts/vision-recording.v1.schema.json",
                "harness/routes/smoke.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    game = root / "game" / "platformer"
    game.mkdir(parents=True)
    (game / "project.godot").write_text("[application]\n", encoding="utf-8")
    (root / "agents" / "specs").mkdir(parents=True)
    (root / "agents" / "specs" / "player-stays-above-ground.json").write_text(json.dumps(SPEC), encoding="utf-8")
    (root / "bugs" / "physics-fall-through").mkdir(parents=True)
    (root / "bugs" / "physics-fall-through" / "v1.patch").write_text(BUG_PATCH, encoding="utf-8")
    return root


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = make_root(self.tmp / "root")
        self.game = Game()
        self.game.look_of = lambda game: "BUG" if (game / "BUG").exists() else "clean"
        self.n = 0

    def quiet(self, fn, *a, **kw):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fn(*a, **kw)

    def run_sample(self, sample: str, **kw) -> tuple[dict, Path]:
        self.n += 1
        out = self.tmp / f"out{self.n}"
        doc = self.quiet(runit.run, sample, out, root=self.root, replay=self.game.replay, **kw)
        return doc, out

    def client(self) -> MetaSamClient:
        return MetaSamClient(transport=self.game.transport, retries=0, sleep=lambda s: None)

    def record(self, sample: str) -> dict:
        target = self.root / "docs" / "run-it" / "vision" / f"{sample}.json"
        self.quiet(runit.record, sample, target, run_id="test-1", client=self.client(), root=self.root,
                   replay=self.game.replay, recorded_at="2026-11-13")
        return recorded.read_recording(target)


class ManifestTest(Case):
    def test_the_shipped_manifest_has_the_three_samples(self):
        doc = runit.read_manifest(REPO)
        self.assertEqual([s["id"] for s in doc["samples"]], ["clean", "fall-through-bug", "fall-through-repair"])
        self.assertEqual([s["expected"] for s in doc["samples"]], ["accept", "reject", "accept"])
        self.assertEqual(json.loads((REPO / "contracts/examples/run-it-samples.json").read_text()), json.loads(
            (REPO / runit.MANIFEST).read_text()))

    def test_the_example_result_matches_its_schema(self):
        doc = json.loads((REPO / "contracts/examples/run-it-result.json").read_text())
        self.assertEqual(rec.errors(doc, json.loads((REPO / runit.RESULT_SCHEMA).read_text())), [])

    def test_only_a_manifest_id_is_accepted(self):
        manifest = runit.read_manifest(REPO)
        for bad in ("", "Clean", "../clean", "clean\n", "clean;rm", "a" * 41, None, ["clean"], "nope"):
            with self.subTest(bad=bad), self.assertRaises(runit.RunItError):
                runit.find_sample(manifest, bad)

    def test_a_bad_request_id_or_a_used_folder_runs_nothing(self):
        for bad in ("A", "x/y", "a" * 41, "id\n"):
            with self.subTest(bad=bad), self.assertRaises(runit.RunItError):
                runit.run("clean", self.tmp / "o", request_id=bad, root=self.root, replay=self.game.replay)
        used = self.tmp / "used"
        used.mkdir()
        (used / "x").write_text("1")
        with self.assertRaises(runit.RunItError):
            runit.run("clean", used, root=self.root, replay=self.game.replay)
        self.assertEqual(self.game.replays, [])

    def test_a_manifest_that_breaks_its_schema_is_refused(self):
        path = self.root / runit.MANIFEST
        doc = json.loads(path.read_text())
        for edit in (lambda d: d["samples"][0].update(id="Bad Id"),
                     lambda d: d["samples"][0].update(vision="docs/run-it/vision/other.json"),
                     lambda d: d.update(game="../elsewhere"),
                     lambda d: d["samples"].append(dict(d["samples"][0]))):
            with self.subTest(edit=edit):
                changed = json.loads(json.dumps(doc))
                edit(changed)
                path.write_text(json.dumps(changed))
                with self.assertRaises(runit.RunItError):
                    runit.read_manifest(self.root)


class WithoutRecordingTest(Case):
    def test_nothing_is_accepted_without_recorded_vision_answers(self):
        for sample, want in (("clean", "needs-review"), ("fall-through-bug", "reject"),
                             ("fall-through-repair", "needs-review")):
            with self.subTest(sample=sample):
                doc, out = self.run_sample(sample)
                self.assertEqual((doc["phase"], doc["decision"]), ("completed", want))
                self.assertTrue(doc["asExpected"])
                self.assertFalse(doc["vision"]["recorded"])
                self.assertEqual(doc["vision"]["why"], runit.NO_RECORDING)
                self.assertEqual(doc["receipt"], {"signed": False, "why": "not signed yet (#255)"})
                self.assertEqual(runit.check(out, sample_id=sample, request_id="local", root=self.root), [])
                self.assertEqual(rec.read_record(out / "findings.json")["decision"], want)
        self.assertEqual(self.game.asked, [])


class RecordedTest(Case):
    def test_recorded_answers_give_the_samples_their_decisions_and_ask_no_model(self):
        for sample, want in (("clean", "accept"), ("fall-through-bug", "reject"), ("fall-through-repair", "accept")):
            with self.subTest(sample=sample):
                recording = self.record(sample)
                self.assertEqual(recording["recordedAt"], "2026-11-13")
                self.assertGreater(len(recording["answers"]), 0)
                asked = len(self.game.asked)
                doc, out = self.run_sample(sample, request_id="0f6c1b2e-aaaa-4bbb-8ccc-123456789abc")
                self.assertEqual(len(self.game.asked), asked, "a recorded run asked the model")
                self.assertEqual((doc["decision"], doc["asExpected"]), (want, True))
                v = doc["vision"]
                self.assertEqual((v["recorded"], v["recordedAt"], v["run"], v["notRecorded"]), (True, "2026-11-13", "test-1", 0))
                self.assertGreater(v["answered"], 0)
                record = rec.read_record(out / "findings.json")
                self.assertEqual(record["observers"]["rule"], "both")
                self.assertEqual(record["observers"]["visual"]["name"], "sam-recorded")
                self.assertIn("recorded 2026-11-13, run test-1", record["observers"]["visual"]["provider"])
                self.assertEqual(runit.check(out, sample_id=sample, request_id="0f6c1b2e-aaaa-4bbb-8ccc-123456789abc",
                                             root=self.root), [])
                page = (out / "viewer" / "index.html").read_text(encoding="utf-8")
                self.assertIn("sam-recorded", page)

    def test_a_frame_not_in_the_recording_is_no_answer_and_needs_review(self):
        self.record("clean")
        # The replay now draws other pixels for the same frames: no answer about another picture.
        original = self.game.replay

        def other_pixels(route, game, out, frames):
            got = original(route, game, out, frames)
            if got["framesDir"] is not None:
                for f in sorted(Path(got["framesDir"]).glob("f*.png"))[40:41]:
                    data = f.read_bytes()
                    f.write_bytes(data + b"\0")   # a different file, so a different SHA256
            return got

        self.game.replay = other_pixels
        doc, out = self.run_sample("clean")
        self.assertEqual(doc["decision"], "needs-review")
        self.assertFalse(doc["asExpected"])
        self.assertGreater(doc["vision"]["notRecorded"], 0)
        self.assertIn("does not hold", doc["vision"]["why"])
        self.assertEqual(runit.check(out, sample_id="clean", request_id="local", root=self.root), [])

    def test_a_recording_for_another_sample_or_a_broken_one_is_not_used(self):
        recording = self.record("clean")
        path = self.root / "docs/run-it/vision/fall-through-repair.json"
        path.write_text(json.dumps(recording))
        doc, _ = self.run_sample("fall-through-repair")
        self.assertEqual((doc["decision"], doc["vision"]["why"]), ("needs-review", "the recording is for another sample"))
        path.write_text("{not json")
        doc, _ = self.run_sample("fall-through-repair")
        self.assertEqual(doc["decision"], "needs-review")
        self.assertIn("could not be used", doc["vision"]["why"])


class RecordedClientTest(Case):
    def recording(self) -> dict:
        return {"format": recorded.FORMAT, "sample": "clean", "recordedAt": "2026-11-13", "run": "1",
                "model": {"name": "sam-3.1", "provider": "meta-model-api"}, "answers": []}

    def test_only_the_recorded_frame_and_question_are_answered(self):
        png = self.tmp / "f.png"
        from tests.test_sam import png_bytes

        png.write_bytes(png_bytes(64, 64, 1))
        from agents.sam_observations import sha256_bytes

        doc = self.recording()
        doc["answers"] = [{"kind": "segment", "frameSha256": sha256_bytes(png), "prompt": "robot",
                           "detections": [{"box": [1, 2, 3, 4], "score": 0.9}]}]
        client = recorded.RecordedClient(doc)
        self.assertEqual(client.segment(png, "robot"), [{"box": [1, 2, 3, 4], "score": 0.9}])
        with self.assertRaises(SamError) as caught:
            client.segment(png, "robot.")
        self.assertEqual(caught.exception.kind, "not-recorded")
        other = self.tmp / "g.png"
        other.write_bytes(png_bytes(64, 64, 2))
        with self.assertRaises(SamError):
            client.segment(other, "robot")
        with self.assertRaises(SamError):
            client.segment_in(png, [(0, 0, 10, 10)])
        self.assertEqual((client.calls, client.answered, client.not_recorded), (4, 1, 3))

    def test_a_recording_that_breaks_the_rules_is_refused(self):
        sha = "a" * 64
        cases = {
            "twice": [{"kind": "segment", "frameSha256": sha, "prompt": "p", "detections": []}] * 2,
            "no score": [{"kind": "segment", "frameSha256": sha, "prompt": "p", "detections": [{"box": [0, 0, 1, 1], "score": None}]}],
            "null for a prompt": [{"kind": "segment", "frameSha256": sha, "prompt": "p", "detections": [None]}],
            "bad sha": [{"kind": "segment", "frameSha256": "A" * 64, "prompt": "p", "detections": []}],
            "score above 1": [{"kind": "segment", "frameSha256": sha, "prompt": "p", "detections": [{"box": [0, 0, 1, 1], "score": 1.5}]}],
        }
        for name, answers in cases.items():
            with self.subTest(name), self.assertRaises(recorded.RecordingError):
                recorded.check({**self.recording(), "answers": answers})
        for bad in ({**self.recording(), "recordedAt": "13 Nov"}, {**self.recording(), "format": "x"},
                    {**self.recording(), "extra": 1}):
            with self.assertRaises(recorded.RecordingError):
                recorded.check(bad)

    def test_the_example_recording_matches_its_schema(self):
        recorded.check(json.loads((REPO / "contracts/examples/vision-recording.json").read_text()))

    def test_the_observer_describes_itself_as_recorded(self):
        observer = recorded.RecordedObserver(self.recording())
        self.assertEqual(observer.describe(), {"name": "sam-recorded", "model": "sam-3.1",
                                               "provider": "meta-model-api (recorded 2026-11-13, run 1)"})

    def test_an_empty_recording_gives_no_answer(self):
        run = self.game.replay(Path("smoke.json"), self.tmp, self.tmp / "run", True)
        with self.assertRaisesRegex(gv.NoAnswer, "not-recorded"):
            recorded.RecordedObserver(self.recording()).look(SPEC, run)


class CheckTest(Case):
    def setUp(self):
        super().setUp()
        _, self.out = self.run_sample("fall-through-bug", request_id="req-1")

    def problems(self, **kw) -> list[str]:
        return runit.check(self.out, **{"sample_id": "fall-through-bug", "request_id": "req-1", "root": self.root, **kw})

    def test_a_good_folder_passes(self):
        self.assertEqual(self.problems(), [])

    def test_other_ids_are_refused(self):
        self.assertTrue(self.problems(request_id="req-2"))
        self.assertTrue(self.problems(sample_id="clean"))
        self.assertTrue(self.problems(request_id="../x"))

    def test_anything_outside_the_allowlist_is_refused(self):
        for rel, data in (("run.sh", b"#!/bin/sh"), ("viewer/frames/x.js", b"1"), ("viewer/other.html", b"<!doctype html>"),
                          (".github/workflows/x.yml", b"on: push"), ("viewer/frames/after-a-00000001.svg", b"<svg/>")):
            with self.subTest(rel=rel):
                p = self.out / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                self.assertTrue(any("not a file the site publishes" in x for x in self.problems()))
                p.unlink()
        self.assertEqual(self.problems(), [])

    def test_links_and_wrong_contents_are_refused(self):
        (self.out / "findings.json").rename(self.tmp / "f.json")
        os.symlink(self.tmp / "f.json", self.out / "findings.json")
        self.assertTrue(any("not a plain file" in x for x in self.problems()))
        (self.out / "findings.json").unlink()
        shutil.copy(self.tmp / "f.json", self.out / "findings.json")
        frame = self.out / "viewer" / "frames" / "after-x-00000001.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"<script>")
        self.assertTrue(any("not a PNG" in x for x in self.problems()))
        frame.unlink()
        page = self.out / "viewer" / "index.html"
        original = page.read_text(encoding="utf-8")
        page.write_text("<!doctype html><script>fetch('https://evil.example')</script>", encoding="utf-8")
        self.assertTrue(any("Content-Security-Policy" in x for x in self.problems()))
        page.write_text(original, encoding="utf-8")
        self.assertEqual(self.problems(), [])

    def test_a_status_that_disagrees_with_its_findings_is_refused(self):
        path = self.out / "status.json"
        doc = json.loads(path.read_text())
        for edit, why in ((dict(decision="accept"), "disagree about the decision"),
                          (dict(findings=None), "disagree about findings.json"),
                          (dict(phase="failed"), "did not complete"),
                          (dict(receipt={"signed": True, "why": "x"}), "schema")):
            with self.subTest(why=why):
                path.write_text(json.dumps({**doc, **edit}))
                self.assertTrue(any(why in x for x in self.problems()), self.problems())
        path.write_text(json.dumps(doc))
        (self.out / "findings.json").unlink()
        path.write_text(json.dumps({**doc, "findings": None, "decision": "accept"}))
        self.assertTrue(any("no findings record" in x for x in self.problems()))

    def test_too_large_is_refused(self):
        big = self.out / "viewer" / "frames" / "after-x-00000002.png"
        big.parent.mkdir(parents=True, exist_ok=True)
        big.write_bytes(runit.PNG_SIGNATURE + b"\0" * runit.MAX_FILE_BYTES)
        self.assertTrue(any("larger than" in x for x in self.problems()))

    def test_the_command_line_says_refused(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runit.main(["check", str(self.out), "--sample", "clean", "--request-id", "req-1"]), 1)
        self.assertIn("refused: status.json is for another sample", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runit.main(["run", "--sample", "../x", "--out", str(self.tmp / "z")]), 2)
        self.assertFalse((self.tmp / "z").exists())


class WorkflowTest(unittest.TestCase):
    """What run-it.yml must keep: the verify job holds no secret and writes nothing, the publish job
    runs no sample code, both inputs are checked before anything is checked out."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)
        cls.on = cls.doc.get("on", cls.doc.get(True))

    def test_only_a_dispatch_with_two_inputs_starts_it(self):
        self.assertEqual(list(self.on), ["workflow_dispatch"])
        self.assertEqual(set(self.on["workflow_dispatch"]["inputs"]), {"sample", "request_id"})
        self.assertEqual(self.doc["permissions"], {})
        self.assertEqual(self.doc["concurrency"], {"group": "run-it", "cancel-in-progress": False})

    def test_the_verify_job_holds_no_secret_and_reads_only(self):
        job = self.doc["jobs"]["verify"]
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["timeout-minutes"], 15)
        self.assertNotIn("environment", job)
        body = yaml.safe_dump(job)
        self.assertNotIn("secrets.", body)
        self.assertNotIn("github.token", body)
        self.assertIn("--require-sandbox", body)
        steps = job["steps"]
        self.assertIn("Check the inputs", steps[0]["name"])
        for step in steps:
            if step.get("uses", "").startswith("actions/checkout"):
                self.assertEqual(step["with"]["persist-credentials"], False)

    def test_the_publish_job_runs_no_sample_code(self):
        job = self.doc["jobs"]["publish"]
        self.assertEqual(job["permissions"], {"contents": "write"})
        self.assertEqual(job["timeout-minutes"], 5)
        self.assertNotIn("environment", job)
        self.assertEqual(job["needs"], "verify")
        body = yaml.safe_dump(job)
        for never in ("godot", "harness", "runit run", "pip install", "get-godot", "apt-install", "secrets."):
            self.assertNotIn(never, body)
        names = [s.get("name", "") for s in job["steps"]]
        self.assertIn("Check the inputs", names[0])
        check = next(i for i, s in enumerate(job["steps"]) if "expectrail.runit check" in s.get("run", ""))
        push = next(i for i, s in enumerate(job["steps"]) if "run-it-results" in s.get("run", ""))
        self.assertLess(check, push)

    def test_inputs_reach_shells_only_through_the_environment(self):
        for job in self.doc["jobs"].values():
            for step in job["steps"]:
                self.assertNotRegex(step.get("run", ""), r"\$\{\{\s*(inputs|github\.event)\.")
        self.assertIn("^[a-z0-9-]{1,40}$", self.text)

    def test_actions_are_pinned(self):
        for job in self.doc["jobs"].values():
            for step in job["steps"]:
                uses = step.get("uses", "")
                if uses and not uses.startswith("./"):
                    self.assertRegex(uses, r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
