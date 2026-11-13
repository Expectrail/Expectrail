"""The third offer setting, ``signals-reach-evidence`` (expectrail/jit/offer.py, issue #285 step 5): the
proposer is also given what the bug build changes against the clean game along each probe, in the
engine's record and on the screen (expectrail/repro/evidence.py).

The other two settings must not move: their prompts are held to digests taken on main at f9c364b,
before this setting existed. Offline: a simulated game, no engine, no model key, no observer."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from expectrail.contracts import load_strict
from expectrail.jit import cli, intent, offer
from expectrail.jit.diff_map import diff_map
from expectrail.repro import bench, evidence
from expectrail.trace.signals import SIGNALS
from tests.jit_fixtures import Transport, reply
from tests.test_jit_offer import NO_FIX, PROF, REPORT, SAMPLE_PROMPT_SHA, SYSTEM_SHA, answer_on, sample_probes, sha
from tests.test_repro_bench import REPO, STUB
from tests.test_repro_screen import Drawn

EV = "signals-reach-evidence"
# Computed on main at f9c364b, before this setting existed, with the inputs of tests/test_jit_offer.py.
REACH_SYSTEM_SHA = "bbaee4b545fbbcbf0f75eb370d6e79414d4e8f9240c22984f622881da89b2da3"
REACH_REVISE_SYSTEM_SHA = "40a622b49f48f387ca93b9f94785fcbba73f31bcee4a86d1b7a64bbfced8e909"
REACH_SAMPLE_PROMPT_SHA = "c14e7207243d5611299a7d89c8c73c36d4a6712fbb34a733ad3effac7f4da483"
SHOWN = ("jump-w0-x8", "hold-right", "shoot-right-every12")


class Simulated(unittest.TestCase):
    """An evidence record made on the simulated game: the view moves and the picture shifts on three probes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jit-offer-evidence-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.base = [self.tmp / "camera-shift.patch"]
        self.base[0].write_text(STUB, encoding="utf-8")
        self.library = offer.library(PROF["actions"], EV, REPORT)
        made = [p for p in self.library if p["id"] in SHOWN]
        evidence.evidence(PROF, made, self.base, self.tmp / "ev", runner=Drawn())
        self.path = self.tmp / "ev" / evidence.NAME


class OtherSettingsDoNotMove(unittest.TestCase):
    def test_the_baseline_and_signals_reach_prompts_are_byte_for_byte_those_of_main(self):
        patch = NO_FIX.read_text(encoding="utf-8")
        self.assertEqual(sha(intent.system_for("baseline")), SYSTEM_SHA)
        self.assertEqual(sha(intent.system_for("signals-reach")), REACH_SYSTEM_SHA)
        self.assertEqual(sha(intent.system_for("signals-reach") + intent.REVISE_SYSTEM), REACH_REVISE_SYSTEM_SHA)
        for which, want in (("baseline", SAMPLE_PROMPT_SHA), ("signals-reach", REACH_SAMPLE_PROMPT_SHA)):
            probes = sample_probes(which)
            self.assertEqual(sha(intent.prompt(REPORT, patch, diff_map(patch, PROF, probes), PROF, probes, offer=which)),
                             want, which)

    def test_a_probe_that_carries_evidence_shows_it_under_the_evidence_setting_only(self):
        patch = NO_FIX.read_text(encoding="utf-8")
        probes = sample_probes("signals-reach")
        probes[0]["differs"] = {"ticksPerSecond": 60, "framesPerSecond": 30, "frame": {"width": 4, "height": 4},
                                "record": None, "screen": {"frames": 1, "of": 2, "firstFrame": 1, "pixels": 1,
                                                           "atFrame": 1, "box": [0, 0, 1, 1]}}
        dmap = diff_map(patch, PROF, probes)
        self.assertEqual(sha(intent.prompt(REPORT, patch, dmap, PROF, probes, offer="signals-reach")),
                         REACH_SAMPLE_PROMPT_SHA)
        sent = json.loads(intent.prompt(REPORT, patch, dmap, PROF, probes, offer=EV))["probesAvailable"]
        self.assertEqual(sent[0]["differs"]["screen"]["firstFrame"], 1)
        self.assertTrue(all("differs" not in p for p in sent[1:]))


class TheSetting(unittest.TestCase):
    def test_it_offers_what_signals_reach_offers(self):
        self.assertEqual(offer.check(EV), EV)
        self.assertTrue(offer.shows_evidence(EV))
        self.assertFalse(offer.shows_evidence("baseline") or offer.shows_evidence("signals-reach"))
        self.assertEqual(offer.meanings(EV), offer.meanings("signals-reach"))
        self.assertEqual(offer.library(PROF["actions"], EV, REPORT), offer.library(PROF["actions"], "signals-reach", REPORT))
        with self.assertRaises(offer.OfferError):
            offer.shows_evidence("everything")

    def test_its_system_prompt_is_signals_reach_with_one_paragraph_more(self):
        system = intent.system_for(EV)
        self.assertEqual(system.count(intent.EVIDENCE_TEXT), 1)
        self.assertEqual(system.replace(intent.EVIDENCE_TEXT, "", 1), intent.system_for("signals-reach"))
        self.assertNotIn(intent.EVIDENCE_TEXT, intent.system_for("baseline"))
        # The paragraph says the checks still read signals only: the closed language has no pixel predicate yet (#286).
        self.assertIn("Checks still read only the signals", intent.EVIDENCE_TEXT)

    def test_a_check_on_a_held_signal_is_kept_as_under_signals_reach(self):
        _p, kept, _n = intent.parse_answer(answer_on("air_jumps", "coins_collected"), PROF,
                                           {"jump-w0-x2", "jump-w0-x8"}, offer=EV)
        self.assertEqual([e["spec"]["operation"]["signal"] for e in kept], ["air_jumps", "coins_collected"])


class Attaching(Simulated):
    def test_the_probes_the_summary_shows_carry_it_and_no_other(self):
        notes = offer.attach_evidence(self.library, self.path, self.base, EV)
        self.assertEqual(notes, [])
        carrying = {p["id"]: p["differs"] for p in self.library if "differs" in p}
        self.assertEqual(set(carrying), set(SHOWN))
        one = carrying["hold-right"]
        self.assertEqual(sorted(one), ["frame", "framesPerSecond", "record", "screen", "ticksPerSecond"])
        self.assertEqual(one["record"]["fields"]["view"]["firstTick"], 0)
        self.assertEqual(sorted(one["screen"]), ["atFrame", "box", "firstFrame", "frames", "of", "pixels"])

    def test_under_another_setting_nothing_is_attached_and_a_file_given_is_said(self):
        for which in ("baseline", "signals-reach"):
            probes = offer.library(PROF["actions"], which, REPORT)
            self.assertEqual(offer.attach_evidence(probes, None, self.base, which), [])
            notes = offer.attach_evidence(probes, self.path, self.base, which)
            self.assertEqual(notes, [f"evidence: not used: the offer {which} does not offer it"])
            self.assertFalse(any("differs" in p for p in probes))

    def test_none_given_or_one_that_cannot_be_used_is_said_and_the_proposal_goes_ahead_without(self):
        self.assertEqual(offer.attach_evidence(self.library, None, self.base, EV), ["evidence: none given"])
        other = self.tmp / "other.patch"
        other.write_text(STUB.replace("+b", "+c"), encoding="utf-8")
        notes = offer.attach_evidence(self.library, self.path, [other], EV)
        self.assertTrue(notes[0].startswith("evidence: not used: repro-evidence: made for a different bug build"), notes)
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["rows"][0]["sees"] = "neither"
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(record), encoding="utf-8")
        self.assertTrue(offer.attach_evidence(self.library, bad, self.base, EV)[0].startswith("evidence: not used"))
        self.assertTrue(offer.attach_evidence(self.library, self.tmp / "missing.json", self.base, EV)[0]
                        .startswith("evidence: not used"))
        self.assertFalse(any("differs" in p for p in self.library))

    def test_a_probe_not_in_this_library_is_counted_and_not_shown(self):
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["rows"][0]["probe"] = record["probes"][0] = "not-a-probe"
        renamed = self.tmp / "renamed.json"
        renamed.write_text(json.dumps(record), encoding="utf-8")
        notes = offer.attach_evidence(self.library, renamed, self.base, EV)
        self.assertEqual(notes, ["evidence: 1 probes that differ are not in this library"])
        self.assertEqual(sum("differs" in p for p in self.library), len(SHOWN) - 1)

    def test_what_reaches_the_prompt_is_numbers_and_names_from_closed_lists(self):
        offer.attach_evidence(self.library, self.path, self.base, EV)
        patch = NO_FIX.read_text(encoding="utf-8")
        sent = json.loads(intent.prompt(REPORT, patch, diff_map(patch, PROF, self.library), PROF, self.library, offer=EV))
        allowed = ({p["id"] for p in self.library} | set(evidence.FIELDS) | set(SIGNALS)
                   | {"ticksPerSecond", "framesPerSecond", "frame", "width", "height", "record", "screen", "fields",
                      "signals", "firstTick", "ticks", "of", "clean", "bugBuild", "frames", "firstFrame", "pixels",
                      "atFrame", "box", "otherFields"})

        def strings(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)
            elif isinstance(value, str):
                yield value

        shown = [p["differs"] for p in sent["probesAvailable"] if "differs" in p]
        self.assertEqual(len(shown), len(SHOWN))
        self.assertEqual(set(strings(shown)) - allowed, set())

    def test_the_budget_prices_the_prompt_that_carries_the_evidence(self):
        patch = NO_FIX.read_text(encoding="utf-8")
        bare = intent.prompt(REPORT, patch, diff_map(patch, PROF, self.library), PROF, self.library, offer=EV)
        offer.attach_evidence(self.library, self.path, self.base, EV)
        t = Transport(reply(answer_on("air_jumps")))
        doc = intent.propose_to_file(intent.spark_intent(transport=t, offer=EV), REPORT, patch, PROF, self.library,
                                     self.tmp / "p", budget_usd=2.0)
        self.assertIsNone(doc["error"])
        self.assertEqual(doc["offer"], EV)
        user = t.bodies[0]["messages"][1]["content"]
        self.assertGreater(len(user), len(bare))
        self.assertIn('"differs"', user)
        self.assertEqual(t.bodies[0]["messages"][0]["content"], intent.system_for(EV))


class TheRecordedBenchEvidence(unittest.TestCase):
    """The evidence recorded on the real engine for the public bench (bench/jit/public/evidence-*.json),
    put on the evidence setting's library as the propose job would."""

    def test_each_record_attaches_to_the_library_of_its_defect(self):
        patches = {d["id"]: REPO / d["patch"] for d in bench.load()["defects"]}
        paths = sorted((REPO / "bench" / "jit" / "public").glob("evidence-*.json"))
        self.assertTrue(paths)
        for path in paths:
            name = path.stem.removeprefix("evidence-")
            library = offer.library(PROF["actions"], EV, "")
            notes = offer.attach_evidence(library, path, [patches[name]], EV)
            self.assertEqual(notes, [], name)
            carrying = [p for p in library if "differs" in p]
            self.assertTrue(1 <= len(carrying) <= evidence.MAX_SHOWN, name)
            self.assertTrue(all(p["differs"]["screen"] or p["differs"]["record"] for p in carrying), name)

    def test_coin_stays_shows_the_picture_change_long_before_the_record(self):
        # Measured on November 12: the picture changes at frame 26 and the record's coins at tick 174.
        path = REPO / "bench" / "jit" / "public" / "evidence-coin-stays.json"
        patch = REPO / "bench" / "jit" / "public" / "coin-stays" / "defect.patch"
        library = offer.library(PROF["actions"], EV, "")
        offer.attach_evidence(library, path, [patch], EV)
        both = [p["differs"] for p in library if "differs" in p and p["differs"]["record"] and p["differs"]["screen"]]
        self.assertTrue(both)
        for d in both:
            seconds_screen = d["screen"]["firstFrame"] / d["framesPerSecond"]
            seconds_record = d["record"]["fields"]["coins"]["firstTick"] / d["ticksPerSecond"]
            self.assertLess(seconds_screen, seconds_record)


class TheCommands(Simulated):
    def test_measure_makes_the_evidence_under_its_setting_and_with_a_bug_build_only(self):
        made = []

        def fake_measure(_profile, base, _out, *, probes, game=None):
            return {"probes": {p["id"]: {} for p in probes}}

        def fake_evidence(_profile, probes, base, out, *, game=None, jobs=1):
            made.append((len(probes), [str(b) for b in base], jobs))
            return {"totals": {"probes": len(probes)}}

        for which, base, expected in ((EV, [str(self.base[0])], 1), (EV, [], 0), ("signals-reach", [str(self.base[0])], 0),
                                      ("baseline", [str(self.base[0])], 0)):
            made.clear()
            args = ["measure", "--out", str(self.tmp / "m"), "--offer", which, "--evidence-jobs", "2"]
            for b in base:
                args += ["--base", b]
            with mock.patch("expectrail.jit.measure.measure", fake_measure), \
                    mock.patch.object(cli, "make_evidence", fake_evidence), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
            self.assertEqual(len(made), expected, (which, base))
            if expected:
                self.assertEqual(made[0], (len(self.library), base, 2))

    def test_measure_refuses_a_number_of_jobs_out_of_range(self):
        for jobs in ("0", "9"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                cli.main(["measure", "--out", str(self.tmp / "m"), "--evidence-jobs", jobs])
            self.assertEqual(stop.exception.code, 2)

    def test_make_evidence_replays_with_frames_on_the_game_it_is_given(self):
        seen = {}

        def fake(_profile, _probes, _base, _out, *, runner, jobs):
            seen.update(runner=runner, jobs=jobs)
            return {}

        with mock.patch.object(evidence, "evidence", fake):
            offer.make_evidence(PROF, [], self.base, self.tmp / "e", game=self.tmp / "game", jobs=3)
        self.assertEqual(seen["jobs"], 3)
        self.assertEqual(seen["runner"].keywords, {"capture_frames": True, "game": self.tmp / "game"})

    def test_make_evidence_on_the_simulated_game_writes_a_record_the_reader_takes(self):
        made = [p for p in self.library if p["id"] in SHOWN]
        offer.make_evidence(PROF, made, self.base, self.tmp / "again", runner=Drawn())
        self.assertEqual(evidence.load(self.tmp / "again" / evidence.NAME, base_patches=self.base)["totals"]["probes"], 3)

    def _propose(self, which, *extra):
        sent = []
        real = intent.spark_intent

        def fake_spark(offer="baseline"):
            t = Transport(reply(answer_on("air_jumps")))
            sent.append(t)
            return real(transport=t, offer=offer)

        report = self.tmp / "r.txt"
        report.write_text(REPORT, encoding="utf-8")
        out = self.tmp / f"p-{which}"
        buf = io.StringIO()
        with mock.patch.object(intent, "spark_intent", fake_spark), contextlib.redirect_stdout(buf):
            cli.main(["propose", "--report-file", str(report), "--candidate", str(NO_FIX), "--out", str(out),
                      "--offer", which, "--base", str(self.base[0]), *extra])
        return (json.loads(buf.getvalue()), json.loads((out / intent.PROPOSAL_NAME).read_text(encoding="utf-8")),
                sent[0].bodies[0]["messages"][1]["content"])

    def test_propose_puts_the_evidence_in_the_prompt_under_its_setting(self):
        said, doc, user = self._propose(EV, "--evidence", str(self.path))
        self.assertTrue(said["evidence"])
        self.assertFalse(said["measured"])      # no measurements were given; that is said apart
        self.assertEqual(doc["offer"], EV)
        self.assertNotIn("evidence: none given", doc["diagnostics"])
        self.assertEqual(sum("differs" in p for p in json.loads(user)["probesAvailable"]), len(SHOWN))

    def test_propose_without_the_evidence_says_so_and_goes_ahead(self):
        said, doc, user = self._propose(EV)
        self.assertFalse(said["evidence"])
        self.assertIn("evidence: none given", doc["diagnostics"])
        self.assertNotIn('"differs"', user)

    def test_propose_under_signals_reach_does_not_read_a_file_given(self):
        said, doc, user = self._propose("signals-reach", "--evidence", str(self.path))
        self.assertFalse(said["evidence"])
        self.assertIn("evidence: not used: the offer signals-reach does not offer it", doc["diagnostics"])
        self.assertNotIn('"differs"', user)

    def test_revise_puts_the_evidence_on_the_probes_too(self):
        seen = []

        def fake_revise(_intent, _report, _patch, _profile, probes, *_a, **kw):
            seen.append(([p["id"] for p in probes if "differs" in p], kw["notes"]))
            raise intent.IntentUnavailable("stop here")

        report = self.tmp / "r.txt"
        report.write_text(REPORT, encoding="utf-8")
        with mock.patch.object(intent, "revise_to_file", fake_revise), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["revise", "--report-file", str(report), "--candidate", str(NO_FIX), "--proposal", "p.json",
                      "--record", "r.json", "--out", str(self.tmp / "rv"), "--offer", EV, "--base", str(self.base[0]),
                      "--evidence", str(self.path)])
        self.assertEqual(sorted(seen[0][0]), sorted(SHOWN))
        self.assertEqual(seen[0][1], ["measurements: none given"])


class TheWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load((REPO / ".github" / "workflows" / "jit.yml").read_text(encoding="utf-8"))
        self.jobs = self.wf["jobs"]

    def run_of(self, job, needle):
        return next(s["run"] for s in self.jobs[job]["steps"] if needle in (s.get("run") or ""))

    def test_the_plan_takes_the_setting(self):
        step = next(s["run"] for s in self.jobs["plan"]["steps"] if s.get("id") == "plan")
        self.assertIn("^(baseline|signals-reach|signals-reach-evidence)$", step)

    def test_the_measure_job_gets_a_display_and_more_time_only_under_the_evidence_setting(self):
        measure = self.jobs["measure"]
        self.assertEqual(measure["timeout-minutes"],
                         "${{ needs.plan.outputs.offer == 'signals-reach-evidence' && 75 || 30 }}")
        install = next(s for s in measure["steps"] if s.get("uses") == "./.github/actions/apt-install")
        self.assertEqual(install["with"]["packages"], "${{ needs.plan.outputs.offer == 'signals-reach-evidence' "
                                                      "&& 'patch xvfb libgl1-mesa-dri libglx-mesa0' || 'patch' }}")
        upload = next(s for s in measure["steps"] if "upload-artifact" in (s.get("uses") or ""))
        self.assertEqual(upload["with"]["path"].split(),
                         ["runs/jit-measure/jit-measurements.json", "runs/jit-measure/repro-evidence.json"])
        self.assertIn("--evidence-jobs 2", self.run_of("measure", "jit.cli measure"))

    def test_propose_and_revise_read_the_evidence_when_the_measure_job_made_it(self):
        line = ("ev=(); if [[ -f runs/jit-measure/repro-evidence.json ]]; then "
                "ev=(--evidence runs/jit-measure/repro-evidence.json); fi")
        for job, command in (("propose", "jit.cli propose"), ("revise", "jit.cli revise")):
            run = self.run_of(job, command)
            self.assertIn(line, run, job)
            self.assertIn('"${ev[@]}"', run, job)
            self.assertNotIn("environment", self.jobs["measure"])   # the job that replays holds no key


if __name__ == "__main__":
    unittest.main()
