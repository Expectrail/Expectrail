"""A schema's `pattern` matches as JSON Schema means it (#251, from the merge guard's review of #367):
`$` is the end of the string, not "before a final newline", and `\\d` is an ASCII digit. One
place, `expectrail.gate.record.schema_pattern`, so every contract reader gets it."""
from __future__ import annotations

import copy
import json
import re
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

    def test_every_contract_pattern_has_a_matching_sample_and_refuses_it_with_a_newline(self):
        # A value that matches each pattern, so "plus a newline is refused" proves something.
        # A pattern added to a contract must get a row here.
        patterns = contract_patterns()
        self.assertGreater(len(patterns), 10)
        missing = sorted(set(patterns) - set(SAMPLES))
        self.assertEqual(missing, [], "add a sample for each new contract pattern")
        for pattern in sorted(patterns):
            sample, newline_refused = SAMPLES[pattern]
            compiled = rec.schema_pattern(pattern)
            self.assertIsNotNone(compiled.search(sample), (patterns[pattern], pattern, sample))
            if newline_refused:
                self.assertIsNone(compiled.search(sample + "\n"), (patterns[pattern], pattern, sample))
                # and main's reading (plain re.search) did take it, so the test shows the change
                self.assertIsNotNone(re.search(pattern, sample + "\n"), (pattern, sample))

    def test_the_capabilities_field_still_refuses_unicode_space_at_either_end(self):
        schema = json.loads((REPO / "contracts" / "capabilities.v1.schema.json").read_text(encoding="utf-8"))
        field = None
        stack = [schema]
        while stack and field is None:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("pattern", "").startswith("^[^;\\s]"):
                    field = node["pattern"]
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        self.assertIsNotNone(field)
        compiled = rec.schema_pattern(field)
        self.assertIsNotNone(compiled.search("x"))
        self.assertIsNotNone(compiled.search("a b"))
        for space in (" ", " ", "　", " ", "\t"):
            self.assertIsNone(compiled.search(space + "x"), repr(space))
            self.assertIsNone(compiled.search("x" + space), repr(space))

    def test_never_accepts_what_pythons_reading_refuses(self):
        # The review's rule: reading a pattern differently must not accept anything main refused.
        # Probe every contract pattern and the translation table's own patterns with values built
        # from the samples and from the characters where the readings differ.
        extra = ["^\\D+$", "^\\W+$", "^[^\\d]+$", "^[^\\w]+$", "^[\\D]+$", "^[\\W]+$", "^\\s*$", "^\\S+$",
                 "^\\w+$", "^[\\w.]+$", "^\\d{2}$"]
        tricky = ["", "x", "\n", "x\n", " ", " ", "　", "٣", "é", "_", "9", "a b",
                  "٣٤", "aé", "  ", "\t", ";", "{n}", "$", "\\"]
        patterns = sorted(set(contract_patterns()) | set(extra))
        for pattern in patterns:
            values = set(tricky)
            if pattern in SAMPLES:
                sample = SAMPLES[pattern][0]
                values |= {sample, sample + "\n", " " + sample, sample + "　", sample[:-1],
                           sample + "x", sample.upper(), sample.replace("0", "٠")}
            compiled = rec.schema_pattern(pattern)
            for value in values:
                if compiled.search(value) is not None:
                    self.assertIsNotNone(re.search(pattern, value), (pattern, value))

    def test_ascii_classes_and_unicode_whitespace(self):
        cases = [
            ("^\\w+$", "abc_9", True), ("^\\w+$", "é", False),
            ("^[\\w.]+$", "a.b", True), ("^[\\w.]+$", "é", False),
            ("^\\D+$", "ab", True), ("^\\D+$", "a1", False), ("^\\W+$", "--", True), ("^\\W+$", "a", False),
            ("^\\s+$", " 　", True), ("^\\S+$", "a ", False),
            ("^[^\\s]+$", "a ", False),
        ]
        for pattern, value, want in cases:
            self.assertEqual(rec.schema_pattern(pattern).search(value) is not None, want, (pattern, value))

    def test_a_misread_pattern_still_refuses_what_python_refuses(self):
        # The fallback: even if the translated reading took a value, Python's reading must as well.
        compiled = rec.schema_pattern("^[a-z]+$")
        broken = rec.SchemaPattern(compiled.pattern, re.compile(".*"), compiled.python)
        self.assertIsNone(broken.search("ABC"))
        self.assertIsNotNone(broken.search("abc"))


def contract_patterns() -> dict[str, str]:
    """Every `pattern` string in `contracts/*.json`, with the first file it appears in."""
    found: dict[str, str] = {}
    for path in sorted((REPO / "contracts").glob("*.json")):
        stack = [json.loads(path.read_text(encoding="utf-8"))]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "pattern" and isinstance(value, str):
                        found.setdefault(value, path.name)
                    else:
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return found


# pattern: (a value that matches it, whether that value plus "\n" must be refused)
SAMPLES = {
    "(^|/)\\.\\.?(/|$)": ("a/..", True),
    "(^|[^0-9{}])\\{n\\}[^0-9{}](.*[^0-9{}])?\\{of\\}([^0-9{}]|$)|(^|[^0-9{}])\\{of\\}[^0-9{}](.*[^0-9{}])?\\{n\\}([^0-9{}]|$)":
        ("{n} of {of}", False),  # "\n" is itself a separator here, so a trailing one still matches
    "^(\\.|[A-Za-z0-9_][A-Za-z0-9._/-]*)$": ("game/a.gd", True),
    "^(bench|bugs)/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$": ("bench/a/b.json", True),
    "^(reference|candidate|clean|held-out-[0-9]+|unlabelled)$": ("held-out-2", True),
    "^EXPECTRAIL_[A-Z_]+\\*?$": ("EXPECTRAIL_SEED*", True),
    "^[0-9A-Za-z.+-]+$": ("4.3-stable", True),
    "^[0-9]{4}-[0-9]{2}-[0-9]{2}$": ("2026-11-13", True),
    "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$": ("2026-11-13T04:38:12.5Z", True),
    "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$": ("2026-11-13T04:38:12Z", True),
    "^[0-9a-f]{12}$": ("0123456789ab", True),
    "^[0-9a-f]{16}$": ("0123456789abcdef", True),
    "^[0-9a-f]{32}$": ("0123456789abcdef" * 2, True),
    "^[0-9a-f]{40}$": ("0123456789" * 4, True),
    "^[0-9a-f]{64}$": ("0123456789abcdef" * 4, True),
    "^[A-Za-z0-9._:-]{1,128}$": ("run:1.a-b", True),
    "^[A-Za-z0-9_-]{1,60}$": ("player-stays_up", True),
    "^[A-Za-z0-9_.][A-Za-z0-9_./-]*(#[A-Za-z0-9_-]+)?$": ("specs/a.yml#check-1", True),
    "^[^;\\s]([^;\\n\\r]*[^;\\s])?$": ("frame count", True),
    "^[^\\n\\r]*$": ("one line", True),
    "^[^\\u0000-\\u001f\\u007f-\\u009f\\u2028\\u2029]*$": ("plain text", False),  # "\n" is refused anyway
    "^[a-z0-9-]+\\.yml$": ("verify.yml", True),
    "^[a-z0-9]+(-[a-z0-9]+)*$": ("smoke-route", True),
    "^[a-z0-9][a-z0-9-]*$": ("godot", True),
    "^[a-z0-9][a-z0-9._/-]*$": ("game/main.tscn", True),
    "^[a-z][a-z0-9-]{0,31}$": ("combat", True),
    "^[a-z][a-z0-9-]{0,39}$": ("combat-2", True),
    "^[a-z_][a-z0-9_]*(\\.[a-z_][a-z0-9_]*)*$": ("player.position_y", True),
    "^assets/[a-z0-9-]+\\.png$": ("assets/run-it.png", True),
    "^docs/[a-z0-9-]+\\.md$": ("docs/review.md", True),
    "^https://github\\.com/Expectrail/Expectrail/actions/runs/[0-9]+(/job/[0-9]+)?$":
        ("https://github.com/Expectrail/Expectrail/actions/runs/1/job/2", True),
    "^jit-[a-z0-9][a-z0-9._/-]{0,120}$": ("jit-a/b", True),
    "^review-[0-9]{8}T[0-9]{6}Z-[0-9]{5}$": ("review-20261113T043812Z-00001", True),
    "frames/f%08d.png": ("frames/f%08d.png", False),  # not anchored
}


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
