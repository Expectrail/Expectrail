import hashlib
"""The home page's interactive parts stay true to the page and to the benches (direction B)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs/index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "docs/assets/home.js").read_text(encoding="utf-8")


def mode(name: str) -> dict:
    body = re.search(name + r": \{(.*?)\}", SCRIPT, re.S)[1]
    return dict(re.findall(r"(\w+): '([^']*)'", body))


class HomeInteractiveTest(unittest.TestCase):
    def test_the_page_loads_its_script_and_styles(self):
        # Each link carries the first 10 hex digits of the file's SHA-256, so a browser holding an older copy
        # fetches the new one as soon as the page changes. A stale tag fails here.
        for name, tag in (("home.js", '<script src="assets/home.js?v={}" defer></script>'),
                          ("home.css", '<link rel="stylesheet" href="assets/home.css?v={}">')):
            digest = hashlib.sha256((ROOT / "docs/assets" / name).read_bytes()).hexdigest()[:10]
            self.assertIn(tag.format(digest), PAGE)

    def test_the_switch_html_shows_the_both_state_the_script_holds(self):
        both = mode("both")
        for key in ("verdict", "caught", "fooled", "blocked"):
            self.assertIn(f'data-field="{key}">{both[key]}<', PAGE, key)
        self.assertEqual(set(re.findall(r'data-mode="(\w+)"', PAGE)), {"engine", "judge", "both"})

    def test_every_switch_count_is_in_its_bench(self):
        detection = (ROOT / "bench/detection/README.md").read_text(encoding="utf-8")
        glimmer = (ROOT / "bench/judge/glimmer/README.md").read_text(encoding="utf-8")
        judge = (ROOT / "bench/judge/README.md").read_text(encoding="utf-8")
        self.assertIn("Without vision: **4 of 8**", detection)
        self.assertIn("**8 of 8**", detection)
        self.assertIn("| Expectrail, SAM on | 41230177124 | 8 of 8 | 0 of 7 | 0 |", glimmer)
        self.assertIn("| Expectrail, SAM off | 41230177124 | 8 of 8 | 3 of 7 | 0 |", glimmer)
        self.assertIn("| Muse from screenshots | 40936362830 | 6 of 8 | 2 of 7 | 0 |", judge)
        self.assertIn("| Muse from screenshots | 40943391994 | 7 of 8 | 2 of 7 | 0 |", judge)
        # The recorded case the switch shows: accepted with vision off and by Muse, rejected with vision on.
        self.assertIn("| bad/fall-through-sink-player | reject | reject, reject | accept, accept | accept, accept |", judge)
        self.assertEqual((mode("engine")["fooled"], mode("judge")["fooled"], mode("both")["fooled"]),
                         ("3 of 7", "2 of 7", "0 of 7"))
        self.assertEqual((mode("engine")["caught"], mode("both")["caught"]), ("4 of 8", "8 of 8"))

    def test_every_flow_button_has_an_explanation_and_every_scenario_a_real_path(self):
        nodes = set(re.findall(r'data-node="(\w+)"', PAGE))
        explained = set(re.findall(r"^    (\w+): \{ title:", SCRIPT, re.M))
        self.assertEqual(nodes, explained)
        for name, path in re.findall(r"(\w+): \[((?:'\w+',?\s*)+)\]", SCRIPT):
            with self.subTest(scenario=name):
                self.assertTrue(set(re.findall(r"'(\w+)'", path)) <= nodes)
        self.assertEqual(set(re.findall(r'data-scenario="(\w+)"', PAGE)), {"accept", "reject", "review"})

    def test_the_repair_stepper_covers_the_five_stages_and_notes(self):
        section = PAGE[PAGE.index('id="repair"'):].split("</section>", 1)[0]
        for hook in ("data-loop-play", "data-loop-prev", "data-loop-next", "data-loop-status"):
            self.assertIn(hook, section)
        self.assertEqual(section.count("<rect "), 5)
        self.assertEqual(section.count("<li>"), 5)
        self.assertIn("var noteFor = [[0], [0], [1], [2, 3], [4]];", SCRIPT)

    def test_counting_numbers_already_show_their_value_without_the_script(self):
        counts = re.findall(r'<span data-count="([\d.]+)"(?: data-decimals="\d")?>([\d.]+)</span>', PAGE)
        self.assertGreaterEqual(len(counts), 6)
        for target, shown in counts:
            self.assertEqual(target, shown)

    def test_scroll_in_text_is_hidden_only_when_the_script_runs(self):
        css = (ROOT / "docs/assets/home.css").read_text(encoding="utf-8")
        self.assertIn(".js .reveal{opacity:0", css)
        self.assertNotRegex(css, r"(?m)^\.reveal\{[^}]*opacity:0")
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertIn("document.documentElement.classList.add('js')", PAGE)

    def test_how_it_works_shows_the_four_term_equation_in_order_with_a_pause(self):
        start = PAGE.index('<figure class="equation')
        fig = PAGE[start:PAGE.index("</figure>", start)]
        kinds = re.findall(r'<p class="eq-kind">([^<]+)</p>', fig)
        self.assertEqual(kinds, ["External perceptual sensor", "Internal runtime telemetry",
                                 "Deterministic evaluator", "Evidence-driven repair"])
        self.assertIn("SAM 3.1", fig)
        self.assertIn("Muse Glimmer 30B", fig)
        self.assertIn('href="#repair"', fig)
        self.assertIn("data-eq-play", fig)
        self.assertIn("accepts only when both sources agree", fig)


if __name__ == "__main__":
    unittest.main()
