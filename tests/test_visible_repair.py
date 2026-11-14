"""The repair recording is data. Stand-in replays judge the patched bug from scratch."""
import hashlib
import html
import json
import subprocess
from unittest import mock

from expectrail import runit, viewer
from expectrail.orchestrator import request, sample
from tests.test_runit import Case, REPO

ID = "recorded-fix"
PATCH = "--- a/BUG\n+++ /dev/null\n@@ -1 +0,0 @@\n-1\n"


class RepairTest(Case):
    def setUp(self):
        super().setUp()
        manifest_path = self.root / runit.MANIFEST
        manifest = runit.read_manifest(self.root)
        runit.find_sample(manifest, ID)["repairRecorded"] = True
        manifest_path.write_text(json.dumps(manifest))
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

    def test_unpublished_card_is_disabled_and_ignores_an_old_latest_run(self):
        subprocess.run(["node", "tests/runit_repair_card.cjs"], cwd=REPO, check=True, timeout=15)

    def test_unpublished_sample_never_reads_even_an_available_record(self):
        manifest = runit.read_manifest(REPO)
        self.assertIs(runit.find_sample(manifest, ID)["repairRecorded"], False)
        (self.root / runit.MANIFEST).write_text(json.dumps(manifest))
        with mock.patch.object(viewer, "read_repair", side_effect=AssertionError("read an unpublished record")):
            with self.assertRaisesRegex(runit.RunItError, "fix not recorded yet"):
                self.run_sample(ID)
        self.assertEqual(self.game.replays, [])

    def test_refuses_symlinks_to_record_patch_or_record_directory(self):
        for path in (self.path, self.patch, self.path.parent):
            with self.subTest(path=path.name):
                moved = path.with_name(path.name + "-saved")
                path.rename(moved)
                path.symlink_to(moved, target_is_directory=moved.is_dir())
                try:
                    with self.assertRaisesRegex(ValueError, "link"):
                        viewer.read_repair(self.path)
                finally:
                    path.unlink()
                    moved.rename(path)

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
        doc, out = self.run_sample(ID)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertIn("<h3>Final verdict</h3><p>needs-review</p>", (out / "viewer/index.html").read_text())
        self.game.look_of = lambda game: "BUG"
        doc, out = self.run_sample(ID)
        self.assertEqual(doc["decision"], "reject")
        page = (out / "viewer/index.html").read_text()
        self.assertIn('data-state="behaviour-failure"', page)
        self.assertIn("<h3>Final verdict</h3><p>reject</p>", page)

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

    def test_one_repair_section_per_page(self):
        # The guard's question on #454: a Run it recorded repair and a rejected job's own auto-fix
        # outcome are different things, and a page never shows two repair sections that disagree.
        job = {"id": "j", "phase": "completed", "decision": "reject", "reasons": [], "diagnostics": [],
               "repair": {"state": "finished", "decision": "accept", "stopReason": "accepted"}}
        base = {"format": viewer.FORMAT, "state": "behaviour-failure", "decision": "reject", "reasons": [],
                "record": None, "views": [], "job": job, "reproduce": None, "sample": None}
        own = viewer.render(dict(base))
        self.assertIn('<section id="auto-fix">', own)
        self.assertNotIn("Recorded repair", own)
        recorded = viewer.render(dict(base, sample="recorded-fix", repair=viewer.read_repair(self.path)))
        self.assertIn("Recorded repair", recorded)
        self.assertNotIn('<section id="auto-fix">', recorded)

    def test_front_pages_show_the_loop_and_human_review(self):
        for name in ("index.html", "concepts.html"):
            with self.subTest(page=name):
                page = (REPO / "docs" / name).read_text()
                figure = page.split('<figure aria-label="The repair loop">', 1)[1].split("</figure>", 1)[0]
                steps = ("Reject", "Sandboxed fixer proposes a patch", "Fresh independent verification",
                         "Accept or needs-review", "A person reviews")
                positions = [figure.index(f"<span>{step}</span>") for step in steps]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("never talks to the verifier or the judge", figure)
                self.assertIn("Expectrail never merges a fix", figure)

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
