"""Local evidence-branch preparation, digest checking and the docs PR size guard.

No model, service or push. Only budget base discovery may fetch a public Git
commit in CI; prepare/verify themselves never access the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from expectrail.gate import record

LIMIT = 256 * 1024
BRANCH = "evidence-results"
MANIFEST = "evidence.manifest.json"
INDEX = "EVIDENCE.md"
EXEMPTIONS = "docs/evidence-exemptions.json"
REPOSITORY = "https://github.com/Expectrail/Expectrail"
# These paths are never evidence inputs, even when a parent folder is selected.
FORBIDDEN = {"heldout-set", "Expectrail-heldout"}


def git(root, *args, input=None):
    p = subprocess.run(["git", "-C", str(root), *args], input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise ValueError(f"git {args[0]}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def relative(value):
    if (not isinstance(value, str) or not value or len(value) > 500
            or any(c in value for c in "\\\n\r\t\x00")
            or PurePosixPath(value).is_absolute()
            or any(p in ("", ".", "..") for p in value.split("/"))
            or any(p in FORBIDDEN or p.startswith("fresh-") or "blind" in p.lower()
                   for p in value.split("/"))):
        raise ValueError(f"unsafe evidence path: {value!r}")
    return value


def safe_path(root, name):
    relative(name)
    root = Path(root).resolve()
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink is not evidence: {name}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"path leaves evidence root: {name}")
    return path


def file_list(root):
    """Do not follow links or even open prohibited material."""
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            rel = p.relative_to(root).as_posix()
            safe_path(root, rel)
            if not p.is_file() and not p.is_dir():
                raise ValueError(f"not a regular file: {rel}")
        result.extend((Path(base) / name).relative_to(root).as_posix() for name in files)
    return sorted(result)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch_command(commit):
    return f"git fetch --no-tags {REPOSITORY}.git {commit}"


def validate_document(doc, schema_name):
    schema = json.loads((ROOT / "contracts" / (schema_name + ".schema.json")).read_text())
    errors = record.errors(doc, schema)
    if errors:
        raise ValueError(f"invalid {schema_name}: " + "; ".join(errors))


def read_manifest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be a regular file, not a symlink")
    doc = record.read_json(path, label=MANIFEST)
    validate_document(doc, "evidence-manifest.v1")
    relative(doc["folder"])
    relative(doc["archive"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", doc["archive"].split("/")[0]) or doc["archive"].split("/", 1)[-1] != doc["folder"]:
        raise ValueError("archive must be a unique run id followed by the source folder")
    if doc["fetch"] != fetch_command(doc["commit"]):
        raise ValueError("manifest fetch command does not name its pinned commit")
    seen = set()
    for item in doc["files"]:
        name = relative(item["path"])
        if name in seen:
            raise ValueError(f"duplicate manifest path: {name}")
        seen.add(name)
    return doc


def anchor(name):
    return "file-" + sha(name.encode())[:20]


def index_text(doc):
    lines = ["# Recorded evidence", "", "Raw files live on the evidence branch; the summary stays on main.",
             "Verify the fetched bytes with the [manifest](evidence.manifest.json).", "",
             f"Evidence commit: `{doc['commit']}` on `{doc['branch']}`.", "", "```sh", doc["fetch"],
             f"python3 tools/evidence_storage.py verify {doc['folder']}/{MANIFEST} --git .", "```", "",
             "Paths below are relative to this folder. Sizes are bytes; digests are SHA-256.", ""]
    for item in doc["files"]:
        name = item["path"]
        url = f"{REPOSITORY}/blob/{doc['commit']}/{quote(doc['archive'] + '/' + name, safe='/')}"
        # HTML-escape arbitrary path labels rather than letting them become Markdown.
        import html
        lines.extend([f'<a id="{anchor(name)}"></a>', "",
                      f"- [{html.escape(name).replace('[', '&#91;').replace(']', '&#93;')}]({url}): "
                      f"{item['size']} bytes; `{item['sha256']}`.", ""])
    return "\n".join(lines)


# Keep destination rewriting deliberately narrow: only local Markdown links and
# HTML href/src attributes. A migration must audit other readers separately.
LINK = re.compile(r'(?P<md>!?\[[^\]\n]*\]\()(?P<mdurl>[^\s)]+)(?P<mdend>\))|'
                  r'(?P<html>\b(?:href|src)=["\'])(?P<htmlurl>[^"\']+)(?P<htmlend>["\'])')


def link_target(page, url, root):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path = (root / unquote(parsed.path).lstrip("/") if parsed.path.startswith("/")
            else page.parent / unquote(parsed.path))
    return Path(os.path.normpath(path))


def rewrite_links(root, doc):
    """Return edits for existing docs links; no file is changed here."""
    moved = {root / doc["folder"] / f["path"]: f["path"] for f in doc["files"]}
    edits = {}
    for page in sorted((root / "docs").rglob("*")):
        if page.suffix not in (".md", ".html") or page.is_symlink():
            continue
        # Never open excluded material or the files being archived.
        try:
            relative(page.relative_to(root).as_posix())
        except ValueError:
            continue
        if page in moved:
            continue
        old = page.read_text(encoding="utf-8")
        def replace(match):
            url = match["mdurl"] or match["htmlurl"]
            target = link_target(page, url, root)
            if target not in moved:
                return match[0]
            if match["html"] and match["html"].startswith("src="):
                raise ValueError(f"{page.relative_to(root)}: replace embedded {url} with a link before moving it")
            dest = os.path.relpath(root / doc["folder"] / INDEX, page.parent)
            dest = quote(dest, safe="/.") + "#" + anchor(moved[target])
            # An image now links to its archived original, rather than trying to
            # render the Markdown index as an image.
            return ((match["md"].lstrip("!") + dest + match["mdend"]) if match["md"]
                    else match["html"] + dest + match["htmlend"])
        new = LINK.sub(replace, old)
        if new != old:
            edits[page] = new
    return edits


def link_errors(root, manifest_path):
    doc = read_manifest(manifest_path)
    index = safe_path(root, doc["folder"] + "/" + INDEX)
    errors = []
    if not index.is_file() or index.read_text(encoding="utf-8") != index_text(doc):
        errors.append(f"{doc['folder']}/{INDEX}: index differs from manifest")
    moved = {root / doc["folder"] / f["path"] for f in doc["files"]}
    anchors = {anchor(f["path"]) for f in doc["files"]}
    for page in sorted((root / "docs").rglob("*")):
        if page.suffix not in (".md", ".html") or page.is_symlink():
            continue
        try:
            relative(page.relative_to(root).as_posix())
        except ValueError:
            continue
        for m in LINK.finditer(page.read_text(encoding="utf-8")):
            url = m["mdurl"] or m["htmlurl"]
            target = link_target(page, url, root)
            if target in moved:
                errors.append(f"{page.relative_to(root)}: stale link {url}")
            if target == index and urlsplit(url).fragment not in anchors | {""}:
                errors.append(f"{page.relative_to(root)}: missing evidence anchor {url}")
    return errors


def verify(manifest_path, *, tree=None, repo=None):
    """Name every missing, changed, unexpected or unsafe file; never run fetch."""
    doc = read_manifest(manifest_path)
    expected = {x["path"]: x for x in doc["files"]}
    errors = []
    if repo is not None:
        prefix = doc["archive"] + "/"
        listing = git(repo, "ls-tree", "-r", "-z", doc["commit"], "--", prefix)
        actual = {}
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            info, raw_name = entry.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            name = raw_name.decode()[len(prefix):]
            actual[name] = (mode, oid)
        def read(name):
            mode, oid = actual[name]
            if mode not in ("100644", "100755"):
                raise ValueError("not a regular file")
            return git(repo, "cat-file", "blob", oid)
    else:
        base = safe_path(Path(tree), doc["archive"])
        actual = {}
        # Enumerate without following links; report links individually.
        for directory, dirs, files in os.walk(base, followlinks=False):
            for name in dirs[:]:
                p = Path(directory) / name
                if p.is_symlink():
                    actual[p.relative_to(base).as_posix()] = None
                    dirs.remove(name)
            for name in files:
                actual[(Path(directory) / name).relative_to(base).as_posix()] = None
        def read(name):
            path = safe_path(base, name)
            if not path.is_file():
                raise ValueError("not a regular file")
            return path.read_bytes()
    for name in sorted(expected.keys() | actual.keys()):
        if name not in expected:
            errors.append(f"{name}: unexpected file")
            continue
        if name not in actual:
            errors.append(f"{name}: missing file")
            continue
        try:
            data = read(name)
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        item = expected[name]
        if len(data) != item["size"]:
            errors.append(f"{name}: size {len(data)}, expected {item['size']}")
        if sha(data) != item["sha256"]:
            errors.append(f"{name}: SHA-256 mismatch")
    return errors


def prepare(root, folder, batch, bundle, *, parent=None, new_branch=False):
    root = Path(root).resolve()
    relative(folder)
    if not folder.startswith("docs/") or folder == "docs/":
        raise ValueError("choose an evidence folder below docs/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", batch):
        raise ValueError("id must be lower-case letters, digits and hyphens (at most 80)")
    if bool(parent) == bool(new_branch):
        raise ValueError("choose --parent COMMIT or --new-branch, after checking the remote branch")
    if parent and not re.fullmatch(r"[0-9a-f]{40}", parent):
        raise ValueError("parent must be a full evidence commit")
    source = safe_path(root, folder)
    if not source.is_dir():
        raise ValueError("evidence folder does not exist")
    names = file_list(source)
    if not names or MANIFEST in names or INDEX in names:
        raise ValueError("folder is empty or already has a manifest/index")
    bundle = Path(bundle).resolve()
    if bundle.exists() or bundle.is_relative_to(source):
        raise ValueError("bundle must be a new path outside the evidence folder")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    archive = batch + "/" + folder
    items = [{"path": n, "size": (source / n).stat().st_size,
              "sha256": sha((source / n).read_bytes())} for n in names]
    with tempfile.TemporaryDirectory(prefix="expectrail-evidence-") as tmp:
        repo = Path(tmp)
        git(repo, "init", "-q", "-b", BRANCH)
        if parent:
            git(repo, "fetch", "--no-tags", str(root), parent)
            git(repo, "checkout", "-q", "-B", BRANCH, "FETCH_HEAD")
        if (repo / batch).exists() or (repo / batch).is_symlink():
            raise ValueError(f"evidence id already exists: {batch}")
        destination = repo / archive
        destination.mkdir(parents=True)
        for name in names:
            dst = destination / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, dst)
        git(repo, "add", "--", batch)
        git(repo, "-c", "user.name=Expectrail evidence", "-c", "user.email=noreply@openai.com",
            "-c", "commit.gpgsign=false", "commit", "-qm", f"Store evidence: {batch}")
        commit = git(repo, "rev-parse", "HEAD").decode().strip()
        doc = {"format": "expectrail.evidence-manifest/v1", "repository": REPOSITORY,
               "branch": BRANCH, "commit": commit, "sourceCommit": base,
               "folder": folder, "archive": archive, "fetch": fetch_command(commit), "files": items}
        temporary_manifest = repo / MANIFEST
        temporary_manifest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        read_manifest(temporary_manifest)
        problems = verify(temporary_manifest, repo=repo)
        if problems:
            raise ValueError("\n".join(problems))
        edits = rewrite_links(root, doc)
        git(repo, "bundle", "create", str(bundle), BRANCH, "HEAD")
        git(repo, "bundle", "verify", str(bundle))
        # No deletion until the bundle and all digests are verified. Recheck the
        # source too, so a concurrent writer cannot have its update removed.
        if file_list(source) != names or any(sha((source / f['path']).read_bytes()) != f['sha256'] for f in items):
            raise ValueError("source changed during preparation; bundle kept, source not removed")
        (source / MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (source / INDEX).write_text(index_text(doc), encoding="utf-8")
        for page, content in edits.items():
            page.write_text(content, encoding="utf-8")
        for name in names:
            (source / name).unlink()
        for directory in sorted((p for p in source.rglob('*') if p.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return doc


NO_BASE_EVENTS = ("schedule", "workflow_dispatch")


def base_commit(root, env=None):
    """Resolve the PR's immutable base, including in a shallow CI checkout.

    Returns None only for a scheduled or manual CI run, which has no change to charge.
    """
    env = os.environ if env is None else env
    if env.get("GITHUB_EVENT_PATH"):
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        value = event.get("pull_request", {}).get("base", {}).get("sha") or event.get("before")
        if not value or value == "0" * 40:
            # A scheduled or manual run has no pull request to charge; the limit is a PR rule.
            if env.get("GITHUB_EVENT_NAME") in NO_BASE_EVENTS:
                return None
            raise ValueError("CI event has no comparison base; cannot enforce evidence limit")
    else:
        try:
            value = git(root, "merge-base", "HEAD", "origin/main").decode().strip()
        except ValueError:
            parents = [line[7:] for line in git(root, "cat-file", "-p", "HEAD").decode().splitlines()
                       if line.startswith("parent ")]
            if not parents:
                raise ValueError("no comparison base; fetch origin/main or supply --base")
            value = parents[0]
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("comparison base is not a full commit")
    try:
        git(root, "cat-file", "-e", value + "^{commit}")
    except ValueError:
        if not env.get("GITHUB_EVENT_PATH"):
            raise ValueError(f"comparison base {value} missing; fetch it first") from None
        git(root, "fetch", "--no-tags", "--depth=1", "origin", value)
        git(root, "cat-file", "-e", value + "^{commit}")
    return value


def budget(root, base):
    """Charge full new bytes, not net growth. Only base-reviewed exemptions apply."""
    root = Path(root).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("base must be a full commit")
    changed = git(root, "diff", "--no-renames", "--name-only", "-z", base, "--", "docs/")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", "docs/")
    names = sorted({n.decode() for n in (changed + untracked).split(b"\0") if n})
    try:
        raw = git(root, "show", base + ":" + EXEMPTIONS)
    except ValueError:
        raw = b'{"format":"expectrail.evidence-exemptions/v1","files":[]}'
    policy = record.strict_loads(raw.decode("utf-8"))
    validate_document(policy, "evidence-exemptions.v1")
    exemptions = {}
    for item in policy["files"]:
        relative(item["path"])
        if item["path"] in exemptions:
            raise ValueError(f"duplicate exemption: {item['path']}")
        # A named Python reader must exist at the reviewed base.
        relative(item["reader"])
        git(root, "cat-file", "-e", base + ":" + item["reader"])
        exemptions[item["path"]] = item
    charged, exempted, errors = [], [], []
    for name in names:
        path = safe_path(root, name)
        if not path.exists():
            continue
        if not path.is_file():
            errors.append(f"{name}: not a regular file")
            continue
        size = path.stat().st_size
        if path.name == MANIFEST:
            try:
                doc = read_manifest(path)
                if doc["folder"] != path.parent.relative_to(root).as_posix():
                    raise ValueError("manifest folder differs from its location")
                exempted.append({"path": name, "bytes": size, "reason": "validated manifest"})
                continue
            except ValueError as exc:
                errors.append(f"{name}: invalid manifest: {exc}")
        item = exemptions.get(name)
        if item and size <= item["maxBytes"]:
            exempted.append({"path": name, "bytes": size, "reason": item["name"]})
        else:
            charged.append({"path": name, "bytes": size})
    total = sum(x["bytes"] for x in charged)
    if total > LIMIT:
        errors.append(f"docs evidence limit exceeded: {total} bytes > {LIMIT}; move raw evidence to {BRANCH}")
    return {"base": base, "limitBytes": LIMIT, "addedBytes": total,
            "charged": charged, "exempted": exempted, "errors": errors}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=ROOT)
    sub = p.add_subparsers(dest="command", required=True)
    move = sub.add_parser("prepare")
    move.add_argument("folder")
    move.add_argument("--id", required=True)
    move.add_argument("--bundle", required=True, type=Path)
    choice = move.add_mutually_exclusive_group(required=True)
    choice.add_argument("--new-branch", action="store_true")
    choice.add_argument("--parent")
    check = sub.add_parser("verify")
    check.add_argument("manifest", type=Path)
    where = check.add_mutually_exclusive_group(required=True)
    where.add_argument("--tree", type=Path)
    where.add_argument("--git", type=Path)
    size = sub.add_parser("budget")
    size.add_argument("--base")
    links = sub.add_parser("links")
    links.add_argument("manifest", type=Path)
    a = p.parse_args(argv)
    try:
        if a.command == "prepare":
            doc = prepare(a.repo, a.folder, a.id, a.bundle, parent=a.parent, new_branch=a.new_branch)
            print(f"Prepared {len(doc['files'])} files at {doc['commit']}; nothing pushed.")
            return 0
        if a.command == "budget":
            base = a.base or base_commit(a.repo)
            if base is None:
                print("Evidence limit not applicable: this scheduled or manual run has no pull request base.")
                return 0
            result = budget(a.repo, base)
            print(json.dumps(result, indent=2))
            return int(bool(result["errors"]))
        errors = (verify(a.manifest, tree=a.tree, repo=a.git) if a.command == "verify"
                  else link_errors(a.repo.resolve(), a.manifest))
        print("\n".join(errors) if errors else "Evidence checks passed")
        return int(bool(errors))
    except (ValueError, OSError) as exc:
        print(f"Cannot check or move evidence: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
