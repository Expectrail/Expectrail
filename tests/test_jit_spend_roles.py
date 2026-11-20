"""Which model roles jit.yml's three key-holding steps send with (#267, the spend-cap audit's review).

``tools/spend_cap_audit.py`` reads imports, so it says a step "may reach" every sender in the import
closure of what it starts. For three steps of jit.yml it listed a cap the step does not set:

- ``propose`` and ``revise`` set only the spec cap, and ``expectrail.jit.cli`` imports
  ``expectrail.jit.sam_observer``, which imports ``agents.sam_observations`` (SAM's sender);
- ``pixel-ask`` exports only SAM's cap, and ``expectrail.jit.cli`` imports ``expectrail.jit.intent``, which
  imports ``expectrail.spec_writer`` (a spec sender).

These tests settle it by running, not by reading. Each subcommand goes through ``cli.main`` as the step runs
it, with the network floor of both senders (``urllib.request.urlopen``) replaced by a recorder that answers
as the service would, and with exactly the caps the step's ``env:`` and script set, read from jit.yml itself.
A step that tried to send a role whose cap it lacks would show the request in the recorder, or stop on the
missing cap. Offline: the simulated game (tests/jit_fixtures.py), the synthetic captured frames of
tests/test_jit_pixel_jobs.py, and a made-up key. Nothing is sent and nothing is spent.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from agents import sam_observations as sam_mod
from expectrail import spend
from expectrail.contracts import load_strict
from expectrail.jit import cli
from expectrail.jit import intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit.intent import from_proposal, propose_to_file
from expectrail.jit.run import generate
from tests.jit_fixtures import GOOD_CHECK, MISCALIBRATED, PROFILE, Case, JitGame, Transport, reply
from tests import test_jit_pixel_jobs as pixel_jobs_tests
from tests.test_jit_pixel_jobs import IMAGES, SETTING, Jobs
from tests.test_jit_pixel_replay import DRAWN, REPORT
from tests.test_jit_revise import SECOND_GOOD

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "jit.yml"
PX = offer_mod.PIXEL
SAM_CAP, SPEC_CAP = spend.CAP_ENV["vision"], spend.CAP_ENV["spec"]
CAPS = frozenset(spend.CAP_ENV.values())
SAM_URL, CHAT_URL = re.compile(r"/responses$"), re.compile(r"/chat/completions$")
FAKE_KEY = "test-key-not-a-real-key"


def step(job: str, name_start: str) -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"][job]["steps"] if s.get("name", "").startswith(name_start))


def caps_of(job: str, name_start: str) -> set[str]:
    """The caps a jit.yml step sets: in its ``env:``, or exported by its script."""
    s = step(job, name_start)
    named = set(s.get("env") or {}) & CAPS
    named |= {m.group(1) for m in re.finditer(r"export\s+([A-Z_]+)=", s.get("run", ""))} & CAPS
    return named


class Wire:
    """``urllib.request.urlopen`` for both senders: answers as the service would and records every request."""

    def __init__(self, chat_answer: dict | None = None):
        self.urls: list[str] = []
        self.chat = reply(chat_answer if chat_answer is not None else {"candidates": []})

    def __call__(self, req, timeout=None):  # noqa: ARG002 - the signature urlopen is called with
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        if CHAT_URL.search(url):
            body = json.dumps(self.chat).encode()
        elif SAM_URL.search(url):
            body = json.dumps({"output_text": ""}).encode()   # SAM found nothing in this frame
        else:
            raise AssertionError(f"a request to an unexpected address: {url}")
        resp = mock.MagicMock()
        resp.read.return_value = body
        resp.headers = {"Content-Type": "application/json"}
        resp.__enter__.return_value = resp
        return resp

    def sam(self) -> list[str]:
        return [u for u in self.urls if SAM_URL.search(u)]

    def spec(self) -> list[str]:
        return [u for u in self.urls if CHAT_URL.search(u)]


@contextlib.contextmanager
def as_the_step_runs(caps: dict[str, str], wire: Wire):
    """The step's environment (a key and exactly ``caps``), a fresh meter, the wire, and a record of holds."""
    held: list[str] = []
    real_hold = spend.hold

    def hold(role, **kw):
        held.append(role)
        return real_hold(role, **kw)

    env = {k: v for k, v in os.environ.items() if k not in CAPS}
    env.update(MODEL_API_KEY=FAKE_KEY, **caps)
    env.pop("META_API_KEY", None)
    env.pop("EXPECTRAIL_VISION_MONTH_LEDGER", None)
    fresh = wire.sam_usage = {"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0}
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(spend, "METER", spend.Meter()), \
            mock.patch.object(sam_mod, "_usage", fresh), \
            mock.patch("expectrail.spec_writer.hold", hold), mock.patch("urllib.request.urlopen", wire), \
            contextlib.redirect_stderr(io.StringIO()):
        yield held


class TheStepsSetTheCapsTheseTestsUse(unittest.TestCase):
    """If jit.yml changes which caps a step sets, the tests below no longer describe it: fail first."""

    def test_propose_and_revise_set_the_spec_cap_alone(self):
        self.assertEqual(caps_of("propose", "Propose checks"), {SPEC_CAP})
        self.assertEqual(caps_of("revise", "Revise the rejected checks"), {SPEC_CAP})

    def test_pixel_ask_exports_sam_s_cap_alone(self):
        self.assertEqual(caps_of("pixel-ask", "Ask SAM 3.1"), {SAM_CAP})


class ProposeAndReviseSendSpecOnly(unittest.TestCase):
    """The audit's ``propose`` and ``revise`` entries: SAM's cap is listed and is not needed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.report = self.tmp / "report.txt"
        self.report.write_text(REPORT, encoding="utf-8")
        self.case = Case()
        self.cand, self.base = self.case.patch("fix-wrong"), self.case.patch("air-jump")

    def propose(self, *extra, answer=None):
        wire = Wire(answer if answer is not None else {"candidates": [GOOD_CHECK], "pixelChecks": [DRAWN]})
        with as_the_step_runs({SPEC_CAP: "2"}, wire) as held, contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["propose", "--report-file", str(self.report), "--candidate", str(self.cand),
                             "--base", str(self.base), "--out", str(self.tmp / "p"), "--budget-usd", "2", *extra])
        return code, json.loads(out.getvalue()), wire, held

    def test_propose_under_every_setting_sends_one_spec_request_and_nothing_to_sam(self):
        for offer in offer_mod.WORKFLOW:
            with self.subTest(offer=offer):
                code, printed, wire, held = self.propose("--offer", offer)
                self.assertEqual(code, 0)
                self.assertIsNone(printed["error"], printed)
                self.assertEqual(len(wire.spec()), 1)
                self.assertEqual(wire.sam(), [])
                self.assertEqual(held, ["spec"])
                self.assertEqual(wire.sam_usage["requests"], 0)

    def test_propose_for_either_pixel_observer_and_withheld_sends_nothing_to_sam(self):
        for observer in ("sam-3.1-anchor", "visual-sensor"):
            with self.subTest(observer=observer):
                code, printed, wire, held = self.propose("--offer", PX, "--observer", observer,
                                                         "--withhold-candidate")
                self.assertEqual(code, 0)
                self.assertIsNone(printed["error"], printed)
                self.assertEqual((len(wire.spec()), wire.sam(), held), (1, [], ["spec"]))
                self.assertEqual(wire.sam_usage["requests"], 0)

    def test_without_the_spec_cap_propose_sends_nothing(self):
        # The control: the cap the step sets is the one the sender holds against.
        wire = Wire({"candidates": [GOOD_CHECK]})
        with as_the_step_runs({}, wire), contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["propose", "--report-file", str(self.report), "--candidate", str(self.cand),
                             "--out", str(self.tmp / "p"), "--budget-usd", "2"])
        self.assertEqual(code, 0)
        self.assertIsNotNone(json.loads(out.getvalue())["error"])
        self.assertEqual(wire.urls, [])

    def test_revise_under_the_pixel_setting_sends_one_spec_request_and_nothing_to_sam(self):
        # The first round, as the propose and replay jobs leave it, with one rejected check to revise.
        prof = load_strict(PROFILE, "mechanics-profile")
        probes = offer_mod.library(prof["actions"], PX, REPORT)
        first = propose_to_file(intent_mod.spark_intent(
            transport=Transport(reply({"candidates": [GOOD_CHECK, MISCALIBRATED], "pixelChecks": [DRAWN]})),
            offer=PX), REPORT, self.cand.read_text(), prof, probes, self.tmp / "p1")
        self.assertIsNone(first["error"])
        generate(PROFILE, REPORT, self.cand, [self.base], self.tmp / "r1", runner=JitGame(),
                 intent=from_proposal(self.tmp / "p1" / "jit-proposal.json", offer=PX),
                 variants_fn=self.case.variants(), offer=PX, clock=lambda: 0.0)
        wire = Wire({"candidates": [SECOND_GOOD]})
        with as_the_step_runs({SPEC_CAP: "2"}, wire) as held, contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["revise", "--report-file", str(self.report), "--candidate", str(self.cand),
                             "--base", str(self.base), "--proposal", str(self.tmp / "p1" / "jit-proposal.json"),
                             "--record", str(self.tmp / "r1" / "jit-run.json"), "--out", str(self.tmp / "p2"),
                             "--budget-usd", "2", "--offer", PX])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["revised"])
        self.assertEqual((len(wire.spec()), wire.sam(), held), (1, [], ["spec"]))
        self.assertEqual(wire.sam_usage["requests"], 0)


class PixelAskSendsSamOnly(Jobs):
    """The audit's ``pixel-ask`` entry: the spec cap is listed and is not needed."""

    @classmethod
    def setUpClass(cls):
        # Jobs caches captures in its module's folder, which that module's tearDownModule deletes while
        # the cache outlives it. This class keeps a cache and a folder of its own.
        cls.shared = Path(tempfile.mkdtemp())
        cls.captured = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.shared, True)

    def setUp(self):
        super().setUp()
        for name, value in (("_CAPTURED", self.captured), ("_SHARED", self.shared)):
            patcher = mock.patch.object(pixel_jobs_tests, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_live_ask_sends_every_image_to_sam_and_nothing_to_spec(self):
        self.capture("fix-wrong", "layering_v1")
        wire = Wire()
        with as_the_step_runs({SAM_CAP: "1"}, wire) as held, contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["pixel-ask", "--replays", str(self.store), "--out", str(self.answers),
                             "--budget-usd", "1", "--sam-live", *SETTING])
        printed = json.loads(out.getvalue())
        self.assertEqual(code, 0, printed)
        self.assertTrue(printed["asked"], printed)
        self.assertIsNone(printed["stopped"], printed)
        self.assertEqual(len(wire.sam()), IMAGES * 9)   # three builds, three replays each
        self.assertEqual(wire.spec(), [])
        self.assertEqual(held, [])

    def test_without_sam_s_cap_a_live_ask_sends_nothing(self):
        self.capture("fix-wrong", "layering_v1")
        wire = Wire()
        with as_the_step_runs({}, wire), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["pixel-ask", "--replays", str(self.store), "--out", str(self.answers),
                      "--budget-usd", "1", "--sam-live", *SETTING])
        self.assertEqual(wire.urls, [])


if __name__ == "__main__":
    unittest.main()
