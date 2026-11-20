"""The public counting audit re-run with #675's pieces: do-nothing rows bound by digest, metamorphic rows reported."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.jit import bench, counting

ROOT = Path(counting.__file__).resolve().parents[2]
RECORDS = ROOT / 'bench/jit/recordings/public-43465090517/repro'


def records():
    for defect in bench.public_cases()['defects']:
        run = json.loads((RECORDS / f"repro-{defect['id']}" / 'jit-run.json').read_bytes())
        yield defect['id'], run


def rows_doc(outcome_for=lambda defect, check: 'fails'):
    rows = []
    for defect, run in records():
        for entry in run['proposed']:
            rows.append({'defect': defect, 'check': entry['spec']['id'], 'specSha256': digest_v1(entry['spec']),
                         'sourceRun': digest_v1(run), 'outcome': outcome_for(defect, entry['spec']['id'])})
    return {'rows': rows}


class DoNothingInTheAudit(unittest.TestCase):
    def audit(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rows.json'
            path.write_text(json.dumps(doc))
            out = Path(tmp) / 'page.md'
            result = counting.public_bench(RECORDS, out, do_nothing=path)
            return result, out.read_text()

    def test_without_rows_the_counts_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = counting.public_bench(RECORDS, Path(tmp) / 'page.md')
            page = (Path(tmp) / 'page.md').read_text()
        self.assertEqual((result['checks'], result['counting'], result['legacyKeptAdvisory']), (137, 0, 91))
        self.assertNotIn('doNothing', result)
        self.assertNotIn('## Do-nothing control', page)
        self.assertEqual(result['metamorphicRows'], 0)
        self.assertIn('Metamorphic rows in these records: 0.', page)

    def test_a_check_that_passes_the_control_is_dropped_with_its_catch(self):
        result, page = self.audit(rows_doc(lambda d, c: 'passes' if d == 'air-jump' else 'fails'))
        t = result['doNothing']
        air = {d: run for d, run in records()}['air-jump']
        air_kept = sum(bool(v['valid']) for v in air['validity'])
        self.assertEqual(t['legacyKept'], 91)
        self.assertEqual(t['dropped'], air_kept)
        self.assertEqual(t['kept'], 91 - air_kept)
        self.assertEqual(t['cannotTell'], 0)
        self.assertEqual(t['catchesDropped'], len(air['catches']))
        self.assertEqual(t['defectsWithNoCatchKept'], ['air-jump'])
        # The control never changes the counting classification.
        self.assertEqual((result['checks'], result['counting']), (137, 0))
        self.assertIn(f'| air-jump | {air_kept} | {air_kept} | 0 | 0 | {len(air["catches"])} | 0 |', page)
        self.assertIn('every recorded catch is dropped: `air-jump`.', page)

    def test_fails_indeterminate_and_not_run_are_kept(self):
        for outcome in ('fails', 'indeterminate', 'not-run'):
            with self.subTest(outcome):
                result, _ = self.audit(rows_doc(lambda d, c: outcome))
                self.assertEqual((result['doNothing']['kept'], result['doNothing']['dropped']), (91, 0))
                self.assertEqual(result['doNothing']['keptBy'][outcome], 91)

    def test_a_row_for_another_record_or_another_check_is_cannot_tell(self):
        doc = rows_doc(lambda d, c: 'passes')
        changed = []
        for row in doc['rows']:
            if row['defect'] == 'slow-left':
                row['sourceRun'] = '0' * 64
                changed.append(row['check'])
            elif row['defect'] == 'gun-cooldown':
                row['specSha256'] = '1' * 64
                changed.append(row['check'])
        doc['rows'] = [r for r in doc['rows'] if not (r['defect'] == 'coin-stays')]
        result, page = self.audit(doc)
        t = result['doNothing']
        recs = dict(records())
        unbound = {'slow-left', 'gun-cooldown', 'coin-stays'}
        expected = sum(bool(v['valid']) for d in unbound for v in recs[d]['validity'])
        self.assertEqual(t['cannotTell'], expected)
        self.assertEqual(t['dropped'], 91 - expected)
        self.assertEqual(t['kept'], 0)
        # Cannot tell is not "every catch dropped".
        self.assertFalse(unbound & set(t['defectsWithNoCatchKept']))
        self.assertIn('"cannot tell"', page)

    def test_bad_rows_are_refused(self):
        good = rows_doc()
        twice = {'rows': good['rows'] + good['rows'][:1]}
        stranger = {'rows': good['rows'] + [dict(good['rows'][0], check='jit-not-in-any-record')]}
        unknown = {'rows': [dict(good['rows'][0], outcome='maybe')] + good['rows'][1:]}
        for name, doc in [('twice', twice), ('stranger', stranger), ('unknown outcome', unknown),
                          ('no rows', {}), ('no check', {'rows': [{'defect': 'air-jump'}]})]:
            with self.subTest(name), self.assertRaises(ValueError):
                self.audit(doc)


class CustomRoutes(unittest.TestCase):
    def test_a_supplied_route_is_used_only_with_the_recorded_digest(self):
        from expectrail.discovery.route_compiler import compile_route
        from expectrail.jit.probes import jit_library

        actions = json.loads((ROOT / 'discovery/platformer.profile.json').read_text())['actions']
        probe = jit_library(actions)[0]
        route = compile_route(probe['program'], name=probe['id'], description=probe['description'], actions=actions)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'repro-example'
            (folder / 'jit-routes').mkdir(parents=True)
            (folder / 'jit-routes' / 'jit-r-made-up.json').write_text(json.dumps(route))
            self.assertEqual(counting.public_custom_route(folder, 'r-made-up', digest_v1(route)), route)
            self.assertEqual(counting.public_custom_route(folder, 'jit-r-made-up', digest_v1(route)), route)
            self.assertIsNone(counting.public_custom_route(folder, 'r-made-up', '2' * 64))
            self.assertIsNone(counting.public_custom_route(folder, 'r-made-up', None))
            self.assertIsNone(counting.public_custom_route(folder, 'r-absent', digest_v1(route)))
            self.assertIsNone(counting.public_custom_route(folder, '../r-made-up', digest_v1(route)))

    def test_the_do_nothing_tool_runs_a_supplied_custom_route(self):
        from tests.test_discovery import FakeGame
        from tools import do_nothing_public as tool

        fake = FakeGame()

        def runner(route, out, game=None, patches=(), capture_frames=False, ui_integers=False):
            fake(route, out, patches=[])
            return {"engine": {"version": "stand-in"}, "game": {"patchSha256": None}}

        with tempfile.TemporaryDirectory() as tmp:
            recs = Path(tmp) / 'records'
            shutil.copytree(RECORDS, recs)
            base = tool.measure(Path(tmp) / 'w1', records=recs, runner=runner)
            custom = [r for r in base['rows'] if r['reason'] and r['reason'].startswith('route not in the probe library')]
            self.assertTrue(custom)
            # Every row names its record and check by digest, so the audit can bind it.
            runs = dict(records())
            for r in base['rows']:
                self.assertEqual(r['sourceRun'], digest_v1(runs[r['defect']]))
            # Supply one missing route under a wrong digest: still not run.
            target = custom[0]
            run = runs[target['defect']]
            entry = next(e for e in run['proposed'] if e['spec']['id'] == target['check'])
            probes = {p['id']: p['routeSha256'] for p in run['probes']}
            library = tool.library_routes(json.loads((ROOT / 'discovery/platformer.profile.json').read_text()))
            missing = [pid for pid in entry['probeIds'] if probes[pid] not in library]
            folder = recs / f"repro-{target['defect']}" / 'jit-routes'
            folder.mkdir(exist_ok=True)
            for pid in missing:
                (folder / ('jit-' + pid.removeprefix('jit-') + '.json')).write_text(json.dumps(next(iter(library.values()))))
            again = tool.measure(Path(tmp) / 'w2', records=recs, runner=runner)
            row = next(r for r in again['rows'] if (r['defect'], r['check']) == (target['defect'], target['check']))
            self.assertEqual(row['outcome'], 'not-run')
            self.assertIn('not supplied beside the record', row['reason'])


if __name__ == '__main__':
    unittest.main()
