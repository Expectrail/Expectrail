"""The control setting (expectrail/jit/offer.py, ``CONTROL``; issue #285, step 5, with #675 and #755).

Since #675 the generator drops a check that passes every run of the do-nothing control, where the actor the
check is about does nothing. #755 found that the form of a check decides how it does there: of the 137
baseline checks, the 79 a still actor satisfies (a relation that holds at equal arms, a bound on activity) all
pass the control, and the 32 strict relations all fail it. No setting told the proposer this: the revision was
sent the reason ``passed-with-the-actor-doing-nothing`` with nothing to explain it.

``signals-reach-evidence-menu-control`` is the menu setting plus that explanation, in the system prompt and in
the revision's. Every other setting's prompts stay byte for byte what they were (their digests are pinned
below and in tests/test_jit_offer.py). Offline: no engine, no model and no key."""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from expectrail.jit import intent, offer
from expectrail.repro import control_form
from expectrail.trace.evaluator import COMPARATORS
from tests.jit_fixtures import PROFILE

REPO = Path(__file__).resolve().parents[1]
PROF = json.loads(PROFILE.read_text(encoding="utf-8"))
REPORT = "I can jump again in the air and go twice as high."
CONTROL = "signals-reach-evidence-menu-control"

# Computed on main at 6335e61, before the control setting existed: the menu setting's system prompt, and that
# prompt with the revision's, for a shown and a withheld candidate. If one of these moves, the menu setting's
# prompt changed, and that is a change to the generator that needs its own run.
MENU_SHA = {
    intent.SHOWN: ("828038a5439b7af223a438db13284fa7dce6c1a3915557ad7e46da470d9a3126",
                   "b19e4400d40de32d44a6a1c0b5ade4c4777f5dd66057c494b70dd8ff7f8e2c4e"),
    intent.WITHHELD: ("92315b5a0b5aea326ee7bb0b0a83971250fafe751f2697ae8785a8aec9fbf842",
                      "376a8fdf0d9b71067627e6fea02cbe947ccbe6966ba6f720550bcf1c25e16255"),
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lib(which):
    return offer.library(PROF["actions"], which, REPORT, profile=PROF)


class TheSetting(unittest.TestCase):
    def test_it_is_a_setting_of_every_step_after_the_menu_setting(self):
        self.assertEqual(offer.CONTROL, CONTROL)
        self.assertEqual(offer.OFFERS[-2:], (offer.MENU, CONTROL))
        for group in (offer.ALL, offer.REPLAYABLE, offer.SCORED, offer.REVISABLE, offer.WORKFLOW):
            self.assertIn(CONTROL, group)
        self.assertEqual(offer.check(CONTROL), CONTROL)
        self.assertEqual(offer.DEFAULT, offer.BASELINE)

    def test_it_offers_what_the_menu_setting_offers(self):
        self.assertTrue(offer.shows_evidence(CONTROL))
        self.assertTrue(offer.offers_menu(CONTROL))
        self.assertFalse(offer.offers_pixel(CONTROL))
        self.assertEqual(offer.meanings(CONTROL), offer.meanings(offer.MENU))
        self.assertEqual(lib(CONTROL), lib(offer.MENU))

    def test_only_it_tells_about_the_control(self):
        for which in offer.ALL:
            self.assertEqual(offer.tells_control(which), which == CONTROL, which)

    def test_its_name_starts_like_the_other_settings_that_show_evidence(self):
        # jit.yml gives the measure job a display and more time by this prefix (tests/test_jit_offer_evidence.py).
        self.assertTrue(CONTROL.startswith("signals-reach-evidence"))

    def test_the_schemas_name_it(self):
        run = json.loads((REPO / "contracts" / "jit-run.v1.schema.json").read_text(encoding="utf-8"))
        scored = json.loads((REPO / "contracts" / "repro-score.v1.schema.json").read_text(encoding="utf-8"))
        self.assertIn(CONTROL, run["properties"]["settings"]["properties"]["offer"]["enum"])
        self.assertIn(CONTROL, scored["properties"]["offer"]["enum"])

    def test_the_workflow_takes_it(self):
        text = (REPO / ".github" / "workflows" / "jit.yml").read_text(encoding="utf-8")
        plan = re.search(r'\[\[ "\$OFFER" =~ \^\(([^)]*)\)\$ \]\]', text)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.group(1).split("|"), list(offer.WORKFLOW))


class TheMenuSettingIsUnchanged(unittest.TestCase):
    def test_the_menu_prompts_are_byte_for_byte_those_of_main_before_the_control_setting(self):
        for candidate, (system, revise) in MENU_SHA.items():
            text = intent.system_for(offer.MENU, candidate)
            self.assertEqual(sha(text), system, candidate)
            self.assertEqual(sha(text + intent.revise_system(offer.MENU)), revise, candidate)


class ThePrompt(unittest.TestCase):
    def test_the_system_prompt_is_the_menu_prompt_and_the_control_text(self):
        for candidate in (intent.SHOWN, intent.WITHHELD):
            text = intent.system_for(CONTROL, candidate)
            self.assertEqual(text.count(intent.CONTROL_TEXT), 1, candidate)
            self.assertEqual(text.replace(intent.CONTROL_TEXT, "", 1), intent.system_for(offer.MENU, candidate))

    def test_no_other_setting_has_the_control_text_in_either_prompt(self):
        for which in offer.ALL:
            if which == CONTROL:
                continue
            for candidate in (intent.SHOWN, intent.WITHHELD):
                self.assertNotIn(intent.CONTROL_TEXT, intent.system_for(which, candidate), which)
            self.assertNotIn(intent.REVISE_CONTROL_TEXT, intent.revise_system(which), which)

    def test_the_revision_is_told_what_the_reason_means(self):
        self.assertEqual(intent.revise_system(CONTROL), intent.REVISE_SYSTEM + intent.REVISE_CONTROL_TEXT)
        # The revision is sent this reason (intent.feedback); the text must name it exactly.
        self.assertIn('"passed-with-the-actor-doing-nothing"', intent.REVISE_CONTROL_TEXT)
        source = (REPO / "expectrail" / "jit" / "intent.py").read_text(encoding="utf-8")
        self.assertIn('"why": "passed-with-the-actor-doing-nothing"', source)

    def test_the_text_names_the_forms_a_still_actor_satisfies_as_the_evaluator_and_755_define_them(self):
        """The text is checked against the evaluator's comparators and control_form's operation sets, so a
        change to either that the prompt does not follow fails here."""
        text = intent.CONTROL_TEXT
        holds = sorted(c for c, f in COMPARATORS.items() if f(0.0, 0.0, 0.0))
        fails = sorted(c for c, f in COMPARATORS.items() if not f(0.0, 0.0, 0.0))
        self.assertEqual(holds, ["eq", "gte", "lte"])
        self.assertEqual(fails, ["gt", "lt"])
        for name in [*holds, *fails, *control_form._HOLDS_WHEN_STILL, *control_form._NEEDS_ACTIVITY]:
            self.assertIn(f'"{name}"', text, name)
        cannot_fail, cannot_pass = text.index("cannot fail"), text.index("cannot pass")
        for name in [*holds, *control_form._HOLDS_WHEN_STILL]:   # named as what a still actor cannot fail
            self.assertTrue(cannot_fail < text.index(f'"{name}"') < cannot_pass, name)
        for name in [*fails, *control_form._NEEDS_ACTIVITY]:     # named as what a still actor cannot pass
            self.assertGreater(text.index(f'"{name}"'), cannot_pass, name)

    def test_the_text_names_the_three_classes_the_control_is_made_for(self):
        from expectrail.jit.do_nothing import CLASSES

        for cls in CLASSES:
            self.assertIn(f'"{cls}"', intent.CONTROL_TEXT, cls)

    def test_the_spark_call_under_it_sends_the_control_text(self):
        from tests.jit_fixtures import Transport, reply

        t = Transport(reply(json.dumps({"candidates": []})))
        intent.spark_intent(transport=t, offer=CONTROL)
        self.assertIn(intent.CONTROL_TEXT, intent.spark_intent(transport=t, offer=CONTROL).system)



class TheRecord(unittest.TestCase):
    def test_a_run_under_it_records_it_sends_the_control_text_and_validates(self):
        import shutil

        from expectrail.contracts import validate_v1
        from expectrail.jit.run import generate
        from tests.jit_fixtures import Case, JitGame, Transport, reply
        from tests.test_jit_offer import answer_on

        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        t = Transport(reply(answer_on("air_jumps")))
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong"), [case.patch("air-jump")], case.dir / "out",
                       runner=JitGame(), variants_fn=case.variants(), offer=CONTROL,
                       intent=intent.spark_intent(transport=t, offer=CONTROL))
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["settings"]["offer"], CONTROL)
        self.assertIn(intent.CONTROL_TEXT, t.bodies[0]["messages"][0]["content"])

    def test_the_example_is_a_control_run_that_validates(self):
        from expectrail.contracts import load_strict

        doc = load_strict(REPO / "contracts" / "examples" / "jit-run-control.json", "jit-run")
        self.assertEqual(doc["settings"]["offer"], CONTROL)
        self.assertEqual(doc["status"], "complete")

    def test_a_record_under_it_is_read_as_it_and_not_as_the_menu_setting(self):
        self.assertEqual(offer.of_record(CONTROL), CONTROL)
        self.assertNotEqual(offer.of_record(CONTROL), offer.MENU)


if __name__ == "__main__":
    unittest.main()
