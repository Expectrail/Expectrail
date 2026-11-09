"""Generate single-edit mutants of the clean game, and the oracle that says which ones show.

Nobody picks a case (#127): this enumerates every possible single edit, then samples with the seed
committed in the pre-registration (bench/mutation/preregistration.json). Only the generator, the seed
and the manifest are committed; a mutant's patch is regenerated from them, never edited by hand.

The steps, the scale factor, the seed, the sample size and the thresholds are the pre-registration's,
and a person sets them. This file holds no defaults for them, on purpose.

Operator classes, as #127 lists them:
  - numeric: ``position``, ``offset`` and ``scale`` per axis, and ``z_index``, plus or minus a step;
  - boolean: ``visible``, ``disabled`` and ``one_way_collision`` flipped;
  - collision-bit: one bit of ``collision_layer`` or ``collision_mask`` flipped;
  - code: a comparison flipped, a sign flipped, or a constant scaled in player.gd and enemy.gd;
  - resource-path: an external resource pointed at a file that does not exist. Its uid goes too, or
    Godot finds the file by uid and nothing breaks (bugs/missing-texture/v1.patch learned this).

    python3 -m agents.mutate_game --sites                       # what each operator can reach
    python3 -m agents.mutate_game --manifest bench/mutation/generated/manifest.json
    python3 -m agents.mutate_game --patch <mutant id> --out runs/m.patch

The oracle compares a replay with the clean game's: its engine record (positions, facing, shots,
enemies) and its frames. It only knows "differs from the clean game".
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

from harness.run import REPO, tree_digest

GAME = REPO / "game" / "platformer"
MANIFEST_FORMAT = "expectrail.mutation-manifest/v0"
PREREGISTRATION = REPO / "bench" / "mutation" / "preregistration.json"
OPERATOR_CLASSES = ("numeric", "boolean", "collision-bit", "code", "resource-path")
STEPS = ("positionStep", "offsetStep", "scaleStep", "zIndexStep", "constantScale", "collisionBits")
CODE_FILES = ("player/player.gd", "enemy/enemy.gd")
HUMAN_FIELDS = ("wrongFix.commentOnlyLabel", "wrongFix.publicSamRuleApprovedBy",
                "generator.seed", "generator.sampleSize", "generator.sampling", "generator.samplingWhy",
                "generator.positionStep", "generator.offsetStep",
                "generator.scaleStep", "generator.zIndexStep", "generator.constantScale", "generator.collisionBits",
                "oracle.traceThresholdPx", "oracle.frameThreshold", "stopRule", "agreement.seed",
                "agreement.minimum", "reportTemplate", "pins")

_NUMBER = r"-?\d+(?:\.\d+)?(?:e-?\d+)?"
_VECTOR = re.compile(rf"^(position|offset|scale) = Vector2\(({_NUMBER}), ({_NUMBER})\)$")
_Z_INDEX = re.compile(r"^z_index = (-?\d+)$")
_BOOLEAN = re.compile(r"^(visible|disabled|one_way_collision) = (true|false)$")
_BITS = re.compile(r"^(collision_layer|collision_mask) = (\d+)$")
_RESOURCE = re.compile(r'^\[ext_resource (?P<head>.*?)(?: uid="[^"]*")? path="(?P<path>res://[^"]+)"(?P<tail>.*)\]$')
_CONST = re.compile(rf"^const (\w+) = ({_NUMBER})$")
_COMPARE = re.compile(r" (<=|>=|==|!=|<|>) ")
_NEGATED = re.compile(r"= -([A-Z][A-Z_]*)\b")
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "!=", "!=": "=="}


MIN_AGREEMENT = 20


class PreregistrationError(RuntimeError):
    pass


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _get(doc: dict, dotted: str):
    for part in dotted.split("."):
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def missing_decisions(doc: dict) -> list[str]:
    """The human-only fields still empty in a pre-registration. Blank text is empty; a 0 is a decision."""
    return [f for f in HUMAN_FIELDS if _get(doc, f) is None or str(_get(doc, f)).strip() == ""]


def load_preregistration(path: Path | None = None, root: Path = REPO) -> dict:
    """The pre-registration, refused while a person's decision is missing or a pin has moved.

    The registration describes the code at commit c169a5e, the baseline: judged runs check
    that commit out, so their pins match. On main the pinned files may change, and then this refuses,
    naming the commit. `root` is the checkout whose files are compared with the pins (tests pass an
    extract of the commit)."""
    path = path or PREREGISTRATION
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = missing_decisions(doc)
    if missing:
        raise PreregistrationError(f"{path} is not complete, so nothing may be judged. Missing: {', '.join(missing)}")
    if doc["wrongFix"]["commentOnlyLabel"] not in ("good", "bad"):
        raise PreregistrationError(f"{path}: wrongFix.commentOnlyLabel must be good or bad")
    problem = sampling_problem(doc["generator"])
    if problem:
        raise PreregistrationError(f"{path}: {problem}")
    problem = values_problem(doc)
    if problem:
        raise PreregistrationError(f"{path}: {problem}")
    if not _whole(doc["agreement"]["minimum"]) or doc["agreement"]["minimum"] < MIN_AGREEMENT:
        raise PreregistrationError(f"{path}: agreement.minimum must be at least {MIN_AGREEMENT} (#127)")
    moved = sorted(k for k, v in current_pins(root).items() if doc["pins"].get(k) != v)
    if moved:
        raise PreregistrationError(
            f"{path}: pinned material changed since registration: {', '.join(moved)}. The mutation bench is "
            f"registered against commit {REGISTERED_COMMIT}, the baseline; judged runs check it out "
            "(bench/mutation/README.md, Reproducing the bench).")
    doc["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return doc


def _sha(rel: str, root: Path = REPO) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


# The commit the registration's pins describe: the baseline. Main moves on; the bench reruns here.
REGISTERED_COMMIT = "c169a5e0da304773587304ed47bc8aabcec80da7"


# What a judged result depends on. If one of these moves after registration, the run refuses.
PINNED = ("agents/mutate_game.py", "agents/mutation_bench.py", "agents/verifier.py", "agents/observations.py",
          "agents/sam_observations.py", "agents/sam_health.py", "agents/sam_warm.py", "agents/gameplay.py",
          "agents/trace_checks.py", "agents/matrix.py", "agents/judge_bench.py", "agents/orchestrator.py",
          "expectrail/evaluator.py", "harness/run.py", "harness/godot/expectrail_harness.gd", "harness/get_godot.sh",
          "harness/routes/smoke.json", "agents/specs/player-stays-above-ground.json",
          "specs/player-always-visible.json", "specs/coins-visible.json", ".github/workflows/mutation-bench.yml")
# bugs/reported/ is Zayyad's (#120) and shapes nothing here, so only the development families are pinned.
PINNED_TREES = ("agents/fixtures/operators", "bugs/physics-fall-through", "bugs/sinking", "bugs/missing-texture",
                "bugs/layering")


def current_pins(root: Path = REPO) -> dict:
    return {"gameTree": tree_digest(root / GAME.relative_to(REPO)), **{rel: _sha(rel, root) for rel in PINNED},
            **{rel: tree_digest(root / rel) for rel in PINNED_TREES}}


def _fmt(value: float) -> str:
    """A number as a scene file writes it: no trailing .0, and no float noise from the arithmetic."""
    rounded = round(value, 6)
    return str(int(rounded)) if rounded == int(rounded) else repr(rounded)


def source_files(game: Path = GAME) -> list[str]:
    """Every file the generator reads, in order. The one statement of what the population can touch."""
    scenes = sorted(p.relative_to(game).as_posix() for p in game.rglob("*.tscn") if ".godot" not in p.parts)
    return scenes + list(CODE_FILES)


def _mutant(cls: str, rel: str, line_no: int, tag: str, before: str, after: str) -> dict:
    return {"id": f"{cls}:{rel}:{line_no}:{tag}", "class": cls, "file": rel, "line": line_no,
            "before": before, "after": after}


def _scene_mutants(rel: str, n: int, line: str, params: dict) -> list[dict]:
    out = []
    if m := _VECTOR.match(line):
        prop, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        step = params[f"{prop}Step"]
        for axis, sign in (("x", 1), ("x", -1), ("y", 1), ("y", -1)):
            nx, ny = (x + sign * step, y) if axis == "x" else (x, y + sign * step)
            out.append(_mutant("numeric", rel, n, f"{prop}.{axis}{'+' if sign > 0 else '-'}", line,
                               f"{prop} = Vector2({_fmt(nx)}, {_fmt(ny)})"))
    elif m := _Z_INDEX.match(line):
        z = int(m.group(1))
        for sign in (1, -1):
            out.append(_mutant("numeric", rel, n, f"z_index{'+' if sign > 0 else '-'}", line,
                               f"z_index = {z + sign * int(params['zIndexStep'])}"))
    elif m := _BOOLEAN.match(line):
        out.append(_mutant("boolean", rel, n, m.group(1), line,
                           f"{m.group(1)} = {'false' if m.group(2) == 'true' else 'true'}"))
    elif m := _BITS.match(line):
        for bit in range(int(params["collisionBits"])):
            out.append(_mutant("collision-bit", rel, n, f"{m.group(1)}.{bit}", line,
                               f"{m.group(1)} = {int(m.group(2)) ^ (1 << bit)}"))
    elif m := _RESOURCE.match(line):
        out.append(_mutant("resource-path", rel, n, "missing", line,
                           f'[ext_resource {m["head"]} path="{m["path"]}.missing"{m["tail"]}]'))
    return out


def _code_mutants(rel: str, n: int, line: str, params: dict) -> list[dict]:
    if line.lstrip().startswith("#"):
        return []
    out = []
    if m := _CONST.match(line):
        name, value = m.group(1), float(m.group(2))
        out.append(_mutant("code", rel, n, f"sign.{name}", line, f"const {name} = {_fmt(-value)}"))
        out.append(_mutant("code", rel, n, f"scale.{name}", line, f"const {name} = {_fmt(value * params['constantScale'])}"))
    for i, m in enumerate(_COMPARE.finditer(line)):
        out.append(_mutant("code", rel, n, f"compare.{i}", line,
                           line[:m.start()] + f" {_FLIP[m.group(1)]} " + line[m.end():]))
    for i, m in enumerate(_NEGATED.finditer(line)):
        out.append(_mutant("code", rel, n, f"sign.{i}", line, line[:m.start()] + f"= {m.group(1)}" + line[m.end():]))
    return out


def enumerate_mutants(params: dict, game: Path = GAME) -> list[dict]:
    """Every possible mutant, in a fixed order: sorted by file, then line, then operator."""
    found: list[dict] = []
    for rel in source_files(game):
        make = _code_mutants if rel in CODE_FILES else _scene_mutants
        for n, line in enumerate((game / rel).read_text(encoding="utf-8").splitlines(), 1):
            found += make(rel, n, line, params)
    ids = [m["id"] for m in found]
    if len(ids) != len(set(ids)):
        raise ValueError("two mutants share an id")
    return found


def sample(mutants: list[dict], seed: int, size: int) -> list[dict]:
    """A seeded sample, in enumeration order. A generator with fewer mutants gives all of them."""
    chosen = random.Random(seed).sample(range(len(mutants)), min(size, len(mutants)))
    return [mutants[i] for i in sorted(chosen)]


def values_problem(doc: dict) -> str | None:
    """A number that cannot do its job. A step of 0 makes mutants that change nothing, and a threshold
    that is not a number only fails once judging has started."""
    gen, oracle = doc["generator"], doc["oracle"]
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    for name in ("positionStep", "offsetStep", "scaleStep"):
        if not number(gen[name]) or gen[name] <= 0:
            return f"generator.{name} must be a number above 0"
    for name in ("zIndexStep", "collisionBits"):
        if not _whole(gen[name]) or gen[name] < 1:
            return f"generator.{name} must be a whole number, 1 or more"
    if not number(gen["constantScale"]) or gen["constantScale"] <= 0 or gen["constantScale"] == 1:
        return "generator.constantScale must be a number above 0, and not 1"
    if not number(oracle["traceThresholdPx"]) or oracle["traceThresholdPx"] < 0:
        return "oracle.traceThresholdPx must be a number, 0 or more"
    if not _whole(oracle["frameThreshold"]) or oracle["frameThreshold"] < 0:
        return "oracle.frameThreshold must be a whole number, 0 or more"
    if not _whole(doc["agreement"]["seed"]):
        return "agreement.seed must be a whole number"
    return None


def sampling_problem(gen: dict) -> str | None:
    """What is wrong with a sampling plan, or None. ``generator.sampling`` is a person's decision:
    ``{"method": "uniform"}``, or ``{"method": "stratified", "perClass": {<class>: <count>, ...}}``."""
    plan = gen.get("sampling")
    if not isinstance(plan, dict):
        return "generator.sampling must be an object with a method"
    if not _whole(gen.get("seed")):
        return "generator.seed must be a whole number"
    if not _whole(gen.get("sampleSize")) or gen["sampleSize"] < 1:
        return "generator.sampleSize must be a whole number, 1 or more"
    method = plan.get("method")
    if method == "uniform":
        return "generator.sampling: a uniform plan takes no perClass" if "perClass" in plan else None
    if method != "stratified":
        return f"generator.sampling.method must be uniform or stratified, not {method!r}"
    per_class = plan.get("perClass")
    if not isinstance(per_class, dict):
        return "generator.sampling.perClass: no classes"
    unknown = sorted(set(per_class) - set(OPERATOR_CLASSES))
    if unknown or not per_class:
        return f"generator.sampling.perClass: unknown or no classes: {unknown}"
    if any(not _whole(n) or n < 0 for n in per_class.values()):
        return "generator.sampling.perClass: every count must be a whole number, 0 or more"
    if sum(per_class.values()) != gen.get("sampleSize"):
        return f"generator.sampling.perClass adds up to {sum(per_class.values())}, not sampleSize {gen.get('sampleSize')}"
    return None


def draw(mutants: list[dict], gen: dict) -> list[dict]:
    """The sample the plan asks for, in enumeration order. A stratified plan draws each class with its
    own seeded generator, so a change to one class's count leaves the others' draws alone. A class
    with fewer mutants than its count gives all it has, and the manifest reports the shortfall; the
    rest is never moved to another class."""
    plan = gen["sampling"]
    if plan["method"] == "uniform":
        return sample(mutants, int(gen["seed"]), int(gen["sampleSize"]))
    chosen: set[str] = set()
    for cls, count in sorted(plan["perClass"].items()):
        pool = [m["id"] for m in mutants if m["class"] == cls]
        chosen.update(random.Random(f"{gen['seed']}:{cls}").sample(pool, min(count, len(pool))))
    return [m for m in mutants if m["id"] in chosen]


def patch_text(mutant: dict, game: Path = GAME) -> str:
    """The mutant as a unified diff against the clean game, regenerated from the game itself."""
    rel = mutant["file"]
    before = (game / rel).read_text(encoding="utf-8").splitlines(keepends=True)
    index = mutant["line"] - 1
    if before[index].rstrip("\n") != mutant["before"]:
        raise ValueError(f"{mutant['id']}: the game no longer has this line")
    after = list(before)
    after[index] = mutant["after"] + "\n"
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def excluded_mutants(prereg: dict) -> list[str]:
    return list((prereg.get("excludedBeforeDraw") or {}).get("mutants") or [])


def build_manifest(prereg: dict, game: Path = GAME) -> dict:
    gen = prereg["generator"]
    every = enumerate_mutants(gen, game)
    excluded = excluded_mutants(prereg)
    unknown = sorted(set(excluded) - {m["id"] for m in every})
    if unknown:
        raise PreregistrationError(f"excludedBeforeDraw names mutants the generator does not make: {unknown}")
    every = [m for m in every if m["id"] not in excluded]  # before the draw, whatever they did
    chosen = draw(every, gen)
    enumerated = {c: sum(m["class"] == c for m in every) for c in OPERATOR_CLASSES}
    sampled = {c: sum(m["class"] == c for m in chosen) for c in OPERATOR_CLASSES}
    asked = (gen["sampling"].get("perClass") or {})
    return {
        "format": MANIFEST_FORMAT,
        "gameTree": tree_digest(game),
        "generatorSha256": _sha("agents/mutate_game.py"),
        "seed": gen["seed"],
        "sampleSize": gen["sampleSize"],
        "sampling": gen["sampling"],
        "excludedBeforeDraw": sorted(excluded),
        "enumerated": len(every),
        "enumeratedByClass": enumerated,
        "sampled": len(chosen),
        "sampledByClass": sampled,
        "shortByClass": {c: n - sampled[c] for c, n in sorted(asked.items()) if n > sampled[c]},
        "shortOfSample": int(gen["sampleSize"]) - len(chosen),
        "mutants": [dict(m, patchSha256=hashlib.sha256(patch_text(m, game).encode()).hexdigest()) for m in chosen],
    }


def load_manifest(prereg: dict, path: Path) -> dict:
    """The committed manifest, refused unless the generator would write exactly this from this
    pre-registration. Mutants are regenerated, never edited by hand (#127)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc != build_manifest(prereg):
        raise PreregistrationError(f"{path} is not what the generator writes from the pre-registration")
    return doc


def mutant_by_id(manifest: dict, mutant_id: str) -> dict:
    found = [m for m in manifest["mutants"] if m["id"] == mutant_id]
    if not found:
        raise SystemExit(f"{mutant_id}: not in the manifest")
    return found[0]


def site_counts(game: Path = GAME) -> dict:
    """How many lines each operator can reach, whatever the steps: a fact about the game."""
    params = {"positionStep": 1, "offsetStep": 1, "scaleStep": 1, "zIndexStep": 1, "constantScale": 2,
              "collisionBits": 1}
    every = enumerate_mutants(params, game)
    tags: dict[str, int] = {}
    for m in every:
        name = m["id"].split(":")[3].split(".")[0].rstrip("+-")
        key = f"{m['class']}/{name}"
        tags[key] = tags.get(key, 0) + 1
    for name in ("visible", "disabled", "one_way_collision"):
        tags.setdefault(f"boolean/{name}", 0)
    return dict(sorted(tags.items()))


# ---------------------------------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------------------------------

def _points(row: dict, key: str) -> dict:
    return {int(p[0]): (float(p[1]), float(p[2])) for p in row.get(key) or []}


def _row_distance(a: dict, b: dict) -> float:
    """How far apart two rows of the engine record are, in world px; inf when they differ in kind."""
    if a.get("facing") != b.get("facing") or bool(a.get("player")) != bool(b.get("player")):
        return math.inf
    worst = 0.0
    if a.get("player"):
        worst = math.dist(a["player"][:2], b["player"][:2])
    for key in ("enemies", "projectiles"):
        pa, pb = _points(a, key), _points(b, key)
        if set(pa) != set(pb):
            return math.inf
        worst = max([worst] + [math.dist(pa[i], pb[i]) for i in pa])
    return worst


def trace_distance(clean: dict, other: dict) -> float:
    a, b = clean.get("rows") or [], other.get("rows") or []
    if len(a) != len(b):
        return math.inf
    return max((_row_distance(x, y) for x, y in zip(a, b)), default=0.0)


def frames_differing(clean: list[str], other: list[str]) -> int:
    return sum(x != y for x, y in zip(clean, other)) + abs(len(clean) - len(other))


def oracle(clean_trace: dict, clean_frames: list[str], trace: dict, frames: list[str], thresholds: dict) -> dict:
    """``visible`` or ``equivalent``, from the pre-registered thresholds. Strictly over a threshold."""
    distance, differing = trace_distance(clean_trace, trace), frames_differing(clean_frames, frames)
    visible = distance > float(thresholds["traceThresholdPx"]) or differing > int(thresholds["frameThreshold"])
    return {"category": "visible" if visible else "equivalent",
            "traceMaxPx": None if math.isinf(distance) else round(distance, 3),
            "traceDiffersInKind": math.isinf(distance),
            "framesDiffering": differing, "framesCompared": max(len(clean_frames), len(frames))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sites", action="store_true", help="what each operator can reach; needs no decisions")
    g.add_argument("--mutants-by-class", action="store_true",
                   help="how many mutants each class has at the pre-registration's steps; needs only those filled in")
    g.add_argument("--pins", action="store_true", help="print the current pins for the pre-registration")
    g.add_argument("--manifest", type=Path, help="write the sampled manifest here")
    g.add_argument("--patch", metavar="MUTANT_ID", help="regenerate one mutant's patch")
    p.add_argument("--prereg", type=Path, default=PREREGISTRATION)
    p.add_argument("--from-manifest", type=Path, default=PREREGISTRATION.parent / "generated" / "manifest.json")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.sites:
        print(json.dumps(site_counts(), indent=2))
        return 0
    if args.pins:
        print(json.dumps(current_pins(), indent=2))
        return 0
    if args.mutants_by_class:
        gen = json.loads(args.prereg.read_text(encoding="utf-8"))["generator"]
        empty = [k for k in STEPS if gen.get(k) is None]
        if empty:
            print(f"error: fill in these steps first: {', '.join(f'generator.{k}' for k in empty)}", file=sys.stderr)
            return 2
        every = enumerate_mutants(gen)
        print(json.dumps({c: sum(m["class"] == c for m in every) for c in OPERATOR_CLASSES}, indent=2))
        return 0
    if args.patch:
        manifest = json.loads(args.from_manifest.read_text(encoding="utf-8"))
        text = patch_text(mutant_by_id(manifest, args.patch))
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    try:
        manifest = build_manifest(load_preregistration(args.prereg))
    except PreregistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{manifest['sampled']} of {manifest['enumerated']} mutants: {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
