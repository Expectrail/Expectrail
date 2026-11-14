"""Release gate, candidate interference (#258): a poisoned import cache.

Godot keeps what it imported from a game's pictures and sounds in the game's ``.godot/`` folder, and
draws from there. A change could carry its own ``.godot/`` whose imported robot is another picture
(here: the enemy's), so the frames the visual observer judges would not be drawn from the game's
source. The defence is that a replay never copies a ``.godot/`` from the checkout (``harness.tree``
leaves it out of every digest and every copy); the only import cache a replay uses is the verifier's
own, kept outside the checkout under a key made from the engine and the game's files.

The control shows the poison is real: the same picture swap made in the verifier's own cache, with
its key left as it was, changes what is drawn. The recorded observer then has no answer for those
frames, and the unchanged game is not cleared. The tests then show a change carrying that poison is
judged on what its source draws: the unchanged game with the poison is cleared, every frame answered
from the recording (so every frame matched the unchanged game's byte for byte), and the seeded bug
with the poison is rejected.

What this does not cover: a run without the replay sandbox has no boundary at all, and its game can
write anywhere the verifier can, the verifier's own cache included (the control above is what that
would do). The sandbox's rows ("reading a private path", "network egress") are about that boundary.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from harness import tree
from tests.release_gate.common import GAME, REPO, GateCase

ROBOT = "robot.webp-"
ENEMY = "enemy.webp-"


def imported(cache: Path, prefix: str) -> Path:
    found = [p for p in (cache / "imported").glob(prefix + "*.ctex")]
    assert len(found) == 1, (prefix, found)
    return found[0]


def poison(cache: Path) -> None:
    """In an import cache (a ``.godot/`` folder), the robot's imported picture becomes the enemy's."""
    robot = imported(cache, ROBOT)
    robot.write_bytes(imported(cache, ENEMY).read_bytes())


class ImportCacheTest(GateCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The verifier's own cache for the bundled game, warmed the way a replay warms it.
        cls.warm = cls.root / "warm-cache"
        done = subprocess.run([sys.executable, "-m", "harness.run", "--warm-cache", "--game", str(cls.clean / GAME)],
                              cwd=REPO, capture_output=True, text=True, timeout=600,
                              env={**os.environ, "EXPECTRAIL_GODOT_CACHE": str(cls.warm)})
        assert done.returncode == 0 and (cls.warm / ".godot" / "imported").is_dir(), done.stdout + done.stderr

    def own_cache(self, name: str) -> tuple[Path, dict]:
        """A copy of the warmed cache, key file and all, and the environment that points a run at it."""
        target = self.tmp / name
        shutil.copytree(self.warm, target)
        return target / ".godot", {"EXPECTRAIL_GODOT_CACHE": str(target)}

    def carrying_poison(self, name: str, source: Path) -> Path:
        """A checkout whose game folder carries a poisoned ``.godot/``."""
        head = self.copy(name, source)
        cache = head / GAME / ".godot"
        shutil.copytree(self.warm / ".godot", cache)
        poison(cache)
        return head

    def test_control_the_same_poison_in_the_verifiers_own_cache_changes_what_is_drawn(self):
        cache, env = self.own_cache("poisoned-own")
        poison(cache)
        code, status, err = self.verify(self.clean, env=env)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"), err)
        # Why: the engine's record passes, and the frames are not the ones recorded, because the
        # robot was drawn from the poisoned picture.
        self.assertTrue(any("not-recorded" in r for r in status["reasons"]), status["reasons"])

    def test_an_import_cache_the_change_carries_is_never_drawn_from(self):
        head = self.carrying_poison("clean-carrying", self.clean)
        _, env = self.own_cache("clean-own")
        code, status, err = self.verify(head, env=env)
        # Cleared on what its source draws: every vision question was answered from the recording,
        # which holds answers only for the unchanged game's exact frames.
        self.assertEqual((code, status["decision"]), (0, "accept"), err)
        self.assertEqual(status["inputs"]["headTree"], tree.digest(self.clean / GAME, skip=tree.GODOT_SKIP))

    def test_a_broken_change_that_carries_an_import_cache_is_still_rejected(self):
        head = self.carrying_poison("bug-carrying", self.bug)
        _, env = self.own_cache("bug-own")
        code, status, err = self.verify(head, base=self.clean, env=env)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (1, "reject"), err)
