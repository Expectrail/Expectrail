import json
import tempfile
import unittest
from pathlib import Path

from expectrail import approval
from expectrail.contracts import validate
from expectrail.spec_writer import SpecDraftError, approve, draft, lint, request_body

GOOD = {
    "id": "player-stays-above-ground",
    "objects": {"player": {"prompt": "small robot character"}, "ground": {"prompt": "grass-topped ground"}},
    "assertion": {"type": "never-crosses", "object": "player",
                  "boundary": {"relativeTo": "ground", "edge": "top", "side": "above", "tolerancePx": 12}},
}


def reply(doc):
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(doc)}}]}


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class DraftTest(unittest.TestCase):
    def test_a_good_draft_is_validated_and_unapproved(self):
        t = FakeTransport(reply(GOOD))
        spec, problems = draft("The player never falls through the ground.", transport=t)
        self.assertEqual(problems, [])
        self.assertEqual(validate(spec), "test-spec")
        self.assertNotIn("approval", spec)
        self.assertEqual(spec["instruction"], "The player never falls through the ground.")
        body = t.bodies[0]
        self.assertEqual(body["model"], "muse-spark-1.3")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(body["temperature"], 0)

    def test_a_bad_draft_is_retried_with_the_problems(self):
        bad = json.loads(json.dumps(GOOD))
        bad["objects"]["ground"]["prompt"] = "ground below the player"
        t = FakeTransport(reply(bad), reply(GOOD))
        spec, problems = draft("The player never falls through the ground.", transport=t)
        self.assertIsNotNone(spec)
        self.assertIn("describes a position", t.bodies[1]["messages"][-1]["content"])

    def test_two_bad_drafts_need_review(self):
        bad = dict(json.loads(json.dumps(GOOD)), assertion={"type": "looks-right", "object": "player"})
        spec, problems = draft("The game looks right.", transport=FakeTransport(reply(bad), reply(bad)))
        self.assertIsNone(spec)
        self.assertTrue(problems)

    def test_unsupported_checks_are_reported_not_forced(self):
        spec, problems = draft("The music feels upbeat.", transport=FakeTransport(reply({"unsupported": "audio"})))
        self.assertIsNone(spec)
        self.assertIn("unsupported", problems[0])

    def test_falls_back_to_plain_json_when_schema_output_is_rejected(self):
        t = FakeTransport(SpecDraftError("HTTP 400: response_format json_schema not supported"), reply(GOOD))
        spec, _ = draft("The player never falls through the ground.", transport=t)
        self.assertIsNotNone(spec)
        self.assertEqual(t.bodies[1]["response_format"], {"type": "json_object"})

    def test_contributor_models_are_refused_by_default(self):
        with self.assertRaises(SpecDraftError):
            draft("x", model="muse-spark-1.3-contributor", transport=FakeTransport())

    def test_markdown_fences_are_tolerated(self):
        fenced = {"choices": [{"message": {"content": "```json\n" + json.dumps(GOOD) + "\n```"}}]}
        spec, _ = draft("The player never falls through the ground.", transport=FakeTransport(fenced))
        self.assertIsNotNone(spec)

    def test_the_request_carries_one_worked_example(self):
        body = request_body("x", "muse-spark-1.3")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])


class ApproveTest(unittest.TestCase):
    def test_approval_is_added_only_to_a_clean_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            spec = dict(json.loads(json.dumps(GOOD)), format="expectrail.test-spec/v0", instruction="x")
            path.write_text(json.dumps(spec))
            doc = approve(path, "sean", at="2026-10-27T15:00:00Z")
            # The approval carries the digest of what was approved (#420), computed by approve.
            self.assertEqual(doc["approval"], {"by": "sean", "at": "2026-10-27T15:00:00Z",
                                               "specSha256": approval.spec_sha256(doc)})
            self.assertEqual(json.loads(path.read_text())["approval"]["by"], "sean")
            spec["objects"]["player"]["prompt"] = "robot on the left"
            path.write_text(json.dumps(spec))
            with self.assertRaises(SpecDraftError):
                approve(path, "sean")

    def test_the_committed_specs_are_lint_clean(self):
        for path in sorted((Path(__file__).resolve().parent.parent / "specs").glob("*.json")):
            with self.subTest(spec=path.name):
                doc = json.loads(path.read_text())
                self.assertEqual(validate(doc), "test-spec")
                # An approved spec carries who approved it and when; the rest must still lint
                # clean as a draft would.
                approval = doc.pop("approval", None)
                if approval is not None:
                    self.assertEqual(sorted(approval), ["at", "by"])
                    self.assertTrue(approval["by"].strip())
                self.assertEqual(lint(doc), [])


if __name__ == "__main__":
    unittest.main()
