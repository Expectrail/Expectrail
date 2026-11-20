"""The public harmless control requires two independent, stable, exercised arms."""
import unittest

from expectrail.jit import assess


class HarmlessControlTest(unittest.TestCase):
    def test_requires_a_stable_passing_clean_arm(self):
        passing = ["pass"] * 3
        failing = ["fail"] * 3
        self.assertEqual(assess.harmless_outcome(passing, passing), "pass")
        self.assertEqual(assess.harmless_outcome(passing, failing), "false-rejection")
        self.assertEqual(assess.harmless_outcome([], []), "not-run")
        for clean, changed in [(failing, failing), (passing, []), (passing, ["fail"]),
                               (passing, ["pass", "fail", "fail"]),
                               (passing, ["not_exercised"] * 3)]:
            with self.subTest(clean=clean, changed=changed):
                self.assertEqual(assess.harmless_outcome(clean, changed), "indeterminate")

    def test_one_probe_cannot_supply_the_other_probes_coverage(self):
        spec = {'evidenceRequirement': {'minimumTriggers': 1, 'minimumEvaluations': 2}}
        full = {'result': 'pass', 'coverageComplete': True, 'applicable': 'yes',
                'triggeredCount': 1, 'evaluatedCount': 2}
        self.assertEqual(assess.harmless_repetition(spec, [full, dict(full, result='fail')]), 'fail')
        for change in [dict(coverageComplete=False), dict(triggeredCount=0), dict(evaluatedCount=1),
                       dict(applicable='unknown'), dict(result='not_exercised')]:
            with self.subTest(change=change):
                self.assertEqual(assess.harmless_repetition(spec, [full, dict(full, **change)]),
                                 'insufficient_observation')

    def test_frozen_public_record_reports_missing_and_failed_replays(self):
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from expectrail.jit import counting

        root = Path(counting.__file__).resolve().parents[2]
        folder = root / 'bench/jit/recordings/public-43465090517/repro/repro-platforms-not-solid'
        source = json.loads((folder / 'jit-run.json').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            control = counting.HarmlessControl(Path(tmp) / 'controls', root)
            with patch('harness.run.run', side_effect=OSError('engine stopped')) as replay:
                control.measure('platforms-not-solid', source, False, folder)
                replay.assert_not_called()
                self.assertEqual([r['outcome'] for r in control.rows], ['not-run'] * len(source['proposed']))
                control.rows.clear()
                # Supply a schema-valid but different library route in the missing custom slot.
                fake_folder = Path(tmp) / 'repro-platforms-not-solid'
                routes = fake_folder / 'jit-routes'
                routes.mkdir(parents=True)
                (routes / 'jit-r-jit-left38-dbl.json').write_text(json.dumps(next(iter(control.routes.values()))))
                control.measure('platforms-not-solid', source, True, fake_folder)
            self.assertGreater(replay.call_count, 0)
            self.assertTrue(any(r['reason'].startswith('missing exact route') for r in control.rows))
            self.assertTrue(any(r['outcome'] == 'indeterminate' for r in control.rows))
            totals = control.report([])
            self.assertEqual(sum(totals.values()), len(source['proposed']))
            self.assertEqual(totals['pass'] + totals['false-rejection'], 0)
            evidence = json.loads((control.work / 'control.json').read_bytes())
            self.assertEqual(evidence['rows'][0]['sourceRun'], counting.digest_v1(source))
            self.assertTrue(all(r['error'] == 'engine stopped' for pair in evidence['probes'].values()
                                for runs in pair.values() for r in runs))
