import json
import unittest
from pathlib import Path

from expectrail.contracts import ContractError, validate
from expectrail.discovery.route_compiler import compile_route
from expectrail.gate import record
from expectrail.jit import offer

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples"
DRAFT = ROOT / "specs" / "drafts" / "727" / "exact-score"
CHECK = "pause-menu-score-after-five-pickups"
ROUTE = "hold-right-then-toggle-pause"
LABEL = "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter/Label"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ExactScoreContractsTest(unittest.TestCase):
    def test_exact_score_requires_named_routes(self):
        draft = read(DRAFT / "checks" / f"{CHECK}.json")
        draft.pop("coverage")
        with self.assertRaises(ContractError):
            validate(draft, "test-spec")

    def test_matching_approval_free_draft_and_example(self):
        draft = read(DRAFT / "checks" / f"{CHECK}.json")
        self.assertEqual(draft, read(EXAMPLES / "test-spec-exact-ui-integer.json"))
        self.assertNotIn("approval", draft)
        self.assertEqual(validate(draft, "test-spec"), "test-spec")
        self.assertEqual(draft["assertion"], {
            "type": "exact-ui-integer", "object": "score", "labelPath": LABEL,
            "expected": 5, "routeTicks": 464,
        })
        self.assertEqual(draft["coverage"], {"routes": [ROUTE], "minFrames": 1})

    def test_frozen_route_matches_public_probe_compiler(self):
        profile = read(ROOT / "discovery" / "platformer.profile.json")
        game = ROOT / profile["game"]["path"]
        probes = offer.library(profile["actions"], offer.CONTROL, profile=profile, game=game)
        probe = next(probe for probe in probes if probe["id"] == ROUTE)
        compiled = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                                 actions=offer.route_actions(profile, probe))
        route = read(DRAFT / "routes" / f"{ROUTE}.json")
        self.assertEqual(validate(route, "route"), "route")
        self.assertEqual(route, compiled)
        self.assertEqual(route["ticks"], 464)

    def test_score_assertion_requires_bounded_integer_and_exact_path(self):
        spec = read(EXAMPLES / "test-spec-exact-ui-integer.json")
        assertion = spec["assertion"]
        for field in ("type", "object", "labelPath", "expected", "routeTicks"):
            with self.subTest(missing=field), self.assertRaises(ContractError):
                validate({**spec, "assertion": {k: v for k, v in assertion.items() if k != field}}, "test-spec")
        for invalid in (
            {"labelPath": "../Label"}, {"labelPath": "/Label"}, {"labelPath": "Menu//Label"},
            {"labelPath": "Menu/-Label"}, {"labelPath": "Menu/Labél"},
            {"labelPath": LABEL + "\n"}, {"labelPath": "x" * 513},
            {"expected": 5.5}, {"expected": 10**9 + 1}, {"routeTicks": 0},
            {"routeTicks": 1.5}, {"tolerance": 0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                validate({**spec, "assertion": {**assertion, **invalid}}, "test-spec")

    def test_legacy_approval_does_not_cover_exact_score(self):
        legacy = read(EXAMPLES / "test-spec.json")
        self.assertNotIn("specSha256", legacy["approval"])
        self.assertEqual(validate(legacy, "test-spec"), "test-spec")
        score = read(EXAMPLES / "test-spec-exact-ui-integer.json")
        with self.assertRaisesRegex(ContractError, r"test-spec: assertion/type:"):
            validate({**legacy, "assertion": score["assertion"], "objects": score["objects"],
                      "coverage": score["coverage"]}, "test-spec")

    def test_trace_label_map_accepts_integer_or_null_and_remains_optional(self):
        trace = read(EXAMPLES / "trace-ui-label-integers.json")
        self.assertEqual(validate(trace, "trace"), "trace")
        self.assertEqual(validate(read(EXAMPLES / "trace-player-visibility.json"), "trace"), "trace")
        trace["rows"][0]["uiLabelIntegers"] = {f"_Menu/Label-{i}": -10**9 for i in range(16)}
        trace["rows"][1]["uiLabelIntegers"] = {"X" * 512: 10**9}
        self.assertEqual(validate(trace, "trace"), "trace")

    def test_trace_label_map_rejects_malformed_keys_or_values(self):
        trace = read(EXAMPLES / "trace-ui-label-integers.json")
        trace_schema = read(ROOT / "contracts" / "trace.schema.json")
        map_schema = trace_schema["properties"]["rows"]["items"]["properties"]["uiLabelIntegers"]
        for invalid in (
            None, [5], {"": 5}, {"../Label": 5}, {"Menu/-Label": 5}, {"Menu//Label": 5},
            {"Menu/Labél": 5}, {LABEL + "\n": 5}, {"x" * 513: 5}, {LABEL: "5"}, {LABEL: False},
            {LABEL: 2.5}, {LABEL: -10**9 - 1}, {LABEL: 10**9 + 1},
            {f"Label{i}": i for i in range(17)},
        ):
            with self.subTest(invalid=invalid):
                trace["rows"][1]["uiLabelIntegers"] = invalid
                with self.assertRaises(ContractError):
                    validate(trace, "trace")
                with self.assertRaises(record.RecordError):
                    record.validate(invalid, map_schema)
