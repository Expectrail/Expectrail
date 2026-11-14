"""The repair recording is data. Stand-in replays judge the patched bug from scratch."""
import hashlib
import html
import json
from unittest import mock

from expectrail import runit, viewer
from expectrail.orchestrator import request, sample
from tests.test_runit import Case, REPO

ID = "recorded-fix"
PATCH = "--- a/BUG\n+++ /dev/null\n@@ -1 +0,0 @@\n-1\n"


class RepairTest(Case):
    def setUp(self):
        super().setUp()
        self.path = self.root / "docs/run-it/repair/repair-run.json"
        self.patch = self.path.parent / "attempt-1/candidate.patch"
        self.patch.parent.mkdir(parents=True)
        self.doc = json.loads((REPO / "contracts/examples/repair-run.v1.json").read_text())
        self.doc["fixer"] = {"source": "muse", "sandboxed": True}
        bug = sample.checkout(self.tmp / "original", bug=True, root=self.root)
        self.doc["parent"]["headTree"] = request.tree_digest(bug / sample.GAME, bug, "godot")
        self.save()

    def save(self):
        self.patch.write_text(PATCH)
        self.doc["attempts"][0]["patchSha256"] = hashlib.sha256(self.patch.read_bytes()).hexdigest()
        self.path.write_text(json.dumps(self.doc))

    def test_absent_fixture_or_changed_patch_runs_nothing(self):
        self.path.unlink()
        with self.assertRaisesRegex(runit.RunItError, "fix not recorded yet"):
            self.run_sample(ID)
        self.doc["fixer"] = {"source": "fixture", "sandboxed": False}
        self.save()
        with self.assertRaisesRegex(runit.RunItError, "live"):
            self.run_sample(ID)
        self.doc["fixer"] = {"source": "codex", "sandboxed": True}
        self.save()
        self.patch.write_text("different")
        with self.assertRaisesRegex(runit.RunItError, "digest"):
            self.run_sample(ID)
        self.assertEqual(self.game.replays, [])

    def test_fresh_verify_uses_patched_bug_and_recorded_answers(self):
        # Prepare stand-in answers for the exact frames the two trees draw.
        answers = self.record("fall-through-repair")
        answers["sample"] = ID
        (self.root / f"docs/run-it/vision/{ID}.json").write_text(json.dumps(answers))
        asked = len(self.game.asked)
        self.game.replays.clear()
        doc, out = self.run_sample(ID)
        self.assertEqual(doc["decision"], "accept")
        findings = json.loads((out / "findings.json").read_text())
        self.assertEqual(findings["intent"], "fix")
        self.assertTrue(findings["repair"]["demonstrated"])
        self.assertEqual({look for _, look, _ in self.game.replays}, {"BUG", "clean"})
        self.assertEqual(len(self.game.asked), asked)
        self.assertEqual(runit.check(out, sample_id=ID, request_id="local", root=self.root), [])
        for filename in ("index.html", "evidence.html"):
            page = html.unescape((out / "viewer" / filename).read_text())
            self.assertIn(self.doc["review"], page)
            self.assertIn(PATCH, page)
            self.assertIn("Attempt 1", page)

    def test_fresh_verdict_overrides_recorded_accept(self):
        self.assertEqual(self.run_sample(ID)[0]["decision"], "needs-review")
        self.game.look_of = lambda game: "BUG"
        doc, out = self.run_sample(ID)
        self.assertEqual(doc["decision"], "reject")
        self.assertIn('data-state="behaviour-failure"', (out / "viewer/index.html").read_text())

    def test_refuse_wrong_parent_unlinked_accept_or_patch_directory_link(self):
        self.doc["parent"]["headTree"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(runit.RunItError, "tree"):
            self.run_sample(ID)
        self.doc["result"]["job"] = self.doc["parent"]["job"]
        self.save()
        with self.assertRaisesRegex(ValueError, "attempt"):
            viewer.read_repair(self.path)
        self.doc["result"]["job"] = self.doc["attempts"][0]["job"]
        self.save()
        moved = self.tmp / "moved"
        self.patch.parent.rename(moved)
        self.patch.parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "link"):
            viewer.read_repair(self.path)
        self.assertEqual(self.game.replays, [])

    def test_stopped_timeline_has_every_attempt_and_no_winning_diff(self):
        first = self.doc["attempts"][0]
        first["decision"] = "reject"
        self.doc["attempts"].append(dict(n=2, patch=None, patchSha256=None, job=None, decision=None, reasons=[]))
        self.doc["result"] = dict(decision="needs-review", patch=None, job=None)
        self.doc["stop"] = dict(reason="fixer-failed", detail="No patch on the second attempt.")
        self.save()
        page = viewer.write_repair(self.path, self.tmp / "viewer").read_text()
        for word in ("Attempt 1", "reject", "Attempt 2", "No verdict", "fixer-failed", "No patch on the second attempt."):
            self.assertIn(word, page)
        self.assertNotIn(self.doc["review"], html.unescape(page))
        self.assertNotIn("candidate.patch", page)

    def test_full_diff_is_escaped_in_both_pages_and_fixture_is_identified(self):
        patch = PATCH + "+<script>bad()</script>" + "x" * 750 + "END-OF-DIFF\n"
        self.patch.write_text(patch)
        self.doc["attempts"][0]["patchSha256"] = hashlib.sha256(self.patch.read_bytes()).hexdigest()
        self.doc["fixer"] = {"source": "fixture", "sandboxed": False}
        self.path.write_text(json.dumps(self.doc))
        page = viewer.write_repair(self.path, self.tmp / "viewer").read_text()
        self.assertIn("Fixture", page)
        self.assertIn("END-OF-DIFF", page)
        self.assertIn("&lt;script&gt;bad()", page)
        self.assertNotIn("<script>bad()", page)
        self.assertIn(self.doc["review"], html.unescape(page))

    def test_live_record_command_refuses_before_making_a_client(self):
        with mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("live client")):
            with self.assertRaisesRegex(runit.RunItError, "recorded"):
                runit.record(ID, self.tmp / "out", run_id="test", root=self.root)
