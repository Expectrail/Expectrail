"""CI image regression and shared approval-policy parity, with temporary specs only.
Guard: test change intended (#331)
Reason: add no-Pillow coverage and refusal parity without changing the original image count.
"""
import base64
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expectrail import approval, onboard_page, onboard_review as review, spec_writer
from tests import test_onboard as original, test_onboard_review as human
from tests.test_init_inspect import command


class NativeArtTest(unittest.TestCase):
    def setUp(self):
        self.fixture=original.ReviewTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_no_image_decoder_keeps_both_bound_sprites_and_the_game(self):
        root=self.fixture.root;path=root/'expectrail.project.json';config=json.loads(path.read_bytes())
        config['bindings']['coin']={'group':'coins','texture':'res://player/robot.webp'};path.write_text(json.dumps(config))
        before=original.contents(root)
        with patch.object(review,'thumbnail',return_value=None),patch.object(review,'local_godot',return_value=None):
            code,msg=self.fixture.render()
        self.assertEqual(code,0,msg);page=original.Page(self.fixture.out)
        self.assertEqual(len(page.images),2)
        self.assertEqual(page.configs,[config]);self.assertEqual(original.contents(root),before)
        for image in page.images:
            prefix,data=image.split(',',1);self.assertEqual(prefix,'data:image/webp;base64')
            self.assertEqual(base64.b64decode(data,validate=True),(root/'player/robot.webp').read_bytes())
        # No captured samples: showing the asset must not turn an object into measured evidence.
        manifest=json.loads(Path(page.payload['reviewFile']).read_bytes())
        self.assertTrue(all(not obj['reviewable'] for obj in manifest['objects']))

    def test_native_preview_is_bounded_bound_to_bytes_and_never_a_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder);source=self.fixture.root/'player/robot.webp'
            image=review.native_sprite(state,source);self.assertIsNotNone(image)
            self.assertEqual(review.webp_size(source.read_bytes()),(512,512))
            self.assertEqual(review.native_sprite_bytes(state,image),source.read_bytes())
            page=onboard_page.figure(state,image,'Original art')
            self.assertIn('data:image/webp;base64,',page)
            (state/image['path']).write_bytes(b'changed')
            self.assertIsNone(review.native_sprite_bytes(state,image))
            self.assertIn('missing or changed',onboard_page.figure(state,image,'Original art'))
            big=state/'oversized.webp';big.write_bytes(source.read_bytes()+b'x'*review.MAX_NATIVE_ART_BYTES)
            self.assertIsNone(review.native_sprite(state,big))
            self.assertIsNone(review.webp_size(b'not a webp'))
            escaped={**image,'path':'../outside.webp'}
            self.assertIsNone(review.native_sprite_bytes(state,escaped))

    def test_false_draft_is_invalid_but_absent_draft_is_a_valid_active_config(self):
        root=self.fixture.root;path=root/'expectrail.project.json';config=json.loads(path.read_bytes());config.pop('draft')
        path.write_text(json.dumps(config));before=original.contents(root)
        with patch.object(review,'local_godot',return_value=None):code,msg=self.fixture.render()
        self.assertEqual(code,0,msg);self.assertNotIn('draft',original.Page(self.fixture.out).configs[0])
        self.assertEqual(original.contents(root),before)
        # Keep the previous explicit-False refusal assertion intact as a separate original test.


class ApprovalParityTest(unittest.TestCase):
    def setUp(self):
        self.fixture=human.HumanReviewTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def rebind(self,body):
        f=self.fixture;f.spec_path.write_bytes(review.encoded(body))
        row=f.record['specs'][0];row['specSha256']=approval.spec_sha256(body);row['fileSha256']=review.sha(f.spec_path.read_bytes())
        for item in f.record['inputs']:
            if item['path']==row['path']:item['sha256']=row['fileSha256']
        f.manifest.write_bytes(review.encoded(f.record))

    def test_existing_policy_refusals_cannot_be_imported_from_forged_review_answers(self):
        f=self.fixture;original_body=json.loads(f.spec_path.read_bytes());original_record=copy.deepcopy(f.record)
        def prompt_position(b):b['objects']['player']['prompt']='test square on top of the floor'
        def unknown_object(b):b['assertion']['object']='missing-object'
        def score_too_high(b):b['objects']['player']['minScore']=1.1
        def bad_window(b):b['window']['fromFrame']=-1
        def unknown_kind(b):b['assertion']['type']='looks-correct'
        def extra_assertion(b):b['assertion']['execute']='not allowed'
        def extra_root(b):b['unchecked']=True
        def no_instruction(b):b.pop('instruction')
        for mutation in (prompt_position,unknown_object,score_too_high,bad_window,unknown_kind,extra_assertion,extra_root,no_instruction):
            with self.subTest(mutation=mutation.__name__):
                body=copy.deepcopy(original_body);mutation(body);f.record=copy.deepcopy(original_record);self.rebind(body)
                before=f.spec_path.read_bytes();config=(f.root/'expectrail.project.json').read_bytes()
                # The legacy public command delegates to exactly the same writer. All calls here refuse;
                # no new approval is created, even on these invented temporary checks.
                with self.assertRaises((ValueError,spec_writer.SpecDraftError)):
                    spec_writer.approve(f.spec_path,'Synthetic Test Person')
                self.assertEqual(f.spec_path.read_bytes(),before)
                answers=f.answers();code,msg=command('onboard','--approve',answers)
                self.assertEqual(code,5,msg);self.assertEqual(f.spec_path.read_bytes(),before)
                self.assertEqual((f.root/'expectrail.project.json').read_bytes(),config)
                self.assertNotIn('approval',json.loads(f.spec_path.read_bytes()))

    def test_a_new_shared_writer_refusal_propagates_without_any_write(self):
        f=self.fixture;before=f.spec_path.read_bytes();config=(f.root/'expectrail.project.json').read_bytes()
        with patch.object(approval,'approve',side_effect=approval.ApprovalError('test-only shared policy refused')) as writer:
            with self.assertRaisesRegex(spec_writer.SpecDraftError,'shared policy refused'):
                spec_writer.approve(f.spec_path,'Synthetic Test Person')
            code,msg=command('onboard','--approve',f.answers())
            self.assertEqual(code,5,msg);self.assertIn('shared policy refused',msg)
            self.assertEqual(writer.call_count,2)
        self.assertEqual(f.spec_path.read_bytes(),before)
        self.assertEqual((f.root/'expectrail.project.json').read_bytes(),config)

    def test_only_the_fixed_hashed_script_and_json_payload_are_present(self):
        from html.parser import HTMLParser
        class Scripts(HTMLParser):
            def __init__(self,text):
                super().__init__();self.items=[];self.current=None;self.feed(text)
            def handle_starttag(self,tag,attrs):
                if tag=='script':self.current={'attrs':dict(attrs),'text':''};self.items.append(self.current)
            def handle_endtag(self,tag):
                if tag=='script':self.current=None
            def handle_data(self,data):
                if self.current is not None:self.current['text']+=data
        f=self.fixture
        page=onboard_page.render(f.record,f.details,f.state,Path('untrusted</script><script>bad</script>'), '0'*64)
        scripts=Scripts(page).items
        self.assertEqual(len(scripts),2)
        self.assertEqual(scripts[0]['attrs'],{'id':'review-data','type':'application/json'})
        self.assertEqual(scripts[1]['attrs'],{});self.assertEqual(scripts[1]['text'],onboard_page.JS)
        expected=base64.b64encode(hashlib.sha256(onboard_page.JS.encode()).digest()).decode()
        self.assertIn("script-src &#x27;sha256-"+expected,page)
        self.assertIn('connect-src &#x27;none&#x27;',page);self.assertIn('form-action &#x27;none&#x27;',page)
        self.assertNotIn('fetch(',page);self.assertNotIn('localStorage',page);self.assertNotIn('FileSystem',page)
