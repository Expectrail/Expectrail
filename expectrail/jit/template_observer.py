"""The no-model sensor of #262 as the ``visual-sensor`` observer of pixel checks (#286).

``run.generate(..., observer=...)`` asks an observer about every pixel replay (expectrail/jit/pixel.py,
``observe``). ``TemplateSensorObserver`` is that observer for ``visual-sensor``: on each replay it looks for
the player in the frames with the template sensor (agents/template_observations.py, ``from_replay``),
searching near the place the engine's record puts the player's body box, against a template bank frozen
from a trusted clean replay. **No model is asked, no request leaves the machine, and nothing is charged:**
``images`` is always 0.

**The bank is the caller's, and frozen.** It is calibrated beforehand from a clean replay of the pinned
clean game (agents/template_observations.py ``calibrate`` or ``calibrate_routes``, or
agents/template_sensor_bench.py), never from a candidate, and read here with ``load_bank``, which checks
every template's bytes against its digest. Nothing a replay shows changes it. The observer's setting names
the bank's algorithm and digest, so two runs judged with different banks are never compared (pixel.py
``keep``: one setting on all six runs).

**The frames are the SAM observer's plan** (sam_observer.py ``plan_frames``: every ``every``-th frame and
the last, within ``first``, at most ``max_frames``), and the replay is checked the same way before anything
is read (sam_observer.py ``checked_replay``): the route, the capture rates, the frames on disk against the
replay's digests, and every planned frame present. Any of these failing is a ``PixelError``: the checks on
that probe are dropped with the reason, never passed.

**What a frame's row says** (one a planned frame, in the shape pixel.py ``observations`` reads):

- ``matched``: the sensor found the player's template inside the search region and overlapping the
  engine's box: ``box`` is the match, ``holdsPoint`` true. The object is seen there.
- ``displaced``: it found the template, but not where the engine puts the player: ``holdsPoint`` false.
  What is drawn there is something else; the object was looked for and not found there.
- ``not-found``: it searched readable pixels around the engine's box and no template reached the
  threshold: ``absent`` true and no box. An observation that the object is not drawn there, not a gap.
- ``unavailable`` or ``out-of-frame``: no readable frame, no engine box, no camera, or the box is not
  wholly on screen: not asked (a gap, so a check over that frame is ``needs-review``).

**What it cannot tell** is declared in pixel.py ``OBSERVERS["visual-sensor"]`` and refused when a check is
proposed: the ground and a label's text (the sensor discards colour semantics and reads no text,
docs/template-sensor.md), any role other than the player (a bank holds the player's templates, and a
second sprite needs its own templates and prediction map, which nothing here supplies yet), and
``reaches`` (it looks for one object near the place the engine puts it).

What this is not, yet: the proposer is not offered this observer, and neither a model's answer nor a saved
proposal may name it (pixel.py ``PROPOSED``), because the propose step is not told which observer will
judge the run; ``run.generate`` judges checks naming it when it is the run's observer and an intent hands
it such checks (tests/test_jit_template_observer.py). The command line does not build it, jit.yml does not,
and no bank has been calibrated for a bench probe. The sensor's measured
false alarms on clean frames are in docs/template-sensor-measurement.md: a false alarm on a clean run
drops the check by the keep rule, so it costs a reproduction, never a false catch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from expectrail.contracts import digest
from expectrail.jit import pixel
from expectrail.jit.sam_observer import (DEFAULT_EVERY, DEFAULT_FPS, DEFAULT_TICKS_PER_SECOND, MAX_EVERY, MAX_FRAMES,
                                         checked_replay, plan_frames)

NAME = "visual-sensor"
ROLE = "player"
GAP_STATUSES = ("unavailable", "out-of-frame")
SEEN = ("matched", "displaced", "not-found")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TemplateSensorObserver:
    """The ``visual-sensor`` observer for ``run.generate``: see the module docstring."""

    name = NAME

    def __init__(self, bank, *, every: int = DEFAULT_EVERY, first: int | None = None, max_frames: int = MAX_FRAMES,
                 fps: int = DEFAULT_FPS, ticks_per_second: int = DEFAULT_TICKS_PER_SECOND):
        from agents import template_observations as sensor

        for label, value in (("every", every), ("max_frames", max_frames), ("fps", fps),
                             ("ticks_per_second", ticks_per_second)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{label} is a whole number, 1 or more")
        if every > MAX_EVERY:
            raise ValueError(f"every is at most {MAX_EVERY} (one frame a second at {DEFAULT_FPS} fps)")
        if first is not None and (not isinstance(first, int) or isinstance(first, bool) or first < 1):
            raise ValueError("first is a whole number of frames, 1 or more")
        if max_frames < 2:
            raise ValueError("max_frames is 2 or more: the first frame and the last")
        try:
            self.bank = sensor.load_bank(bank)
        except (sensor.SensorError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"the template bank cannot be used: {' '.join(str(exc).split())[:160]}") from exc
        roles = sorted({t["object"] for t in self.bank["templates"]})
        if ROLE not in roles:
            raise ValueError(f"the template bank has no template of the {ROLE} (it has {', '.join(roles) or 'none'})")
        self.every, self.first, self.max_frames = every, first, max_frames
        self.fps, self.ticks_per_second = fps, ticks_per_second
        self._setting = {"model": self.bank["config"]["algorithm"], "bankSha256": digest(self.bank)}

    @property
    def step(self) -> int:
        return max(self.ticks_per_second // self.fps, 1)

    def setting(self) -> dict:
        """The sensor's algorithm and the bank's digest: two runs are compared only under one."""
        return dict(self._setting)

    def frames(self, route: dict) -> list[int]:
        return plan_frames(route, self.step, self.every, self.first, self.max_frames)

    def most_images(self, route: dict, objects=(), player: bool = True) -> int:
        """Nothing is sent anywhere, so a replay takes no images and the budget reserves nothing for it."""
        self._roles(objects, player)
        return 0

    @staticmethod
    def _roles(objects, player) -> None:
        objects = tuple(objects)
        if objects:
            raise pixel.PixelError(f"{NAME} is not pointed at the boxes of {', '.join(map(str, objects))[:60]}: its "
                                   f"bank holds the {ROLE}'s templates only")
        if player is not True:
            raise pixel.PixelError(f"{NAME} would be asked about nothing: it looks for the {ROLE} only")

    def __call__(self, run_dir, route: dict, objects=(), player: bool = True) -> dict:
        from agents import template_observations as sensor

        self._roles(objects, player)
        run_dir = Path(run_dir)
        planned = self.frames(route)
        replay, hashes, on_disk = checked_replay(run_dir, route, planned, self.fps, self.ticks_per_second)
        try:
            trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise pixel.PixelError(f"no readable trace.json ({type(exc).__name__}): the sensor searches where the "
                                   f"engine's record puts the {ROLE}") from exc
        recorded = (replay.get("trace") or {}).get("sha256") if isinstance(replay.get("trace"), dict) else None
        if recorded is not None and _sha256(run_dir / "trace.json") != recorded:
            raise pixel.PixelError("trace.json on disk is not the trace the replay recorded")
        if not isinstance(trace, dict) or trace.get("physicsTicksPerSecond") != self.ticks_per_second:
            raise pixel.PixelError(f"the trace was not recorded at {self.ticks_per_second} ticks a second")
        asked = [n for n in planned if n in on_disk]
        for n in asked:
            if _sha256(on_disk[n]) != hashes[n]:
                raise pixel.PixelError(f"frame {n} on disk is not the frame the replay recorded")
        found = self._look(sensor, trace, replay, run_dir, asked) if asked else {}
        rows = []
        for n in planned:
            if n not in on_disk:
                rows.append({"frame": n, "asked": False, "note": "the replay did not capture this frame"})
                continue
            row = found.get(n)
            if row is None:
                rows.append({"frame": n, "asked": False, "note": "the trace has no tick for this frame"})
                continue
            rows.append(_row(n, row))
        summary = {status: sum(1 for r in rows if r.get("status") == status) for status in (*SEEN, *GAP_STATUSES)}
        summary["notAsked"] = sum(1 for r in rows if not r["asked"])
        run = {"run": run_dir.name, "route": {"name": str(replay["route"]["name"]), "sha256": replay["route"].get("sha256")},
               "framesProbed": planned, "frames": rows, "summary": summary}
        return {"setting": self.setting(), "run": run, "images": 0}

    def _look(self, sensor, trace: dict, replay: dict, run_dir: Path, asked: list[int]) -> dict:
        """The sensor's row for each frame in ``asked``. Frames between them are handed to ``from_replay`` as
        already done (its checkpoint argument), so only the planned frames are decoded and searched."""
        lo, hi = asked[0], asked[-1]
        foreground = self.bank["config"]["algorithm"] != sensor.ALGORITHM
        skipped = {}
        for n in range(lo, hi + 1):
            if n not in asked:
                row = dict(status="unavailable", reason="not planned", predictedBox=None, searchBox=None, rawBox=None,
                           score=None, templateFrame=None, scale=None)
                if foreground:
                    row["components"] = None
                skipped[n] = {"frame": n, "objects": {ROLE: []}, "sensor": {ROLE: row}}
        spec = {"objects": {ROLE: {"prompt": ROLE}}, "window": {"fromFrame": lo, "toFrame": hi}}
        try:
            doc = sensor.from_replay(trace, replay_sha256=_sha256(run_dir / "replay.json"), frames_dir=run_dir / "frames",
                                     bank=self.bank, spec=spec, fps=self.fps, completed=skipped)
        except (sensor.SensorError, OSError, ValueError, KeyError, TypeError) as exc:
            raise pixel.PixelError(f"the template sensor could not look: {' '.join(str(exc).split())[:200]}") from exc
        return {f["frame"]: f["sensor"][ROLE] for f in doc["frames"] if f["frame"] in asked}


def _row(n: int, row: dict) -> dict:
    """One planned frame's row, in the shape pixel.py ``observations`` reads, from the sensor's own row."""
    status = row["status"]
    if status in GAP_STATUSES:
        return {"frame": n, "asked": False, "status": status, "note": f"{status}: {row.get('reason')}"[:200]}
    if status not in SEEN:
        raise pixel.PixelError(f"the template sensor gave frame {n} a status it does not define: {str(status)[:40]}")
    out = {"frame": n, "asked": True, "status": status, "promptBox": row["predictedBox"], "score": row["score"]}
    if status == "not-found":
        out.update(box=None, absent=True)
    else:
        out.update(box=list(row["rawBox"]), holdsPoint=status == "matched")
    return out
