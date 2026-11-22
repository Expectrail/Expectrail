import copy
import json
from pathlib import Path
import tempfile
import unittest

from expectrail import blind_set
from expectrail.contracts import ContractError
from expectrail.jit import registration


EXAMPLE = Path(__file__).resolve().parents[1] / "contracts/examples/blind-registration.v2.json"


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.draft = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_draft_roundtrips_to_canonical_bytes_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp, "first.json")
            second = Path(temp, "second.json")
            registration.write(first, self.draft)
            registration.write(second, dict(reversed(list(self.draft.items()))))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(registration.read(first), self.draft)
            with self.assertRaises(FileExistsError):
                registration.write(first, self.draft)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_legacy_protocol_is_out_of_format(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "legacy.json")
            path.write_text('{"format":"expectrail.jit-blind-preregistration/v0"}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "out of format"):
                registration.read(path)

    def test_requires_registered_record_when_requested(self):
        with self.assertRaisesRegex(ContractError, "requires a registered record"):
            registration.validate(self.draft, require_registered=True)
        self.draft["status"] = "registered"
        with self.assertRaisesRegex(ContractError, "sign-off"):
            registration.validate(self.draft)

    def test_fixed_protocol_constraints_are_checked(self):
        changes = [
            (("questions", "Q7"), None),
            (("arms", "releaseFallback"), "B"),
            (("strata", "minimums", "wrongFixes"), 29),
            (("controls", "unchangedReplaysPerProject"), 2),
            (("scoring", "replaysPerCandidate"), 2),
            (("rerun", "maximum"), 2),
        ]
        for keys, value in changes:
            with self.subTest(keys=keys):
                changed = copy.deepcopy(self.draft)
                group = changed
                for key in keys[:-1]:
                    group = group[key]
                group[keys[-1]] = value
                with self.assertRaises(ContractError):
                    registration.validate(changed)

    def test_published_minimums_match_the_existing_manifest_validator(self):
        strata = self.draft["strata"]
        quotas = strata["fixedQuotas"]
        existing = blind_set.QUOTAS
        self.assertEqual(strata["minimums"], {
            "wrongFixes": existing["wrongFixes"]["minimum"],
            "correctFixes": existing["correctFixes"]["minimum"],
            "otherChanges": existing["notAFix"]["minimum"],
        })
        self.assertEqual(quotas["maxSharePerProjectPct"], 100 * existing["maxProjectShare"])
        self.assertEqual(quotas["minScreenOnlyWrongFixesPct"], 100 * existing["screenOnlyWrongShare"])
        self.assertEqual(quotas["minPerFamily"], existing["perFamily"])
        self.assertEqual(quotas["minPerWrongFixKind"], existing["perWrongFixKind"])
        self.assertEqual(tuple(quotas["families"]), blind_set.FAMILIES)
        self.assertEqual(tuple(quotas["wrongFixKinds"]), blind_set.WRONG_FIX_KINDS)
        self.assertEqual(set(quotas["otherChanges"]), set(blind_set.NOT_A_FIX_KINDS))
        self.draft["strata"]["projects"][0] += "\n"
        with self.assertRaisesRegex(ContractError, "project"):
            registration.validate(self.draft)

    def complete_record(self):
        record = copy.deepcopy(self.draft)
        record["status"] = "registered"
        record["signOff"] = {"by": "synthetic reviewer", "at": "2031-01-01T10:00:00Z"}
        record["runWindow"] = {"start": "2031-01-02T00:00:00Z", "end": "2031-01-04T00:00:00Z"}
        record["thresholds"] = dict.fromkeys(record["thresholds"], 2)
        record["budget"] = {"samUsd": 1, "totalUsd": 2}
        record["pins"]["commit"] = "a" * 40
        record["pins"]["setManifestSha256"] = "b" * 64
        for group in record["pins"]["files"]:
            record["pins"]["files"][group] = {f"synthetic/{group}.json": "c" * 64}
        return record

    def test_registered_record_preserves_caller_supplied_decisions(self):
        record = self.complete_record()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "registration.json")
            registration.write(path, record)
            self.assertEqual(registration.read(path, require_registered=True), record)

    def test_registered_record_requires_complete_pre_run_decisions(self):
        cases = {
            "thresholds": lambda doc: doc["thresholds"].update(maxFalseRejectPct=None),
            "budget": lambda doc: doc["budget"].update(samUsd=None),
            "pins": lambda doc: doc["pins"]["files"].update(observers={}),
            "before": lambda doc: doc["signOff"].update(at="2031-01-03T00:00:00Z"),
        }
        for error, change in cases.items():
            with self.subTest(error=error):
                record = self.complete_record()
                change(record)
                with self.assertRaisesRegex(ContractError, error):
                    registration.validate(record)

    def test_reader_refuses_duplicate_keys_and_path_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "duplicate.json")
            path.write_text('{"status":"draft","status":"registered"}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate key"):
                registration.read(path)
        for name in ("../outside", "a/../outside", "a//b", "/absolute", "a\\b"):
            with self.subTest(name=name):
                self.draft["pins"]["files"]["routes"] = {name: "a" * 64}
                with self.assertRaisesRegex(ContractError, "repo-relative"):
                    registration.validate(self.draft)

    def test_rejects_conflicting_pins_and_inconsistent_budget(self):
        record = self.complete_record()
        record["pins"]["files"]["routes"]["synthetic/verifier.json"] = "d" * 64
        with self.assertRaisesRegex(ContractError, "conflicting"):
            registration.validate(record)
        del record["pins"]["files"]["routes"]["synthetic/verifier.json"]
        record["budget"]["samUsd"] = 3
        with self.assertRaisesRegex(ContractError, "budget"):
            registration.validate(record)
