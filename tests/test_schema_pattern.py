"""A schema's `pattern` matches as JSON Schema means it (#251, from the merge guard's review of #367):
`$` is the end of the string, not "before a final newline", and `\\d` is an ASCII digit. One
place, `expectrail.gate.record.schema_pattern`, so every contract reader gets it."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from expectrail.gate import record as rec
from expectrail.gate import verify as gv

REPO = Path(__file__).resolve().parent.parent


class SchemaPatternTest(unittest.TestCase):
    def test_a_name_followed_by_a_newline_is_refused(self):
        doc = json.loads((REPO / "contracts" / "examples" / "findings.json").read_text(encoding="utf-8"))
        rec.check_record(doc)
        bad = copy.deepcopy(doc)
        bad["adapter"] = doc["adapter"] + "\n"
        with self.assertRaises(rec.RecordError):
            rec.check_record(bad)

    def test_a_verify_request_with_a_trailing_newline_in_its_adapter_is_refused(self):
        schema = json.loads((REPO / "contracts" / "verify-request.v1.schema.json").read_text(encoding="utf-8"))
        doc = json.loads((REPO / "contracts" / "examples" / "verify-request.json").read_text(encoding="utf-8"))
        rec.validate(doc, schema)
        bad = copy.deepcopy(doc)
        bad["project"]["adapter"] = "godot\n"
        with self.assertRaises(rec.RecordError):
            rec.validate(bad, schema)

    def test_the_translation(self):
        cases = [
            ("^[a-z]+$", "godot", True), ("^[a-z]+$", "godot\n", False),
            ("(^|/)\\.\\.?(/|$)", "a/..", True), ("(^|/)\\.\\.?(/|$)", "a/..\n", False),
            ("^[$]+$", "$$", True), ("^a\\$$", "a$", True), ("^a\\$$", "a$\n", False),
            ("^\\d+$", "123", True), ("^\\d+$", "١٢", False),
            ("^[0-9a-f]{12}$", "0123456789ab", True), ("^[0-9a-f]{12}$", "0123456789ab\n", False),
        ]
        for pattern, value, want in cases:
            self.assertEqual(rec.schema_pattern(pattern).search(value) is not None, want, (pattern, value))

    def test_every_contract_pattern_compiles_and_refuses_a_trailing_newline_where_anchored(self):
        seen = 0
        for path in sorted((REPO / "contracts").glob("*.json")):
            stack = [json.loads(path.read_text(encoding="utf-8"))]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key == "pattern" and isinstance(value, str):
                            seen += 1
                            compiled = rec.schema_pattern(value)
                            if value.startswith("^") and value.endswith("$"):
                                self.assertIsNone(compiled.search("x\n"), (path.name, value))
                        else:
                            stack.append(value)
                elif isinstance(node, list):
                    stack.extend(node)
        self.assertGreater(seen, 10)


class AdapterArgumentTest(unittest.TestCase):
    def test_an_adapter_that_is_not_a_string_is_a_config_error(self):
        for name in (["godot"], None, 3, {"name": "godot"}):
            with self.assertRaises(gv.ConfigError):
                gv.adapter_for(name)

    def test_a_registered_adapter_given_as_itself_still_resolves(self):
        from harness import adapters

        self.assertEqual(gv.adapter_for(adapters.get("godot")).name, "godot")
        self.assertEqual(gv.adapter_for("godot").name, "godot")


if __name__ == "__main__":
    unittest.main()
