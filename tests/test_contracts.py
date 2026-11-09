import json
import unittest
from pathlib import Path

from expectrail.contracts import KINDS, ContractError, digest, kind_of, validate

EXAMPLES = Path(__file__).resolve().parent.parent / "contracts" / "examples"


class ContractsTest(unittest.TestCase):
    def test_every_kind_has_a_schema_and_a_valid_example(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                doc = json.loads((EXAMPLES / f"{kind}.json").read_text())
                self.assertEqual(validate(doc), kind)

    def test_a_replay_names_one_of_the_engines_an_adapter_can_write(self):
        replay = json.loads((EXAMPLES / "replay.json").read_text())
        for name in ("godot", "unity", "web", "chromium"):
            with self.subTest(engine=name):
                replay["engine"]["name"] = name
                self.assertEqual(validate(replay), "replay")
        replay["engine"]["name"] = "unreal"
        with self.assertRaises(ContractError):
            validate(replay)

    def test_invalid_documents_are_rejected(self):
        spec = json.loads((EXAMPLES / "test-spec.json").read_text())
        spec["assertion"] = {"type": "looks-fine", "object": "player"}
        with self.assertRaises(ContractError):
            validate(spec)
        with self.assertRaises(ContractError):
            kind_of({"format": "something-else/v1"})
        gameplay = json.loads((EXAMPLES / "gameplay-verdict.json").read_text())
        gameplay["result"] = "maybe"
        with self.assertRaises(ContractError):
            validate(gameplay, "gameplay-verdict")
        gameplay = json.loads((EXAMPLES / "gameplay-verdict.json").read_text())
        del gameplay["metrics"]["deltaX"]
        with self.assertRaises(ContractError):
            validate(gameplay, "gameplay-verdict")
        gameplay = json.loads((EXAMPLES / "gameplay-verdict.json").read_text())
        gameplay["extra"] = True
        with self.assertRaises(ContractError):
            validate(gameplay, "gameplay-verdict")
        rc = json.loads((EXAMPLES / "release-candidate.json").read_text())
        rc["decision"] = "maybe"
        with self.assertRaises(ContractError):
            validate(rc, "release-candidate")
        rc = json.loads((EXAMPLES / "release-candidate.json").read_text())
        rc["extra"] = True
        with self.assertRaises(ContractError):
            validate(rc, "release-candidate")
        rc = json.loads((EXAMPLES / "release-candidate.json").read_text())
        rc["format"] = "expectrail.release-candidate/v1"
        with self.assertRaises(ContractError):
            validate(rc, "release-candidate")
        rc = json.loads((EXAMPLES / "release-candidate.json").read_text())
        del rc["verificationSha256"]
        with self.assertRaises(ContractError):
            validate(rc, "release-candidate")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        del overnight["results"]
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        overnight["accepted"] = overnight["runs"] + 1
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        overnight["results"] = overnight["results"][:1]
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        overnight["cost"] = {
            "modelCalls": 0,
            "costUsd": None,
            "costProvenance": "metered",
        }
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        overnight["format"] = "expectrail.overnight-summary/v1"
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        del overnight["cost"]
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        overnight["extra"] = True
        with self.assertRaises(ContractError):
            validate(overnight, "overnight-summary")

    def test_digest_ignores_key_order(self):
        self.assertEqual(digest({"a": 1, "b": [1, 2]}), digest({"b": [1, 2], "a": 1}))
        self.assertNotEqual(digest({"a": 1}), digest({"a": 2}))


if __name__ == "__main__":
    unittest.main()
