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

**Objects the game has many of** (``objects``: the enemy and the bullet; pixel.py ``named``). When the bank
holds a role's templates and its calibration on the validation replay is ``met``
(``calibration.objects``, agents/template_foreground.py ``calibrate_routes``), the observer is pointed at
every one of them the engine logged on screen, each at its own logged box (agents/template_observations.py
``object_predictions``), and the run carries ``objects[role]``: one row a planned frame, with one entry a
box in the shape pixel.py ``named_observations`` reads. An object wholly off screen is counted in
``outside``, not judged; one partly on screen is a gap for that box (``out-of-frame``); more than
pixel.MAX_BOXES on screen is a frame not asked about. A role the bank has no templates for, or whose
calibration is not ``met``, is refused, so its checks are not run, never passed.

**What it cannot tell** is declared in pixel.py ``OBSERVERS["visual-sensor"]`` and refused when a check is
proposed: the ground and a label's text (the sensor discards colour semantics and reads no text,
docs/template-sensor.md), the coin (the engine logs no box for it), and ``reaches`` (it looks for one object
near the place the engine puts it).

**The bullet** is witnessed by its rings, not its templates (agents/template_radial.py; ``RADIAL_OBJECTS``
below): it turns as it flies, so no template matched it pixel for pixel. When the bank holds its witness
(``radialWitnesses.bullet``) and that witness's validation is ``met``, each bullet on screen is looked for along
the path the engine logged for it in the frame (two ticks back to the frame's tick, all through the frame's
camera: the game interpolates bodies, so it is drawn behind its logged box), with the same row shape as the
enemy's. A bullet in the last part of its life, which the game fades out, is a gap.

**Which way the enemy faces** (``faces-motion``). The bank keeps every template mirrored as well, so an enemy
drawn facing backwards is still ``matched`` and ``visible`` cannot see ``enemy-walks-backwards``. When the
bank's facing validation is ``met`` (``calibration.objects.enemy.facing``; agents/template_foreground.py
``_validate_facing``), each enemy box row also carries ``motion``, the way the engine moves that enemy
(agents/template_observations.py ``object_motion``: from its own logged box on the ticks either side), and,
for a box ``matched`` while it moves one way, ``facing``: the heading (``right`` or ``left``) whose labelled
templates match it better by the bank's margin, or None when the sensor cannot tell, with both scores. The
run lists the roles it tells the facing of (``facing``); pixel.py ``named_observations`` reads a
faces-motion check from these and nothing else, and a run that does not list the role is a gap.

The proposer is offered this observer when the propose step is told it will judge the run (pixel.py
``proposed``; expectrail/jit/intent.py ``observer``), and the command line builds it (``run --observer
visual-sensor --sensor-bank BANK``). jit.yml passes it when its ``observer`` input is ``visual-sensor``: a
``sensor-bank`` job calibrates the bank once a run on the clean game (``calibrate_bank`` below) and the job
that replays the change judges with it. Not shown yet: this bank's false alarms on the bench's probes. The sensor's measured
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
        calibrated = self.bank.get("calibration", {}).get("objects") or {}
        # The named roles this bank can be pointed at, and why each other one cannot.
        self.named, self.refused = (), {}
        foreground = self.bank["config"]["algorithm"] != sensor.ALGORITHM
        self.witnesses = self.bank.get("radialWitnesses") or {}
        for role in pixel.OBSERVERS[NAME]["boxes"]:
            if not foreground:
                # Only an approved-art bank's reader checks a named object's calibration record.
                self.refused[role] = "its bank is not an approved-art foreground bank"
            elif role not in roles and role not in self.witnesses:
                self.refused[role] = "its bank holds no template of it"
            elif (calibrated.get(role) or {}).get("status") != "met":
                self.refused[role] = "its bank's calibration of it on the validation replay is not met"
            else:
                self.named += (role,)
        # The named roles whose facing the bank's validation backs (calibration.objects.<role>.facing ``met``):
        # only for these does a box row say which way the object faces (``facing``), so ``faces-motion`` can be
        # judged; for any other the run says nothing about facing, and a faces-motion check is a gap.
        self.facing = tuple(role for role in self.named
                            if ((calibrated.get(role) or {}).get("facing") or {}).get("status") == "met")
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

    def most_images(self, route: dict, objects=(), player: bool = True, windows=None) -> int:
        """Nothing is sent anywhere, so a replay takes no images and the budget reserves nothing for it."""
        self._roles(objects, player)
        return 0

    def _roles(self, objects, player) -> tuple[str, ...]:
        objects = tuple(objects)
        if not isinstance(player, bool):
            raise pixel.PixelError("whether the player is asked about is true or false")
        if len(set(objects)) != len(objects):
            raise pixel.PixelError("each named object is asked about once")
        for role in objects:
            if role not in self.named:
                why = self.refused.get(role, "the engine logs no box for it")
                raise pixel.PixelError(f"{NAME} is not pointed at the boxes of {str(role)[:40]}: {why}")
        if not player and not objects:
            raise pixel.PixelError(f"{NAME} would be asked about nothing: neither the {ROLE} nor a named object")
        return objects

    def __call__(self, run_dir, route: dict, objects=(), player: bool = True, windows=None) -> dict:
        from agents import template_observations as sensor

        objects = self._roles(objects, player)
        run_dir = Path(run_dir)
        # Only the planned frames inside the checks' windows are looked at (#605; pixel.py ``planned``).
        planned = pixel.planned(self, route, windows)
        if not planned:
            raise pixel.PixelError("the checks' windows hold no frame this observer would be asked about")
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
        found = self._look(sensor, trace, replay, run_dir, asked) if asked and player else {}
        rows = []
        for n in planned:
            if n not in on_disk:
                rows.append({"frame": n, "asked": False, "note": "the replay did not capture this frame"})
                continue
            if not player:
                rows.append({"frame": n, "asked": False, "note": pixel.NOT_ASKED_PLAYER})
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
        if objects:
            run["objects"] = {role: self._look_named(sensor, role, trace, planned, on_disk) for role in objects}
            run["facing"] = [role for role in objects if role in self.facing]
        return {"setting": self.setting(), "run": run, "images": 0}

    def _look_named(self, sensor, role: str, trace: dict, planned: list[int], on_disk: dict) -> list[dict]:
        """One row a planned frame about every ``role`` object the engine logged: see the module docstring."""
        if role in self.witnesses:
            return self._look_radial(sensor, role, trace, planned, on_disk)
        foreground = self.bank["config"]["algorithm"] != sensor.ALGORITHM
        matcher = sensor.matchers_for(self.bank, [role])[role]
        headings = moves = None
        try:
            where = sensor.object_predictions(trace, [n for n in planned if n in on_disk], role, self.fps)
            if role in self.facing:
                from agents import template_foreground

                headings = template_foreground.heading_matchers(
                    [t for t in self.bank["templates"] if t["object"] == role], self.bank["config"])
                moves = sensor.object_motion(trace, [n for n in planned if n in on_disk], role, self.fps)
        except sensor.SensorError as exc:
            raise pixel.PixelError(f"the engine's boxes of {role} cannot be read: {exc}") from exc
        rows = []
        for n in planned:
            if n not in on_disk:
                rows.append({"frame": n, "asked": False, "note": "the replay did not capture this frame"})
                continue
            logged = where.get(n)
            if logged is None:
                rows.append({"frame": n, "asked": False,
                             "note": f"the engine's record gives no boxes of {role} for this frame"})
                continue
            try:
                image = sensor._image(on_disk[n], mode="RGB" if foreground else "L")
            except (OSError, ValueError) as exc:
                rows.append({"frame": n, "asked": False, "note": f"frame unavailable ({type(exc).__name__})"})
                continue
            shown, outside = [], 0
            for ident, box in logged:
                if box[2] <= 0 or box[3] <= 0 or box[0] >= image.width or box[1] >= image.height:
                    outside += 1
                else:
                    shown.append((ident, box))
            if len(shown) > pixel.MAX_BOXES:
                rows.append({"frame": n, "asked": False, "outside": outside,
                             "note": f"{len(shown)} on screen, more than the {pixel.MAX_BOXES} asked about"})
                continue
            boxes = []
            for ident, box in shown:
                try:
                    row = sensor.look(matcher, image, box, self.bank["config"], foreground)
                except (sensor.SensorError, ValueError, KeyError, TypeError) as exc:
                    raise pixel.PixelError(f"the template sensor could not look at {role} {ident} in frame {n}: "
                                           f"{' '.join(str(exc).split())[:160]}") from exc
                entry = {"id": ident, **_box_row(row)}
                if moves is not None:
                    entry.update(self._facing(role, headings, image, box, (moves.get(n) or {}).get(ident), row["status"]))
                boxes.append(entry)
            rows.append({"frame": n, "asked": True, "boxes": boxes, "outside": outside})
        return rows

    def _look_radial(self, sensor, role: str, trace: dict, planned: list[int], on_disk: dict) -> list[dict]:
        """``_look_named`` for a role witnessed by its rings (agents/template_radial.py): each logged object is
        looked for along the path the engine logged for it in the frame, not at one box. The rows have the same
        shape; ``promptBox`` is its box on the frame's tick."""
        import numpy as np

        from agents import template_radial as radial

        witness = self.witnesses[role]
        try:
            where = radial.paths(trace, [n for n in planned if n in on_disk], role, self.fps, witness["pathTicks"])
            # Every other object the engine logged in each frame (the player and the other roles): one within the
            # witness's clearance of a path means that box is not judged (agents/template_radial.py ``crowded``).
            others = radial._others(trace, [n for n in planned if n in on_disk], self.fps, role)
        except sensor.SensorError as exc:
            raise pixel.PixelError(f"the engine's boxes of {role} cannot be read: {exc}") from exc
        rows = []
        for n in planned:
            if n not in on_disk:
                rows.append({"frame": n, "asked": False, "note": "the replay did not capture this frame"})
                continue
            logged = where.get(n)
            if logged is None:
                rows.append({"frame": n, "asked": False,
                             "note": f"the engine's record gives no boxes of {role} for this frame"})
                continue
            if logged and others[n] is None:
                rows.append({"frame": n, "asked": False,
                             "note": f"the engine's record cannot say what else is beside each {role} in this frame"})
                continue
            try:
                image = sensor._image(on_disk[n], mode="RGB")
            except (OSError, ValueError) as exc:
                rows.append({"frame": n, "asked": False, "note": f"frame unavailable ({type(exc).__name__})"})
                continue
            shown, outside = [], 0
            for ident, before, now, age in logged:
                if now[2] <= 0 or now[3] <= 0 or now[0] >= image.width or now[1] >= image.height:
                    outside += 1
                else:
                    shown.append((ident, before, now, age))
            if len(shown) > pixel.MAX_BOXES:
                rows.append({"frame": n, "asked": False, "outside": outside,
                             "note": f"{len(shown)} on screen, more than the {pixel.MAX_BOXES} asked about"})
                continue
            rgb = np.asarray(image)
            boxes = []
            for ident, before, now, age in shown:
                try:
                    row = radial.look(witness, rgb, before, now, age,
                                      others=radial._neighbours(logged, ident, others[n]))
                except (sensor.SensorError, ValueError, KeyError, TypeError) as exc:
                    raise pixel.PixelError(f"the radial witness could not look at {role} {ident} in frame {n}: "
                                           f"{' '.join(str(exc).split())[:160]}") from exc
                boxes.append({"id": ident, **_box_row(row)})
            rows.append({"frame": n, "asked": True, "boxes": boxes, "outside": outside})
        return rows

    def _facing(self, role, headings, image, box, motion, status) -> dict:
        """What a box row says about facing: the engine's ``motion`` always, and, for an object matched where
        the engine puts it while it moves one way, which way it is drawn facing (``facing``: ``right``,
        ``left``, or None when the sensor cannot tell) with each heading's score."""
        from agents import template_foreground
        from agents import template_observations as sensor

        out = {"motion": motion}
        if status != "matched" or motion not in sensor.HEADINGS:
            return out
        if headings is None:
            return {**out, "facing": None, "facingScores": None}
        try:
            margin = self.bank["calibration"]["objects"][role]["facing"]["margin"]
            decided = template_foreground.facing(headings, image, box, self.bank["config"], margin)
        except (sensor.SensorError, ValueError, KeyError, TypeError) as exc:
            raise pixel.PixelError(f"the template sensor could not tell which way an object faces: "
                                   f"{' '.join(str(exc).split())[:160]}") from exc
        return {**out, "facing": decided["facing"], "facingScores": decided["scores"]}

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


def _box_row(row: dict) -> dict:
    """One named object's box in one frame, in the shape pixel.py ``named_observations`` reads."""
    status = row["status"]
    out = {"status": status, "promptBox": row["predictedBox"], "score": row["score"]}
    if status in GAP_STATUSES:
        return {**out, "box": None, "error": f"{status}: {row.get('reason')}"[:200]}
    if status not in SEEN:
        raise pixel.PixelError(f"the template sensor gave a status it does not define: {str(status)[:40]}")
    if status == "not-found":
        return {**out, "box": None, "absent": True}
    return {**out, "box": list(row["rawBox"]), "holdsPoint": status == "matched"}


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


# The bank jit.yml calibrates for this observer (#286): the bundled game's player, from its clean art and four
# dedicated clean routes (agents/template_sensor_bench.py ``calibration_routes``: three to calibrate from, a
# fourth, separate, to validate the threshold), with the pose catalogue the published measurement used
# (docs/template-sensor.md). The same recipe as that measurement, so its clean false-alarm figures describe
# this bank's algorithm and settings; they are not a measurement of this bank on the bench's probes.
BANK_ART = {ROLE: "player/robot.webp", "enemy": "enemy/enemy.webp"}
# The named roles calibrated beside the player by their templates, each from the boxes the engine logs for it.
BANK_OBJECTS = ("enemy",)
# The named roles witnessed by their rings instead (agents/template_radial.py): the bullet, which turns as it
# flies, is drawn under an additive glow and fades out, so its templates never matched it pixel for pixel.
# - "art": its approved art, which locates it on trusted clean frames only.
# - "side": the sprite as drawn, in frame pixels: its 16 x 16 art at the capture's 2x (the window is 1600 x 960
#   for an 800 x 480 viewport), the same size as its logged collision box (a circle of radius 8).
# - "fadesAfterTicks": its Timer (the default 1 s, 120 ticks at the game's 120 a second) calls destroy, which
#   fades the sprite out over 0.3 s (game/platformer/player/bullet.tscn); from then on a box is a gap.
# - "clearPx": how far another bullet's box must stay from the area searched along a bullet's path for the bullet to
#   be judged; any other logged box (the player, an enemy) must not touch that area at all. 0: measured on the
#   calibration replays on November 19, a clean bullet whose searched area touched no other logged box had rings
#   within 2.5 of a profile (the limit is 12) at every gap, down to 0 to 3 pixels; one overlapping another bullet
#   reached 14.3. Its Glow (additive, alpha 0.25) reaches about 27 frame pixels beyond its box, but is too faint
#   there to move the rings (docs/new-work/2026-11-19-sensor-bullet.md).
RADIAL_OBJECTS = {"bullet": {"art": "player/bullet.webp", "side": 32, "fadesAfterTicks": 120, "clearPx": 0}}
BANK_CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "template-foreground-catalogue.json"
CLEAN_GAME = Path(__file__).resolve().parents[2] / "game" / "platformer"


def calibrate_bank(out, work, *, game=None, godot=None, run_replay=None) -> dict:
    """Calibrate the ``visual-sensor`` bank on the pinned clean game and write it to ``out``; return a summary.

    Only the clean game is replayed, with no patch: no bug build, candidate or measured route reaches the bank
    (agents/template_foreground.py ``calibrate_routes`` refuses a patched or other-tree replay). ``work`` holds
    the routes and the replays and must not exist yet; ``out`` must not exist either, so a bank is never
    overwritten or silently recalibrated. ``run_replay`` stands in for harness/run.py ``run`` in tests.
    """
    from agents import template_foreground as foreground
    from agents import template_observations as sensor
    from agents.template_sensor_bench import atomic_json, calibration_routes
    from harness import run as harness

    out, work = Path(out), Path(work)
    game = Path(game or CLEAN_GAME).resolve()
    if out.exists():
        raise ValueError(f"{out} exists: a bank is never overwritten; name a new file")
    if work.exists():
        raise ValueError(f"{work} exists: the calibration replays go in a new folder")
    if work.resolve() == game or game in work.resolve().parents or game in out.resolve().parents:
        raise ValueError("the calibration's files go outside the clean game")
    runner = run_replay or harness.run
    clean_tree = harness.tree_digest(game)
    replays = []
    for route in calibration_routes():
        path = work / "routes" / f"{route['name']}.json"
        atomic_json(path, route)
        target = work / route["name"]
        runner(path, target, game=game, godot=godot, patches=[], capture_frames=True)
        replays.append(target)
    try:
        bank = foreground.calibrate_routes(replays[:-1], replays[-1], clean_game=game, clean_tree=clean_tree,
                                           art=dict(BANK_ART), catalogue=BANK_CATALOGUE, objects=BANK_OBJECTS)
        bank = sensor.load_bank(add_radial(bank, replays[:-1], replays[-1], game=game, clean_tree=clean_tree))
    except (sensor.SensorError, OSError, ValueError, KeyError) as exc:
        raise ValueError(f"calibration failed: {' '.join(str(exc).split())[:200]}") from exc
    if ROLE not in {t["object"] for t in bank["templates"]}:
        raise ValueError(f"calibration produced no template of the {ROLE}")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    temporary.write_text(json.dumps(bank, indent=2) + "\n", encoding="utf-8")
    temporary.replace(out)
    named = bank["calibration"].get("objects") or {}
    return {"bank": str(out), "bankSha256": digest(bank), "algorithm": bank["config"]["algorithm"],
            "templates": len(bank["templates"]), "cleanTree": clean_tree,
            "objects": {role: {"templates": named[role]["templates"], "status": named[role]["status"]} for role in named},
            "routes": [r.name for r in replays[:-1]], "validation": replays[-1].name}


def add_radial(bank: dict, clean_runs, validation_run, *, game, clean_tree, objects=None) -> dict:
    """``bank`` with a radial witness for each role in ``objects`` (default RADIAL_OBJECTS), calibrated from the
    same clean replays and validated on the same separate clean replay (agents/template_radial.py ``calibrate``).
    The art is read from the pinned clean game only (template_foreground.py ``art_sources`` checks the tree)."""
    import numpy as np

    from agents import template_foreground as foreground
    from agents import template_observations as sensor
    from agents import template_radial as radial

    Image, _, _ = sensor.imaging()
    out = dict(bank)
    out["calibration"] = dict(bank["calibration"])
    out["calibration"]["objects"] = dict(bank["calibration"].get("objects") or {})
    witnesses = dict(bank.get("radialWitnesses") or {})
    for role, recipe in (RADIAL_OBJECTS if objects is None else objects).items():
        source = foreground.art_sources(game, {role: recipe["art"]}, clean_tree)[0]
        with Image.open(Path(game) / recipe["art"]) as image:
            rgba = np.asarray(image.convert("RGBA"))
        witness, counts = radial.calibrate(clean_runs, validation_run, role=role, art_rgba=rgba,
                                           art={"path": source["path"], "sha256": source["sha256"]},
                                           side=recipe["side"], fades=recipe["fadesAfterTicks"],
                                           clear=recipe["clearPx"], clean_tree=clean_tree)
        if not witness["profiles"]:
            # No clean frame located the sprite: there is nothing to witness it with. The role is left out, so
            # the observer refuses it ("its bank holds no template of it").
            continue
        witnesses[role] = witness
        out["calibration"]["objects"][role] = counts
    if witnesses:
        out["radialWitnesses"] = witnesses
    return out

