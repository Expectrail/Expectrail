"""Every destination a reader can follow from the repair story exists in the tested tree."""
import re
import unittest

from tools import front_door as front


class LoopStoryTest(unittest.TestCase):
    def test_every_story_link_resolves_including_fragments(self):
        for name in ("docs/index.html", "docs/concepts.html", "README.md"):
            with self.subTest(page=name):
                path = front.ROOT / name
                text = path.read_text()
                if name.endswith(".md"):
                    start = text.index("## Verify, then repair\n")
                    section = text[start:].split("\n##", 1)[0]
                    links = re.findall(r"\[[^\]]+\]\(([^\s)]+)\)", section)
                else:
                    start = text.index('id="repair"')
                    section = text[start:].split("</section>", 1)[0]
                    self.assertIn("<svg ", section)
                    links = front.Page(section).links
                self.assertTrue(links)
                targets = set()
                for link in links:
                    with self.subTest(link=link):
                        found = front.target(front.ROOT, path, link)
                        self.assertIsNotNone(found, "use a checkable project destination")
                        destination, fragment = found
                        self.assertTrue(destination.is_file(), destination)
                        if fragment:
                            self.assertIn(fragment, front.anchors(destination))
                        targets.add(destination.relative_to(front.ROOT).as_posix())
                self.assertTrue({"docs/run-it/index.html", "docs/viewer-samples/fixture-repair.html",
                                 "docs/app.md"} <= targets)
