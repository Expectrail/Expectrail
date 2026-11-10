"""Shared fixtures for the generated-checks tests (docs/jit.md): a simulated game, a fake model, patches."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from expectrail.jit.intent import spark_intent
from tests.test_discovery import PROFILE, FakeGame  # noqa: F401 - re-exported

STUB = "--- a/player/player.gd\n+++ b/player/player.gd\n@@ -1,1 +1,1 @@\n-a\n+b\n"


class JitGame(FakeGame):
    """FakeGame, plus the candidate fixes and near misses the tests use, recognised by file name:
    fix-good removes the air-jump bug, fix-wrong and fix-comment leave it, variant-airjump puts it back."""

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        if "fix-good" in stems or "fix-good-injected" in stems:
            stems.discard("air-jump")
        if "variant-airjump" in stems:
            stems.add("air-jump")
        moved = "variant-airjump-moved" in stems
        if moved:  # the air jump back, and the player 1 px to the right: unlike an air-jumping candidate
            stems.add("air-jump")
        if "variant-crash" in stems:
            stems.add("crash")
        out = super().__call__(route_path, run_dir, patches=[Path(s + ".patch") for s in sorted(stems)])
        if moved:
            trace_path = Path(run_dir) / "trace.json"
            trace = json.loads(trace_path.read_text())
            for row in trace["rows"]:
                row["player"][0] = round(row["player"][0] + 1.0, 3)
            trace_path.write_text(json.dumps(trace))
        return out


GOOD_CHECK = {"id": "no-extra-air-jumps", "statement": "Eight presses in the air give no more air jumps than two.",
              "claimId": "player.jump", "class": "player",
              "operation": {"type": "relation", "signal": "air_jumps", "comparator": "lte", "toleranceAbs": 0,
                            "left": "jump-w0-x2", "right": "jump-w0-x8"}}
ALWAYS_PASSES = {"id": "always-passes", "statement": "The player rises less than 100000 px.", "claimId": "player.jump",
                 "class": "player", "operation": {"type": "max_episode_rise", "maxPx": 100000},
                 "appliesTo": ["jump-w0-x8"]}
MISCALIBRATED = {"id": "miscalibrated", "statement": "The player never rises more than 1 px.", "claimId": "player.jump",
                 "class": "player", "operation": {"type": "max_episode_rise", "maxPx": 1}, "appliesTo": ["jump-w0-x8"]}
ANSWER = {"candidates": [GOOD_CHECK, ALWAYS_PASSES, MISCALIBRATED]}


def reply(doc, usage=None):
    content = doc if isinstance(doc, str) else json.dumps(doc)
    return {"choices": [{"message": {"content": content}}],
            "usage": usage if usage is not None else {"prompt_tokens": 1000, "completion_tokens": 2000}}


class Transport:
    def __init__(self, response):
        self.response, self.bodies = response, []

    def __call__(self, body):
        self.bodies.append(body)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def model(answer=ANSWER, **kw):
    t = Transport(reply(answer, **kw))
    return spark_intent(transport=t), t


class Case:
    """A temporary folder with the base bug, candidate fixes and near-miss patches as stub files."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jit-test-"))

    def patch(self, name: str, text: str = STUB) -> Path:
        p = self.dir / f"{name}.patch"
        p.write_text(text)
        return p

    def variants(self, *names):
        paths = [self.patch(n) for n in names]
        return lambda candidate, base: [{"id": f"v-{p.stem}", "kind": "operator", "path": p} for p in paths]
