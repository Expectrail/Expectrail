"""Keep the installation instructions at the package's declared Python minimum (#335)."""
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A minimum needs "requires", "+", or "or later/newer". A tested version is not a minimum.
# The optional pipe covers the install guide's "| Python | 3.N or later |" table row.
MINIMUM = re.compile(
    r"\b(?P<requires>requires?[ \t]+)?Python[ \t]+(?:\|[ \t]*)?"
    r"(?P<version>3\.(?:0|[1-9][0-9]*))(?![\w.])"
    r"(?P<floor>\+|[ \t]+or[ \t]+(?:later|newer)\b)?", re.I)


def package_minimum():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        requirement = tomllib.load(stream)["project"]["requires-python"]
    match = re.fullmatch(r">=(3\.(?:0|[1-9][0-9]*))", requirement)
    if not match:
        raise AssertionError(f"Unrecognised requires-python: {requirement!r}; update this test's parser")
    return match[1]


def check_minimum(text, name, expected):
    versions = [m["version"] for m in MINIMUM.finditer(text) if m["requires"] or m["floor"]]
    if not versions:
        raise AssertionError(f"{name}: no minimum Python version found")
    for version in versions:
        if version != expected:
            raise AssertionError(
                f"{name}: minimum Python {version} differs from pyproject.toml requires-python >={expected}")


class PythonFloorTest(unittest.TestCase):
    def test_readme_matches_package(self):
        check_minimum((ROOT / "README.md").read_text(encoding="utf-8"), "README.md", package_minimum())

    def test_install_guide_matches_package(self):
        check_minimum((ROOT / "docs/install.md").read_text(encoding="utf-8"), "docs/install.md", package_minimum())


class MinimumParserTest(unittest.TestCase):
    def test_plain_plus_later_and_table_forms(self):
        for text in ("Requires Python 3.12", "Python 3.12+", "Python 3.12 or later",
                     "Python 3.12 or newer", "| Python | 3.12 or later | yes |"):
            with self.subTest(text=text):
                check_minimum(text, "example.md", "3.12")

    def test_wrong_minimum_below_and_above(self):
        for version in ("3.0", "3.9", "3.10", "3.11", "3.13", "3.120"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(AssertionError, rf"example.md: minimum Python {re.escape(version)} differs"):
                    check_minimum(f"Requires Python {version}+", "example.md", "3.12")

    def test_missing_minimum_fails_even_with_other_versions(self):
        for text in ("", "Install Python.", "Tested on Python 3.12 and Python 3.13.",
                     "Not shown: Python below 3.12.", "Godot 3.12 or later; Python is also needed."):
            with self.subTest(text=text):
                with self.assertRaisesRegex(AssertionError, "example.md: no minimum Python version found"):
                    check_minimum(text, "example.md", "3.12")

    def test_partial_versions_are_not_read_as_a_minor_version(self):
        for version in ("3.12.1", "3.12rc1", "3.012", "3.x"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(AssertionError, "no minimum Python version found"):
                    check_minimum(f"Requires Python {version}+", "example.md", "3.12")

    def test_a_matching_statement_does_not_hide_a_wrong_table_row(self):
        text = "Python 3.12 or later\n| Python | 3.11 or later | yes |"
        with self.assertRaisesRegex(AssertionError, "minimum Python 3.11 differs"):
            check_minimum(text, "docs/install.md", "3.12")

    def test_readme_copy_with_old_minimum_is_rejected(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        changed = MINIMUM.sub(lambda m: m[0].replace(m["version"], "3.10"), text, count=1)
        self.assertIn("Python 3.10+", changed)
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "README.md"
            copy.write_text(changed, encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "README.md: minimum Python 3.10 differs"):
                check_minimum(copy.read_text(encoding="utf-8"), copy.name, package_minimum())


if __name__ == "__main__":
    unittest.main()
