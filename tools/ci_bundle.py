"""Capture public replays and judge the immutable bundle against the base policy."""
import json
import os
import re
import shutil
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from agents import export_scan
from expectrail import contracts
from expectrail.gate import record, verify
from tools import outside_vision as evidence

FORMAT = "expectrail.ci-bundle/v1"
SCHEMA = "ci-bundle.v1"
MAX_BYTES = 512 * 1024**2
MAX_FILES = 32768


@dataclass
class Policy:
    game: str
    specs: str
    routes: list[str]

    @classmethod
    def configured(cls):
        return cls(verify.safe_relative(os.environ["GAME"], "game", root_ok=True),
                   verify.safe_relative(os.environ["SPECS"], "specs"),
                   [verify.safe_relative(r, "route", glob=True) for r in os.environ["ROUTES"].splitlines() if r])


def groups(intent):
    count = record.REPAIR_RUNS if intent == "fix" else 1
    return [f"{side}-{n}" for side in ("base", "head") for n in range(1, count + 1)]


def routes_for(checks, folder):
    if checks.problems or not checks.routes or not checks.specs:
        raise ValueError("the base needs readable routes and approved checks")
    folder.mkdir()
    routes = {}
    for name, data, digest in checks.routes:
        path = folder / (digest + ".json")
        path.write_bytes(data)
        routes[digest] = path
    return routes


def capture(policy, base, head, pr, intent, archive, replay=verify.harness_replay):
    if pr.get("fixLinks") and intent != "fix":
        raise ValueError("closing-keyword links require fix capture")
    checks = verify.read_checks(base, policy.specs, policy.routes, "base")
    mine = verify.read_checks(head, policy.specs, policy.routes)
    names_by_digest = {}
    for name, _data, digest in checks.routes:
        names_by_digest.setdefault(digest, set()).add(name)
    label_paths_by_digest = {digest: verify.label_paths_for(checks.specs, names)
                             for digest, names in names_by_digest.items()}
    changed = {"specs": verify.changed_count(mine.spec_entries, checks.spec_entries),
               "routes": verify.changed_count(mine.route_entries, checks.route_entries)}
    manifest = {"format": FORMAT, "writerRef": pr["baseSha"], "pullRequest": pr, "intent": intent,
                "checksSha256": checks.digest, "changed": changed, "runs": []}
    with tempfile.TemporaryDirectory(dir=archive.parent) as tmp:
        root = Path(tmp)
        routes = routes_for(checks, root / "routes")
        staged = root / "capture.zip"
        with zipfile.ZipFile(staged, "x", zipfile.ZIP_STORED) as out:
            for group in groups(intent):
                checkout = base if group.startswith("base-") else head
                game = checkout / policy.game
                if not game.resolve().is_relative_to(checkout.resolve()):
                    raise ValueError("game folder leaves its checkout")
                tree = verify.game_tree(game, checkout)
                for digest, route in routes.items():
                    folder = root / group / digest
                    label_paths = label_paths_by_digest[digest]
                    options = {"label_paths": label_paths} if label_paths else {}
                    replay(route, game, folder, True, sandbox="require", checkouts=(checkout,), **options)
                    run = evidence.saved_run(folder, route)
                    if run["tree"] != tree:
                        raise ValueError("captured a different game tree")
                    paths = [folder / "trace.json", folder / "replay.json", *sorted(run["framesDir"].iterdir())]
                    if any(row["level"] == "error" for row in export_scan.scan(paths)):
                        raise ValueError("public capture failed the export scan")
                    if out.fp.tell() + sum(p.stat().st_size for p in paths) > MAX_BYTES or len(out.filelist) + len(paths) >= MAX_FILES:
                        raise ValueError("capture exceeds the bundle limits")
                    manifest["runs"].append({"group": group, "route": digest, "replay": run["replaySha256"]})
                    for path in paths:
                        out.write(path, path.relative_to(root))
                    shutil.rmtree(folder)
            contracts.validate(manifest, SCHEMA)
            out.writestr("manifest.json", json.dumps(manifest))
        if staged.stat().st_size > MAX_BYTES:
            raise ValueError("capture exceeds bundle size limit")
        archive.hardlink_to(staged)


def unpack(archive, root):
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError("bundle exceeds size limit")
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_BYTES:
            raise ValueError("bundle exceeds extraction limits")
        for entry in entries:
            name = entry.orig_filename
            if name == "manifest.json" or name.endswith("/replay.json"):
                cap = 1024**2
            elif name.endswith("/trace.json"):
                cap = 64 * 1024**2
            else:
                cap = 32 * 1024**2
            valid = re.fullmatch(r"(?:base|head)-[1-3]/[0-9a-f]{64}/(?:replay\.json|trace\.json|frames/f[0-9]{8}\.png)", name)
            if (not valid and name != "manifest.json" or entry.file_size > cap
                    or entry.compress_type != zipfile.ZIP_STORED
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
                raise ValueError("unexpected archive member, encoding or size")
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as target, source.open(entry) as stream:
                shutil.copyfileobj(stream, target)


class Attempts(verify.SavedReplays):
    """Dispatch each repetition requested by the shared repair rule to its own saved run."""
    def __call__(self, route, game, out, frames, *, label_paths=()):
        side, _, repeat = out.parent.name.partition("-run")
        options = {"label_paths": label_paths} if label_paths else {}
        return self.runs[f"{side}-{repeat or '1'}"](route, game, out, frames, **options)


def judge(policy, base, pr, intent, archive, out, observer, *, head_checkout):
    # The saved runs are looked up by game folder, and the gate names the base's folder by its
    # resolved path. Both are spelled the same way here, so a checkout or temporary folder reached
    # through a link (every temporary folder on macOS) is not read as "no Godot project" (#378).
    base = Path(base).resolve()
    checks = verify.read_checks(base, policy.specs, policy.routes, "base")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        data, head = root / "data", root / "head-policy"
        try:
            unpack(archive, data)
            manifest = record.strict_loads(evidence.read(data / "manifest.json", 1024**2).decode())
            if isinstance(manifest, dict) and (manifest.get("format") != FORMAT or manifest.get("writerRef") != pr["baseSha"]):
                raise ValueError("writer and reader versions differ; pin both to the same base commit")
            contracts.validate(manifest, SCHEMA)
            if manifest['pullRequest'].get('fixLinks') and manifest['intent'] != 'fix':
                raise ValueError('closing-keyword links require fix capture')
            if manifest["pullRequest"] != pr or manifest["intent"] != intent or manifest["checksSha256"] != checks.digest:
                raise ValueError("pull request, commit, intent or base policy differs")
            routes = routes_for(checks, root / "routes")
            listed = {(e["group"], e["route"]): e["replay"] for e in manifest["runs"]}
            expected = {(g, r) for g in groups(intent) for r in routes}
            if set(listed) != expected or len(expected) != len(manifest["runs"]):
                raise ValueError("missing, duplicate or unexpected replay")
            evidence.directory(data, ["manifest.json", *groups(intent)])
            # Only this digest comes from the head checkout. The gate still receives the
            # logical head folder, saved replays and trusted base policy.
            trees = {base / policy.game: verify.game_tree(base / policy.game, base),
                     head / policy.game: verify.game_tree(head_checkout / policy.game, head_checkout)}
            arms = {}
            for group in groups(intent):
                evidence.directory(data / group, routes)
                game = (base if group.startswith("base-") else head) / policy.game
                runs = {}
                for digest, route in routes.items():
                    folder = data / group / digest
                    evidence.directory(folder, ("replay.json", "trace.json", "frames"))
                    run = evidence.saved_run(folder, route)
                    if listed[group, digest] != run["replaySha256"]:
                        raise ValueError("replay digest differs")
                    if trees[game] != run["tree"]:
                        side = group.split("-")[0]
                        raise ValueError(f"{side} game tree differs from the checkout")
                    ticks = json.loads(route.read_bytes())["ticks"]
                    trace = run["trace"]
                    if (trace["ticks"] != ticks or len(trace["rows"]) != ticks
                            or any(row["tick"] != i for i, row in enumerate(trace["rows"]))):
                        raise ValueError("replay did not cover the route's ticks")
                    need = verify.window_frames({}, ticks, trace)
                    if not need or verify.captured_frames(run["framesDir"]) != set(need):
                        raise ValueError("replay did not capture exactly the route's frames")
                    size = None
                    for frame in need:
                        with (run["framesDir"] / f"f{frame:08d}.png").open("rb") as image:
                            header = image.read(24)
                        if (len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n"
                                or header[8:16] != b"\x00\x00\x00\x0dIHDR"):
                            raise ValueError("frame has no valid PNG dimensions")
                        dimensions = struct.unpack(">II", header[16:24])
                        if not all(dimensions):
                            raise ValueError("frame has invalid PNG dimensions")
                        if size is not None and dimensions != size:
                            raise ValueError("frame resolution changed during the route")
                        size = dimensions
                    runs[game, digest] = run
                arms[group] = verify.SavedReplays(trees, runs)
        except (OSError, ValueError, LookupError, TypeError, RuntimeError, zipfile.BadZipFile) as exc:
            raise ValueError(f"EVIDENCE_MISMATCH: {str(exc)[:240]}") from exc
        return verify.run_gate(repo=head, base=base, game=policy.game, routes=policy.routes, specs=policy.specs,
                               checks=checks, work=root / "work", out=out, replay=Attempts(trees, arms),
                               rule=record.BOTH, visual=observer, pr=pr, expectrail_commit=pr["baseSha"],
                               require_sandbox=True, intent=intent, changed_checks=manifest["changed"],
                               # `head` is a name for the saved replays, not a folder: the head's project
                               # config is compared from the real head checkout, whose tree was matched above.
                               head_config_game=Path(head_checkout).resolve() / policy.game)


if __name__ == "__main__":
    import sys
    from expectrail.gate.intent import of_pull_request, pull_request_metadata
    pr = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())["pull_request"]
    capture(Policy.configured(), Path.cwd(), Path(sys.argv[1]), pull_request_metadata(pr),
            of_pull_request(pr).intent, Path(sys.argv[2]))
