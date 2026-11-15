"""The public summaries cite the observed outside run and keep its four outcomes together."""
import re
import unittest
from html.parser import HTMLParser

from tools import dossier, front_door


class VerdictLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.href = None
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs)["href"]

    def handle_endtag(self, tag):
        if tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.href:
            self.links.append((data, self.href))


class OutsideResultTest(unittest.TestCase):
    def test_pages_link_each_observed_verdict_and_the_total_to_its_run(self):
        root = front_door.ROOT
        source = (root / dossier.OUTSIDE).read_text().split("## First outside game verified with vision", 1)[1]
        run = re.search(r"\[Run \d+\]\(([^)]+)\)", source)[1]
        cost = re.search(r"\$[\d.]+ at list price", source)[0].split()[0]
        cases = next(rows for _, rows in dossier.tables(source) if rows[0][:2] == ["Change", "Verdict"])
        self.assertEqual(len(cases[1:]), 4)
        for name in ("README.md", "docs/index.html", "docs/release/index.html"):
            with self.subTest(page=name):
                text = (root / name).read_text()
                if name.endswith(".md"):
                    section = text.split("## What’s been shown\n", 1)[-1].split("\n## ", 1)[0]
                    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", section)
                else:
                    section = text.split('id="outside-vision"', 1)[-1].split("</section>", 1)[0]
                    links = VerdictLinks(section).links
                observed = [label for label, href in links if href == run and label in dossier.DECISIONS]
                self.assertEqual(observed, [row[1] for row in cases[1:]])
                self.assertIn((cost, run), links)
                if name != "docs/release/index.html":
                    self.assertIn("Dodge the Creeps", section)
                    for suffix in ("docs/capabilities.md#outside-projects", "docs/outside-projects.md",
                                   "/pull/481", "#blind"):
                        self.assertTrue(any(suffix in href for _, href in links), suffix)
                else:
                    self.assertNotIn("First successfully verified outside project with vision:", text)
                    self.assertIn("Attempted vision run", text)

    def test_dossier_refuses_an_incomplete_record(self):
        sources = dossier.sources(front_door.ROOT, "0" * 40)
        report = sources[dossier.OUTSIDE]
        report.text = "\n".join(line for line in report.text.splitlines()
                                if not line.startswith("| invisible (sprite hidden) |"))
        with self.assertRaisesRegex(dossier.EvidenceError, "cohort incomplete"):
            dossier.outside(sources[dossier.COMMENTS], report)
