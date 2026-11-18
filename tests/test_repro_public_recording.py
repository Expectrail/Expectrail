"""Recompute the published public score from its actual hosted run, without a model or engine."""
import hashlib
import json
import unittest
from pathlib import Path

from expectrail.repro import bench, breakdown, score

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / 'bench/jit/recordings/public-43465090517'


class PublicHostedRecordingTest(unittest.TestCase):
    def test_every_recovered_byte_matches_the_download_manifest(self):
        source = json.loads((RECORDING / 'source.json').read_text())
        for name, digest in source['files'].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((RECORDING / name).read_bytes()).hexdigest(), digest)

    def test_current_reader_reproduces_the_hosted_score_exactly(self):
        original = score.load(RECORDING / 'repro-score/repro-score.json')
        rebuilt = score.score(bench.load(), RECORDING / 'repro', visibility_path=REPO / 'bench/jit/public/visibility.json',
                              source=original['source'])
        self.assertEqual(rebuilt, original)
        # The public hand findings sort otherwise-undetermined misses; never change the score.
        hand = breakdown.load()
        counts = breakdown.counts(breakdown.breakdown(rebuilt, hand))
        self.assertEqual({key: counts.get(key, {'misses': 0})['misses'] for key in ('route-never-reaches', 'no-signal',
                          'probe-language', 'wrong-predicate', 'flaky', 'budget')},
                         {'route-never-reaches': 2, 'no-signal': 2, 'probe-language': 2,
                          'wrong-predicate': 1, 'flaky': 0, 'budget': 0})
        self.assertEqual(rebuilt, original)
