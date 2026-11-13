"""The player's place, asked of the vision model, on the base and the head (issue #327, decision B).

The gate replays the base and the head on the same routes. For each route this asks the vision model
what is drawn inside the player's own collision box (the trace's ``body``, widened a little) in
sampled frames of both replays, and compares each frame of the head with the same frame of the base
where the engine has the player in the same place (``agents.anchor_rule.pair_frame``).

What it may do to a decision, and nothing more (Sean's decision B on #327, November 12, 2026):

- A frame where the two differ (``out``: a different size, the box no longer holding the player's
  point, or the model's confidence falling by more than ``drop``) makes an accept needs-review, with
  the two frames kept side by side under ``anchor/`` in the artifact. It does not reject until blind
  test 4 has given this check a false-alarm rate.
- A frame the model was asked about and gave no answer for makes an accept needs-review too: an
  observer that was asked and did not answer is never read as agreement.
- A frame where the engine moved the player, where the base has no box, or that was not asked about
  says nothing. Nothing here can make a decision accept, and nothing here turns a reject into
  anything else: the accept still needs the checks and the visual observer's evidence on them.

Measured on the bundled game only (docs/sam.md, runs 43337979278 and 43351238364): no false alarm in
26 harmless pairs, and every compared frame of sinking v2 and 8 of 13 of layering differ. That is one
game; the false-alarm rate on any other is not known, which is why a difference is needs-review.

Every frame asked about is a paid image: ``every`` decides how many (by default every tenth captured
frame of a route and its last, on each side: 26 images for the bundled game's 120-frame routes).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from agents import anchor_rule
from agents.sam_anchor import BODY, DEFAULT_PAD, STOP_KINDS, anchors, measure

FORMAT = "expectrail.anchor/v0"
DEFAULT_EVERY = 10   # the same as expectrail.gate.verify.ANCHOR_EVERY
MAX_KEPT = 8        # differing frames whose pictures are kept per route
MAX_LISTED = 32     # frames listed per route in the record
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
STATES = ("in", "out", "moved", "no-base", "no-answer", "not-asked")


class Stop(RuntimeError):
    """The model stopped answering for a reason the next frame would meet too (no key, no credit,
    the spend cap, the network). The routes after it are not asked."""


def _frames(run: dict) -> dict[int, Path]:
    from agents.sam_observations import frame_files

    folder = run.get("framesDir")
    return frame_files(Path(folder)) if folder and Path(folder).is_dir() else {}


def _ask(run: dict, chosen: list[int], frames: dict[int, Path], client, pad: float) -> list[dict]:
    """One row per chosen frame, as agents.sam_anchor.probe_run writes them, from a run held in memory."""
    from agents.sam_observations import SamError, png_size

    size = png_size(frames[chosen[0]])
    where = anchors(run.get("trace") or {}, size, chosen, box=BODY, pad=pad)
    rows = []
    for n in chosen:
        anchor = where[n]
        if "why" in anchor:
            rows.append({"frame": n, "asked": False, "note": anchor["why"],
                         **{k: anchor[k] for k in ("world", "point") if k in anchor}})
            continue
        try:
            answer = client.segment_in(frames[n], [tuple(anchor["promptBox"])])[0]
        except SamError as exc:
            if exc.kind in STOP_KINDS or exc.status is not None:
                raise Stop(exc.kind or f"HTTP {exc.status}") from exc
            rows.append({"frame": n, "world": anchor["world"], "point": anchor["point"], "asked": True,
                         "box": None, "score": None, "error": "the answer could not be read"})
            continue
        rows.append({"frame": n, **measure(anchor, answer, png_size(frames[n]))})
    return rows


def compare(route: str, base: dict, head: dict, client, *, every: int = DEFAULT_EVERY, pad: float = DEFAULT_PAD,
            tolerance: float = anchor_rule.DEFAULT_TOLERANCE, drop: float = anchor_rule.DEFAULT_DROP) -> dict:
    """One route's row: the head's sampled frames against the base's, asked of ``client``.

    ``base`` and ``head`` are finished replays as the gate holds them (``trace``, ``framesDir``).
    Raises Stop when the model stops for a reason the next frame would meet as well."""
    from agents.sam_observations import sample

    row = {"route": route, **{_key(s): 0 for s in STATES}, "frames": [], "kept": []}
    b_frames, h_frames = _frames(base), _frames(head)
    common = sorted(set(b_frames) & set(h_frames))
    if not common:
        return {**row, "result": "silent", "reason": "the two replays have no captured frame in common"}
    chosen = sample(common, every)
    base_rows = {r["frame"]: r for r in _ask(base, chosen, b_frames, client, pad)}
    head_rows = _ask(head, chosen, h_frames, client, pad)
    judged = [anchor_rule.pair_frame(base_rows.get(r["frame"]), r, tolerance, drop) for r in head_rows]
    for one in judged:
        row[_key(one["state"])] += 1
    row["frames"] = [{"frame": f["frame"], "state": f["state"], "why": [w[:160] for w in f["why"]][:6]}
                     for f in judged if f["state"] != "in"][:MAX_LISTED]
    row["kept"] = [f["frame"] for f in judged if f["state"] == "out"][:MAX_KEPT]
    first = next((f for f in judged if f["state"] == "out"), None)
    if first is not None:
        row["result"] = "differ"
        row["reason"] = (f"{row['out']} of {row['in'] + row['out']} compared frames show something different at "
                         f"the player's place than the unchanged game, first frame {first['frame']}: "
                         f"{'; '.join(first['why'])}")[:300]
    elif row["noAnswer"]:
        row["result"] = "no-answer"
        row["reason"] = f"the vision model gave no answer for {row['noAnswer']} of {len(judged)} frames"
    elif row["in"]:
        row["result"] = "agree"
        row["reason"] = f"{row['in']} compared frames agree with the unchanged game"
    else:
        row["result"] = "silent"
        row["reason"] = "no frame could be compared (the engine moved the player, or nothing was asked)"
    row["_pictures"] = {n: (b_frames[n], h_frames[n]) for n in row["kept"]}
    return row


def _key(state: str) -> str:
    return {"no-base": "noBase", "no-answer": "noAnswer", "not-asked": "notAsked"}.get(state, state)


def block(pairs: list[tuple[str, dict, dict]], client, observer: dict | None, *, every: int = DEFAULT_EVERY,
          pad: float = DEFAULT_PAD) -> dict:
    """The record's ``anchor`` block for every route replayed on both sides.

    ``pairs`` is (route name, base replay, head replay). ``client`` answers ``segment_in``; with no
    client nothing is asked and the block says so. Anything that stops the asking leaves the routes
    not yet asked as not asked, and the block says why."""
    out = {"format": FORMAT, "observer": observer, "box": BODY, "pad": pad, "every": every,
           "tolerance": anchor_rule.DEFAULT_TOLERANCE, "drop": anchor_rule.DEFAULT_DROP,
           "status": "asked", "stopped": None, "routes": []}
    if client is None:
        return {**out, "status": "not-asked", "stopped": "no vision model that answers box prompts was given"}
    for route, base, head in pairs:
        try:
            out["routes"].append(compare(route, base, head, client, every=every, pad=pad))
        except Stop as exc:
            out["status"], out["stopped"] = "stopped", f"the vision model stopped ({str(exc)[:60]})"
            break
        except Exception as exc:  # noqa: BLE001 - a run this cannot read is a route that was not compared
            out["routes"].append({"route": route, **{_key(s): 0 for s in STATES}, "frames": [], "kept": [],
                                  "result": "no-answer", "reason": f"the route could not be asked about ({type(exc).__name__})"})
    return out


def effect(anchor: dict | None) -> str | None:
    """Why an accept is not an accept, by decision B (the reader's rule, ``record.anchor_effect``)."""
    from expectrail.gate.record import anchor_effect

    return anchor_effect(anchor)


def keep_pictures(anchor: dict, out: Path) -> dict:
    """Copy the frames that differ into ``out/anchor/<route>/`` as base-NNNNNN.png and head-NNNNNN.png, and
    return the block as the record holds it (without the in-memory picture paths)."""
    clean = {k: v for k, v in anchor.items() if k != "routes"}
    clean["routes"] = []
    for row in anchor.get("routes", []):
        pictures = row.get("_pictures") or {}
        if not SAFE_NAME.fullmatch(row["route"]):
            pictures = {}   # a route name that is not a plain file name gets no folder of its own
        for n, (before, after) in pictures.items():
            folder = out / "anchor" / row["route"]
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before, folder / f"base-{n:06d}.png")
            shutil.copyfile(after, folder / f"head-{n:06d}.png")
        clean["routes"].append({k: v for k, v in row.items() if k != "_pictures"})
    return clean
