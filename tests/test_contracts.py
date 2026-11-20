import json
import tempfile
import unittest
from pathlib import Path

from expectrail import contracts
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

    def test_a_route_carries_only_the_current_format_id(self):
        # The ID from before the October 30 rename was dropped once the pins were retired (Nov 9).
        schema = json.loads((EXAMPLES.parent / "route.schema.json").read_text())
        self.assertEqual(schema["properties"]["format"], {"const": "expectrail.route/v0"})
        route = json.loads((EXAMPLES / "route.json").read_text())
        self.assertEqual(validate(route, "route"), "route")
        route["format"] = "earlier.route/v0"
        with self.assertRaises(ContractError):
            validate(route, "route")
        harness = (EXAMPLES.parent.parent / "harness" / "godot" / "expectrail_harness.gd").read_text()
        self.assertIn('const ROUTE_FORMATS := ["expectrail.route/v0"]', harness)

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


class V1RegistryTest(unittest.TestCase):
    def test_every_v1_schema_is_registered_once(self):
        files = {path.name for path in contracts.SCHEMAS.glob("*.v1.schema.json")}
        registered = [filename for _, filename in contracts.V1_FORMATS.values()]
        self.assertCountEqual(registered, files)
        for format_id, (kind, filename) in contracts.V1_FORMATS.items():
            with self.subTest(filename=filename):
                self.assertEqual(contracts.v1_kind({"format": format_id}), kind)
                self.assertEqual(contracts.schema_v1(kind), json.loads((contracts.SCHEMAS / filename).read_bytes()))

    def test_pre_derivation_mappings_are_identical(self):
        # Frozen snapshot of main 2e014e1. New schemas do not need a line here.
        previous = {
            f"expectrail.{kind}/v1": (kind, f"{kind}.v1.schema.json")
            for kind in (
                "repair-publication", "onboard-review", "onboard-answers", "onboard-timing",
                "template-closeout", "observer-calibration", "playtest-reproduction", "episode",
                "trace-spec", "trace-verdict", "mechanics-profile", "discovery-run", "jit-run",
                "pixel-check", "project", "fixer-invocation", "repair-run",
            )
        }
        current = {name: contracts.V1_FORMATS.get(name) for name in previous}
        self.assertEqual(current, previous)

    def test_a_new_schema_uses_its_format_const_or_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "check.v1.schema.json").write_text(json.dumps(
                {"properties": {"format": {"const": "expectrail.check/v1"}}}))
            (folder / "api.v1.schema.json").write_text(json.dumps(
                {"$id": "https://expectrail.tech/contracts/api.v1.schema.json"}))
            self.assertEqual(contracts._v1_formats(folder), {
                "expectrail.api/v1": ("api", "api.v1.schema.json"),
                "expectrail.check/v1": ("check", "check.v1.schema.json"),
            })

    def test_two_files_claiming_one_format_name_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "one.v1.schema.json").write_text(json.dumps(
                {"properties": {"format": {"const": "expectrail.one/v1"}}}))
            (folder / "two.v1.schema.json").write_text(json.dumps(
                {"$id": "https://expectrail.tech/contracts/one.v1.schema.json"}))
            with self.assertRaisesRegex(ContractError, r"expectrail\.one/v1.*one\.v1\.schema\.json.*two\.v1\.schema\.json"):
                contracts._v1_formats(folder)

    def test_unreadable_schema_or_format_names_the_file(self):
        cases = ('{}', '[]', '{', '{"$id": 7}', '{"$id": "https://example.test/unknown"}',
                 '{"properties": {"format": {"const": "expectrail.invalid/v0"}}}')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bad = folder / "bad.v1.schema.json"
            for content in cases:
                with self.subTest(content=content):
                    bad.write_text(content)
                    with self.assertRaisesRegex(ContractError, r"bad\.v1\.schema\.json"):
                        contracts._v1_formats(folder)


if __name__ == "__main__":
    unittest.main()
