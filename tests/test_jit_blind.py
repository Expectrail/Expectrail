"""Blind set 3 (expectrail/jit/blind.py) on a stand-in set built from the public reported bugs: the
candidates it makes, the arms it runs, what it publishes, and the scoring rule."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.discovery.fresh import digest
from expectrail.jit import blind

REPO = Path(__file__).resolve().parents[1]
BUGS = ["air-jump", "gun-cooldown", "body-flip", "enemy-ledge", "air-jump", "gun-cooldown", "body-flip", "enemy-ledge"]


def stand_in_set() -> Path:
    """8 defects (the reported bugs, twice) with the known bench's fixes, and 2 intentional changes."""
    root = Path(tempfile.mkdtemp()) / "set"
    d = root / blind.SET_DIR
    d.mkdir(parents=True)
    entries = []
    for n, bug in enumerate(BUGS, 1):
        eid = f"h{n:02d}"
        shutil.copy(REPO / "bugs/reported" / f"{bug}.patch", d / f"{eid}.patch")
        shutil.copy(REPO / "bench/jit/known" / bug / "comment-only.patch", d / f"{eid}.wrong-fix.patch")
        shutil.copy(REPO / "bench/jit/known" / bug / "undo.patch", d / f"{eid}.correct-fix.patch")
        entries.append({"id": eid, "kind": "defect", "patch": f"fresh-3/{eid}.patch", "description": f"secret {eid}",
                        "howItShows": "SECRET-HOW", "traceVisible": "yes" if n % 2 else "no"})
    for n in (9, 10):
        eid = f"h{n:02d}"
        shutil.copy(REPO / "bugs/reported/gun-cooldown.patch", d / f"{eid}.patch")
        entries.append({"id": eid, "kind": "intentional", "patch": f"fresh-3/{eid}.patch", "description": "x",
                        "howItShows": "y", "traceVisible": "unsure"})
    (d / "manifest.json").write_text(json.dumps({"entries": entries}))
    return root


class Candidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("patch"):
            raise unittest.SkipTest("patch is not installed")
        cls.set = stand_in_set()

    def test_entries_need_eight_defects_two_changes_and_every_patch(self):
        self.assertEqual(len(blind.entries(self.set)), 10)
        (self.set / blind.SET_DIR / "h03.wrong-fix.patch").rename(self.set / "moved")
        try:
            with self.assertRaises(ValueError):
                blind.entries(self.set)
        finally:
            (self.set / "moved").rename(self.set / blind.SET_DIR / "h03.wrong-fix.patch")

    def test_a_defect_gets_its_own_fixes_plus_a_comment_and_the_exact_undo(self):
        entry = blind.entries(self.set)[0]
        work = Path(tempfile.mkdtemp())
        cands = blind.candidates(self.set, entry, work)
        self.assertEqual([(c["cid"], c["source"], c["label"]) for c in cands],
                         [("h01-wrong", "primary", "wrong"), ("h01-correct", "primary", "correct"),
                          ("h01-comment", "supplementary", "wrong"), ("h01-undo", "supplementary", "correct")])
        self.assertTrue(all(c["base"] == [self.set / blind.SET_DIR / "h01.patch"] for c in cands))
        self.assertEqual(cands[0]["report"], "secret h01\n\nSECRET-HOW\n")
        # The undo restores the clean game; the comment changes one line and nothing else.
        g = blind._copy_game(work / "check", [cands[0]["base"][0], cands[3]["candidate"]])
        import subprocess
        self.assertEqual(subprocess.run(["diff", "-r", "-q", "-x", ".godot", str(blind.GAME), str(g)],
                                        capture_output=True).returncode, 0)
        added = [l for l in cands[2]["candidate"].read_text().splitlines() if l.startswith("+") and not l.startswith("+++")]
        self.assertEqual(added, ["+# Fixed: the reported problem no longer happens."])

    def test_a_scene_file_gets_a_scene_comment_and_an_intentional_change_has_no_base(self):
        es = blind.entries(self.set)
        cands = blind.candidates(self.set, es[3], Path(tempfile.mkdtemp()))
        self.assertIn("+; Fixed:", cands[2]["candidate"].read_text())
        change = blind.candidates(self.set, es[8], Path(tempfile.mkdtemp()))
        self.assertEqual([(c["cid"], c["base"], c["label"]) for c in change], [("h09-change", [], "correct")])


class Entry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("patch"):
            raise unittest.SkipTest("patch is not installed")
        cls.set = stand_in_set()

    def test_the_public_rows_carry_outcomes_only_and_errors_are_no_result(self):
        calls = []

        def fake_a(base, cand, work):
            calls.append(("a", [p.name for p in base], cand.name))
            return "accept"

        def fake_b(base, cand, report, work, *, budget_usd):
            calls.append(("b", report, budget_usd))
            if "correct" in cand.name:
                raise RuntimeError("model down")
            return {"status": "complete", "counts": {"strong": 2 if "wrong" in cand.name else 0, "weak": 0},
                    "spend": {"usd": 0.05}}

        out = Path(tempfile.mkdtemp())
        rows = blind.run_entry(self.set, "h01", out, budget_usd=2.0, arm_a_fn=fake_a, arm_b_fn=fake_b)
        text = (out / "public-rows.json").read_text()
        self.assertNotIn("SECRET", text)
        self.assertNotIn("secret", text)
        for r in rows:
            self.assertEqual(set(r), {"cid", "source", "label", "kind", "traceVisible", "armA", "jitStatus",
                                      "jitStrong", "jitWeak", "spendUsd", "error"})
        by = {r["cid"]: blind.outcome(r) for r in rows}
        self.assertEqual(by["h01-wrong"], {"A": False, "B": True})
        self.assertEqual(by["h01-correct"], {"A": False, "B": None})
        self.assertIn(("b", "secret h01\n\nSECRET-HOW\n", 2.0), calls)


    def test_the_command_the_workflow_runs_with_relative_paths(self):
        """Blind run 42940175240 failed here: the workflow passes --set heldout-set and --out runs/...,
        relative, and patch -d could not open a relative patch path. Real candidates and patches;
        both arms stubbed, called through main() exactly as the workflow calls it."""
        import contextlib
        import io
        import os
        from unittest import mock

        def fake_a(base, cand, work):
            g = blind._copy_game(work / "head", [*base, cand])   # the real patching, relative inputs
            return "accept" if g.is_dir() else "needs-review"

        def fake_b(base, cand, report, work, *, budget_usd):
            return {"status": "complete", "counts": {"strong": 0, "weak": 0}, "spend": {"usd": 0.0}}

        cwd = os.getcwd()
        os.chdir(self.set.parent)
        try:
            with mock.patch.object(blind, "arm_a", fake_a), mock.patch.object(blind, "arm_b", fake_b), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                code = blind.main(["entry", "--set", self.set.name, "--id", "h04", "--out", "runs/blind/h04"])
            rows = json.loads((self.set.parent / "runs/blind/h04/public-rows.json").read_text())
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed.getvalue()), {"candidates": 4, "errors": 0})
        self.assertEqual({r["armA"] for r in rows}, {"accept"})


class Score(unittest.TestCase):
    def row(self, cid, label, kind="defect", source="primary", a="accept", strong=0, weak=0, status="complete", tv="yes"):
        return {"cid": cid, "source": source, "label": label, "kind": kind, "traceVisible": tv, "armA": a,
                "jitStatus": status, "jitStrong": strong, "jitWeak": weak, "spendUsd": 0.1, "error": None}

    def rows(self):
        rows = []
        for n in range(1, 9):
            rows.append(self.row(f"h{n:02d}-wrong", "wrong", a="reject" if n <= 3 else "accept", strong=1 if n <= 6 else 0))
            rows.append(self.row(f"h{n:02d}-correct", "correct"))
            rows.append(self.row(f"h{n:02d}-comment", "wrong", source="supplementary", strong=1))
            rows.append(self.row(f"h{n:02d}-undo", "correct", source="supplementary"))
        rows += [self.row("h09-change", "correct", kind="intentional"), self.row("h10-change", "correct", kind="intentional")]
        return rows

    def test_adds_value_only_with_more_catches_and_no_more_false_catches(self):
        doc = blind.score(self.rows())
        self.assertEqual(doc["groups"]["primary/wrong"]["Acaught"], 3)
        self.assertEqual(doc["groups"]["primary/wrong"]["Bcaught"], 6)
        self.assertEqual(doc["verdict"], "adds-value")
        rows = self.rows()
        rows[-1]["jitStrong"] = 1   # a generated check catches an intentional change
        self.assertEqual(blind.score(rows)["verdict"], "more-catches-with-more-false-catches")
        rows = self.rows()
        rows[0]["jitStatus"] = "nothing-generated"
        self.assertEqual(blind.score(rows)["verdict"], "incomplete")

    def test_missing_rows_are_incomplete_never_no_added_value(self):
        # Blind run 42939008550: every entry job failed before writing a row, and the score said
        # "no-added-value" on zero rows.
        self.assertEqual(blind.score([])["verdict"], "incomplete")
        rows = [r for r in self.rows() if r["cid"] != "h04-wrong"]
        doc = blind.score(rows)
        self.assertEqual((doc["verdict"], doc["missingPrimary"]), ("incomplete", 1))
        self.assertIn("1 of the 18 primary candidates have no row", blind.render(doc))

    def test_supplementary_never_mixes_into_primary_and_weak_does_not_count(self):
        rows = [r for r in self.rows() if r["source"] == "primary"]
        for r in rows:
            if r["label"] == "wrong":
                r.update(jitStrong=0, jitWeak=1)
        doc = blind.score(rows + [r for r in self.rows() if r["source"] == "supplementary"])
        self.assertEqual(doc["groups"]["primary/wrong"]["Bcaught"], 3)
        self.assertEqual(doc["groups"]["primary/wrong"]["weakOnly"], 8)
        self.assertEqual(doc["verdict"], "no-added-value")
        self.assertIn("| h01-wrong | primary | wrong | caught | caught |", blind.render(doc))


class Registration(unittest.TestCase):
    def test_registered_with_pins_that_hold_and_the_digest_rule(self):
        prereg = json.loads(blind.PREREG.read_text())
        self.assertEqual(prereg["set"]["sha256"], "a5ffad12605bc3bd8ed3891ce23c3e31fe583575b0cb2a05b0ba5424a2bfc6ac")
        if prereg["status"] == "registered" and prereg["pins"]:
            self.assertEqual(blind.check_registration(prereg), [])
        moved = dict(prereg, status="registered", signedOffBy="x", pins=dict(blind.pins(), **{"expectrail/jit/blind.py": "0"}))
        self.assertEqual(blind.check_registration(moved), ["pin moved: expectrail/jit/blind.py"])

    def test_the_digest_is_the_fresh_sets_rule(self):
        root = stand_in_set()
        self.assertEqual(blind.set_digest(root), digest(root / blind.SET_DIR))


class Workflow(unittest.TestCase):
    def test_from_main_only_every_job_with_the_set_in_main_only_and_no_private_upload(self):
        import yaml

        text = (REPO / ".github/workflows/jit-blind.yml").read_text()
        doc = yaml.safe_load(text)
        self.assertEqual(set(doc.get("on", doc.get(True))), {"workflow_dispatch"})
        for name in ("verify", "entry"):
            self.assertEqual(doc["jobs"][name]["environment"], "main-only")
        self.assertNotIn("secrets", yaml.safe_dump(doc["jobs"]["score"]))
        uploads = [s["with"]["path"] for j in doc["jobs"].values() for s in j["steps"] if "upload-artifact" in str(s.get("uses"))]
        self.assertEqual(uploads, ["public/${{ matrix.id }}/public-rows.json", "runs/blind-score/"])
        self.assertIn('> "runs/blind-$ID.log" 2>&1', text)
        # The log's folder exists before the redirect (blind run 42939008550 failed there, in 0 s).
        self.assertLess(text.index('mkdir -p "runs/blind/$ID"'), text.index('> "runs/blind-$ID.log"'))


if __name__ == "__main__":
    unittest.main()
