"""Exercise an installed expectrail on disposable copies of three local games.

python3 -m tests.check_onboarding_games EXPECTRAIL KINEMATIC_GAME DODGE_GAME
Use the two public games pinned in tests/outside/projects.json. No download or replay.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from time import perf_counter_ns

from expectrail import contracts, project_config

ROOT = Path(__file__).resolve().parents[1]


def contents(game):
    return {p.relative_to(game): hashlib.sha256(p.read_bytes()).digest() if p.is_file() else None
            for p in game.rglob("*")}


def check(binary, game, player, texture, camera, ground):
    original = contents(game)
    for command in ("inspect", "init"):
        start = perf_counter_ns()
        output = subprocess.run([binary, command, game], cwd=game.parent, capture_output=True, text=True)
        seconds = (perf_counter_ns() - start) / 1e9
        print(f"{game.name} {command}: {seconds:.6f} seconds, exit {output.returncode}", flush=True)
        print(output.stdout, end="")
        assert output.returncode == 0, output.stderr
        if command == "inspect":
            report = json.loads(subprocess.check_output([binary, "inspect", game, "--json"], cwd=game.parent))
            assert report["players"] == [player], report
            assert report["cameras"] == camera and report["groundLayers"] == ground, report
            assert contents(game) == original
    config = project_config.read_game(game)
    if texture:
        assert config["bindings"]["player"] == {"node": player, "texture": texture}
        contracts.validate_v1(config, "project")
        document = project_config.FILENAME
    else:
        assert config is None
        document = "expectrail.project.draft.json"
        review = json.loads((game / document).read_bytes())
        config = review["config"]
        assert config["bindings"]["player"] == {"node": player}
        assert review["unresolvedBindings"] == report["unresolvedBindings"]
        assert "Player/AnimatedSprite2D.sprite_frames" in " ".join(review["unresolvedBindings"])
        assert set(review["textureCandidates"]) == {
            "res://art/playerGrey_" + suffix + ".png" for suffix in ("walk1", "walk2", "up1", "up2")}
    assert config["draft"] is True and "approvedContracts" not in config
    route, = config["routes"]
    generated = json.loads((game / route).read_bytes())
    contracts.validate(generated, "route")
    assert "draft" in generated["name"]
    assert set(report["actions"]) == set(config["inputActions"]) == {e["action"] for e in generated["events"]}
    current = contents(game)
    assert {k: current[k] for k in original} == original
    assert {p.as_posix() for p in current.keys() - original.keys() if (game / p).is_file()} == {document, route}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    for arg in ("expectrail", "kinematic", "dodge"):
        args.add_argument(arg, type=Path)
    opts = args.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        for name, source, player, image, cameras, ground in (
            ("platformer", ROOT / "game/platformer", "Level/Player", "res://player/robot.webp",
             ["Level/Player/Camera"], ["Level/TileMapLayer"]),
            ("kinematic-character", opts.kinematic, "Player", "res://player/player.png", ["Camera2D"], ["TileMapLayer"]),
            ("dodge-the-creeps", opts.dodge, "Player", None, [], []),
        ):
            game = Path(tmp) / name
            shutil.copytree(source, game, ignore=shutil.ignore_patterns(".git", ".godot"))
            check(opts.expectrail.resolve(), game, player, image, cameras, ground)
            print(f"{name}: checks passed")


if __name__ == "__main__":
    main()
