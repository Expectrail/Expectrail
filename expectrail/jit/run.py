"""One change, report-only: generate checks for it, keep the valid ones, run them, report what they catch.

    generate(profile, report, candidate, base_patches, out, runner=..., intent=...) -> expectrail.jit-run/v1

Snapshots, all replayed headless and trace-only:

- **reference**: the clean game (``patches=[]``). A generated check must pass here on every run.
- **variants**: near misses of the candidate (expectrail/jit/dodgy.py), ``[*base, candidate, variant]``.
  A valid check must fail on every run of at least one.
- **candidate**: ``[*base, candidate]``. A valid check that fails here on every run is a catch.
- **base**: ``[*base]``, the build the bug report describes. It is the first near miss of any fix
  (a fix that changes nothing behaves like it), and its runs label a catch strong or weak.

The rules (docs/jit.md):

1. **Report-only.** The record has no decision field and ``advisory`` is always true. Nothing reads a
   jit-run record to accept or reject a change.
2. **The fixer never sees it.** Every file this writes is named ``jit-*``, a prefix the fixer's
   workspace refuses (agents/isolation.py).
3. **Fail closed to "nothing generated".** A patch that cannot be read, a model that is unavailable or
   answers with nothing valid, a budget that runs out, or any replay error ends the run with
   ``status: nothing-generated`` and the reason. Never a pass, never a catch.
4. **Budget.** At most ``budgetUsd`` (default $2) per change across the model call, replays and SAM
   images, checked before each call and each replay. v1 is trace-only, so it uses no SAM image.
5. **Untrusted input.** The patch and the report reach the model as data (expectrail/jit/intent.py);
   whether a check is valid and whether it catches is decided by replay outcomes only
   (expectrail/jit/assess.py).

Pixel checks (#286; the pixel setting only, ``offer.PIXEL``). The proposal's pixel checks
(expectrail/jit/pixel.py) are judged after the trace checks, in ``_pixel_stage``: each check's probe is
replayed **with frames** (``frame_runner``) on the clean game and on the bug build (``[*base]``), ``reps``
times each, and the ``observer`` is asked about every run. A check is kept only by ``pixel.keep``: it
passes on every clean run and fails on every bug run, one observer setting on all of them, no frame
without both the observer and the engine's record. A kept check is then judged on the candidate the same
way: failing on every run is a catch. Observer images are reserved against the same cap before the
replays (``observer.frames``), and what was actually sent is charged. With no observer, no frame runner,
no bug build or no budget left, a pixel check is ``not-run`` with the reason, never kept. The rows are the
record's ``pixelChecks``; they are not in ``catches``, ``counts`` or ``gate_summary``.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import traceback
from pathlib import Path

from expectrail.contracts import digest_v1, load_strict, validate_v1
from expectrail.discovery.route_compiler import ProgramError, compile_route
from expectrail.discovery.templates import applies_to
from expectrail.jit import assess
from expectrail.jit import offer as offer_mod
from expectrail.jit.diff_map import PatchError, diff_map
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import from_run_dir

FORMAT = "expectrail.jit-run/v1"
RECORD_NAME = "jit-run.json"
DEFAULT_BUDGET_USD = 2.0
# Price assumptions, recorded in every run. Muse Spark's per-token price is not published to us, so these
# are set high on purpose; the record names them, and `--spark-usd-per-mtok-*` overrides them.
DEFAULT_PRICES = {
    "sparkUsdPerMTokIn": 1.00,
    "sparkUsdPerMTokOut": 4.00,
    "runnerUsdPerMinute": 0.008,     # a GitHub-hosted Linux runner
    "samUsdPerImage": 2.50 / 1000,   # agents/case_spend.py
    "source": "assumed",
}
DEFAULT_REPLAY_SECONDS = 30.0        # reserved before a replay until one has been timed


class NothingGenerated(RuntimeError):
    """Rule 3: the run ends with no generated checks, and this is the reason."""


class OutOfBudget(NothingGenerated):
    pass


class ReplayFailed(NothingGenerated):
    pass


class Spend:
    def __init__(self, cap_usd: float, prices: dict):
        self.cap, self.prices = float(cap_usd), {**DEFAULT_PRICES, **(prices or {})}
        self.spark_usd = self.replay_usd = self.sam_usd = 0.0
        self.replays = self.sam_images = 0
        self.prompt_tokens = self.completion_tokens = 0
        self.replay_seconds: list[float] = []

    @property
    def usd(self) -> float:
        return self.spark_usd + self.replay_usd + self.sam_usd

    def spark_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.prices["sparkUsdPerMTokIn"] + completion_tokens * self.prices["sparkUsdPerMTokOut"]) / 1e6

    def reserve(self, usd: float, what: str) -> None:
        if self.usd + usd > self.cap + 1e-9:
            raise OutOfBudget(f"OUT_OF_BUDGET: {what} needs up to ${usd:.4f}; ${self.usd:.4f} of ${self.cap:.2f} spent")

    def replay_estimate(self) -> float:
        secs = max(self.replay_seconds) if self.replay_seconds else DEFAULT_REPLAY_SECONDS
        return secs / 60 * self.prices["runnerUsdPerMinute"]

    def add_replay(self, seconds: float) -> None:
        self.replays += 1
        self.replay_seconds.append(seconds)
        self.replay_usd += seconds / 60 * self.prices["runnerUsdPerMinute"]

    def check_after(self, what: str) -> None:
        """A replay is reserved at the longest one seen so far, so one that runs longer can carry spend
        past the cap by its own cost. When it has, nothing further runs (review of #231)."""
        if self.usd > self.cap + 1e-9:
            raise OutOfBudget(f"OUT_OF_BUDGET: ${self.usd:.4f} of ${self.cap:.2f} spent after {what}, which ran "
                              f"longer than reserved")

    def add_spark(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
        p, c = int(prompt_tokens or 0), int(completion_tokens or 0)
        self.prompt_tokens += p
        self.completion_tokens += c
        self.spark_usd += self.spark_cost(p, c)

    def doc(self) -> dict:
        return {"usd": round(self.usd, 4), "capUsd": self.cap, "sparkUsd": round(self.spark_usd, 4),
                "replayUsd": round(self.replay_usd, 4), "samUsd": round(self.sam_usd, 4), "samImages": self.sam_images,
                "replays": self.replays, "promptTokens": self.prompt_tokens,
                "completionTokens": self.completion_tokens, "prices": dict(self.prices)}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _default_runner(game: Path | None = None, frames: bool = False):
    from functools import partial

    from harness.run import run as harness_run

    # Trace checks replay trace-only, like discovery: no frames. Pixel checks (the pixel setting only)
    # replay with frames, for the observer.
    return partial(harness_run, capture_frames=frames, **({"game": Path(game)} if game else {}))


def _probe_ids_for(entry: dict, probes: list[dict], allowed: set[str]) -> list[str]:
    a = entry["applies"]
    if a["kind"] == "pair":
        return [a["left"], a["right"]]
    return [p["id"] for p in probes if p["id"] in allowed and applies_to(entry, p)]


def _evaluate(entry: dict, probe_ids: list[str], eps: dict[str, dict]) -> str:
    """One run's outcome for one check, over the episodes of that run."""
    spec = entry["spec"]
    if entry["applies"]["kind"] == "pair":
        left, right = eps.get(probe_ids[0]), eps.get(probe_ids[1])
        if left is None or right is None:
            return "execution_error"
        return evaluate(spec, left, right)["result"]
    return assess.combine([evaluate(spec, eps[pid])["result"] if eps.get(pid) is not None else "execution_error"
                           for pid in probe_ids])


def generate(profile_path: Path, report: str, candidate: Path, base_patches: list[Path], out: Path, *,
             runner=None, intent=None, variants_fn=None, game: Path | None = None,
             budget_usd: float = DEFAULT_BUDGET_USD, prices: dict | None = None, reps: int = assess.REPS,
             variant_limit: int = 8, approved_claims: frozenset[str] = frozenset(),
             run_id: str | None = None, clock=time.monotonic, offer: str = offer_mod.BASELINE,
             candidate_to_model: str = "shown", observer=None, frame_runner=None) -> dict:
    """One change: propose, replay, judge. ``candidate_to_model`` is ``shown`` (the default) or
    ``withheld``: under ``withheld`` the intent is given no byte of the candidate patch and no diff map made
    from it (issue #285, step 6), and the record says so in ``settings.candidate``. The candidate is
    still what the record judges.

    ``observer`` and ``frame_runner`` are for pixel checks only (the pixel setting): the observer asked
    about each pixel replay (expectrail/jit/pixel.py, ``observe``), and the runner that replays with
    frames. Without a ``runner`` the frame runner is the harness with frames; with a ``runner`` and no
    ``frame_runner``, pixel checks are not run."""
    from expectrail.jit.intent import check_candidate

    offer_mod.replayable(offer)
    check_candidate(candidate_to_model)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if frame_runner is None and runner is None:
        frame_runner = _default_runner(game, frames=True)
    runner = runner or _default_runner(game)
    spend = Spend(budget_usd, prices or {})
    profile = load_strict(Path(profile_path), "mechanics-profile")
    cand_bytes = Path(candidate).read_bytes()
    report = report if isinstance(report, str) else ""
    diagnostics: list[str] = []
    state: dict = {"diffMap": None, "proposed": [], "probes": [], "variants": [], "validity": [], "catches": [],
                   "model": str(getattr(intent, "model", None))[:100] if getattr(intent, "model", None) else None,
                   "promptSha256": None, "pixelChecks": [],
                   "pixel": {"observer": observer, "frameRunner": frame_runner}}
    inputs = {"patchSha256": _sha_bytes(cand_bytes), "reportSha256": _sha_bytes(report.encode("utf-8")),
              "basePatchSha256": [_sha_bytes(Path(p).read_bytes()) for p in base_patches],
              "profileSha256": digest_v1(profile)}
    status, reason = "complete", None
    try:
        _pipeline(profile, report, cand_bytes, Path(candidate), list(base_patches), out, runner, intent,
                  variants_fn, game, spend, reps, variant_limit, approved_claims, state, diagnostics, clock, offer,
                  candidate_to_model)
    except (PatchError, NothingGenerated) as exc:
        status, reason = "nothing-generated", " ".join(str(exc).split())[:300]
    except Exception as exc:  # noqa: BLE001 - rule 3: anything unexpected is "nothing generated", never a pass
        status, reason = "nothing-generated", f"{type(exc).__name__}: {' '.join(str(exc).split())[:260]}"
        (out / "jit-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    if status != "complete":
        state["catches"] = []
        for row in state["pixelChecks"]:
            row["outcome"] = "not-evaluated"
    doc = {
        "format": FORMAT,
        "runId": run_id or out.name,
        "advisory": True,
        "status": status,
        "reason": reason,
        "inputs": dict(inputs, model=state["model"], promptSha256=state["promptSha256"]),
        "settings": {"reps": reps, "variantLimit": variant_limit, "budgetUsd": float(budget_usd), "offer": offer,
                     "candidate": candidate_to_model},
        "diffMap": state["diffMap"],
        "proposed": state["proposed"],
        "probes": state["probes"],
        "variants": state["variants"],
        "validity": state["validity"],
        "catches": state["catches"],
        "counts": {"proposed": len(state["proposed"]), "valid": sum(1 for v in state["validity"] if v["valid"]),
                   "strong": sum(1 for c in state["catches"] if c["strength"] == "strong"),
                   "weak": sum(1 for c in state["catches"] if c["strength"] == "weak")},
        "spend": spend.doc(),
        "diagnostics": diagnostics[:50],
    }
    if offer_mod.offers_pixel(offer):
        doc["pixelChecks"] = state["pixelChecks"]
    try:
        validate_v1(doc, "jit-run")
    except Exception as exc:  # noqa: BLE001 - rule 3 holds even for a record we could not write as built
        doc.update(status="nothing-generated", reason=f"RECORD_INVALID: {' '.join(str(exc).split())[:240]}",
                   diffMap=None, proposed=[], probes=[], variants=[], validity=[], catches=[],
                   counts={"proposed": 0, "valid": 0, "strong": 0, "weak": 0})
        if "pixelChecks" in doc:
            doc["pixelChecks"] = []
        doc["inputs"].update(model=None, promptSha256=None)
        validate_v1(doc, "jit-run")
    (out / RECORD_NAME).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def _pipeline(profile, report, cand_bytes, candidate, base_patches, out, runner, intent, variants_fn, game,
              spend: Spend, reps, variant_limit, approved_claims, state, diagnostics, clock,
              offer: str = offer_mod.BASELINE, candidate_to_model: str = "shown") -> None:
    from expectrail.jit.diff_map import withheld_map

    probes = offer_mod.library(profile["actions"], offer, report)
    for p in probes:
        p["source"] = "reach" if p.get("family") == "reach" else "library"
    withheld = candidate_to_model == "withheld"
    # What the intent is given about the candidate: all of it, or (withheld) nothing. The candidate's own
    # bytes are still replayed and judged below.
    shown_text = "" if withheld else cand_bytes.decode("utf-8", errors="replace")
    if withheld:
        diff_map(cand_bytes.decode("utf-8", errors="replace"), profile, probes)  # still refuses a non-patch
        dmap = withheld_map(probes)
    else:
        dmap = diff_map(shown_text, profile, probes)
    state["diffMap"] = {k: v for k, v in dmap.items() if not k.startswith("_")}

    # Intent: one model call, reserved against the budget before it is made.
    if intent is None:
        raise NothingGenerated("MODEL_UNAVAILABLE: no intent model configured")
    # One setting per change (expectrail/jit/offer.py): a model told about more than this run offers, or
    # less, would make the record say one thing and the prompt another. An intent that states none is a
    # test double or predates the setting.
    told = getattr(intent, "offer", None)
    if told is not None and told != offer:
        raise NothingGenerated(f"OFFER_MISMATCH: the intent was given offer {str(told)[:40]!r}, and this run is {offer!r}")
    # The same for the candidate: an intent that would put the patch in its prompt cannot serve a run that
    # records it as withheld, nor the other way round. One that states nothing is a test double.
    saw = getattr(intent, "candidate", None)
    if saw is not None and saw != candidate_to_model:
        raise NothingGenerated(f"CANDIDATE_MISMATCH: the intent has the candidate {str(saw)[:20]!r}, "
                               f"and this run has it {candidate_to_model!r}")
    from expectrail.jit import intent as intent_mod

    est_prompt = intent_mod.estimate_prompt_tokens(getattr(intent, "system", ""), intent_mod.prompt(
        report, shown_text, dmap, profile, probes, offer=offer, candidate=candidate_to_model))
    spend.reserve(spend.spark_cost(est_prompt, intent_mod.RESERVED_COMPLETION_TOKENS), "the intent call")
    try:
        answer = intent(report, shown_text, dmap, profile, probes)
    except intent_mod.IntentUnavailable as exc:
        spend.add_spark(est_prompt, 0)  # a failed call is charged for its prompt, conservatively
        raise NothingGenerated(str(exc)) from exc
    usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}

    def tokens(value, fallback: int) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else fallback

    # A revised proposal carries the first round's replays (expectrail/jit/intent.py, revise_to_file):
    # its usage already sums both model calls, so the one budget covers the whole change.
    prior = answer.get("prior")
    if prior:
        spend.replay_usd += prior["replayUsd"]
        spend.replays += prior["replays"]
        diagnostics.append(f"revision: includes the first round's {prior['replays']} replays")
    # Unknown completion tokens are charged as the full reservation, never as zero.
    spend.add_spark(tokens(usage.get("promptTokens"), est_prompt),
                    tokens(usage.get("completionTokens"), intent_mod.RESERVED_COMPLETION_TOKENS))
    sha = answer.get("promptSha256")
    state["promptSha256"] = sha if isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha) else None
    diagnostics += [f"intent: {n}" for n in answer.get("diagnostics", [])]
    entries = answer["candidates"]

    routes: dict[str, tuple[dict, Path]] = {}
    route_dir = out / "jit-routes"
    route_dir.mkdir(exist_ok=True)
    for p in probes + answer.get("probes", []):
        if p["id"] in routes:
            continue
        try:
            route = compile_route(p["program"], name=p["id"], description=p["description"], actions=profile["actions"])
        except ProgramError as exc:
            diagnostics.append(f"probe {p['id']} refused by the route compiler: {exc}")
            continue
        path = route_dir / f"jit-{p['id'].removeprefix('jit-')}.json"
        path.write_text(json.dumps(route, indent=1) + "\n", encoding="utf-8")
        routes[p["id"]] = (route, path)
    all_probes = [p for p in probes + answer.get("probes", []) if p["id"] in routes]
    allowed = set(dmap["probeIds"]) | {p["id"] for p in answer.get("probes", [])}
    plan = []
    for e in entries:
        ids = _probe_ids_for(e, all_probes, allowed)
        if not ids or any(i not in routes for i in ids):
            diagnostics.append(f"{e['spec']['id']}: applies to no probe that can run")
            continue
        plan.append((e, ids))
    state["proposed"] = [{"spec": e["spec"], "applies": e["applies"], "probeIds": ids} for e, ids in plan]
    pixel_checks = list(answer.get("pixelChecks") or []) if offer_mod.offers_pixel(offer) else []
    needed = sorted({i for _, ids in plan for i in ids} | {c["probe"] for c in pixel_checks if c["probe"] in routes})
    state["probes"] = [{"id": pid, "source": next(p["source"] if "source" in p else "jit" for p in all_probes
                                                 if p["id"] == pid),
                        "routeSha256": digest_v1(routes[pid][0])} for pid in needed]
    if not plan and not pixel_checks:
        raise NothingGenerated("MODEL_OUTPUT_INVALID: no proposed check applies to a probe that can run")

    prints: dict[tuple[str, str, int], str] = {}

    def replay(name: str, patches: list[Path], pid: str, n: int, with_runner=None) -> dict:
        spend.reserve(spend.replay_estimate(), f"replay {name}/{pid}#{n}")
        route, path = routes[pid]
        run_dir = out / "jit-replays" / name / f"{pid}-{n}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        t0 = clock()
        try:
            (with_runner or runner)(path, run_dir, patches=patches)
            ep = from_run_dir(run_dir, route, episode_id=f"{name}-{pid}-{n}")
            prints[(name, pid, n)] = _sha_bytes((run_dir / "trace.json").read_bytes())
        except Exception as exc:  # noqa: BLE001 - rule 3
            raise ReplayFailed(f"REPLAY_ERROR: {name} {pid} run {n}: {type(exc).__name__}: "
                               f"{' '.join(str(exc).split())[:160]}") from exc
        finally:
            spend.add_replay(max(0.0, clock() - t0))
        spend.check_after(f"replay {name}/{pid}#{n}")
        return ep

    def runs_of(name: str, patches: list[Path], todo: list[tuple[dict, list[str]]], count: int,
                stop_early=None) -> dict[str, list[str]]:
        """{specId: [outcome per run]} for each check, replaying only the probes the checks need."""
        results: dict[str, list[str]] = {e["spec"]["id"]: [] for e, _ in todo}
        active = list(todo)
        for n in range(1, count + 1):
            pids = sorted({i for _, ids in active for i in ids})
            eps = {pid: replay(name, patches, pid, n) for pid in pids}
            for e, ids in active:
                results[e["spec"]["id"]].append(_evaluate(e, ids, eps))
            if stop_early:
                active = [(e, ids) for e, ids in active if not stop_early(results[e["spec"]["id"]])]
            if not active:
                break
        return results

    # 1. Reference: a check that does not pass on the first run is dropped before any more replays.
    ref = runs_of("reference", [], plan, reps, stop_early=lambda rs: rs[-1] != "pass")
    on_ref = [(e, ids) for e, ids in plan if assess.all_of(ref[e["spec"]["id"]], "pass", reps)]

    # 2. Near-miss variants: one run each, then confirm kills to reps runs. The base build (the game the
    #    bug report describes, without the candidate) is the first near miss of any fix; its runs also
    #    label a catch strong or weak.
    vlist = variants_fn(candidate, base_patches) if variants_fn else _variants(game, base_patches, candidate, variant_limit)
    # The candidate's behaviour on each probe the surviving checks use, once: a generated near miss that
    # behaves exactly like the candidate (a partial revert that only undoes a comment, a mutant of dead
    # code) is no near miss, and a check would "kill" it just by catching the candidate (review of #231).
    cand_print: dict[str, str] = {}
    if on_ref and vlist:
        for pid in sorted({i for _, ids in on_ref for i in ids}):
            replay("candidate-print", [*base_patches, candidate], pid, 1)
            cand_print[pid] = prints[("candidate-print", pid, 1)]
    vdir = out / "jit-variants"
    vdir.mkdir(exist_ok=True)
    variant_results: dict[str, dict[str, list[str]]] = {e["spec"]["id"]: {} for e, _ in plan}
    planned: list[tuple[dict, list[Path], str]] = []
    if base_patches:
        planned.append(({"id": "base", "kind": "base", "file": "", "line": 0},
                        list(base_patches), _sha_bytes(b"".join(Path(p).read_bytes() for p in base_patches))))
    for k, v in enumerate(vlist):
        vpath = Path(v["path"]) if v.get("path") else vdir / f"jit-variant-{k + 1}.patch"
        if not v.get("path"):
            vpath.write_text(v["patchText"], encoding="utf-8")
        planned.append((v, [*base_patches, candidate, vpath], _sha_bytes(vpath.read_bytes())))
    for k, (v, patches, sha) in enumerate(planned):
        state["variants"].append({"id": v["id"], "kind": v["kind"], "file": v.get("file", ""),
                                  "line": v.get("line", 0), "patchSha256": sha})
        if not on_ref:
            continue
        vname = "base" if v["kind"] == "base" else f"variant-{k}"
        res = runs_of(vname, patches, on_ref, reps, stop_early=lambda rs: rs[-1] != "fail")
        same: list[str] = []
        for e, ids in on_ref:
            sid = e["spec"]["id"]
            # The base build stays a near miss even when the candidate behaves like it: a check that fails
            # on the bug is meaningful, and a "fix" that behaves like the bug is what a catch is for.
            if v["kind"] != "base" and cand_print and all(
                    prints.get((vname, pid, 1)) == cand_print.get(pid) for pid in ids):
                same.append(sid)
                continue
            variant_results[sid][v["id"]] = res[sid]
        if same:
            state["variants"][-1]["sameAsCandidateFor"] = sorted(same)

    # 3. Validity, then the candidate for the valid checks.
    valid_plan = []
    for e, ids in plan:
        sid = e["spec"]["id"]
        verdict = assess.validity(ref[sid], variant_results[sid], reps)
        state["validity"].append({"specId": sid, "valid": verdict["valid"], "reference": ref[sid],
                                  "killed": verdict["killed"], "reasons": verdict["reasons"], "candidate": []})
        if verdict["valid"]:
            valid_plan.append((e, ids))
    cand = runs_of("candidate", [*base_patches, candidate], valid_plan, reps) if valid_plan else {}
    rows = {v["specId"]: v for v in state["validity"]}
    caught = []
    for e, ids in valid_plan:
        sid = e["spec"]["id"]
        rows[sid]["candidate"] = cand[sid]
        outcome = assess.catch(True, cand[sid], reps)
        rows[sid]["outcome"] = outcome
        if outcome == "catch":
            caught.append((e, ids))
    for v in state["validity"]:
        v.setdefault("outcome", "not-evaluated")

    if pixel_checks:
        _pixel_stage(pixel_checks, routes, base_patches, candidate, out, replay, spend, reps, state, diagnostics)

    # 4. Label each catch from the base build's runs (step 2), never from anything a model said.
    for e, ids in caught:
        sid = e["spec"]["id"]
        base_runs = variant_results[sid].get("base") if base_patches else None
        state["catches"].append({
            "specId": sid, "statement": e["spec"]["statement"], "claimId": e["spec"]["expectationRef"]["claimId"],
            "strength": assess.strength(base_runs, e["spec"]["expectationRef"]["claimId"], approved_claims, reps),
            "probeIds": ids, "candidate": cand[sid], "base": base_runs, "killed": rows[sid]["killed"],
        })


def _pixel_stage(checks: list[dict], routes: dict, base_patches: list, candidate: Path, out: Path, replay,
                 spend: Spend, reps: int, state: dict, diagnostics: list[str]) -> None:
    """Judge the proposal's pixel checks (#286): replay with frames, ask the observer, keep by the keep rule,
    then the candidate for a kept check. The rows go to ``state["pixelChecks"]``; a replay that fails ends
    the run (rule 3), and an observer that fails or answers badly drops the checks on that probe."""
    from expectrail.jit import pixel

    observer, frame_runner = state["pixel"]["observer"], state["pixel"]["frameRunner"]
    bindings = pixel.bindings_for()
    rows: dict[str, dict] = {}

    def not_run(check, why):
        rows[check["id"]] = pixel.record_row(check, "not-run", why)

    by_probe: dict[str, list[dict]] = {}
    for check in checks:
        if observer is None:
            not_run(check, "no observer was given to this run, so nothing on the screen can be judged")
        elif frame_runner is None:
            not_run(check, "no runner that captures frames was given to this run")
        elif getattr(observer, "name", None) != check["observer"]:
            not_run(check, f"the check names {check['observer']}, and this run's observer is "
                           f"{str(getattr(observer, 'name', None))[:40]}")
        elif not base_patches:
            not_run(check, "no bug build: a pixel check is kept only where it fails on the build the report describes")
        elif check["probe"] not in routes:
            not_run(check, f"probe {check['probe']} cannot be run")
        else:
            by_probe.setdefault(check["probe"], []).append(check)

    price = spend.prices["samUsdPerImage"]
    held = 0.0  # observer images reserved and not yet sent, across probes
    for pid, group in sorted(by_probe.items()):
        route = routes[pid][0]
        try:
            planned = [int(n) for n in observer.frames(route)]
        except Exception as exc:  # noqa: BLE001 - an observer that cannot say what it will ask is not asked
            for check in group:
                not_run(check, f"the observer could not say which frames it would ask about ({type(exc).__name__})")
            continue
        # One image a planned frame, on reps runs of each of the clean game, the bug build and the candidate.
        usd = len(planned) * 3 * reps * price
        try:
            spend.reserve(held + usd, f"pixel checks on {pid} ({observer.name})")
        except OutOfBudget as exc:
            for check in group:
                not_run(check, str(exc))
            continue
        held += usd

        def runs_on(name: str, patches: list) -> list[tuple[dict, dict]]:
            nonlocal held
            pairs = []
            for n in range(1, reps + 1):
                replay(name, patches, pid, n, with_runner=frame_runner)
                setting, run, images = pixel.observe(observer, out / "jit-replays" / name / f"{pid}-{n}", route)
                spend.sam_images += images
                spend.sam_usd += images * price
                held = max(0.0, held - images * price)
                spend.check_after(f"observer on {name}/{pid}#{n}")
                pairs.append((setting, run))
            return pairs

        try:
            clean = runs_on("pixel-reference", [])
            bug = runs_on("pixel-base", list(base_patches))
        except pixel.PixelError as exc:
            for check in group:
                rows[check["id"]] = pixel.record_row(check, "dropped", f"observer: {exc}", usd / len(group))
            continue
        except OutOfBudget as exc:
            # The trace checks' results stand; the pixel checks left are not run, and nothing more is asked.
            for check in [c for g in by_probe.values() for c in g if c["id"] not in rows]:
                not_run(check, str(exc))
            break
        cand_pairs = None
        for check in group:
            verdict = pixel.keep(check, clean, bug, bindings, reps)
            settings = {json.dumps(s, sort_keys=True) for s, _ in [*clean, *bug]}
            setting = clean[0][0] if len(settings) == 1 else None
            if not verdict["kept"]:
                rows[check["id"]] = pixel.record_row(check, "dropped", verdict["reason"], usd / len(group), setting,
                                                     verdict["runs"]["clean"], verdict["runs"]["bug"])
                continue
            if cand_pairs is None:
                try:
                    cand_pairs = runs_on("pixel-candidate", [*base_patches, candidate])
                except (pixel.PixelError, OutOfBudget) as exc:
                    cand_pairs = pixel.PixelError(str(exc))
            if isinstance(cand_pairs, pixel.PixelError):
                rows[check["id"]] = pixel.record_row(check, "kept", verdict["reason"], usd / len(group), setting,
                                                     verdict["runs"]["clean"], verdict["runs"]["bug"],
                                                     outcome="needs-review")
                diagnostics.append(f"{check['id']}: the candidate was not judged: observer: {cand_pairs}"[:200])
                continue
            if {json.dumps(s, sort_keys=True) for s, _ in cand_pairs} != settings:
                cand = [{"result": "needs-review"} for _ in cand_pairs]
            else:
                cand = [pixel.judge(check, r, bindings) for _, r in cand_pairs]
            results = [c["result"] for c in cand]
            outcome = ("catch" if len(results) == reps and all(r == "fail" for r in results)
                       else "needs-review" if any(r == "needs-review" for r in results) else "no-catch")
            rows[check["id"]] = pixel.record_row(check, "kept", verdict["reason"], usd / len(group), setting,
                                                 verdict["runs"]["clean"], verdict["runs"]["bug"], cand, outcome)
    state["pixelChecks"] = [rows[c["id"]] for c in checks]


def _variants(game, base_patches, candidate, limit):
    from expectrail.jit import dodgy
    from harness.run import REPO

    return dodgy.variants(Path(game) if game else REPO / "game" / "platformer", base_patches, candidate, limit=limit)


def gate_summary(doc: dict | None, *, max_rows: int = 10) -> dict:
    """The small, closed block the gate record carries (contracts/findings.schema.json generatedChecks).
    ``None`` (JiT not run) gives ``not-run``. Counts come from the record's rows, never its own counts."""
    if doc is None:
        return {"status": "not-run", "reason": None, "proposed": 0, "valid": 0, "strong": 0, "weak": 0,
                "catches": [], "runSha256": None}
    validate_v1(doc, "jit-run")
    ran = doc["status"] == "complete"
    catches = doc["catches"] if ran else []
    order = sorted(catches, key=lambda c: (c["strength"] != "strong", c["specId"]))
    return {"status": "ran" if ran else "nothing-generated", "reason": doc["reason"],
            "proposed": len(doc["proposed"]), "valid": sum(1 for v in doc["validity"] if v["valid"]),
            "strong": sum(1 for c in catches if c["strength"] == "strong"),
            "weak": sum(1 for c in catches if c["strength"] == "weak"),
            "catches": [{"specId": c["specId"], "statement": c["statement"][:200], "strength": c["strength"]}
                        for c in order[:max_rows]],
            "runSha256": digest_v1(doc)}


def from_base_alone(doc: dict) -> dict:
    """Which of a record's checks reproduce the reported bug, and whether they were derived without the
    candidate (issue #285, step 6; the first condition of #271).

    ``candidate`` is the record's ``settings.candidate`` (``shown`` when the record predates it).
    ``reproducing`` lists the checks that passed on the clean game ``reps`` times of ``reps`` and failed
    on the bug build as many times (the base near miss in the check's ``killed``, which holds only a
    near miss every run of which failed). ``fromBaseAlone`` lists those of them proposed with the
    candidate withheld: with the candidate shown it is empty, whatever the checks did, because the fix
    could have shaped them. A record that did not complete reproduces nothing.

    Only for a record with ``pixelChecks`` (#286; the pixel setting): ``pixelReproducing`` lists the
    pixel checks the keep rule keeps on the record's own runs (``pixel.kept_rows``): they passed on the
    clean game and failed on the bug build ``reps`` times each, under one observer setting. ``pixelFromBaseAlone`` is the same list when the
    candidate was withheld, and empty otherwise.

    Read from the record's rows, never its counts; the record is checked against its schema first."""
    from expectrail.jit import pixel
    from expectrail.jit.intent import of_record_candidate

    validate_v1(doc, "jit-run")
    candidate = of_record_candidate(doc["settings"].get("candidate"))
    reps = doc["settings"]["reps"]
    base_ids = {v["id"] for v in doc["variants"] if v["kind"] == "base"}
    reproducing = []
    if doc["status"] == "complete" and base_ids:
        reproducing = sorted(v["specId"] for v in doc["validity"]
                             if assess.all_of(v["reference"], "pass", reps) and base_ids & set(v["killed"]))
    out = {"candidate": candidate, "reproducing": reproducing,
           "fromBaseAlone": reproducing if candidate == "withheld" else []}
    if "pixelChecks" in doc:
        pixel_reproducing = sorted(row["check"]["id"] for row in pixel.kept_rows(doc)) if base_ids else []
        out.update(pixelReproducing=pixel_reproducing,
                   pixelFromBaseAlone=pixel_reproducing if candidate == "withheld" else [])
    return out
