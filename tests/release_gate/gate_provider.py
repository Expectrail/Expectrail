"""Release gate, the vision provider (#258): provider outage and budget exhausted.

Since #379 ``expectrail verify`` judges with both observers, so the visual observer and its spend cap
are on the path to clearance. These tests run the real command (``python3 -m expectrail.cli``, the
registered engine, its live visual observer and SAM client: nothing replaced) against a stand-in
provider on this machine (``tests.release_gate.provider``), with a stand-in key and a fresh answer
cache per test, so nothing leaves the machine and nothing is spent.

``ProviderBaselineTest`` is the positive control for these rows: with the stand-in answering from
the recorded answers of the "Run it" samples, the same command clears the unchanged game. So when
the provider is down, out of credit, or the cap stops every request, "not cleared" is the fault's
doing and not the setup's.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.release_gate import worker
from tests.release_gate.common import GAME, LEASE, REPO, ROUTE, SPECS, GateCase
from tests.release_gate.provider import ANSWER, DOWN, NO_CREDIT, STAND_IN_KEY, Provider

# Settings of the visual observer this suite sets itself; anything of the same name in the caller's
# environment is dropped first, so a real key can never reach these runs.
VISION_ENV = ("MODEL_API_KEY", "META_API_KEY", "EXPECTRAIL_SAM_USD_CAP", "EXPECTRAIL_MODEL_API_BASE",
              "EXPECTRAIL_SAM_CACHE", "EXPECTRAIL_VISION_BACKEND", "EXPECTRAIL_SAM_MODEL")


def said(status: dict) -> str:
    return " ".join(list(status.get("reasons") or []) + [d.get("detail", "") for d in status.get("diagnostics") or []])


class ProviderCase(GateCase):
    def live(self, provider: Provider, head, *, cap: str = "2", base=None) -> tuple[int, dict | None, str]:
        """The real ``expectrail verify --json`` with its visual observer pointed at ``provider``."""
        env = {k: v for k, v in os.environ.items() if k not in VISION_ENV}
        env.update({
            "MODEL_API_KEY": STAND_IN_KEY,             # a stand-in: the provider is on this machine
            "EXPECTRAIL_SAM_USD_CAP": cap,
            "EXPECTRAIL_MODEL_API_BASE": provider.base,
            "EXPECTRAIL_SAM_CACHE": str(self.tmp / "vision-cache"),   # no answer from an earlier test
            "EXPECTRAIL_VISION_BACKEND": "sam",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        })
        argv = [sys.executable, "-m", "expectrail.cli", "--jobs-root", str(self.jobs), "--lease-seconds", LEASE,
                "verify", "--head", str(head), "--game", GAME, "--routes", ROUTE, "--specs", SPECS, "--json"]
        if base is not None:
            argv += ["--base", str(base)]
        done = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
        try:
            status = json.loads(done.stdout)
        except ValueError:
            status = None
        if status and "id" in status:
            self.watched.append(status["id"])
        return done.returncode, status, done.stderr

    def provider(self, mode: str) -> Provider:
        provider = Provider(worker.recording(), mode).__enter__()
        self.addCleanup(provider.__exit__, None, None, None)
        return provider


class ProviderBaselineTest(ProviderCase):
    def test_with_the_provider_answering_the_live_observer_clears_the_unchanged_game(self):
        provider = self.provider(ANSWER)
        code, status, err = self.live(provider, self.clean)
        self.assertEqual((code, status["phase"], status["decision"]), (0, "completed", "accept"), err)
        self.assertGreater(provider.asked[ANSWER], 0, "the visual observer asked the provider nothing")


class ProviderTest(ProviderCase):
    # --- provider outage ----------------------------------------------------------------------------
    def test_a_provider_outage_is_not_clearance_and_does_not_hide_a_broken_build(self):
        provider = self.provider(DOWN)
        code, status, err = self.live(provider, self.clean)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["phase"], status["decision"]), (2, "completed", "needs-review"), err)
        self.assertGreater(provider.asked[DOWN], 0, "the provider was never asked, so this was no outage")
        self.assertIn("did not answer", said(status))
        # The engine still judges: the seeded bug is rejected with the provider down, not waved through
        # as "needs review".
        code, status, err = self.live(provider, self.bug, base=self.clean)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (1, "reject"), err)

    # --- budget exhausted ---------------------------------------------------------------------------
    def test_a_cap_of_nothing_sends_nothing_and_is_not_clearance(self):
        provider = self.provider(ANSWER)
        code, status, err = self.live(provider, self.clean, cap="0")
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"), err)
        self.assertEqual(provider.asked[ANSWER], 0, "a request was sent past a cap of $0")
        self.assertIn("budget", said(status))

    def test_a_cap_spent_part_way_stops_the_requests_and_is_not_clearance(self):
        # $0.005 is two images at the list price the client counts ($2.50 per 1,000).
        provider = self.provider(ANSWER)
        code, status, err = self.live(provider, self.clean, cap="0.005")
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"), err)
        self.assertGreater(provider.asked[ANSWER], 0)
        self.assertLessEqual(provider.asked[ANSWER], 2, "more requests were sent than the cap pays for")
        self.assertIn("budget", said(status))

    def test_a_provider_out_of_credit_is_not_clearance(self):
        provider = self.provider(NO_CREDIT)
        code, status, err = self.live(provider, self.clean)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"), err)
        self.assertGreater(provider.asked[NO_CREDIT], 0)
        self.assertIn("credit", said(status))
