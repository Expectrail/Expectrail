"""Ask SAM what is drawn where the engine says the player is: a point, not words (#330).

Words did not find the player in the two outside games (November 12, 2026): "player character"
found nothing in 26 frames, and "small square" found 38 to 46 squares a frame in a level made of
squares. A point asks a different question. The engine's position log says where the player is;
the point is that place in the frame's own pixels; SAM answers with the one object drawn there.

This is a probe. It measures and decides nothing. For every probed frame it reports the box that
came back, its size in the frame and in the game's own pixels, how far it reaches above and below
the player's origin, its confidence when the service gives one, whether it holds the point it was
asked about, and how much of the frame it covers (a box the size of the level is the level, not
the player). On the bundled game's seeded bugs those numbers have known right answers.

What it leans on, said plainly: the point comes from the engine's record, so a game that lies about
where its player is sends the question to the wrong place. The pixels can only say what is drawn
at the place the engine names.

    python3 -m agents.sam_anchor --runs runs/seeded/* --every 10 --out runs/sam-anchor --dry-run
    python3 -m agents.sam_anchor --runs runs/seeded/* --every 10 --out runs/sam-anchor

One image per probed frame (13 a run at the default). EXPECTRAIL_SAM_USD_CAP must be set: nothing
is sent without it. Writes <out>/anchor.md and <out>/anchor.json, and overlays and a contact sheet
per run when Pillow is installed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path

from agents.observations import _frame_tick, _to_frame, _view_at
from agents.sam_observations import MetaSamClient, SamError, frame_files, png_size, sample, vision_backend

# A failed frame is written down and the run goes on only when the reply could not be read: that is
# what the first live run is for (the page does not say what comes back when nothing is there).
# Anything the next frame would hit as well ends the run: no key, no credit, the cap, the network,
# or an HTTP error.
STOP_KINDS = ("auth", "credit", "budget", "network", "rate-limit", "server", "request")


def load_trace(run: Path) -> dict:
    try:
        return json.loads((run / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SamError(f"{run.name}: no readable trace.json ({type(exc).__name__}); the point is the engine's "
                       "player position, so a run without its position log cannot be asked about") from exc


def anchors(trace: dict, frame_size: tuple[int, int], frames: list[int], lift: float = 0.0,
            fps: int = 60) -> dict[int, dict]:
    """Where to point in each frame: the engine's player origin, ``lift`` game pixels up, in frame pixels.

    {frame: {"world": [x, y], "point": [px, py], "scale": [sx, sy]}} for a frame that can be asked
    about, or {"why": reason} when it cannot: no row for that frame, no player in it, no camera, or
    the player is outside the picture. Timing and camera are the verifier's (_frame_tick, _view_at).
    """
    rows = list(trace.get("rows") or [])
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // fps, 1)
    width, height = frame_size
    out: dict[int, dict] = {}
    for n in frames:
        tick = _frame_tick(n, step)
        if tick >= len(rows):
            out[n] = {"why": "the position log ends before this frame"}
            continue
        player, view = rows[tick].get("player"), _view_at(rows, tick)
        if player is None:
            out[n] = {"why": "the engine logged no player"}
            continue
        if not view:
            out[n] = {"why": "the engine logged no camera"}
            continue
        wx, wy = float(player[0]), float(player[1]) - lift
        fx, fy = _to_frame(view, wx, wy)
        if not (math.isfinite(fx) and math.isfinite(fy)):
            out[n] = {"why": "the player's place in the frame is not a number", "world": [wx, wy]}
            continue
        px, py = int(math.floor(fx)), int(math.floor(fy))
        entry = {"world": [round(wx, 2), round(wy, 2)], "point": [px, py],
                 "scale": [round(math.hypot(view[0], view[1]), 4), round(math.hypot(view[2], view[3]), 4)]}
        if not (0 <= px < width and 0 <= py < height):
            entry["why"] = "the player is outside the picture"
        out[n] = entry
    return out


def measure(anchor: dict, answer: dict | None, frame_size: tuple[int, int]) -> dict:
    """One frame's row: the answer measured against the point it was asked about."""
    row = {"world": anchor["world"], "point": anchor["point"], "asked": True, "box": None, "score": None}
    if answer is None:
        row["note"] = "nothing came back for the point"
        return row
    x0, y0, x1, y1 = answer["box"]
    px, py = anchor["point"]
    sx, sy = (s or 1.0 for s in anchor["scale"])
    width, height = frame_size
    row.update({
        "box": [round(v, 1) for v in answer["box"]],
        "score": answer["score"],
        "holdsPoint": bool(x0 <= px < x1 and y0 <= py < y1),
        "size": [round(x1 - x0, 1), round(y1 - y0, 1)],
        "worldSize": [round((x1 - x0) / sx, 1), round((y1 - y0) / sy, 1)],
        # From the player's origin, in the game's own pixels: how far the box reaches up and down.
        "aboveOrigin": round((py - y0) / sy, 1),
        "belowOrigin": round((y1 - py) / sy, 1),
        "frameShare": round(max(0.0, x1 - x0) * max(0.0, y1 - y0) / (width * height), 4),
    })
    return row


def _spread(values: list, digits: int = 2) -> dict | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"min": round(min(values), digits), "median": round(statistics.median(values), digits),
            "max": round(max(values), digits)}


def summarise(rows: list[dict]) -> dict:
    asked = [r for r in rows if r.get("asked")]
    answered = [r for r in asked if r.get("box")]
    return {
        "frames": len(rows),
        "asked": len(asked),
        "notAsked": len(rows) - len(asked),
        "answered": len(answered),
        "unreadable": sum(1 for r in asked if r.get("error")),
        "holdsPoint": sum(1 for r in answered if r["holdsPoint"]),
        "scored": sum(1 for r in answered if r["score"] is not None),
        "score": _spread([r["score"] for r in answered]),
        "worldWidth": _spread([r["worldSize"][0] for r in answered]),
        "worldHeight": _spread([r["worldSize"][1] for r in answered]),
        "aboveOrigin": _spread([r["aboveOrigin"] for r in answered]),
        "belowOrigin": _spread([r["belowOrigin"] for r in answered]),
        "frameShare": _spread([r["frameShare"] for r in answered], 4),
    }


def plan(run: Path, picked: list[int] | None, every: int, first: int, lift: float) -> tuple[dict, list[int], dict]:
    """(frame files, chosen frames, anchors) for one run, with nothing sent."""
    frames = frame_files(run / "frames")
    if not frames:
        raise SamError(f"no frames in {run / 'frames'}")
    indices = [i for i in frames if i < first]
    chosen = [i for i in (picked or sample(indices, every)) if i in frames]
    if not chosen:
        raise SamError(f"{run.name}: none of the frames asked for was captured")
    return frames, chosen, anchors(load_trace(run), png_size(frames[chosen[0]]), chosen, lift)


def probe_run(run: Path, picked: list[int] | None, every: int, first: int, lift: float, client,
              out: Path | None) -> dict:
    """Ask about every chosen frame of one run. A stop (see STOP_KINDS) is raised with the rows so far."""
    frames, chosen, where = plan(run, picked, every, first, lift)
    rows = []
    result = {"run": run.name, "framesProbed": chosen, "frames": rows}
    for n in chosen:
        anchor = where[n]
        if "why" in anchor:
            rows.append({"frame": n, "asked": False, "note": anchor["why"],
                         **{k: anchor[k] for k in ("world", "point") if k in anchor}})
            continue
        size = png_size(frames[n])
        try:
            answer = client.segment_at(frames[n], [tuple(anchor["point"])])[0]
        except SamError as exc:
            if exc.kind in STOP_KINDS or exc.status is not None:
                result["summary"] = summarise(rows)
                exc.partial = result
                raise
            rows.append({"frame": n, "world": anchor["world"], "point": anchor["point"], "asked": True, "box": None,
                         "score": None, "error": str(exc)[:300]})
            continue
        rows.append({"frame": n, **measure(anchor, answer, size)})
    result["summary"] = summarise(rows)
    if out is not None:
        result["images"] = draw(run.name, frames, rows, out)
    return result


def draw(run_name: str, frames: dict[int, Path], rows: list[dict], out: Path) -> list[str]:
    """Overlay PNGs (half size) and one contact sheet: the point as a cross, the answer as a box."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []
    written, thumbs = [], []
    run_dir = out / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        n = row["frame"]
        img = Image.open(frames[n]).convert("RGB")
        pen = ImageDraw.Draw(img)
        if row.get("box"):
            score = "no score" if row["score"] is None else f"{row['score']:.2f}"
            pen.rectangle(row["box"], outline="#00e05a", width=3)
            pen.text((row["box"][0] + 4, max(0, row["box"][1] - 14)), score, fill="#00e05a")
        if row.get("point"):
            x, y = row["point"]
            pen.line((x - 14, y, x + 14, y), fill="#ff4fd8", width=3)
            pen.line((x, y - 14, x, y + 14), fill="#ff4fd8", width=3)
        label = f"{run_name}  frame {n}" + (f"  ({row.get('note') or row.get('error')})"
                                             if row.get("note") or row.get("error") else "")
        pen.text((8, 8), label[:150], fill="#ffffff")
        path = run_dir / f"f{n:08d}.png"
        img.resize((img.width // 2, img.height // 2)).save(path)
        written.append(str(path))
        thumbs.append(img.resize((img.width // 4, img.height // 4)))
    if thumbs:
        cols = min(4, len(thumbs))
        tw, th = thumbs[0].size
        sheet = Image.new("RGB", (cols * tw, -(-len(thumbs) // cols) * th), "#111111")
        for k, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((k % cols) * tw, (k // cols) * th))
        path = out / f"{run_name}-sheet.png"
        sheet.save(path)
        written.append(str(path))
    return written


def _num(value) -> str:
    return "n/a" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _range(spread: dict | None) -> str:
    return "n/a" if not spread else f"{_num(spread['min'])} / {_num(spread['median'])} / {_num(spread['max'])}"


def markdown(runs: list[dict], model: str, stats: dict, stopped: str | None) -> str:
    lines = ["# SAM asked with a point at the engine's player position", "",
             f"Model {model}. Calls {stats['calls']}, counted ${stats['reservedUsd']:.4f} at the list price of an "
             "image (what a point request is billed at is not on the price page).", ""]
    if stopped:
        lines += [f"**Stopped early:** {stopped}", ""]
    lines += ["| Run | Asked | Answered | Holds the point | Confidence min / median / max | Width (game px) | "
              "Height (game px) | Below origin (game px) | Share of frame, largest |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for run in runs:
        s = run["summary"]
        share = "n/a" if not s["frameShare"] else f"{s['frameShare']['max'] * 100:.1f}%"
        lines.append(f"| {run['run']} | {s['asked']} of {s['frames']} | {s['answered']} | {s['holdsPoint']} | "
                     f"{_range(s['score'])} | {_range(s['worldWidth'])} | {_range(s['worldHeight'])} | "
                     f"{_range(s['belowOrigin'])} | {share} |")
    for run in runs:
        lines += ["", f"## {run['run']}", "",
                  "| Frame | Player (game) | Point (frame) | Box (frame) | Size (game px) | Above / below origin | "
                  "Confidence | Holds the point | Note |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in run["frames"]:
            box = r.get("box")
            lines.append(
                f"| {r['frame']} | {_pair(r.get('world'))} | {_pair(r.get('point'))} | "
                f"{'none' if not box else ', '.join(_num(v) for v in box)} | "
                f"{'' if not box else _num(r['worldSize'][0]) + ' x ' + _num(r['worldSize'][1])} | "
                f"{'' if not box else _num(r['aboveOrigin']) + ' / ' + _num(r['belowOrigin'])} | "
                f"{'' if not box else 'none given' if r['score'] is None else _num(r['score'])} | "
                f"{'' if not box else 'yes' if r['holdsPoint'] else 'no'} | "
                f"{(r.get('note') or r.get('error') or '').replace('|', '/')} |")
    lines += ["", "A box is in frame pixels, left, top, right, bottom, with right and bottom one past the last "
              "pixel. Game pixels are frame pixels divided by the camera's scale. \"Below origin\" is how far the "
              "box reaches under the engine's player position: on a clean run it is the distance from the origin "
              "to the feet as drawn."]
    return "\n".join(lines) + "\n"


def _pair(value) -> str:
    return "" if not value else f"{_num(value[0])}, {_num(value[1])}"


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(runs: list[dict], stats: dict, stopped: str | None) -> list[str]:
    """One GitHub notice per run and one for the cost (GitHub keeps ten a step): readable through the
    checks API, so the numbers can be read back without the artifact."""
    lines = []
    for run in runs[:9]:
        s = run["summary"]
        parts = [f"asked {s['asked']} of {s['frames']}", f"answered {s['answered']}",
                 f"holds the point {s['holdsPoint']}", f"unreadable {s['unreadable']}",
                 f"confidence {_range(s['score'])} ({s['scored']} scored)",
                 f"game px w {_range(s['worldWidth'])} h {_range(s['worldHeight'])}",
                 f"below origin {_range(s['belowOrigin'])}", f"above origin {_range(s['aboveOrigin'])}",
                 f"frame share {_range(s['frameShare'])}"]
        for r in run["frames"]:
            if r.get("box"):
                parts.append(f"f{r['frame']} pt {r['point'][0]},{r['point'][1]} box "
                             + ",".join(_num(v) for v in r["box"]) + f" c {_num(r['score'])}")
            else:
                parts.append(f"f{r['frame']} {r.get('note') or r.get('error') or 'no box'}"[:160])
        lines.append(f"::notice title=SAM anchor {run['run']}::{_escape('; '.join(parts))}")
    cost = f"calls {stats['calls']}; counted ${stats['reservedUsd']:.4f}" + (f"; stopped early: {stopped}" if stopped else "")
    lines.append(f"::notice title=SAM anchor summary::{_escape(cost)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    from agents.sam_observations import sam_usage

    p = argparse.ArgumentParser(description="Ask SAM 3.1 what is drawn at the engine's player position.")
    p.add_argument("--runs", type=Path, nargs="+", required=True, help="run dirs with frames/ and trace.json")
    p.add_argument("--every", type=int, default=10, help="probe every Nth frame (default 10)")
    p.add_argument("--frames", help="explicit comma-separated frame numbers instead of --every")
    p.add_argument("--first", type=int, default=120, help="only the first N frames of each run (default 120)")
    p.add_argument("--lift", type=float, default=0.0,
                   help="point this many game pixels above the player's origin (default 0: the origin itself)")
    p.add_argument("--out", type=Path, default=Path("runs/sam-anchor"))
    p.add_argument("--dry-run", action="store_true", help="print the frames and points, send nothing")
    args = p.parse_args(argv)
    load_dotenv()
    if args.every < 1 or args.first < 1:
        p.error("--every and --first must be 1 or more")

    picked = [int(x) for x in args.frames.split(",")] if args.frames else None
    runs = [r for r in args.runs if (r / "frames").is_dir()]
    if not runs:
        print("no run dirs with frames/ given", file=sys.stderr)
        return 2
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    if args.dry_run:
        total = 0
        try:
            for run in runs:
                _, chosen, where = plan(run, picked, args.every, args.first, args.lift)
                ask = [n for n in chosen if "why" not in where[n]]
                total += len(ask)
                print(f"{run.name}: " + " ".join(
                    f"f{n}@{where[n]['point'][0]},{where[n]['point'][1]}" if n in ask else f"f{n}(not asked: {where[n]['why']})"
                    for n in chosen))
        except SamError as exc:
            print(f"cannot plan the probe: {exc}", file=sys.stderr)
            return 2
        print(f"{total} requests at most, one image each")
        return 0

    if vision_backend() != "sam":
        print("the anchored probe asks SAM 3.1 only: a point prompt is the Model API's own", file=sys.stderr)
        return 2
    client = MetaSamClient()
    args.out.mkdir(parents=True, exist_ok=True)
    before = sam_usage()
    results, stopped = [], None
    for run in runs:
        try:
            results.append(probe_run(run, picked, args.every, args.first, args.lift, client, args.out))
        except SamError as exc:
            stopped = f"{run.name}: {exc}"
            partial = getattr(exc, "partial", None)
            if partial and partial["frames"]:
                results.append(partial)
            break
        s = results[-1]["summary"]
        print(f"{run.name}: asked {s['asked']}, answered {s['answered']}, holds the point {s['holdsPoint']}", flush=True)
    after = sam_usage()
    stats = {"calls": client.calls, "seconds": round(client.seconds, 2),
             "reservedUsd": round(after["reservedUsd"] - before["reservedUsd"], 4)}
    report = {"model": client.model, "lift": args.lift, "stats": stats, "stopped": stopped, "runs": results}
    (args.out / "anchor.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "anchor.md").write_text(markdown(results, client.model, stats, stopped), encoding="utf-8")
    print(f"wrote {args.out / 'anchor.md'}")
    if on_github:
        for line in annotations(results, stats, stopped):
            print(line)
    if stopped:
        print(f"SAM anchor probe stopped: {stopped}", file=sys.stderr)
        if on_github:
            print(f"::error title=SAM anchor probe stopped::{_escape(stopped[:500])} (after {client.calls} calls)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
