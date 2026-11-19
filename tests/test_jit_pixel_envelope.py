"""Pixel checks in the generated-counting/v1 envelope and the gate's visual-evidence policy (#271, #286).

Until this change ``counting.make`` carried trace rows only, so a pixel check could never reach ``decide``
however many of the six rules it met. Now the envelope's assessment carries a row for each pixel check,
recomputed from the source run's ``pixelChecks`` on every read, and the gate treats a counting pixel row
as its own per-check visual evidence under the ``both`` observer rule: its runs are the visual observer's
verdicts over frames where the engine's record also places the object (expectrail/jit/pixel.py). A
counting trace row still has no visual evidence, so it still keeps an accept away under ``both``.

Records are the committed hand-written stand-ins (bench/jit/stand-in/), changed one field at a time, and
the receipts are signed here with a throwaway key. No replay, no observer, no model."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from expectrail.contracts import ContractError, digest_v1
from expectrail.gate import record as rec
from expectrail.jit import counting
from tests.test_jit_pixel_counting import ENEMY, ENEMY_REPORT, BULLET, BULLET_REPORT, load, passing

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "contracts/examples/generated-counting-pixel.json"
COUNTS = {"checks": 1, "passed": 1, "failed": 0, "needsReview": 0}
HELD = {"status": "not-used", "routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
BOTH = {"rule": rec.BOTH, "visual": {"name": "sam", "provider": "stand-in", "model": "stand-in"}}


def trusted(doc, report=ENEMY_REPORT):
    """The envelope and its trust context for ``doc``, with a fresh receipt carrying both capabilities."""
    from expectrail.receipt import write_receipt
    from tests.test_receipt import _base_doc, _key
    key, pub = _key()
    cert = _base_doc(pub)
    cert["evidence"]["capabilities"] = ["jit-trusted-proposal", "jit-trusted-replay"]
    cert["evidence"]["artifacts"] = {"jit-run-canonical": digest_v1(doc)}
    cert = write_receipt(cert, key)
    trust = counting.Trust({"test-issuer": pub}, "Expectrail/Expectrail", cert["baseSha256"], cert["headSha256"],
                           cert["buildSha256"], cert["policySha256"], copy.deepcopy(doc["inputs"]))
    return counting.make(doc, report, cert, trust=trust), trust


def pixel_rows(envelope):
    return [r for r in envelope["assessment"]["rows"] if r.get("kind") == "pixel"]


class PixelRowsInTheEnvelope(unittest.TestCase):
    def test_make_carries_one_row_per_pixel_check(self):
        doc = passing()
        envelope, trust = trusted(doc)
        rows = pixel_rows(envelope)
        self.assertEqual([r["specId"] for r in rows], [p["check"]["id"] for p in doc["pixelChecks"]])
        self.assertTrue(all(r["counting"] for r in rows), [r["reasons"] for r in rows])
        self.assertTrue(all(r["observer"] == "visual-sensor" for r in rows))
        self.assertEqual(rows[0]["setting"], doc["pixelChecks"][0]["setting"])
        proof = counting.read(envelope, trust=trust)
        self.assertEqual(proof.block, envelope["assessment"])

    def test_without_trust_every_pixel_row_is_advisory(self):
        envelope = counting.make(passing(), ENEMY_REPORT)
        rows = pixel_rows(envelope)
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(r["counting"] for r in rows))
        self.assertTrue(all("rule-5" in " ".join(r["reasons"]) for r in rows))

    def test_the_committed_stand_ins_give_no_counting_row(self):
        for path, report in ((ENEMY, ENEMY_REPORT), (BULLET, BULLET_REPORT)):
            with self.subTest(record=path.parent.name):
                envelope = counting.make(load(path), report)
                self.assertEqual(len(pixel_rows(envelope)), 3)
                self.assertFalse(any(r["counting"] for r in envelope["assessment"]["rows"]))

    def test_a_changed_pixel_row_is_refused_on_read(self):
        envelope, trust = trusted(passing())
        for change in ("label", "observer", "runs", "drop", "kind"):
            forged = copy.deepcopy(envelope)
            row = pixel_rows(forged)[0]
            if change == "label":
                row["counting"] = not row["counting"]
            elif change == "observer":
                row["observer"] = "sam-3.1-anchor"
            elif change == "runs":
                row["candidate"] = ["fail"] * 3
            elif change == "drop":
                forged["assessment"]["rows"].remove(row)
            else:
                del row["kind"]
            with self.subTest(change=change), self.assertRaises((ValueError, ContractError)):
                counting.read(forged, trust=trust)

    def test_a_changed_source_pixel_run_is_refused_on_read(self):
        envelope, trust = trusted(passing())
        envelope["sourceRun"]["pixelChecks"][0]["bug"][0] = "pass"
        with self.assertRaises(ValueError):
            counting.read(envelope, trust=trust)

    def test_a_pixel_check_sharing_a_trace_checks_id_is_refused(self):
        doc = passing()
        base = json.loads((REPO / "contracts/examples/generated-counting.json").read_text())["sourceRun"]
        doc["proposed"] = copy.deepcopy(base["proposed"][:1])
        doc["validity"] = copy.deepcopy(base["validity"][:1])
        doc["pixelChecks"][0]["check"]["id"] = doc["proposed"][0]["spec"]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            counting.make(doc, ENEMY_REPORT)

    def test_the_pixel_example_reads_and_is_what_make_gives(self):
        example = json.loads(EXAMPLE.read_text())
        proof = counting.read(example)
        self.assertEqual(len([r for r in proof.block["rows"] if r.get("kind") == "pixel"]), 3)
        self.assertFalse(any(r["counting"] for r in proof.block["rows"]))
        self.assertEqual(example, counting.make(load(ENEMY), ENEMY_REPORT))

    def test_the_trace_example_is_unchanged_by_the_pixel_rows(self):
        example = json.loads((REPO / "contracts/examples/generated-counting.json").read_text())
        self.assertFalse(any("kind" in r for r in counting.read(example).block["rows"]))


def validate(doc, schema):
    import jsonschema
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(doc))
    if errors:
        raise ContractError(errors[0].message)


class RowSchemas(unittest.TestCase):
    """A trace row and a pixel row each have their own closed shape, in both schemas that carry them."""

    def schemas(self):
        envelope = json.loads((REPO / "contracts/generated-counting.v1.schema.json").read_text())
        findings = json.loads((REPO / "contracts/findings.schema.json").read_text())
        return (envelope["properties"]["assessment"], findings["properties"]["countingChecks"])

    def test_the_envelope_and_the_gate_record_take_the_same_rows(self):
        a, b = self.schemas()
        self.assertEqual(a, b)

    def test_each_row_kind_is_closed(self):
        envelope, _ = trusted(passing())
        block = envelope["assessment"]
        schema = self.schemas()[0]
        validate(block, schema)
        trace = json.loads((REPO / "contracts/examples/generated-counting.json").read_text())["assessment"]["rows"][0]
        cases = {
            "a pixel row without its observer": lambda b: b["rows"][0].pop("observer"),
            "a pixel row with another kind": lambda b: b["rows"][0].update(kind="trace"),
            "a pixel row with an unknown observer": lambda b: b["rows"][0].update(observer="eyeballed"),
            "a trace row with a pixel field": lambda b: b["rows"].append(dict(trace, observer="visual-sensor")),
            "a trace row with a pixel run value": lambda b: b["rows"].append(dict(trace, candidate=["needs-review"] * 3)),
            "a pixel row with a trace run value": lambda b: b["rows"][0].update(candidate=["execution_error"] * 3),
        }
        for name, change in cases.items():
            changed = copy.deepcopy(block)
            change(changed)
            with self.subTest(name), self.assertRaises(ContractError):
                validate(changed, schema)
        mixed = copy.deepcopy(block)
        mixed["rows"].append(trace)
        validate(mixed, schema)


class VisualEvidencePolicy(unittest.TestCase):
    def proof(self, doc=None):
        envelope, trust = trusted(doc or passing())
        return counting.read(envelope, trust=trust)

    def test_a_counting_pixel_check_demonstrates_a_repair(self):
        decision, reasons = rec.decide(COUNTS, HELD, intent="fix", generated=self.proof())
        self.assertEqual(decision, "accept", reasons)

    def test_under_both_a_counting_pixel_check_is_its_own_visual_evidence(self):
        decision, reasons = rec.decide(COUNTS, HELD, intent="fix", generated=self.proof(), observers=BOTH)
        self.assertEqual(decision, "accept", reasons)
        self.assertNotIn("required visual evidence", " ".join(reasons))

    def test_under_both_a_counting_trace_check_still_lacks_visual_evidence(self):
        doc = passing()
        base = json.loads((REPO / "contracts/examples/generated-counting.json").read_text())
        # A counting trace row beside the pixel rows: the trace example's row, made to count. Trusted
        # in-process evidence is built directly here; the gate reads the rows, not how they were made.
        block = self.proof(doc).block
        trace = copy.deepcopy(base["assessment"]["rows"][0])
        trace.update(rules=[True] * 6, counting=True, killed=["v-variant-airjump-moved"])
        block["rows"].append(trace)
        mixed = rec.VerifiedGenerated(block)
        decision, reasons = rec.decide(COUNTS, HELD, intent="fix", generated=mixed, observers=BOTH)
        self.assertEqual(decision, "needs-review")
        self.assertIn("not-exercised: counting generated checks lack the required visual evidence", reasons)
        # Engine-only, the same rows demonstrate the repair.
        self.assertEqual(rec.decide(COUNTS, HELD, intent="fix", generated=mixed)[0], "accept")

    def test_an_advisory_pixel_check_does_not_demonstrate_a_repair(self):
        for change in ("untrusted", "flaky", "shown"):
            doc = passing()
            if change == "flaky":
                doc["pixelChecks"][0]["candidate"][1] = "needs-review"
                for row in doc["pixelChecks"][1:]:
                    row["candidate"] = ["fail"] * 3
            if change == "shown":
                doc["settings"]["candidate"] = "shown"
            if change == "untrusted":
                envelope = counting.make(doc, ENEMY_REPORT)
                proof = counting.read(envelope)
            else:
                proof = self.proof(doc)
            with self.subTest(change=change):
                decision, reasons = rec.decide(COUNTS, HELD, intent="fix", generated=proof, observers=BOTH)
                self.assertEqual(decision, "needs-review", reasons)
                self.assertIn("repair", " ".join(reasons))

    def test_a_counting_pixel_check_never_clears_a_change_alone(self):
        decision, reasons = rec.decide(dict(COUNTS, checks=0, passed=0), HELD, intent="fix",
                                       generated=self.proof(), observers=BOTH)
        self.assertEqual(decision, "needs-review")
        self.assertIn("cannot clear a change alone", " ".join(reasons))

    def test_a_public_failure_still_rejects(self):
        decision, _ = rec.decide(dict(COUNTS, passed=0, failed=1), HELD, intent="fix", generated=self.proof())
        self.assertEqual(decision, "reject")

    def test_the_words_name_a_pixel_check_that_demonstrated_the_repair(self):
        proof = self.proof()
        doc = {"countingChecks": proof.block, "pullRequest": None, "intent": "fix"}
        words = rec.repair_words(doc)
        self.assertIn("generated pixel check", words)
        self.assertIn(proof.block["rows"][0]["specId"], words)


class PressureStopsOnPixelChecks(unittest.TestCase):
    def test_a_counting_pixel_check_stops_the_pressure_replays(self):
        # The pressure replays judge trace predicates only; replaying fewer checks than count would let a
        # correct fix through untested, so they stop before any fixer, model or replay.
        import tempfile
        from expectrail.jit import pressure
        envelope, trust = trusted(passing())
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "generated-counting.json").write_text(json.dumps(envelope))
            with self.assertRaisesRegex(pressure.Stop, "pixel-checks-not-replayed"):
                pressure.frozen(Path(tmp), trust)


if __name__ == "__main__":
    unittest.main()
