"""Compare headless trace.json bytes from two checkouts on the same Godot binary.

    python3 -m tests.compare_ground_traces BASE_CHECKOUT OUTPUT --godot /path/to/godot
    python3 -m tests.compare_ground_traces BASE_CHECKOUT OUTPUT --godot /path/to/godot --kinematic PINNED_GAME

The default runs all five bundled routes. --kinematic runs the public walk route in the
required replay sandbox. The game is a local checkout of the demo pinned in tests/outside.
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLED = [Path("harness/routes") / f"{name}.json" for name in ("smoke", "coins", "combat", "traversal")]
BUNDLED.append(Path("tests/routes/slope.json"))
WALK = Path("tests/outside/kinematic-character/routes/walk.json")

# Load the harness from the checkout under test, keeping the game and route identical on both arms.
RECORD = """from pathlib import Path
import sys
from harness.run import run
route, out, game, godot, sandbox = sys.argv[1:]
run(Path(route), Path(out), game=Path(game), godot=Path(godot), capture_frames=False, sandbox=sandbox)
"""


def compare(base, output, godot, kinematic=None):
    game = kinematic or ROOT / "game/platformer"
    for route in ([WALK] if kinematic else BUNDLED):
        records = []
        for side, checkout in (("base", base), ("head", ROOT)):
            out = output / side / game.name / route.stem
            out.mkdir(parents=True, exist_ok=False)
            subprocess.run([sys.executable, "-c", RECORD, str(ROOT / route), str(out), str(game),
                            str(godot), "require" if kinematic else "auto"], cwd=checkout, check=True)
            records.append((out / "trace.json").read_bytes())
        if records[0] != records[1]:
            raise AssertionError(f"{game.name}/{route.stem}: trace.json differs; see {output}")
        print(f"{game.name}/{route.stem}: identical, {len(records[0])} bytes, "
              f"SHA-256 {hashlib.sha256(records[0]).hexdigest()}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_checkout", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--kinematic", type=Path)
    args = parser.parse_args()
    compare(args.base_checkout.resolve(), args.output.resolve(), args.godot.resolve(),
            args.kinematic.resolve() if args.kinematic else None)
