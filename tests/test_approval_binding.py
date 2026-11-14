"""An approval binds to the spec's content (issue #420): the digest, the writer that computes it, and
every reader that decides whether a spec is approved (the gate, the Spark comparison, the comment and
the merge guard). No Godot: the gate's replays are the fixture traces, as in tests/test_ci_gate.py."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import jsonschema

from agents import spark_open
from expectrail import approval
from expectrail.gate import comment as gc
from expectrail.gate import verify as gv
from expectrail.spec_writer import SpecDraftError, approve
from tests.test_ci_gate import FakeReplay, ctx, head_example, make_repo
from tools import merge_guard as mg

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
SCHEMA = REPO / "contracts" / "test-spec.schema.json"


def body() -> dict:
    """The live spec without its approval: what a person would approve."""
    doc = json.loads(SPEC.read_text(encoding="utf-8"))
    doc.pop("approval", None)
    return doc


def approved(doc: dict | None = None, by: str = "sean", at: str = "2026-11-14T00:00:00Z") -> dict:
    """``doc`` approved through the writer a person runs, in a temporary file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "spec.json"
        path.write_text(json.dumps(doc if doc is not None else body()), encoding="utf-8")
        return approve(path, by, at=at)


class DigestTest(unittest.TestCase):
    def test_whitespace_and_key_order_do_not_change_the_digest(self):
        doc = approved()
        compact = json.dumps(doc, separators=(",", ":"))
        spread = json.dumps(dict(reversed(list(doc.items()))), indent=7)
        for text in (compact, spread):
            with self.subTest(text=text[:40]):
                again = json.loads(text)
                self.assertEqual(approval.spec_sha256(again), doc["approval"]["specSha256"])
                self.assertEqual(approval.state(again), approval.BOUND)

    def test_the_digest_leaves_out_the_approval_and_covers_everything_else(self):
        doc = approved()
        other = copy.deepcopy(doc)
        other["approval"] = {"by": "someone-else", "at": "2030-01-01T00:00:00Z"}
        self.assertEqual(approval.spec_sha256(other), approval.spec_sha256(doc))
        self.assertEqual(approval.canonical(doc), approval.canonical(body()))

    def test_every_edit_of_the_body_makes_the_approval_not_count(self):
        edits = {
            "the tolerance": lambda d: d["assertion"]["boundary"].update(tolerancePx=200),
            "the window": lambda d: d["window"].update(toFrame=1),
            "the assertion's object": lambda d: d["assertion"].update(object="ground"),
            "a prompt": lambda d: d["objects"]["player"].update(prompt="anything"),
            "the instruction": lambda d: d.update(instruction="The player may fall."),
            "the id": lambda d: d.update(id="another-check"),
            "a coverage block": lambda d: d.update(coverage={"minFrames": 1}),
            "a number written as a float": lambda d: d["assertion"]["boundary"].update(tolerancePx=12.0),
        }
        doc = approved()
        for label, edit in edits.items():
            with self.subTest(label):
                edited = copy.deepcopy(doc)
                edit(edited)
                self.assertEqual(approval.state(edited), approval.MISMATCH)
                self.assertFalse(approval.approved(edited))

    def test_an_approval_copied_from_another_spec_does_not_match(self):
        first = approved()
        other = body()
        other["id"] = "player-other-check"
        other["approval"] = copy.deepcopy(first["approval"])
        self.assertEqual(approval.state(other), approval.MISMATCH)

    def test_an_approval_without_a_digest_still_counts_and_is_named(self):
        doc = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertNotIn("specSha256", doc["approval"])
        self.assertEqual(approval.state(doc), approval.LEGACY)
        self.assertTrue(approval.approved(doc))
        self.assertEqual(approval.note(doc["id"], approval.LEGACY),
                         "spec player-stays-above-ground: approved before content binding")

    def test_anything_that_is_not_a_matching_digest_is_no_approval(self):
        doc = approved()
        cases = {
            "null": None, "a number": 7, "upper case": doc["approval"]["specSha256"].upper(),
            "empty": "", "not ascii": "é" * 64, "a prefix": doc["approval"]["specSha256"][:32],
        }
        for label, value in cases.items():
            with self.subTest(label):
                bad = copy.deepcopy(doc)
                bad["approval"]["specSha256"] = value
                self.assertEqual(approval.state(bad), approval.MISMATCH)
        not_a_dict = dict(body(), approval="sean")
        self.assertEqual(approval.state(not_a_dict), approval.MISMATCH)
        nan = copy.deepcopy(doc)
        nan["assertion"]["boundary"]["tolerancePx"] = float("nan")
        self.assertEqual(approval.state(nan), approval.MISMATCH)

    def test_no_approval_is_a_draft(self):
        for doc in (body(), dict(body(), approval=None), dict(body(), approval={}), "not a spec"):
            self.assertEqual(approval.state(doc), approval.NONE)
            self.assertFalse(approval.approved(doc))


class WriterAndSchemaTest(unittest.TestCase):
    def test_approve_writes_the_digest_and_the_file_reads_back_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(body()), encoding="utf-8")
            approve(path, "sean", at="2026-11-14T00:00:00Z")
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertRegex(doc["approval"]["specSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(approval.state(doc), approval.BOUND)

    def test_approving_again_after_an_edit_binds_to_the_new_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(approved()), encoding="utf-8")
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["window"]["toFrame"] = 60
            path.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(approval.state(json.loads(path.read_text())), approval.MISMATCH)
            approve(path, "sean", at="2026-11-15T00:00:00Z")
            self.assertEqual(approval.state(json.loads(path.read_text())), approval.BOUND)

    def test_a_spec_that_cannot_be_digested_is_not_approved(self):
        doc = body()
        doc["assertion"]["boundary"]["tolerancePx"] = float("inf")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(doc), encoding="utf-8")  # Python writes Infinity
            with self.assertRaises(SpecDraftError):
                approve(path, "sean")
            self.assertNotIn("approval", json.loads(path.read_text(encoding="utf-8").replace("Infinity", "1")))

    def test_the_schema_takes_a_digest_and_refuses_one_that_is_not_hex(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        doc = approved()
        jsonschema.validate(doc, schema)
        jsonschema.validate(json.loads(SPEC.read_text(encoding="utf-8")), schema)  # an approval from before
        for bad in ("XYZ", doc["approval"]["specSha256"].upper(), 12):
            with self.subTest(bad=bad):
                wrong = copy.deepcopy(doc)
                wrong["approval"]["specSha256"] = bad
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(wrong, schema)

    def test_the_comment_knows_the_same_words_as_the_approval_module(self):
        self.assertEqual(gc.APPROVAL_NOTE_ENDINGS, (": " + approval.MISMATCH_REASON, ": " + approval.LEGACY_NOTE))


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="approval-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def gate(self, head: Path) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                               out=self.tmp / "out", work=self.tmp / "work", base=None, heldout=None,
                               pr={"number": 7, "headSha": "1" * 40, "baseSha": None}, replay=FakeReplay())

    def write(self, repo: Path, name: str, doc: dict) -> None:
        (repo / "specs" / name).write_text(json.dumps(doc, indent=2), encoding="utf-8")

    def test_the_reader_counts_an_edited_approved_spec_with_the_drafts_and_says_why(self):
        repo = make_repo(self.tmp / "repo")
        bound = approved(dict(body(), id="bound-check"))
        edited = approved(dict(body(), id="edited-check"))
        edited["assertion"]["boundary"]["tolerancePx"] = 400
        copied = dict(body(), id="copied-check", approval=copy.deepcopy(bound["approval"]))
        for doc in (bound, edited, copied):
            self.write(repo, doc["id"] + ".json", doc)
        checks = gv.read_checks(repo, "specs", ["routes/*.json"])
        self.assertEqual([s["id"] for s in checks.specs], ["bound-check", "player-stays-above-ground"])
        self.assertEqual(checks.drafts, 2)
        self.assertEqual(checks.problems, [])
        self.assertEqual(checks.approval_notes, [
            "spec copied-check: " + approval.MISMATCH_REASON,
            "spec edited-check: " + approval.MISMATCH_REASON,
            "spec player-stays-above-ground: " + approval.LEGACY_NOTE,
        ])

    def test_when_the_only_spec_was_edited_after_approval_nothing_is_accepted(self):
        repo = make_repo(self.tmp / "repo")
        edited = approved()
        edited["window"]["toFrame"] = 10
        self.write(repo, "player-stays-above-ground.json", edited)
        doc = self.gate(repo)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual((doc["specs"], doc["drafts"], doc["counts"]["checks"]), ([], 1, 0))
        self.assertIn("spec player-stays-above-ground: " + approval.MISMATCH_REASON, doc["reasons"])
        body_text = gc.render(doc, ctx())
        self.assertIn("approval does not match the spec", body_text)

    def test_a_bound_spec_judges_and_the_record_names_no_approval(self):
        repo = make_repo(self.tmp / "repo")
        self.write(repo, "player-stays-above-ground.json", approved())
        doc = self.gate(repo)
        self.assertEqual(doc["decision"], "accept", doc["reasons"])
        self.assertFalse([r for r in doc["reasons"] if approval.is_note(r)])

    def test_an_approval_from_before_binding_still_judges_and_the_comment_names_it_on_accept(self):
        doc = self.gate(make_repo(self.tmp / "repo"))
        self.assertEqual(doc["decision"], "accept", doc["reasons"])
        self.assertIn("spec player-stays-above-ground: approved before content binding", doc["reasons"])
        self.assertIn("approved before content binding", gc.render(doc, ctx()))

    def test_the_comment_names_no_approval_when_the_record_has_none(self):
        self.assertNotIn("content binding", gc.render(head_example(), ctx()))


class SparkOpenTest(unittest.TestCase):
    def test_only_approvals_that_match_their_spec_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bound = approved(dict(body(), id="bound-check"))
            edited = copy.deepcopy(approved(dict(body(), id="edited-check")))
            edited["window"]["toFrame"] = 3
            legacy = json.loads(SPEC.read_text(encoding="utf-8"))
            for doc in (bound, edited, legacy, dict(body(), id="draft-check")):
                (folder / f"{doc['id']}.json").write_text(json.dumps(doc), encoding="utf-8")
            ids = [s["id"] for s in spark_open.approved_specs(folder)]
        self.assertEqual(ids, ["bound-check", "player-stays-above-ground"])


class MergeGuardTest(unittest.TestCase):
    def change(self, old: dict | None, new: dict | None, path: str = "agents/specs/x.json") -> list:
        dump = lambda d: None if d is None else json.dumps(d, indent=2) + "\n"   # noqa: E731
        return mg.check_approved_specs([mg.Change(path, dump(old), dump(new))])

    def test_an_edited_spec_under_an_approval_from_before_binding_needs_sean(self):
        old = json.loads(SPEC.read_text(encoding="utf-8"))
        new = copy.deepcopy(old)
        new["assertion"]["boundary"]["tolerancePx"] = 99
        for path in ("agents/specs/x.json", "somewhere/else/check.json"):
            with self.subTest(path=path):
                reasons = self.change(old, new, path)
                self.assertEqual([(r.label, r.rule, r.message) for r in reasons],
                                 [("needs-sean", "approved-spec", "an approved spec's content changed; a person approves it again")])

    def test_an_edited_spec_under_a_bound_approval_needs_sean(self):
        old = approved()
        new = copy.deepcopy(old)
        new["window"]["toFrame"] = 5
        self.assertEqual(len(self.change(old, new)), 1)

    def test_no_reason_when_only_the_layout_changed_or_the_spec_is_a_draft(self):
        old = approved()
        respaced = json.dumps(dict(reversed(list(old.items()))))
        self.assertEqual(mg.check_approved_specs([mg.Change("specs/x.json", json.dumps(old), respaced)]), [])
        draft_old, draft_new = body(), dict(body(), instruction="changed")
        self.assertEqual(self.change(draft_old, draft_new), [])
        self.assertEqual(self.change(None, old), [])   # a new file: the approvals rule reports the approval
        self.assertEqual(self.change(old, None), [])
        self.assertEqual(self.change({"format": "other", "approval": {"by": "a"}}, {"format": "other", "approval": {"by": "a"}, "x": 1}), [])

    def test_a_new_approval_bound_to_the_new_content_is_left_to_the_approvals_rule(self):
        old = json.loads(SPEC.read_text(encoding="utf-8"))
        edited = body()
        edited["window"]["toFrame"] = 50
        new = approved(edited)
        self.assertEqual(self.change(old, new), [])
        # The approvals rule still reports the changed approval in a specs folder.
        reasons = mg.check([mg.Change("agents/specs/x.json", json.dumps(old), json.dumps(new))])
        self.assertIn("approval", [r.rule for r in reasons])

    def test_the_guard_runs_the_rule(self):
        old = json.loads(SPEC.read_text(encoding="utf-8"))
        new = copy.deepcopy(old)
        new["instruction"] = "edited"
        reasons = mg.check([mg.Change("agents/specs/x.json", json.dumps(old), json.dumps(new))])
        self.assertIn(("needs-sean", "approved-spec"), [(r.label, r.rule) for r in reasons])


if __name__ == "__main__":
    unittest.main()
