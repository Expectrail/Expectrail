import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import validate
from expectrail.project_config import read_game
from expectrail.project_model import ModelError, draft_pair, read_model, write_model
from expectrail.project_model_godot import authored_rail, exercised_route


FIXTURE = Path(__file__).resolve().parents[1] / "bench/project-model/741/reference"


def model_record():
    version = "a" * 64
    return {
        "format": "expectrail.project-model/v1",
        "reference": {
            "treeSha256": version, "profileSha256": version, "bindingsSha256": version,
            "harnessSha256": version,
            "engine": {"name": "example", "version": "1", "sha256": version},
            "route": {"name": "out-and-back", "sha256": version, "ticks": 4},
            "capture": {"viewport": [320, 180], "ticksPerSecond": 60, "framesPerSecond": 60},
        },
        "constraint": {"kind": "fixed-axis-band", "subject": "player", "axis": "y",
                       "coordinateSpace": "world", "units": "pixels", "minimum": 72, "maximum": 88},
        "sources": [
            {"path": "source.file", "sha256": version, "location": "actor", "property": "position"},
            {"path": "source.file", "sha256": version, "location": "shape", "property": "size"},
        ],
        "evidence": {"traceSha256": version, "transform": "identity", "firstTick": 0,
                     "lastTick": 3, "goalTick": 1, "returnTick": 3},
    }


def trace_for(config):
    def role(name, x):
        width = 0.5 if name != "player" else 2
        return {"role": name, "id": config["bindings"][name]["node"], "visible": True,
                "boundsSource": "drawing", "worldBox": [x - width, 72, x + width, 88]}

    return {"ticks": 4, "physicsTicksPerSecond": 60, "unknownActions": [],
            "bindings": config["bindings"], "viewport": [320, 180], "rows": [
                {"tick": t, "view": [1, 0, 0, 1, 0, 0],
                 "roleObjects": [role("player", x), role("goal", 130), role("home", 100)]}
                for t, x in enumerate([102, 130, 110, 100])
            ]}


class ProjectModelTest(unittest.TestCase):
    def test_model_is_deterministic_and_stale_references_need_review(self):
        data = model_record()
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.json"
            second = Path(folder) / "second.json"
            write_model(first, data)
            write_model(second, dict(reversed(list(data.items()))))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(read_model(first, data["reference"]), data)
            for field in ("treeSha256", "profileSha256", "bindingsSha256", "harnessSha256"):
                with self.subTest(field=field), self.assertRaisesRegex(ModelError, "needs-review"):
                    read_model(first, {**data["reference"], field: "b" * 64})
            with self.assertRaisesRegex(ModelError, "needs-review"):
                read_model(first, {**data["reference"], "route": {**data["reference"]["route"], "sha256": "b" * 64}})

    def test_model_yields_both_existing_assertions(self):
        pair = draft_pair(model_record())
        self.assertEqual(set(pair), {"rail", "movement"})
        for spec in pair.values():
            validate(spec, "test-spec")
            self.assertNotIn("approval", spec)
            self.assertEqual(spec["window"], {"fromFrame": 0, "toFrame": 3})
            self.assertEqual(spec["coverage"]["routes"], ["out-and-back"])
        self.assertEqual(pair["rail"]["assertion"]["region"]["box"], [0, 72, 320, 88])
        self.assertEqual(pair["movement"]["assertion"]["type"], "reaches")

    def test_unfounded_geometry_or_window_cannot_draft(self):
        for path, leaf, invalid in [("constraint", "minimum", 100), ("evidence", "lastTick", 2),
                                    ("evidence", "goalTick", 3)]:
            data = model_record()
            data[path][leaf] = invalid
            with self.subTest(path=path, leaf=leaf), self.assertRaises(ModelError):
                draft_pair(data)

    def test_godot_adapter_reads_authored_position_and_shape(self):
        constraint, sources = authored_rail(FIXTURE, read_game(FIXTURE))
        self.assertEqual((constraint["minimum"], constraint["maximum"]), (72, 88))
        self.assertEqual({source["property"] for source in sources}, {"position", "shape", "size"})
        self.assertEqual({source["path"] for source in sources}, {"main.tscn"})

    def test_godot_adapter_refuses_an_entry_scene_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "reference"
            shutil.copytree(FIXTURE, root)
            shutil.copyfile(root / "main.tscn", root / "different.tscn")
            config = {**read_game(root), "entryScene": "res://different.tscn"}
            with self.assertRaisesRegex(ModelError, "entry scene"):
                authored_rail(root, config)

    def test_route_exercise_requires_complete_bound_identity_and_both_legs(self):
        config = read_game(FIXTURE)
        route = {"ticks": 4, "events": [
            {"tick": 0, "action": "right", "pressed": True},
            {"tick": 2, "action": "right", "pressed": False},
            {"tick": 2, "action": "left", "pressed": True},
        ]}
        original = trace_for(config)
        reached = exercised_route(original, route, config)
        self.assertEqual(reached, (1, 3))
        for label, change in {
            "incomplete": lambda t: t["rows"].pop(),
            "moved camera": lambda t: t["rows"][2]["view"].__setitem__(-1, 1),
            "identity switch": lambda t: t["rows"][2]["roleObjects"][0].__setitem__("id", "Other"),
            "no return": lambda t: t["rows"][3]["roleObjects"][0].__setitem__("worldBox", [128, 72, 132, 88]),
        }.items():
            with self.subTest(label=label), self.assertRaisesRegex(ModelError, "needs-review"):
                changed = copy.deepcopy(original)
                change(changed)
                exercised_route(changed, route, config)
