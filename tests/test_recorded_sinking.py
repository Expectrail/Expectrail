"""Judge the bundled smoke route as recorded by Godot, without starting an engine."""
import gzip
import json
import unittest
from pathlib import Path

from agents.observations import from_trace_synthetic
from expectrail.contracts import load
from expectrail.evaluator import evaluate


class RecordedSinkingTest(unittest.TestCase):
    def test_clean_passes_and_sinking_v1_fails_on_the_recorded_traces(self):
        tests = Path(__file__).resolve().parent
        spec = load(tests.parent / "agents/specs/player-stays-above-ground.json", "test-spec")
        for variant, expected in (("clean", "pass"), ("sinking_v1", "fail")):
            with self.subTest(variant=variant):
                with gzip.open(tests / "data/sinking" / f"{variant}.json.gz", "rt", encoding="utf-8") as file:
                    trace = json.load(file)
                verdict = evaluate(spec, from_trace_synthetic(trace))
                self.assertEqual(verdict["result"], expected, verdict["reason"])
