"""The shared verifier (agents/domain_verifier.py) on a third domain that lives in its own module.

tests/toy_domain.py is written as a new engine would be: an adapter, specs, an engine-observations
builder and a behaviour check, registered from that module alone. Nothing in agents/ or harness/
knows it; the verifier and the fixer take it by name.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import domain_verifier
from expectrail.contracts import validate
from harness import adapters
from tests import toy_domain as toy


class SharedVerifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        adapters.register(toy.make(self.root))
        self.adapter = adapters.get(toy.NAME)
        private = self.root / "private" / "toy" / "routes"
        private.mkdir(parents=True)
        (private / "late.json").write_text(json.dumps({"name": "late", "frames": 6}) + "\n")
        self.held_out = private
        self.request = {"format": "expectrail.repair-request/v0", "id": "rr-toy-dark",
                        "base": {"tree": self.adapter.tree_digest(), "patch": str(self.root / "bugs" / "dark" / "v1.patch")},
                        "editable": list(self.adapter.editable),
                        "failing": [{"spec": toy.SPEC, "verdict": {"result": "fail", "reason": "the lamp is dark"},
                                     "route": json.loads(self.adapter.default_route.read_text())}],
                        "budget": {"attempts": 1, "minutesPerAttempt": 1}}

    def tearDown(self):
        adapters.unregister(toy.NAME)
        self.tmp.cleanup()

    def verify(self, candidate: Path, out: str, held_out: Path | None = None) -> tuple[str, dict]:
        return domain_verifier.verify(toy.NAME, self.request, candidate, self.root / out, specs=[toy.SPEC],
                                      observe=toy.observe, behaviour=toy.behaviour,
                                      behaviour_spec=toy.BEHAVIOUR_SPEC, routes=[self.adapter.default_route],
                                      held_out=held_out)

    def test_a_real_fix_is_accepted_on_every_check_kind(self):
        decision, doc = self.verify(self.root / "fix.patch", "fixed", self.held_out)
        self.assertEqual(decision, "accept", doc["reasons"])
        validate(doc, "verification")
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual([(c["kind"], c["spec"], c["route"]) for c in doc["checks"]], [
            ("regression", "lamp-visible", "evening"), ("gameplay", "lamp-is-switched-on", "evening"),
            ("clean", "lamp-visible", "evening"),
            ("held-out", "lamp-visible", "held-out-routes"), ("held-out", "lamp-is-switched-on", "held-out-routes")])
        self.assertEqual(json.loads((self.root / "fixed" / "verification.json").read_text()), doc)
        self.assertTrue((self.root / "fixed" / "candidate" / "evening" / "verdict-engine-lamp-visible.json").is_file())
        self.assertFalse((self.root / "fixed" / "held-out-note.txt").exists())

    def test_a_fix_that_only_restores_the_behaviour_is_rejected(self):
        decision, doc = self.verify(self.root / "switch-only.patch", "switch-only", self.held_out)
        self.assertEqual(decision, "reject")
        failed = {(c["kind"], c["spec"]) for c in doc["checks"] if c["result"] == "fail"}
        self.assertEqual(failed, {("regression", "lamp-visible"), ("held-out", "lamp-visible")})

    def test_an_empty_candidate_leaves_the_bug_and_is_rejected(self):
        empty = self.root / "empty.patch"
        empty.write_text("")
        decision, doc = self.verify(empty, "empty", self.held_out)
        self.assertEqual(decision, "reject")
        self.assertIn(("gameplay", "fail"), {(c["kind"], c["result"]) for c in doc["checks"]})

    def test_without_the_private_routes_nothing_is_accepted(self):
        decision, doc = self.verify(self.root / "fix.patch", "unmounted")
        self.assertEqual(decision, "needs-review")
        self.assertEqual(doc["checks"][-1], {"spec": "held-out-unavailable", "kind": "held-out",
                                             "route": "held-out-routes", "result": "needs-review",
                                             "verdictSha256": "0" * 64})
        self.assertEqual((self.root / "unmounted" / "held-out-note.txt").read_text(),
                         "the private held-out set is not mounted\n")
        empty = self.root / "private" / "none" / "routes"
        empty.mkdir(parents=True)
        self.assertEqual(domain_verifier.held_out_routes(empty), (None, "the private set has no none routes"))

    def test_a_replay_that_fails_is_needs_review_and_names_its_cause(self):
        class LampError(RuntimeError):
            pass

        def broken(route, out, patches=None, **_):
            Path(out).mkdir(parents=True, exist_ok=True)
            raise SystemExit("the lamp did not start") from LampError("no bulb")

        broken_adapter = adapters.Adapter(**{**self.adapter.__dict__, "run": broken})
        run_dir = self.root / "broken"
        got = domain_verifier.judge_route(broken_adapter, self.adapter.default_route, [], run_dir, [toy.SPEC],
                                          toy.observe, toy.behaviour)
        self.assertEqual(got, {"engine": "needs-review", "behaviour": "needs-review"})
        self.assertEqual((run_dir / "bench-error.txt").read_text(), "LampError: no bulb\n")
        bad_seed = dict(self.request, base={**self.request["base"], "patch": str(self.root / "fix.patch")})
        decision, doc = domain_verifier.verify(toy.NAME, bad_seed, self.root / "fix.patch", self.root / "no-apply",
                                               specs=[toy.SPEC], observe=toy.observe, behaviour=toy.behaviour,
                                               behaviour_spec=toy.BEHAVIOUR_SPEC, routes=[self.adapter.default_route],
                                               held_out=self.held_out)
        self.assertEqual(decision, "needs-review")
        self.assertEqual((self.root / "no-apply" / "candidate" / "evening" / "bench-error.txt").read_text(),
                         "SystemExit: fix.patch does not apply to the lamp\n")

    def test_a_vision_judge_decides_each_spec_when_it_is_on(self):
        def judge(trace, replay_sha, run_dir, specs):
            for spec in specs:
                (run_dir / f"verdict-eyes-{spec['id']}.json").write_text(json.dumps({"result": "fail"}))
            return {"eyes": "fail"}, ["eyes: squinting"]

        eyes = domain_verifier.Vision(label="eyes", judge=judge, names=lambda specs: ["eyes"])
        decision, doc = domain_verifier.verify(toy.NAME, self.request, self.root / "fix.patch", self.root / "eyes",
                                               specs=[toy.SPEC], observe=toy.observe, behaviour=toy.behaviour,
                                               behaviour_spec=toy.BEHAVIOUR_SPEC, routes=[self.adapter.default_route],
                                               held_out=self.held_out, vision=eyes)
        self.assertEqual(decision, "reject")
        self.assertEqual([c["result"] for c in doc["checks"] if c["spec"] == "lamp-visible"], ["fail"] * 3)
        self.assertEqual(json.loads((self.root / "eyes" / "candidate" / "evening" / "bench-errors.json").read_text()),
                         ["eyes: squinting"])

    def test_the_fixer_takes_the_new_adapter_by_name(self):
        from agents.fixer import build_muse_prompt, run_fixer

        meta = run_fixer(self.request, self.root / "fix", candidate_patch=self.root / "fix.patch", adapter=toy.NAME)
        self.assertEqual(meta["source"], "fixture")
        self.assertFalse((self.root / "fix" / "fixer-work" / toy.CACHE).exists())
        decision, _doc = self.verify(self.root / "fix" / "candidate.patch", "fixer-candidate", self.held_out)
        self.assertEqual(decision, "accept")
        self.assertTrue(build_muse_prompt(self.request, rr_relpath="repair-request.json", attempt=1,
                                          adapter=toy.NAME).startswith("You are fixing a lamp bug."))


class WebOnTheSharedVerifierTest(unittest.TestCase):
    def test_the_web_bench_judges_with_the_shared_judge_and_the_page_s_pieces(self):
        from agents import web_bench
        from harness.web import layout

        with mock.patch.object(domain_verifier, "judge_route", return_value={"layout": "pass"}) as judge:
            self.assertEqual(web_bench.judge_route(Path("r.json"), [], Path("out"), [], use_sam=False), {"layout": "pass"})
            web_bench.judge_route(Path("r.json"), [], Path("out"), [], use_sam=True)
        first, second = judge.call_args_list
        self.assertEqual(first.args, ("web", Path("r.json"), [], Path("out"), [], layout.layout_observations,
                                      layout.behaviour))
        self.assertEqual(first.kwargs, {"label": "layout", "vision": None})
        self.assertIs(second.kwargs["vision"], web_bench.SAM)


if __name__ == "__main__":
    unittest.main()
