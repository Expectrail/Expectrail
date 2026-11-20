"""Which model roles two vision-only workflow steps send with (#267, the spend-cap audit's review).

``tools/spend_cap_audit.py`` reads imports, so it says a step "may reach" every sender in the import closure
of what it starts. For two steps that set only the vision model's cap (``EXPECTRAIL_SAM_USD_CAP``) it lists
caps they do not set:

- ``run-it-record.yml::record`` (``python -m expectrail.runit record``): Muse and spec. This is the step a
  person dispatches to record a Run it sample's vision answers (#265).
- ``outside-vision.yml::judge`` (``python -m tools.outside_vision judge``): spec.

These tests settle it by running, not by reading. Each command runs as the step runs it, with exactly the caps
the step sets (read from the workflow itself), a made-up key, a fresh spend meter that records every hold,
and the network floor of every HTTP sender (``urllib.request.urlopen``) replaced by a recorder. The recorder
answers the vision model's address as the stand-in model would and refuses every other address. A step that
tried to send a role whose cap it lacks would show the request in the recorder, a hold in the meter, or a stop
for the missing cap. Offline: the stand-in replays and model of tests/test_two_observers.py. Nothing is sent
and nothing is spent.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

import yaml

from agents import sam_observations as sam_mod
from expectrail import recorded, runit, spend
from tests import test_outside_vision as outside_tests
from tests.test_runit import Case
from tools import outside_vision as vision

REPO = Path(__file__).resolve().parents[1]
SAM_CAP = spend.CAP_ENV["vision"]
CAPS = frozenset(spend.CAP_ENV.values())
SAM_URL = re.compile(r"/responses$")
FAKE_KEY = "test-key-not-a-real-key"
# Settings that pick another vision backend or a month ledger would change what the step runs: the
# workflows set none of them, so the tests clear them.
CLEARED = ("META_API_KEY", "EXPECTRAIL_VISION_MONTH_LEDGER", sam_mod.BACKEND_ENV, sam_mod.CACHE_ENV)


def step(workflow: str, job: str, name_start: str) -> dict:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"][job]["steps"] if s.get("name", "").startswith(name_start))


def caps_of(workflow: str, job: str, name_start: str) -> set[str]:
    """The caps a step sets: in its ``env:``, or exported by its script."""
    s = step(workflow, job, name_start)
    named = set(s.get("env") or {}) & CAPS
    named |= {m.group(1) for m in re.finditer(r"export\s+([A-Z_]+)=", s.get("run", ""))} & CAPS
    return named


def env_names_of(workflow: str, job: str, name_start: str) -> set[str]:
    """Every name the step's ``env:``, its job's and its workflow's set (to hold the tests to them)."""
    wf = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))
    names = set(wf.get("env") or {}) | set(wf["jobs"][job].get("env") or {})
    return names | set(step(workflow, job, name_start).get("env") or {})


class Wire:
    """``urllib.request.urlopen``: answers the vision model's address with ``answer`` (a function of the
    request body) and refuses, after recording it, a request to any other address."""

    def __init__(self, answer=None):
        self.urls: list[str] = []
        self.answer = answer

    def __call__(self, req, timeout=None):  # noqa: ARG002 - the signature urlopen is called with
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        if not (SAM_URL.search(url) and self.answer is not None):
            raise AssertionError(f"a request to an unexpected address: {url}")
        body, ctype = self.answer(json.loads(req.data))
        resp = mock.MagicMock()
        resp.read.return_value = body
        resp.headers = {"Content-Type": ctype}
        resp.__enter__.return_value = resp
        return resp

    def sam(self) -> list[str]:
        return [u for u in self.urls if SAM_URL.search(u)]

    def others(self) -> list[str]:
        return [u for u in self.urls if not SAM_URL.search(u)]


class RecordingMeter(spend.Meter):
    """The spend meter, also recording the role of every hold asked for (held or refused)."""

    def __init__(self):
        super().__init__()
        self.asked: list[str] = []

    def reserve(self, role, usd, *, live):
        self.asked.append(role)
        return super().reserve(role, usd, live=live)


@contextlib.contextmanager
def as_the_step_runs(caps: dict[str, str], wire: Wire):
    """The step's environment (a key and exactly ``caps``), a fresh meter and SAM counter, and the wire."""
    env = {k: v for k, v in os.environ.items() if k not in CAPS and k not in CLEARED}
    env.update(MODEL_API_KEY=FAKE_KEY, **caps)
    meter = RecordingMeter()
    fresh = {"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0}
    required = []
    real_require = spend.require_cap

    def require_cap(role):
        required.append(role)
        return real_require(role)

    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(spend, "METER", meter), \
            mock.patch.object(spend, "require_cap", require_cap), \
            mock.patch("expectrail.spec_writer.require_cap", require_cap), \
            mock.patch.object(sam_mod, "_usage", fresh), mock.patch("urllib.request.urlopen", wire):
        yield meter, fresh, required


class TheStepsSetTheCapsTheseTestsUse(unittest.TestCase):
    """If a workflow changes which caps a step sets, or sets a backend, the tests below no longer describe
    it: fail first."""

    def test_the_recording_step_exports_the_vision_cap_alone(self):
        self.assertEqual(caps_of("run-it-record.yml", "record", "Record the vision answers"), {SAM_CAP})

    def test_the_outside_judge_step_sets_the_vision_cap_alone(self):
        self.assertEqual(caps_of("outside-vision.yml", "judge", "Judge saved runs"), {SAM_CAP})

    def test_neither_step_picks_another_vision_backend_or_a_month_ledger(self):
        for wf, job, name in (("run-it-record.yml", "record", "Record the vision answers"),
                              ("outside-vision.yml", "judge", "Judge saved runs")):
            with self.subTest(workflow=wf):
                self.assertEqual(env_names_of(wf, job, name) & set(CLEARED) - {"META_API_KEY"}, set())
                self.assertNotIn(sam_mod.BACKEND_ENV, step(wf, job, name).get("run", ""))

    def test_the_recording_targets_are_the_ones_tested_here(self):
        wf = yaml.safe_load((REPO / ".github" / "workflows" / "run-it-record.yml").read_text(encoding="utf-8"))
        options = wf[True]["workflow_dispatch"]["inputs"]["target"]["options"]
        self.assertEqual(sorted(options), sorted([*RecordingSendsVisionOnly.SAMPLES, runit.GATE_COMBAT]))


class RecordingSendsVisionOnly(Case):
    """The audit's ``run-it-record.yml::record`` entry: the Muse and spec caps are listed and not needed."""

    SAMPLES = ("clean", "fall-through-bug", "fall-through-repair")

    def setUp(self):
        super().setUp()
        # What gate-combat replays besides what a sample reads: the combat route.
        (self.root / runit.COMBAT_ROUTE).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / runit.COMBAT_ROUTE, self.root / runit.COMBAT_ROUTE)

    def wire(self):
        return Wire(self.game.transport)

    def record_live(self, target: str, caps: dict[str, str], wire: Wire):
        """``runit.record`` as ``python -m expectrail.runit record`` calls it: no client given, so the live
        client the step would build (agents.sam_observations.default_client) sends over the wire."""
        out = self.tmp / f"{target}.json"
        with as_the_step_runs(caps, wire) as (meter, usage, required):
            try:
                self.quiet(runit.record, target, out, run_id="test-1", root=self.root, replay=self.game.replay,
                           recorded_at="2026-11-20")
                error = None
            except Exception as exc:  # noqa: BLE001 - the control below expects the step to fail
                error = exc
        return out, error, meter, usage, required

    def test_every_target_sends_only_to_the_vision_model_and_holds_no_other_role(self):
        for target in (*self.SAMPLES, runit.GATE_COMBAT):
            with self.subTest(target=target):
                wire = self.wire()
                out, error, meter, usage, required = self.record_live(target, {SAM_CAP: "1"}, wire)
                self.assertIsNone(error, repr(error))
                self.assertGreater(len(recorded.read_recording(out)["answers"]), 0)
                self.assertGreater(len(wire.sam()), 0)
                self.assertEqual(wire.others(), [])
                self.assertEqual(usage["requests"], len(wire.sam()))
                self.assertEqual((meter.asked, required), ([], []))
                self.assertEqual({r: v for r, v in meter.snapshot_roles().items()
                                  if v != {"reserved": 0.0, "requests": 0, "stopped": None}}, {})

    def test_without_the_vision_cap_nothing_is_sent(self):
        # The control: the cap the step sets is the one the sender holds against.
        wire = self.wire()
        out, error, *_ = self.record_live("clean", {}, wire)
        self.assertEqual(wire.urls, [])
        self.assertFalse(out.exists() and recorded.read_recording(out)["answers"])

    def test_with_the_vision_cap_spent_no_further_request_is_sent(self):
        # One image's worth: the second request would pass the cap and is not sent.
        wire = self.wire()
        self.record_live("clean", {SAM_CAP: str(sam_mod.USD_PER_IMAGE)}, wire)
        self.assertEqual(len(wire.sam()), 1)
        self.assertEqual(wire.others(), [])


class OutsideJudgeSendsNoSpec(unittest.TestCase):
    """The audit's ``outside-vision.yml::judge`` entry: the spec cap is listed and not needed.

    The vision model here is the stand-in of tests/test_outside_vision.py, put where the command builds its
    client, so its requests are counted by the stand-in rather than on the wire. Any other sender would still
    go through the wire and the meter. The saved captures are tests/test_outside_vision.py's, made by its
    fixture (used here, not inherited, so its own tests do not run twice)."""

    def setUp(self):
        fixture = outside_tests.CaptureJudgeTest("test_saved_gate_runs_no_process_and_records_the_real_trees_and_both_observers")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.project, self.data, self.receipt, self.root = fixture.project, fixture.data, fixture.receipt, fixture.root

    def judge_live(self, caps: dict[str, str], client):
        wire = Wire()
        out = self.root / f"findings-{len(caps)}"
        cli = ["judge", "--project", self.project["name"], "--data", str(self.data), "--digest", self.receipt,
               "--out", str(out)]
        with as_the_step_runs(caps, wire) as (meter, _usage, required), \
                mock.patch("agents.sam_observations.MetaSamClient", return_value=client), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = vision.main(cli)
            except SystemExit as exc:
                code = exc.code
        return code, out, wire, meter, required

    def test_judging_every_variant_asks_the_vision_model_and_holds_no_other_role(self):
        client = outside_tests.Sees()
        code, out, wire, meter, required = self.judge_live({SAM_CAP: "2"}, client)
        self.assertEqual(code, 0)
        self.assertGreater(client.calls, 0)
        self.assertEqual(self.fixture.decisions(out), {"pinned": "accept", "broken": "reject", "harmless": "accept"})
        self.assertEqual((wire.urls, meter.asked, required), ([], [], []))

    def test_without_the_vision_cap_the_command_refuses_before_any_model_is_built(self):
        client = outside_tests.Sees()
        code, out, wire, meter, _ = self.judge_live({}, client)
        self.assertNotEqual(code, 0)
        self.assertEqual((client.calls, wire.urls, meter.asked), (0, [], []))
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
