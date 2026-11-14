"""SAM 3.1 as the observer the replay asks about pixel checks (#286).

``run.generate(..., observer=...)`` asks an observer about every pixel replay (expectrail/jit/pixel.py,
``observe``). ``SamAnchorObserver`` is that observer for ``sam-3.1-anchor``: on each replay it asks SAM
3.1 what is drawn inside the player's box at the place the engine's record puts the player, one image a
planned frame, with agents/sam_anchor.py doing the asking and the measuring (``anchors``, ``measure``).

**Asked with the engine's body box by default.** The box is the player's own collision box as the
harness logged it on that tick (the trace's ``body``), widened by ``pad`` game pixels each way. Nothing
about the player's size is typed in. A sized box (``box=(w, h)`` with ``lift``) is the setting SAM was
recorded with on the bundled game (tests/data/sam-anchor/), kept so those answers can be replayed.

**The frames line up with the replay's own, or nothing is judged.** The frames to ask about are planned
from the route alone (``frames``), before any replay, so the budget can be reserved for them. On each
replay the observer then checks, before it asks anything:

- the replay is of the route the check names (replay.json's ``route.name``);
- it was captured at the frame rate and physics rate the frames were planned at, so frame ``n`` shows the
  tick the plan says (agents/observations.py, ``_frame_tick``);
- the frames on disk are the replay's: numbered from 0 without a hole, as many as replay.json counts, and
  each frame asked about has the digest replay.json gives it.

Any of these failing is a ``PixelError``: the checks on that probe are dropped with the reason, never
passed. A planned frame the replay did not capture (the game ended sooner than the route), or one where
the engine logged no player, camera or body box, or where the player is outside the picture, is not
asked about: it is a gap, and a check over a gap is ``needs-review`` (pixel.py, ``observations``).

**What is charged.** Every request the client makes is one image, retries included (the client counts
them in ``calls``); ``images`` is that count for the replay. When the observer stops part way, the images
already sent ride on the error (``PixelError.images``) and the replay charges them too.

**Recorded answers.** ``RecordedSamClient`` answers as SAM answered once, from an agents/sam_anchor.py
answer file. It answers only the question SAM was asked: a frame it was not asked about, or a different
box, stops the run. So a recorded replay shows the observer asks exactly what SAM was asked, and judges
what SAM said, with no call. Its setting must be the observer's.

What this is not, yet: the command line and jit.yml do not build this observer, and no live SAM call has
been made on a bench probe. Nothing here sends a request unless it is given a client that does
(agents.sam_observations.MetaSamClient, which needs a key and EXPECTRAIL_SAM_USD_CAP).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from agents.sam_anchor import BODY, DEFAULT_PAD, STOP_KINDS, anchors, load_trace, measure, summarise
from agents.sam_observations import SamError, frame_files, png_size, sample
from expectrail.jit import pixel

NAME = "sam-3.1-anchor"
DEFAULT_EVERY = 10
DEFAULT_FPS = 60
DEFAULT_TICKS_PER_SECOND = 120
MAX_FRAMES = 30   # images a replay at most: 30 x 9 runs x $0.0025 = $0.675 a probe at list price


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SamAnchorObserver:
    """The ``sam-3.1-anchor`` observer for ``run.generate``: see the module docstring."""

    name = NAME

    def __init__(self, client=None, *, box=BODY, pad: float = DEFAULT_PAD, lift: float = 0.0,
                 every: int = DEFAULT_EVERY, first: int | None = None, max_frames: int = MAX_FRAMES,
                 fps: int = DEFAULT_FPS, ticks_per_second: int = DEFAULT_TICKS_PER_SECOND):
        if box == BODY:
            if lift:
                raise ValueError("lift moves a point; the body box has its own middle")
            if not (isinstance(pad, (int, float)) and 0 <= pad < 1000):
                raise ValueError("pad is a number of game pixels, 0 or more")
        else:
            try:
                w, h = (float(v) for v in box)
            except (TypeError, ValueError):
                raise ValueError("box is 'body' or a (width, height) in game pixels") from None
            if not (0 < w < 10000 and 0 < h < 10000):
                raise ValueError("box is 'body' or a (width, height) in game pixels")
            box = (w, h)
        for label, value in (("every", every), ("max_frames", max_frames), ("fps", fps),
                             ("ticks_per_second", ticks_per_second)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{label} is a whole number, 1 or more")
        if first is not None and (not isinstance(first, int) or isinstance(first, bool) or first < 1):
            raise ValueError("first is a whole number of frames, 1 or more")
        if max_frames < 2:
            raise ValueError("max_frames is 2 or more: the first frame and the last")
        self.box, self.pad, self.lift = box, float(pad), float(lift)
        self.every, self.first, self.max_frames = every, first, max_frames
        self.fps, self.ticks_per_second = fps, ticks_per_second
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from agents.sam_observations import MetaSamClient
            self._client = MetaSamClient()
        return self._client

    @property
    def step(self) -> int:
        return max(self.ticks_per_second // self.fps, 1)

    def setting(self) -> dict:
        """How SAM is asked, as pixel.setting_of reads an answer file: two runs are compared only under one."""
        doc = {"model": self.client.model, "lift": self.lift,
               "box": BODY if self.box == BODY else list(self.box)}
        if self.box == BODY:
            doc["pad"] = self.pad
        return pixel.setting_of(doc)

    def frames(self, route: dict) -> list[int]:
        """The frames asked about on a replay of ``route``, from the route alone: every ``every``-th frame
        and the last one the route's ticks fill, within ``first``, at most ``max_frames``."""
        ticks = route.get("ticks") if isinstance(route, dict) else None
        if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < 1:
            raise pixel.PixelError("the route does not say how many ticks it runs")
        last = (ticks - self.step) // self.step   # the last frame n whose tick n*step+step-1 is in the route
        if last < 0:
            return []
        if self.first is not None:
            last = min(last, self.first - 1)
        every = max(self.every, math.ceil(last / (self.max_frames - 1)) if last else 1)
        picked = sample(list(range(last + 1)), every)
        return picked if len(picked) <= self.max_frames else [*picked[:self.max_frames - 1], last]

    def __call__(self, run_dir, route: dict) -> dict:
        run_dir = Path(run_dir)
        setting = self.setting()
        recorded = getattr(self.client, "setting", None)
        if recorded is not None and recorded != setting:
            raise pixel.PixelError(f"the recorded answers were asked with {json.dumps(recorded, sort_keys=True)}, "
                                   f"and this observer asks with {json.dumps(setting, sort_keys=True)}")
        try:
            replay = json.loads((run_dir / "replay.json").read_text(encoding="utf-8"))
            replayed = str(replay["route"]["name"])
            capture = replay.get("capture") or {}
            hashes = list(replay["frameSha256"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise pixel.PixelError(f"no readable replay.json with the route and the frames' digests "
                                   f"({type(exc).__name__})") from exc
        if replayed != route.get("name"):
            raise pixel.PixelError(f"the replay is of {replayed[:60]!r}, and the frames were planned for "
                                   f"{str(route.get('name'))[:60]!r}")
        if capture.get("fps") != self.fps or capture.get("physicsTicksPerSecond") != self.ticks_per_second:
            raise pixel.PixelError(f"the frames were planned at {self.fps} fps and {self.ticks_per_second} ticks a "
                                   f"second, and the replay was captured at {capture.get('fps')} fps and "
                                   f"{capture.get('physicsTicksPerSecond')} ticks a second")
        on_disk = frame_files(run_dir / "frames")
        if not on_disk:
            raise pixel.PixelError("the replay captured no frames")
        if list(on_disk) != list(range(len(on_disk))) or len(hashes) != len(on_disk) \
                or capture.get("frames") != len(on_disk):
            raise pixel.PixelError(f"the frames on disk ({len(on_disk)}) are not the replay's "
                                   f"({capture.get('frames')} counted, {len(hashes)} digests)")
        try:
            trace = load_trace(run_dir)
            size = png_size(on_disk[0])
        except SamError as exc:
            raise pixel.PixelError(str(exc)[:200]) from exc
        planned = self.frames(route)
        where = anchors(trace, size, [n for n in planned if n in on_disk], self.lift, fps=self.fps,
                        box=self.box, pad=self.pad)
        client = self.client
        before = client.calls
        rows = []
        for n in planned:
            if n not in on_disk:
                rows.append({"frame": n, "asked": False, "note": "the replay did not capture this frame"})
                continue
            if _sha256(on_disk[n]) != hashes[n]:
                raise self._stop(f"frame {n} on disk is not the frame the replay recorded", client, before)
            anchor = where[n]
            if "why" in anchor:
                rows.append({"frame": n, "asked": False, "note": anchor["why"],
                             **{k: anchor[k] for k in ("world", "point") if k in anchor}})
                continue
            try:
                if png_size(on_disk[n]) != size:
                    raise self._stop(f"frame {n} is not the size of frame 0", client, before)
                answer = client.segment_in(on_disk[n], [tuple(anchor["promptBox"])])[0]
            except SamError as exc:
                if exc.kind in STOP_KINDS or exc.status is not None:
                    raise self._stop(f"SAM stopped at frame {n}: {exc}", client, before) from exc
                rows.append({"frame": n, "world": anchor["world"], "point": anchor["point"], "asked": True,
                             "box": None, "score": None, "promptBox": anchor["promptBox"],
                             "error": " ".join(str(exc).split())[:300]})
                continue
            rows.append({"frame": n, **measure(anchor, answer, size)})
        run = {"run": run_dir.name, "route": {"name": replayed, "sha256": replay["route"].get("sha256")},
               "framesProbed": planned, "frames": rows, "summary": summarise(rows)}
        return {"setting": setting, "run": run, "images": client.calls - before}

    @staticmethod
    def _stop(why: str, client, before: int) -> pixel.PixelError:
        exc = pixel.PixelError(" ".join(why.split())[:300])
        exc.images = client.calls - before
        return exc


class RecordedSamClient:
    """Answers ``segment_in`` as SAM answered once, from an agents/sam_anchor.py answer file.

    ``pick`` names the run in the file whose answers to give: a run name, or a callable from the frame's
    path to a run name (one observer judges the clean game and the bug build). A frame the recording did
    not ask about, or a box other than the one it asked with, stops the run: the recording says nothing
    about a question SAM was not asked."""

    def __init__(self, recording, pick):
        doc = json.loads(Path(recording).read_text(encoding="utf-8"))
        self.model = doc["model"]
        self.setting = pixel.setting_of(doc)
        self.runs = {str(r["run"]): {f["frame"]: f for f in r["frames"]} for r in doc["runs"]}
        self.pick = pick
        self.calls = 0
        self.seconds = 0.0

    def segment_in(self, png, boxes):
        self.calls += 1
        png = Path(png)
        name = self.pick(png) if callable(self.pick) else self.pick
        frames = self.runs.get(name)
        if frames is None:
            raise SamError(f"the recording has no run {str(name)[:40]!r}", kind="request")
        n = int(png.stem[1:])
        row = frames.get(n)
        if row is None or not row.get("asked") or row.get("promptBox") is None:
            raise SamError(f"{name} frame {n} was not asked about with a box in the recording", kind="request")
        if [list(b) for b in boxes] != [list(row["promptBox"])]:
            raise SamError(f"{name} frame {n}: asked about {[list(b) for b in boxes]}, and the recording "
                           f"answers {row['promptBox']}", kind="request")
        if row.get("error"):
            raise SamError(row["error"], kind="unreadable")
        return [None if row.get("box") is None else {"box": list(row["box"]), "score": row["score"]}]

    def segment_at(self, png, points):
        raise SamError("these recorded answers were asked with a box, not a point", kind="request")
