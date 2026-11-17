"""The reproduction rate of a live run on the public bench, read from that run's records.

    python3 -m expectrail.repro cases                                   # the cases a live run covers, as JSON
    python3 -m expectrail.repro score --records runs/repro --out runs/repro-score [--source "run 123"]
    python3 -m expectrail.repro score-render runs/repro-score/repro-score.json

Nothing here calls a model or starts the engine. A live run (jit.yml, mode ``repro``, from main) writes
one ``expectrail.jit-run/v1`` record per defect; this reads them and says, per defect, whether the bug
was reproduced.

**The case.** The pipeline judges a candidate change, and reproduction has none: the check has to
come from the bug build and the report alone, so that a fix cannot shape the check that judges it
(issue #285, step 6). So every defect runs with the same stand-in candidate,
``bench/jit/public/no-fix.patch``: one comment line in the game's ``README.md``, a file the engine
never loads. It changes nothing in the game, it names no file of any defect, and because no profile
claim names that file the diff map keeps every probe. The build with it applied is the bug build.

**Reproduced.** At least one proposed check that, in the record's own runs,

- passed on the clean game 3 times of 3, and
- failed on the bug build 3 times of 3 (the record's ``base`` near miss), and
- failed 3 times of 3 again on the bug build with the no-fix candidate applied.

The last is stricter than the issue's wording by three runs: the candidate build behaves as the bug
build, so a check that fails 3 of 3 on one and not on the other is flaky, and a flaky check never
counts. The scorer works this out from the runs and refuses a record whose own ``valid`` flag says
otherwise.

Where each of the three is read from. The clean game's runs and the no-fix candidate's runs are in
the record for every check (``validity``). The bug build's runs are kept only for a catch
(``catches[].base``); for any other check the record keeps the bug build's name in a list
(``killed``) and not its runs. A reproducing check is always a catch, because it failed 3 of 3 on
the candidate, so **a check counts as reproducing only when its catch entry is there and shows three
fails on the bug build, with the same candidate runs as its validity row**. A record that names the
bug build as killed for such a check and has no catch that shows it disagrees with itself, and gives
no result. The ``flaky`` reason for "failed on the bug build, then did not with the no-fix candidate"
still rests on the ``killed`` list: that check is no catch, so the record has no runs to read. It
is a reason for a miss and cannot raise the rate.

**Free text is one line.** A reason copied from a record (``why``, ``evidence``) has its whitespace
collapsed where the row is finished, so no text from a record can start a line of the page; the
schema refuses a control character in either, so a score record edited by hand cannot either; and the
page writes every such cell as a code span, where GitHub renders no link, image, HTML or mention.

**A miss gets a reason** in the issue's vocabulary, where the records can show one:

- ``budget``: the run ended with OUT_OF_BUDGET.
- ``flaky``: a check gave different outcomes on the same build (pass and not-pass on the clean game,
  or fail 3 of 3 on the bug build and then not with the no-fix candidate).
- ``wrong-predicate``: checks were proposed, none failed 3 of 3 on the bug build, and the visibility
  record (expectrail/repro/visibility.py) shows a signal that moves on a library probe. That signal
  can be a side effect a hundredth of a pixel wide; the visibility table says which.
- ``no-signal``: the visibility record shows the engine's record differs and no signal does.
- ``route-never-reaches`` and ``probe-language``: only with a screen record (``--screen``, below), for a
  miss the visibility record shows no difference for on any library probe. ``probe-language`` when the
  screen record says the frames differ there and the engine's record does not (``screen-only``), and the
  setting offers no check about the screen (any setting but the pixel one). ``route-never-reaches`` when
  the screen record says nothing differs on any library probe, in the record or in the frames
  (``neither``): no library route reaches anything this defect changes that either can see. That reading
  is the measurement's, and its limit is the screen record's: a defect whose effect neither the record nor
  the frames carry would read the same way.
- ``undetermined``: the records cannot say. The visibility record shows no difference on any library
  probe and there is no screen record (or no row in it, or it disagrees with the visibility record about
  the engine's record, or the pixel setting offered checks about the screen and none reproduced), or
  there is no visibility row.

Without a screen record, ``route-never-reaches`` and ``probe-language`` are never assigned here: no record
separates them from the others, and a person's hand finding (expectrail/repro/breakdown.py) has to. The
reader recomputes both from the row's ``visibility`` and ``screen``, so neither can be written where the
screen record does not show it, and ``undetermined`` cannot be written where it does.

A defect with no usable record is ``no-result``: counted in the bench, never as reproduced. So is a record
made from one of the repository's stand-in proposals (``STAND_INS``: the rehearsal fixture, the hand-written
``faces-motion`` checks of tools/faces_motion_stand_in.py): its checks were not proposed by a model.

**One offer per score.** What the generator was offered is a setting of the run (expectrail/jit/offer.py,
``settings.offer`` in each record). A score counts the records of one setting, ``baseline`` unless it is
told another, and a record made with another setting is ``no-result`` with that reason. So a rate
measured with the held-back signals and reach probes on offer is never read as the baseline, nor the
other way round, and the score record and its page name the setting.

**One candidate setting per score** (issue #285, step 6). Whether the model that proposed the checks was
given the candidate (``shown``, the default) or nothing of it (``withheld``, ``--withhold-candidate``) is a
setting of the run too (``settings.candidate`` in each record; a record written before the setting existed
was made with it shown). A score counts the records of one candidate setting, ``shown`` unless it is told
``withheld``, and a record made with the other is ``no-result`` with that reason, as for the offer. The no-fix
candidate tells the model nothing either way, but the two prompts differ (the system prompt says no fix is
shown, and every probe is on offer), so a rate measured one way is never read as the other. A score of
withheld records names the setting (``candidate``); a score of shown records leaves it out, so a score made
as before is byte for byte what it was. Under ``withheld`` every reproducing check was derived from the
report and the bug build alone, which is #271's first condition; the page says so.

**Pixel checks are counted on their own** (#286; records made under the pixel setting,
``signals-reach-evidence-pixel``). Such a record carries ``pixelChecks`` beside its trace checks
(expectrail/jit/pixel.py). A pixel check reproduces by the same rule as a trace check: it is kept by its
own runs (``pixel.kept_rows``: passed on the clean game 3 of 3 and failed on the bug build 3 of 3, under
one observer setting), and it failed 3 of 3 again on the bug build with the no-fix candidate. A row's
``proposed``, ``kept`` and ``reproducing`` count both kinds; its ``pixel`` object says how many of each were
pixel checks, and the totals' ``pixel`` how many defects a pixel check reproduced, and how many only a
pixel check did. A pixel row whose status or outcome its own runs contradict gives the defect no result,
like a trace row. ``pixel`` is there on every scored row of a pixel score and on no row of any other.

**Screen-only defects** (``--screen``, the screen record of expectrail/repro/screen.py). With one, each row
says what that record measured of its defect (``screen``: ``screen-only``, ``record-and-screen``, ...), and
the totals give the rate on the screen-only defects apart: those are the defects no check that reads only
the engine's record can fail on along the library probes. A screen record made for another bench is
refused. Without one, nothing about the screen is said.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

from expectrail.contracts import ContractError, load_strict, strict_loads
from expectrail.jit import offer as offer_mod
from expectrail.repro import bench

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-score.v1.schema.json"
FORMAT = "expectrail.repro-score/v1"
NAME = "repro-score.json"
PAGE = "repro-score.md"
NO_FIX = "bench/jit/public/no-fix.patch"
NO_FIX_FILE = "README.md"            # of the game: the engine never loads it and no profile claim names it
CASE_PREFIX = "repro-"
REPS = 3
CAP_USD = 2.0
MAX_BYTES = 1024 * 1024
TEXT_MAX = 300
OUTCOMES = ("reproduced", "not-reproduced", "no-result")
MISS_REASONS = ("route-never-reaches", "no-signal", "probe-language", "wrong-predicate", "flaky", "budget",
                "undetermined")
ASSIGNED_HERE = ("budget", "flaky", "wrong-predicate", "no-signal", "undetermined")
# Given only with a screen record, and recomputed by the reader (screen_reason).
SCREEN_REASONS = ("route-never-reaches", "probe-language")
TRACE_VISIBLE = ("signal", "trace-only")
SCREEN_ONLY = "screen-only"
PIXEL_PREFIX = "jit-px-"
# The candidate settings a jit-run record states (settings.candidate). Spelled here, not imported: this
# package never imports the model's code (tests/test_repro_bench.py); a test holds them to the pipeline's.
SHOWN, WITHHELD = "shown", "withheld"
CANDIDATE_SETTINGS = (SHOWN, WITHHELD)
# The repository's own stand-ins for a model (inputs.model of a record made from a hand-written or rehearsal
# proposal). Their checks were written by a person or an agent, not proposed by a model, so a record made
# from one is no result: a reproduction rate counts generated checks only (#286, the faces-motion stand-in).
STAND_INS = ("rehearsal-fixture", "hand-written-stand-in")


class ScoreError(ValueError):
    """A score record cannot be used, or the bench cannot be scored."""


def _sha_text(path: Path) -> str:
    """The digest the pipeline records for a report: the text as it reads it, not the file's bytes."""
    return hashlib.sha256(path.read_text(encoding="utf-8", errors="replace").encode("utf-8")).hexdigest()


def no_fix_problems(doc: dict, root: Path = REPO) -> list[str]:
    """Why the stand-in candidate cannot be used with this bench: [] when it can.

    It must add one comment line to the game's README and do nothing else, and no defect may touch
    that file, so it applies after every defect and tells the model nothing about any of them."""
    from expectrail.jit.diff_map import PatchError, parse

    try:
        path = bench._inside(root, NO_FIX)
        files = parse(path.read_text(encoding="utf-8"))
    except (bench.BenchError, PatchError, UnicodeDecodeError, OSError) as exc:
        return [f"{NO_FIX}: {exc}"[:300]]
    out = []
    if [f["path"] for f in files] != [NO_FIX_FILE]:
        out.append(f"{NO_FIX}: must change the game's {NO_FIX_FILE} and no other file")
    added = [text for f in files for _n, text in f["added"]]
    removed = [text for f in files for _n, text in f["removed"]]
    if removed or len(added) != 1 or not (added[0].startswith("<!--") and added[0].endswith("-->")
                                          and added[0].count("--") == 2):
        out.append(f"{NO_FIX}: must add one comment line (<!-- ... -->) and remove nothing")
    for d in doc["defects"]:
        try:
            touched = {f["path"] for f in parse((root / d["patch"]).read_text(encoding="utf-8"))}
        except (PatchError, UnicodeDecodeError, OSError) as exc:
            out.append(f"{d['id']}: the patch cannot be read ({exc})"[:300])
            continue
        if NO_FIX_FILE in touched:
            out.append(f"{d['id']}: changes the game's {NO_FIX_FILE}, so the no-fix candidate may not apply after it")
    return out


def cases(doc: dict, root: Path = REPO) -> list[dict]:
    """One case per defect, in the shape jit.yml's matrix takes: the defect is the base, the candidate is no fix."""
    found = no_fix_problems(doc, root)
    if found:
        raise ScoreError("; ".join(found))
    return [{"case": CASE_PREFIX + d["id"], "base": d["patch"], "candidate": NO_FIX, "report": d["report"]}
            for d in doc["defects"]]


def _all(runs: list[str], outcome: str) -> bool:
    return len(runs) >= REPS and all(r == outcome for r in runs[:REPS])


def _read(defect: dict, path: Path, root: Path, offer: str = offer_mod.BASELINE,
          candidate: str = SHOWN) -> tuple[dict | None, str | None]:
    """The defect's record, or why there is none to score."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None, f"the record is over {MAX_BYTES} bytes"
        record = load_strict(path, "jit-run")
    except (OSError, ValueError) as exc:
        return None, f"no readable record ({type(exc).__name__})"
    inputs = record["inputs"]
    if inputs["patchSha256"] != bench.sha256(root / NO_FIX):
        return None, "the record is for another candidate than the no-fix patch"
    if inputs["basePatchSha256"] != [bench.sha256(root / defect["patch"])]:
        return None, "the record is for another defect"
    if inputs["reportSha256"] != _sha_text(root / defect["report"]):
        return None, "the record is for another report"
    if inputs.get("model") in STAND_INS:
        return None, (f"the checks were written by hand ({inputs['model']}), not proposed by a model, and the "
                      "bench counts generated checks only")
    made = record["settings"].get("offer", offer_mod.BASELINE)
    if made != offer:
        return None, f"the record was made with offer {made}, and this score counts offer {offer}"
    made_with = record["settings"].get("candidate", SHOWN)
    if made_with != candidate:
        return None, (f"the record was made with the candidate {made_with}, and this score counts records made "
                      f"with it {candidate}")
    if record["settings"]["reps"] != REPS:
        return None, f"the record ran each check {record['settings']['reps']} times, and the bench counts {REPS} of {REPS}"
    return record, None


def one_line(text, limit: int = TEXT_MAX) -> str:
    """Free text as one line: every run of whitespace or control characters becomes one space.

    A fixed point: ``one_line(one_line(x)) == one_line(x)``. The reader holds each text to
    ``text == one_line(text)``, so the cut is made first and what it leaves is stripped; a cut that
    ended on a space would be a text the writer wrote and the reader refused."""
    flat = "".join(" " if (ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")) else ch
                   for ch in str(text))
    return " ".join(flat.split())[:limit].rstrip()


_NO_SCREEN = object()


def screen_reason(visible: str | None, sees: str | None, pixel_offer: bool) -> tuple[str, str] | None:
    """(reason, evidence) that the screen record gives a miss, or None when it gives none.

    Only for a miss the visibility record shows no difference for on any library probe (``visible`` is
    ``none``). ``sees`` is the screen record's word for the defect (expectrail/repro/screen.py), None
    when there is no screen record or no row for the defect in it."""
    if visible != "none":
        return None
    if sees == "neither":
        return ("route-never-reaches",
                "nothing differs on any library probe, in the engine's record or in the frames (the screen "
                "record): no library route reaches anything this defect changes that either can see")
    if sees == SCREEN_ONLY and not pixel_offer:
        return ("probe-language",
                "the frames differ on a library probe and the engine's record does not (the screen record): "
                "no check about the record can fail on it, and this setting offers no check about the screen")
    return None


def score_one(defect: dict, record_path: Path, visible: str | None, root: Path = REPO,
              offer: str = offer_mod.BASELINE, screen=_NO_SCREEN, candidate: str = SHOWN) -> dict:
    """One defect's row. Its free text (``why``, ``evidence``) is made one line here, whatever set it.
    ``screen`` is what the screen record measured of the defect (None when it has no row for it); left
    out, the row says nothing about the screen."""
    row = _score_one(defect, record_path, visible, root, offer, candidate,
                     None if screen is _NO_SCREEN else screen)
    for key in ("why", "evidence"):
        if row[key] is not None:
            row[key] = one_line(row[key])
    if offer_mod.offers_pixel(offer) and row["recordSha256"] is not None:
        row.setdefault("pixel", {"proposed": 0, "kept": 0, "reproducing": []})
    else:
        row.pop("pixel", None)
    if screen is not _NO_SCREEN:
        row["screen"] = screen
    return row


def _pixel_rows(record: dict) -> tuple[dict | None, list[str], str | None]:
    """The pixel share of a record: ({proposed, kept, reproducing}, flaky notes, None), or
    (None, [], why) when the record's pixel rows disagree with themselves.

    Kept is decided from the runs (``pixel.kept_rows``), and a row whose status says otherwise, or a kept
    row whose outcome its candidate runs contradict, is a disagreement."""
    from expectrail.contracts import ContractError
    from expectrail.jit import pixel

    rows = record.get("pixelChecks") or []
    ids = [r["check"].get("id") for r in rows]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i.startswith(PIXEL_PREFIX) for i in ids):
        return None, [], "the record disagrees with itself: its pixel checks are not named once each as pixel checks"
    try:
        kept = {r["check"]["id"] for r in pixel.kept_rows(record)}
    except (ContractError, ValueError) as exc:
        return None, [], f"the record disagrees with itself: a pixel check is not one ({type(exc).__name__})"
    reproducing, flaky = [], []
    for r in rows:
        cid = r["check"]["id"]
        if (r["status"] == "kept") != (cid in kept) or max(len(r["clean"]), len(r["bug"]), len(r["candidate"])) > REPS:
            return None, [], (f"the record disagrees with itself: pixel check {cid} is marked {r['status']}, "
                              f"and its runs say otherwise")
        if cid not in kept:
            continue
        caught = _all(r["candidate"], "fail")
        if r["outcome"] in ("catch", "no-catch") and (r["outcome"] == "catch") != caught:
            return None, [], (f"the record disagrees with itself: pixel check {cid} is marked {r['outcome']}, "
                              f"and its candidate runs say otherwise")
        if caught:
            reproducing.append(cid)
        elif r["candidate"]:
            flaky.append(f"{cid} failed {REPS} of {REPS} on the bug build, then gave {', '.join(r['candidate'])} "
                         f"on the same build with the no-fix candidate")
    return {"proposed": len(rows), "kept": len(kept), "reproducing": sorted(reproducing)}, flaky, None


def _bug_build_runs(record: dict, spec_id: str, candidate: list[str]) -> list[str] | None:
    """The bug build's runs for a check, from its catch entry; None when the record has none to read."""
    entries = [c for c in record["catches"] if c["specId"] == spec_id]
    if len(entries) != 1 or entries[0]["base"] is None or entries[0]["candidate"] != candidate:
        return None
    return entries[0]["base"]


def _score_one(defect: dict, record_path: Path, visible: str | None, root: Path, offer: str,
               candidate: str = SHOWN, sees: str | None = None) -> dict:
    row = {"id": defect["id"], "family": defect["family"], "tunedOn": defect["tunedOn"],
           "patchSha256": bench.sha256(root / defect["patch"]), "visibility": visible,
           "outcome": "no-result", "why": None, "proposed": 0, "kept": 0, "reproducing": [],
           "missReason": None, "evidence": None, "spendUsd": None, "recordSha256": None}
    record, why = _read(defect, Path(record_path), root, offer, candidate)
    if record is None:
        row["why"] = why
        return row
    row["recordSha256"] = bench.sha256(Path(record_path))
    row["spendUsd"] = record["spend"]["usd"]
    if record["status"] != "complete":
        reason = record["reason"] or ""
        if reason.startswith("OUT_OF_BUDGET"):
            row.update(outcome="not-reproduced", missReason="budget", evidence=reason[:300])
        else:
            row["why"] = f"{record['status']}: {reason}"[:300]
        return row
    proposed = {p["spec"]["id"] for p in record["proposed"]}
    rows = record["validity"]
    ids = [v["specId"] for v in rows]
    if len(set(ids)) != len(ids) or not set(ids) <= proposed:
        row.update(spendUsd=None, recordSha256=None, why="the record disagrees with itself: its checks and its runs do not match")
        return row
    kept, reproducing, flaky = 0, [], []
    for v in rows:
        passes_clean = _all(v["reference"], "pass")
        is_kept = passes_clean and bool(v["killed"])
        if is_kept != v["valid"] or len(v["reference"]) > REPS or len(v["candidate"]) > REPS:
            row.update(spendUsd=None, recordSha256=None,
                       why=f"the record disagrees with itself: {v['specId']} is marked "
                           f"{'valid' if v['valid'] else 'not valid'}, and its runs say otherwise"[:300])
            return row
        kept += is_kept
        fails_bug = is_kept and "base" in v["killed"]
        if fails_bug and _all(v["candidate"], "fail"):
            # Counted from runs, not from the killed list: a reproducing check is a catch, and a catch
            # keeps the bug build's runs.
            base_runs = _bug_build_runs(record, v["specId"], v["candidate"])
            if base_runs is None or len(base_runs) > REPS or not _all(base_runs, "fail"):
                row.update(spendUsd=None, recordSha256=None,
                           why=f"the record disagrees with itself: {v['specId']} is listed as failing on the "
                               f"bug build, and no catch of it shows {REPS} fails there")
                return row
            reproducing.append(v["specId"])
        elif fails_bug:
            flaky.append(f"{v['specId']} failed {REPS} of {REPS} on the bug build, then gave "
                         f"{', '.join(v['candidate']) or 'no run'} on the same build with the no-fix candidate")
        elif "pass" in v["reference"] and any(r != "pass" for r in v["reference"]):
            flaky.append(f"{v['specId']} gave {', '.join(v['reference'])} on the clean game")
    if offer_mod.offers_pixel(offer):
        share, pixel_flaky, disagree = _pixel_rows(record)
        if disagree:
            row.update(spendUsd=None, recordSha256=None, why=disagree)
            return row
        row["pixel"] = share
        flaky += pixel_flaky
        reproducing += share["reproducing"]
        kept += share["kept"]
        proposed |= {r["check"]["id"] for r in record.get("pixelChecks") or []}
    row.update(proposed=len(proposed), kept=kept, reproducing=sorted(reproducing))
    if reproducing:
        row["outcome"] = "reproduced"
        return row
    row["outcome"] = "not-reproduced"
    n = len(proposed)
    if flaky:
        row.update(missReason="flaky", evidence="; ".join(flaky)[:300])
    elif visible == "signal":
        row.update(missReason="wrong-predicate",
                   evidence=f"a signal moves on a library probe, and none of the {n} proposed checks failed "
                            f"{REPS} of {REPS} on the bug build")
    elif visible == "trace-only":
        row.update(missReason="no-signal",
                   evidence="the engine's record differs on a library probe and no signal reads the difference")
    elif visible == "none":
        by_screen = screen_reason(visible, sees, offer_mod.offers_pixel(offer))
        if by_screen is not None:
            row.update(missReason=by_screen[0], evidence=by_screen[1])
        elif sees in ("record-and-screen", "record-only"):
            row.update(missReason="undetermined",
                       evidence=f"the visibility record shows no difference in the engine's record on any library "
                                f"probe, and the screen record says it differs ({sees}): the two measurements disagree")
        elif sees == SCREEN_ONLY:
            row.update(missReason="undetermined",
                       evidence=f"the frames differ on a library probe and the engine's record does not (the screen "
                                f"record); checks about the screen were on offer and none of the {n} proposed "
                                f"reproduced it, and the records cannot say whether the observer could not tell or "
                                f"the predicate was wrong")
        else:
            row.update(missReason="undetermined",
                       evidence="the record is the same on every library probe: no route reaches the behaviour, or "
                                "it shows only on screen")
    else:
        row.update(missReason="undetermined", evidence="no visibility row for this defect")
    return row


def totals(rows: list[dict]) -> dict:
    spends = [r["spendUsd"] for r in rows if r["spendUsd"] is not None]
    done = [r for r in rows if r["outcome"] == "reproduced"]
    return {
        "defects": len(rows),
        "reproduced": len(done),
        "notReproduced": sum(r["outcome"] == "not-reproduced" for r in rows),
        "noResult": sum(r["outcome"] == "no-result" for r in rows),
        "untuned": sum(not r["tunedOn"] for r in rows),
        "reproducedUntuned": sum(not r["tunedOn"] for r in done),
        "traceVisible": sum(r["visibility"] in TRACE_VISIBLE for r in rows),
        "reproducedTraceVisible": sum(r["visibility"] in TRACE_VISIBLE for r in done),
        "keptChecks": sum(r["kept"] for r in rows),
        "misses": {k: n for k in MISS_REASONS if (n := sum(r["missReason"] == k for r in rows))},
        "spendUsd": round(sum(spends), 4),
        "maxSpendUsd": max(spends, default=0),
        "overCap": sum(s > CAP_USD + 1e-9 for s in spends),
        **_pixel_totals(rows), **_screen_totals(rows),
    }


def _pixel_totals(rows: list[dict]) -> dict:
    """The pixel checks' share of a pixel score's totals; nothing for a score of any other setting."""
    shares = [(r, r["pixel"]) for r in rows if "pixel" in r]
    if not shares:
        return {}
    done = [(r, p) for r, p in shares if r["outcome"] == "reproduced"]
    return {"pixel": {
        "proposed": sum(p["proposed"] for _, p in shares),
        "kept": sum(p["kept"] for _, p in shares),
        "reproducedBy": sum(bool(p["reproducing"]) for _, p in done),
        "reproducedOnlyBy": sum(bool(p["reproducing"]) and set(r["reproducing"]) == set(p["reproducing"])
                                for r, p in done),
    }}


def _screen_totals(rows: list[dict]) -> dict:
    """The screen-only defects apart, when the rows say what the screen record measured; else nothing."""
    if not rows or not all("screen" in r for r in rows):
        return {}
    only = [r for r in rows if r["screen"] == SCREEN_ONLY]
    return {"screenOnly": len(only), "reproducedScreenOnly": sum(r["outcome"] == "reproduced" for r in only)}


def score(doc: dict, records_dir: Path, *, visibility_path: Path | None = None, source: str | None = None,
          root: Path = REPO, bench_path: Path = bench.BENCH, offer: str = offer_mod.BASELINE,
          screen_path: Path | None = None, candidate: str = SHOWN) -> dict:
    """The score record, from ``records_dir/repro-<id>/jit-run.json`` for each defect of the bench,
    counting only records made with ``offer`` and with the candidate ``candidate`` (shown or withheld).

    With a visibility record, each row says what the library probes see of its defect, and a miss can
    be given a reason from it. A visibility record made for another bench is refused."""
    try:
        if offer_mod.check(offer) not in offer_mod.SCORED:
            raise offer_mod.OfferError(f"the offer {offer} is not scored")
    except offer_mod.OfferError as exc:
        raise ScoreError(str(exc)) from exc
    if candidate not in CANDIDATE_SETTINGS:
        raise ScoreError(f"the candidate setting must be one of {', '.join(CANDIDATE_SETTINGS)}")
    found = no_fix_problems(doc, root)
    if found:
        raise ScoreError("; ".join(found))
    seen = {}
    if visibility_path is not None:
        from expectrail.repro import visibility

        try:
            visibility_record = visibility.load(visibility_path)
        except (visibility.VisibilityError, OSError) as exc:
            raise ScoreError(f"the visibility record cannot be read: {exc}"[:300]) from exc
        old = visibility.stale(visibility_record, doc, root, bench_path)
        if old:
            raise ScoreError("the visibility record does not describe this bench: " + "; ".join(old)[:240])
        seen = {r["id"]: r["visibility"] for r in visibility_record["defects"] if r["visibility"] != "error"}
    sees: dict = {}
    if screen_path is not None:
        from expectrail.repro import screen

        try:
            screen_record = screen.load(screen_path)
        except (screen.ScreenError, OSError) as exc:
            raise ScoreError(f"the screen record cannot be read: {exc}"[:300]) from exc
        old = screen.stale(screen_record, doc, root, bench_path)
        if old:
            raise ScoreError("the screen record does not describe this bench: " + "; ".join(old)[:240])
        sees = {r["id"]: r["sees"] for r in screen_record["defects"] if r["sees"] != "error"}
    rows = [score_one(d, Path(records_dir) / (CASE_PREFIX + d["id"]) / "jit-run.json", seen.get(d["id"]), root,
                      offer, candidate=candidate, **({"screen": sees.get(d["id"])} if screen_path is not None else {}))
            for d in doc["defects"]]
    record = {"format": FORMAT, "benchSha256": bench.sha256(bench_path), "noFixSha256": bench.sha256(root / NO_FIX),
              "visibilitySha256": bench.sha256(Path(visibility_path)) if visibility_path is not None else None,
              "source": (one_line(source, 200) or None) if source else None, "offer": offer,
              "reps": REPS, "capUsd": CAP_USD, "rows": rows, "totals": totals(rows)}
    if candidate == WITHHELD:
        # Left out when shown, so a score made as before is the record it always was.
        record["candidate"] = WITHHELD
    if screen_path is not None:
        record["screenSha256"] = bench.sha256(Path(screen_path))
    found = problems(record)
    if found:
        raise ScoreError("; ".join(found))
    return record


def write(record: dict, out: Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / PAGE).write_text(render(record), encoding="utf-8")
    return out / NAME


def problems(record) -> list[str]:
    """What is wrong with a score record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-score: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300] for e in errors[:10]]
    out = []
    ids = [r["id"] for r in record["rows"]]
    if len(set(ids)) != len(ids):
        out.append("repro-score: a defect is listed twice")
    pixel_score = offer_mod.offers_pixel(record["offer"])
    for r in record["rows"]:
        scored = r["recordSha256"] is not None
        expect = {
            "reproduced": bool(r["reproducing"]) and r["missReason"] is None and r["why"] is None and scored,
            "not-reproduced": not r["reproducing"] and r["missReason"] is not None and r["evidence"] is not None
                              and r["why"] is None and scored,
            "no-result": not r["reproducing"] and r["missReason"] is None and r["why"] is not None
                         and r["kept"] == 0 and r["proposed"] == 0,
        }[r["outcome"]]
        if not expect:
            out.append(f"repro-score: {r['id']}: outcome {r['outcome']!r} does not follow from its row")
        if len(r["reproducing"]) > r["kept"] or r["kept"] > r["proposed"]:
            out.append(f"repro-score: {r['id']}: more reproducing checks than kept, or more kept than proposed")
        if scored != (r["spendUsd"] is not None):
            out.append(f"repro-score: {r['id']}: spend and record digest must both be there or both be missing")
        for key in ("why", "evidence"):
            if r[key] is not None and r[key] != one_line(r[key]):
                out.append(f"repro-score: {r['id']}: {key} is not one line of plain text")
        by_screen = screen_reason(r["visibility"], r.get("screen"), pixel_score) if "screen" in r else None
        if r["missReason"] in SCREEN_REASONS:
            if by_screen is None or by_screen[0] != r["missReason"]:
                out.append(f"repro-score: {r['id']}: {r['missReason']!r} is given only where the screen record "
                           f"shows it")
        elif r["missReason"] is not None and r["missReason"] not in ASSIGNED_HERE:
            out.append(f"repro-score: {r['id']}: {r['missReason']!r} is not a reason the records can show")
        elif r["missReason"] == "undetermined" and by_screen is not None:
            out.append(f"repro-score: {r['id']}: 'undetermined', where the screen record gives {by_screen[0]!r}")
    for r in record["rows"]:
        share = r.get("pixel")
        if pixel_score and (share is not None) != (r["recordSha256"] is not None):
            out.append(f"repro-score: {r['id']}: a pixel score gives every scored row, and only those, its pixel checks")
        if not pixel_score and share is not None:
            out.append(f"repro-score: {r['id']}: pixel checks on a row of a score made with offer {record['offer']}")
        if share is not None and (not set(share["reproducing"]) <= set(r["reproducing"])
                                  or len(share["reproducing"]) > share["kept"] or share["kept"] > r["kept"]
                                  or share["proposed"] > r["proposed"] or share["kept"] > share["proposed"]
                                  or not all(c.startswith(PIXEL_PREFIX) for c in share["reproducing"])):
            out.append(f"repro-score: {r['id']}: its pixel checks do not fit inside its counts")
    has_screen = [("screen" in r) for r in record["rows"]]
    if any(has_screen) and not all(has_screen):
        out.append("repro-score: some rows say what the screen record measured and some do not")
    if ("screenSha256" in record) != (bool(record["rows"]) and all(has_screen)):
        out.append("repro-score: rows say what a screen record measured only when the score names that record")
    if record["source"] is not None and record["source"] != one_line(record["source"], 200):
        out.append("repro-score: source is not one line of plain text")
    if record["totals"] != totals(record["rows"]):
        out.append("repro-score: the totals do not match the rows")
    return out


def load(path: Path) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise ScoreError(f"repro-score: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise ScoreError(f"repro-score: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise ScoreError("; ".join(found))
    return record


def stale(record: dict, doc: dict, root: Path = REPO, bench_path: Path = bench.BENCH) -> list[str]:
    """Why the score no longer describes the bench: [] when it covers exactly these defects and patches."""
    out = []
    now = {d["id"]: bench.sha256(root / d["patch"]) for d in doc["defects"]}
    then = {r["id"]: r["patchSha256"] for r in record["rows"]}
    for did in sorted(set(now) | set(then)):
        if did not in then:
            out.append(f"{did}: not scored")
        elif did not in now:
            out.append(f"{did}: scored, and no longer in the bench")
        elif now[did] != then[did]:
            out.append(f"{did}: the patch changed after it was scored")
    if not out and record["benchSha256"] != bench.sha256(bench_path):
        out.append("the bench file changed after it was scored")
    if record["noFixSha256"] != bench.sha256(root / NO_FIX):
        out.append("the no-fix candidate changed after it was scored")
    return out


def _share(n: int, of: int) -> str:
    return f"{n} of {of}" + (f" ({100 * n / of:.0f}%)" if of else "")


def _code(text) -> str:
    """Text from a record as a code span on one line: no link, image, HTML or mention is rendered in one,
    and it cannot end the table cell or the span. No text gives a dash: an empty code span is not one,
    GitHub shows its two backticks."""
    flat = one_line(text).replace("`", "'").replace("|", "/")
    return f"`{flat}`" if flat else "-"


def render(record: dict) -> str:
    """The score as a page: the rate first, then what it does not cover, then one row per defect."""
    t = record["totals"]
    lines = [f"# Reproduction on the public bench: {_share(t['reproduced'], t['defects'])}", "",
             f"Generator offered: `{record['offer']}` (expectrail/jit/offer.py)."
             + (" This is the generator as it was before steps 3 and 4 of issue #285." if record["offer"] == "baseline"
                else "") + " A record made with another setting is counted as no result.", "",
             *(["Candidate: **withheld**. The model was given no byte of the candidate, so every reproducing "
                "check below was derived from the report and the bug build alone (issue #285, step 6). A record "
                "made with the candidate shown is counted as no result.", ""]
               if record.get("candidate") == WITHHELD else []),
             f"From {_code(record['source']) if record['source'] else 'records with no named source'}. "
             f"A defect is reproduced when a generated "
             f"check passed on the clean game {REPS} times of {REPS} and failed on the bug build {REPS} times of "
             f"{REPS}, with and without the no-fix candidate.", "",
             f"- Reproduced: {_share(t['reproduced'], t['defects'])}; not reproduced: {t['notReproduced']}; "
             f"no result: {t['noResult']}",
             f"- Of the defects that change the engine's record on a library probe: "
             f"{_share(t['reproducedTraceVisible'], t['traceVisible'])}"
             + ("" if record["visibilitySha256"] else " (no visibility record was given, so none is counted)"),
             f"- Of the defects nothing was tuned on: {_share(t['reproducedUntuned'], t['untuned'])}",
             f"- Checks kept (passed on the clean game {REPS} of {REPS} and failed {REPS} of {REPS} on a near "
             f"miss): {t['keptChecks']}",
             f"- Spend: ${t['spendUsd']:.4f} in all, at most ${t['maxSpendUsd']:.4f} for one defect; over the "
             f"${record['capUsd']:.2f} cap: {t['overCap']}"]
    if "screenOnly" in t:
        lines.append(f"- Of the defects that change only the screen on a library probe (the screen record): "
                     f"{_share(t['reproducedScreenOnly'], t['screenOnly'])}")
    if "pixel" in t:
        px = t["pixel"]
        lines.append(f"- Pixel checks (#286): {px['proposed']} proposed, {px['kept']} kept; defects a pixel check "
                     f"reproduced: {px['reproducedBy']}, of which only a pixel check: {px['reproducedOnlyBy']}")
    if t["misses"]:
        lines.append("- Misses by reason: " + ", ".join(f"{k} {n}" for k, n in t["misses"].items()))
    lines += ["",
              "| Defect | Family | Tuned on | Library probes see | Proposed | Kept | Outcome | Reason, or why no result | Spend |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in record["rows"]:
        if r["outcome"] == "reproduced":
            note = ", ".join(f"`{s}`" for s in r["reproducing"])
        elif r["outcome"] == "not-reproduced":
            note = f"{r['missReason']}: {_code(r['evidence'])}"
        else:
            note = _code(r["why"])
        spend = "" if r["spendUsd"] is None else f"${r['spendUsd']:.4f}"
        sees = r['visibility'] or 'not measured'
        if "screen" in r:
            sees += f"; screen record: {r['screen'] or 'not measured'}"
        if r.get("pixel", {}).get("reproducing"):
            note += " (pixel)" if set(r["pixel"]["reproducing"]) == set(r["reproducing"]) else " (trace and pixel)"
        lines.append(f"| `{r['id']}` | {r['family']} | {'yes' if r['tunedOn'] else 'no'} | {sees} | "
                     f"{r['proposed']} | {r['kept']} | {r['outcome']} | {note} | {spend} |")
    return "\n".join(lines) + "\n"
