"""Frozen closeout accounting; image checks skip by name without optional libraries."""
import copy
import json
import unittest
from pathlib import Path
from tools import template_sensor_closeout as closeout
from expectrail.contracts import digest,validate_v1
from tests.test_template_sensor import needs_pixels,replay,CONFIG,SPEC,TREE,ts


def runs_fixture():
    statuses=[['matched','matched','unavailable','matched','out-of-frame'],
              ['matched','displaced','not-found','out-of-frame','unavailable'],
              ['not-found','not-found','unavailable','matched','out-of-frame'],
              ['not-found','not-found','unavailable','not-found','out-of-frame'],
              ['matched','matched','unavailable','matched','out-of-frame']]
    rows=[]
    for name,values in zip(closeout.CASES,statuses):
        frames=[{'frame':i,'pngSha256':('b' if name=='invisible-player' else 'a')*64,'status':s,
                 'newPixel':i!=0 or name=='invisible-player','crossed':name=='fall-through' and i in (1,3),
                 'newCrossed':name=='fall-through' and i in (1,3),'regionUnknown':s in ('unavailable','out-of-frame')}
                 for i,s in enumerate(values)]
        rows.append({'name':name,'route':'synthetic-example','frames':frames,'sources':{'synthetic-source.json':'a'*64},
                     'newPixelSelectionSha256':digest([f['frame'] for f in frames if f['newPixel']])})
    return rows


def proof_fixture():
    return {'identicalPredictions':True,'identicalEngineCueRows':True,'entireTraceRowsIdentical':True,
            'cleanCueSha256':'a'*64,'hiddenCueSha256':'a'*64,'frames':5,'rule':'Synthetic contract example only.'}


def report_fixture():
    runs=runs_fixture();proof=proof_fixture()
    return {'format':closeout.FORMAT,'baseCommit':'a'*40,'planSha256':'a'*64,
            'bank':{'rawSha256':'a'*64,'canonicalSha256':'a'*64,'algorithm':'synthetic-example','threshold':.9,
                    'templates':1,'calibrationStatus':'met'},'sensorFiles':{'synthetic.py':'a'*64},'runs':runs,
            'pixelOnlyProof':proof,'summary':closeout.summarize_runs(runs,proof),
            'scope':{'optIn':True,'modelCalls':0,'defaultVerdictChanged':False,
                     'calibrationOrThresholdsChangedAfterFreeze':False,'newPixelRule':'Synthetic contract example, not a recorded measurement.'}}


class Accounting(unittest.TestCase):
    def test_unknowns_are_separate_and_not_a_pass_or_a_false_alarm(self):
        result=closeout.metrics(runs_fixture()[0]['frames'],clean=True)
        self.assertEqual((result['frames'],result['measured'],result['agreementRate']),(5,3,1))
        self.assertEqual(result['counts']['unavailable'],1);self.assertEqual(result['counts']['out-of-frame'],1)
        self.assertEqual(result['falseAlarmRate'],0)

    def test_no_measurement_is_null_never_perfect_agreement(self):
        frames=copy.deepcopy(runs_fixture()[0]['frames'])
        for f in frames:f.update(status='unavailable',crossed=False,newCrossed=False)
        result=closeout.metrics(frames,clean=True)
        self.assertIsNone(result['agreementRate']);self.assertIsNone(result['falseAlarmRate'])

    def test_presence_and_region_alarm_union_counts_a_frame_once(self):
        frames=runs_fixture()[1]['frames'];frames[1].update(crossed=True,newCrossed=True)
        result=closeout.metrics(frames,clean=True)
        self.assertEqual(result['alarmFrames'],[1,2]);self.assertEqual(result['falseAlarmRate'],2/3)

    def test_unknown_cannot_supply_a_crossing(self):
        frames=runs_fixture()[0]['frames'];frames[2]['crossed']=True
        with self.assertRaisesRegex(ValueError,'Unknown evidence'):closeout.metrics(frames)

    def test_seed_alarm_rates_are_not_called_false_alarm_rates(self):
        result=closeout.metrics(runs_fixture()[2]['frames'])
        self.assertIsNone(result['falseAlarmRate']);self.assertEqual(result['alarmRate'],2/3)

    def test_pair_needs_matching_clean_and_two_new_hashes_for_new_column(self):
        rows=runs_fixture()
        self.assertEqual(closeout.paired(rows[0]['frames'],rows[2]['frames']),[0,1])
        self.assertEqual(closeout.paired(rows[0]['frames'],rows[2]['frames'],novel=True),[1])
        rows[0]['frames'][1]['status']='not-found'
        self.assertEqual(closeout.paired(rows[0]['frames'],rows[2]['frames'],novel=True),[])

    def test_common_region_alarm_is_not_a_discriminating_seed_event(self):
        rows=runs_fixture();rows[0]['frames'][1].update(crossed=True,newCrossed=True)
        self.assertEqual(closeout.paired(rows[0]['frames'],rows[4]['frames'],region=True),[3])

    def test_rates_and_done_when_are_derived_not_caller_assertions(self):
        doc=report_fixture();closeout.validate_report(doc)
        doc['summary']['pooledClean']['raw']['falseAlarmRate']=0
        with self.assertRaisesRegex(ValueError,'figures'):closeout.validate_report(doc)

    def test_missing_or_duplicate_frames_and_cases_refuse(self):
        for change in ('duplicate','missing-case'):
            rows=runs_fixture()
            if change=='duplicate':rows[0]['frames'][1]['frame']=0
            else:rows.pop()
            with self.subTest(change=change),self.assertRaises(ValueError):closeout.summarize_runs(rows,proof_fixture())

    def test_pixel_only_claim_requires_equal_engine_cues_and_a_new_pair(self):
        proof=proof_fixture();proof['hiddenCueSha256']='b'*64
        result=closeout.summarize_runs(runs_fixture(),proof)
        self.assertFalse(result['doneWhen']['allMet'])
        proof=proof_fixture();proof['frames']=6
        with self.assertRaisesRegex(ValueError,'denominator'):closeout.summarize_runs(runs_fixture(),proof)

    def test_new_pixel_selection_hash_cannot_be_substituted(self):
        doc=report_fixture();doc['runs'][0]['newPixelSelectionSha256']='b'*64
        with self.assertRaisesRegex(ValueError,'selection digest'):closeout.validate_report(doc)

    def test_contract_example_and_markdown_keep_seed_and_clean_meanings_separate(self):
        doc=report_fixture();validate_v1(doc,'template-closeout')
        text=closeout.markdown(doc)
        self.assertIn('Clean false alarms',text);self.assertIn('identical engine cue rows',text)
        self.assertIn('2.35%',text);self.assertIn('not independent trials',text)
        example=Path(__file__).resolve().parents[1]/'contracts/examples/template-closeout.v1.json'
        closeout.validate_report(json.loads(example.read_bytes()))


@needs_pixels
class PixelOnlyProof(unittest.TestCase):
    def test_same_trace_and_bank_flag_hidden_pixels_without_a_visibility_hint(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            clean_root=Path(tmp)/'clean';hidden_root=Path(tmp)/'hidden'
            clean=replay(clean_root,count=3);hidden=replay(hidden_root,count=3,hidden=True)
            self.assertEqual(clean['trace'],hidden['trace'])
            bank=ts.calibrate(clean_root,clean_tree=TREE,frames=[0],config=CONFIG)
            present=ts.from_replay(clean['trace'],replay_sha256=clean['replaySha256'],frames_dir=clean['framesDir'],bank=bank,spec=SPEC)
            absent=ts.from_replay(clean['trace'],replay_sha256=hidden['replaySha256'],frames_dir=hidden['framesDir'],bank=bank,spec=SPEC)
            self.assertEqual([f['sensor']['player']['status'] for f in present['frames']],['matched']*3)
            self.assertEqual([f['sensor']['player']['status'] for f in absent['frames']],['not-found']*3)
