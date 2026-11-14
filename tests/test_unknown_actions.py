"""An unreachable input makes the replay inconclusive even when the player stays above ground."""
import json
from pathlib import Path
from unittest import mock

from expectrail import contracts
from expectrail.gate import record as rec
from tests.test_two_observers import Case, repo

ABSENT = object()


class UnknownActionsTest(Case):
    def gate_with(self, root, head=ABSENT, base=None, before=(), **kw):
        replay = self.game.replay

        def recorded(route, game, out, frames):
            result = replay(route, game, out, frames)
            field = before if base is not None and game.is_relative_to(base) else head
            if field is ABSENT:
                result["trace"].pop("unknownActions", None)
            else:
                result["trace"]["unknownActions"] = list(field) if isinstance(field, tuple) else field
            return result

        with mock.patch.object(self.game, "replay", side_effect=recorded):
            return self.gate(root, base, **kw)

    def test_partial_or_wholly_unusable_route_names_actions_with_either_rule(self):
        for rule in (rec.ENGINE_ONLY, rec.BOTH):
            for look in ("clean", "BUG"):
                with self.subTest(rule=rule, look=look):
                    head = repo(self.tmp / (rule + look), look)
                    result = self.gate_with(head, ["teleport_through_wall", "duck"], rule=rule,
                                            visual=self.game.observer() if rule == rec.BOTH else None)
                    self.assertEqual(result["decision"], "needs-review")
                    self.assertEqual(self.row(result)["after"], "needs-review")
                    for action in ("teleport_through_wall", "duck"):
                        self.assertIn(action, " ".join(result["reasons"]))
                        self.assertIn(action, result["findings"][0]["reason"])

    def test_unreported_or_malformed_is_not_an_empty_list(self):
        head = repo(self.tmp / "clean")
        for field in (ABSENT, None, "jump", [None]):
            with self.subTest(field=field):
                result = self.gate_with(head, field)
                self.assertEqual(result["decision"], "needs-review")
                self.assertIn("cannot tell", " ".join(result["reasons"]))
        self.assertEqual(self.gate_with(head, [])["decision"], "accept")

    def test_unreachable_base_cannot_clear_a_change(self):
        doc = self.gate_with(repo(self.tmp / "head"), [], repo(self.tmp / "base"), ["gone"])
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(self.row(doc)["before"], "needs-review")
        self.assertIn("gone", " ".join(doc["reasons"]))

    def test_a_failure_on_a_different_route_still_rejects(self):
        from tests.test_ci_gate import make_repo
        head = make_repo(self.tmp / "two-routes", bug=True)
        replay = self.game.replay
        def partial(route, game, out, frames):
            result = replay(route, game, out, frames)
            result["trace"]["unknownActions"] = ["teleport"] if route.stem == "smoke" else []
            return result
        with mock.patch.object(self.game, "replay", side_effect=partial):
            doc = self.gate(head)
        self.assertEqual(doc["decision"], "reject")
        self.assertEqual({r["route"]: r["after"] for r in doc["checks"]}, {"combat": "fail", "smoke": "needs-review"})
        self.assertIn("teleport", " ".join(doc["reasons"]))

    def test_schema_accepts_example_and_old_traces_and_refuses_bad_lists(self):
        examples = Path(__file__).resolve().parents[1] / "contracts/examples"
        doc = json.loads((examples / "trace-unknown-actions.json").read_text())
        contracts.validate(doc, "trace")
        self.assertIn("teleport_through_wall", doc["unknownActions"])
        doc.pop("unknownActions")
        contracts.validate(doc, "trace")
        for invalid in (None, "jump", ["jump", "jump"], [42]):
            with self.subTest(invalid=invalid), self.assertRaises(contracts.ContractError):
                contracts.validate(dict(doc, unknownActions=invalid), "trace")
