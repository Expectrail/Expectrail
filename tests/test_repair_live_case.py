"""The live operator wrapper is a zero-send plan until explicitly requested."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import repair_live_case as case


class LiveCase(unittest.TestCase):
    def test_default_plan_sends_nothing_and_keeps_the_existing_quote(self):
        with mock.patch.object(case,'execute',side_effect=AssertionError('command started')), redirect_stdout(io.StringIO()) as text:
            self.assertEqual(case.main([]),0)
        plan=json.loads(text.getvalue())
        self.assertEqual(plan['totalEnvelopeUsd'],'10')
        self.assertEqual(plan['mode'],'auto')
        self.assertEqual(plan['paidCallsMadeByPlan'],0)

    def test_literal_commands_select_only_llm_patch_and_one_isolated_attempt(self):
        for mode in ('manual','auto'):
            args=case.parser().parse_args(['--mode',mode])
            command=case.commands(Path('run'),args)
            self.assertIn('verify',command);self.assertIn('isolated',command)
            if mode=='auto':
                self.assertEqual(command[command.index('--auto-fix-agent')+1],'llm-patch')
                self.assertEqual(command[command.index('--auto-fix-attempts')+1],'1')
            else:
                repair=case.commands(Path('run'),args,'a'*32)
                self.assertEqual(repair[repair.index('--agent')+1],'llm-patch')

    def test_no_reject_means_no_standalone_repair_and_no_changed_budget_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run'
            environment={'PATH':os.defpath,'EXPECTRAIL_FIXER_API_KEY':'offline-only','MODEL_API_KEY':'offline-only',
                'EXPECTRAIL_MODEL_MONTH_LEDGER':str(Path(tmp)/'models.json'),
                'EXPECTRAIL_VISION_MONTH_LEDGER':str(Path(tmp)/'vision.json')}
            with mock.patch.dict(os.environ,environment,clear=True), \
                 mock.patch.object(case,'execute',return_value=(2,json.dumps({'decision':'needs-review'}))) as execute, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(case.main(['--run','--mode','manual','--out',str(out)]),2)
            self.assertEqual(execute.call_count,1)
            env=execute.call_args.args[1]
            self.assertEqual(env['EXPECTRAIL_FIXER_INVOCATION_USD_CAP'],'6')
            self.assertEqual(env['EXPECTRAIL_MUSE_USD_CAP'],'6')
            self.assertEqual(env['EXPECTRAIL_SAM_USD_CAP'],'2')

    def test_this_run_sheet_cannot_add_a_second_attempt(self):
        with mock.patch.object(case,'execute') as execute:
            with self.assertRaises(ValueError):case.main(['--attempts','2'])
        execute.assert_not_called()
