"""Exercise the installed review command on copies of the bundled game and two pinned public games.

python3 -m tests.check_onboard_games EXPECTRAIL KINEMATIC_GAME DODGE_GAME NEW_OUTPUT_FOLDER
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from expectrail import project_config
from tests.check_onboarding_games import ROOT, contents
from tests.test_onboard import Page


def check(binary, source, game):
    shutil.copytree(source, game, ignore=shutil.ignore_patterns(".git", ".godot"))
    subprocess.run([binary, "init", game], cwd=game.parent, check=True)
    info = json.loads(subprocess.check_output([binary, "inspect", game, "--json"], cwd=game.parent))
    pending = (game / "expectrail.project.draft.json").is_file()
    before = contents(game)
    page = game.parent / (game.name + ".html")
    subprocess.run([binary, "onboard", "--project", game, "--out", page], cwd=game.parent, check=True)
    assert contents(game) == before
    parsed = Page(page)
    assert ("script" not in parsed.tags if pending else parsed.tags.count("script") == 2)
    if pending:
        assert len(parsed.images) == len(info["textures"])
    assert all(image.startswith("data:image/") for image in parsed.images)
    if pending:
        assert all(action in page.read_text() for action in info["actions"])
    else:
        assert parsed.payload is not None
    if pending:
        proposal = json.loads((game / "expectrail.project.draft.json").read_bytes())["config"]
    else:
        proposal = project_config.read_game(game)
    assert [c["bindings"]["player"]["texture"] for c in parsed.configs] == info["textures"]
    for config in parsed.configs:
        expected = json.loads(json.dumps(proposal))
        expected["bindings"]["player"]["texture"] = config["bindings"]["player"]["texture"]
        assert config == expected and config["draft"] is True and "approval" not in json.dumps(config)
        assert project_config.validate(config, game) == expected
    print(f"{game.name}: {len(parsed.images)} images, {len(parsed.configs)} validated downloads, game unchanged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("binary", "kinematic", "dodge", "output"):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir()
    for name, source in (("platformer", ROOT / "game/platformer"),
                         ("kinematic-character", args.kinematic), ("dodge-the-creeps", args.dodge)):
        check(args.binary.resolve(), source, output / name)


if __name__ == "__main__":
    main()
