"""Build an offline review page from the files written by expectrail init."""
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from html import escape
from pathlib import Path

from expectrail import onboarding, project_config, route

ACTIVE = project_config.FILENAME
PENDING = "expectrail.project.draft.json"
CSS = """
*{box-sizing:border-box}body{margin:0;background:#f6f5ef;color:#172c28;font:1rem/1.5 system-ui,sans-serif}
main{max-width:54rem;margin:auto;padding:2rem 1rem 4rem}h1{line-height:1.1;font-size:clamp(2rem,6vw,3rem)}
h2{font-size:1.4rem;margin:2rem 0 .5rem}h3,p{margin:.5rem 0}code{overflow-wrap:anywhere}
article{padding:1rem;background:white;border:1px solid #c6d0c8;border-radius:.5rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr));gap:.8rem}
figure{margin:.5rem 0}img{display:block;max-width:100%;height:6rem;object-fit:contain;background:#eee}
figcaption{margin:.4rem 0}.save{display:inline-block;background:#125442;color:white;border-radius:.3rem;
padding:.55rem .8rem;text-decoration:none;font-weight:600}.save:focus-visible{outline:3px solid #ae4800}
"""


def local_file(root, name):
    root = Path(root).resolve()  # one spelling for both sides, as in onboarding.resource (#378)
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"Expected {name} inside the game. Check the path or run expectrail init again.")
    return path


def preview(root, uri):
    # Only embed raster images with matching signatures. Other formats retain their path as evidence.
    path = onboarding.resource(root, uri)
    uri_text = f"<code>{escape(uri)}</code>"
    with path.open("rb") as stream:
        header = stream.read(12)
        mime = None
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif header.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif header[:4] == b"RIFF" and header[8:] == b"WEBP":
            mime = "image/webp"
        if mime is None and path.stat().st_size <= 16 * 1024:
            from expectrail.onboard_review import svg_size

            raw = header + stream.read(16 * 1024)
            if svg_size(raw) is not None:
                data = base64.b64encode(raw).decode("ascii")
                return (f'<figure><img alt="{escape(path.name)}" src="data:image/svg+xml;base64,{data}">'
                        f'<figcaption>{uri_text}</figcaption></figure>')
        if not mime or path.stat().st_size > 4 * 1024 * 1024:
            return f"<p>{uri_text} (preview unavailable)</p>"
        data = base64.b64encode(header + stream.read(4 * 1024 * 1024)).decode("ascii")
    return (f'<figure><img alt="{escape(path.name)}" src="data:{mime};base64,{data}">'
            f'<figcaption>{uri_text}</figcaption></figure>')


def download(root, config, label):
    project_config.validate(config, root)
    data = base64.b64encode(onboarding.encode(config)).decode("ascii")
    return (f'<a class="save" download="{ACTIVE}" href="data:application/json;base64,{data}">'
            f'{escape(label)}</a>')


def saved_draft(root, source):
    if source is None:
        found = [n for n in (ACTIVE, PENDING) if (root / n).exists()]
        if len(found) != 1:
            raise ValueError("Both draft files exist; select one with --source." if found else
                             "No init draft found. Run expectrail init on this game first.")
        source = found[0]
    doc = json.loads(local_file(root, source).read_bytes())
    if not isinstance(doc, dict) or doc.get("draft") is not True:
        raise ValueError(f"{source} must be an init draft.")
    config = doc if source == ACTIVE else doc.get("config")
    if not isinstance(config, dict) or config.get("draft") is not True or config.get("approvedContracts"):
        raise ValueError("Review requires a draft config without approved contracts.")
    if source == ACTIVE:
        project_config.validate(config, root)
    return source, doc, config


def inputs(root, config):
    routes = config.get("routes")
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], str):
        raise ValueError("The draft needs the first route written by expectrail init.")
    name = routes[0]
    if not re.fullmatch(r"routes/draft-first-[0-9a-f]{16}\.json", name):
        raise ValueError("Expected the content-addressed first route from expectrail init.")
    raw = local_file(root, name).read_bytes()
    if hashlib.sha256(raw).hexdigest()[:16] != Path(name).stem.removeprefix("draft-first-"):
        raise ValueError("The saved first route has changed. Review the inputs and run init again.")
    actions = list(dict.fromkeys(event["action"] for event in json.loads(raw)["events"]))
    return name, actions


def words(values):
    return ", ".join(f"<code>{escape(v)}</code>" for v in values) or "none found"


def render(root, source=None):
    source, doc, config = saved_draft(root, source)
    route_name, actions = inputs(root, config)
    info = onboarding.inspect(root)
    pending = source == PENDING
    if pending and doc != {k: v for k, v in onboarding.proposal(root, info).items() if k != "route"}:
        raise ValueError("The binding review file differs from the current project. Review the changes and rerun init.")
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; '
             'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             f'<title>Binding review · Expectrail</title><style>{CSS}</style></head><body><main>',
             f'<header><p>Expectrail · {escape(root.name)}</p><h1>Review the game bindings</h1>',
             '<p>Check which objects and images describe your game. Saving downloads a draft. '
             'Approving checks is a separate, explicit human step.</p></header>',
             '<h2>Starting scene and first route</h2>',
             f'<p>Scene: <code>{escape(info["entryScene"])}</code><br>Route: <code>{escape(route_name)}</code></p>',
             f'<p>Inputs listed in the draft: {words(config["inputActions"])}.</p>',
             f'<p>The route presses {words(actions)}. Check that these inputs start play and exercise '
             'the behaviour you want to verify.</p><h2>Bindings</h2>']
    for role, binding in config["bindings"].items():
        selector = "node" if "node" in binding else "group"
        parts.append(f'<article><h3>{escape(role)}</h3><p>Use the {selector} '
                     f'<code>{escape(binding[selector])}</code> for this role.</p>')
        if "texture" in binding:
            parts.append("<p>Representative image in the draft:</p>" + preview(root, binding["texture"]))
        parts.append("</article>")
    parts.append(f'<p>Player nodes found by inspect: {words(info["players"])}. '
                 'The images are project art. This page contains no replay measurement.</p>')
    if pending:
        parts.extend(f"<p>{escape(reason)}</p>" for reason in doc["unresolvedBindings"])
    parts.extend(["<h2>Save a draft config</h2>",
                  f"<p>Save as <code>{ACTIVE}</code> next to <code>project.godot</code>. "
                  "If a binding is wrong, leave the file unsaved and revise the draft.</p>"])
    if pending and len(doc["playerCandidates"]) == 1 and doc["textureCandidates"]:
        parts.append('<p>Choose the image that should represent the player. Each link downloads the '
                     'whole config with that image selected.</p><div class="grid">')
        for uri in doc["textureCandidates"]:
            choice = deepcopy(config)
            choice["bindings"]["player"]["texture"] = uri
            link = download(root, choice, f"Use {uri.removeprefix('res://')} and save")
            parts.append("<article>" + preview(root, uri) + link + "</article>")
        parts.append("</div>")
    elif pending:
        parts.append("<p>No complete choice is available. Identify the player and its image in the game, "
                     "then prepare a complete draft before saving.</p>")
    else:
        parts.append(download(root, config, "Save these bindings"))
    return "\n".join(parts) + "</main></body></html>\n"


def main(argv):
    parser = route.Parser(prog="expectrail onboard", description=__doc__)
    parser.add_argument("--project", type=Path, help="game folder (an existing init draft or a readable project)")
    answer_mode = parser.add_mutually_exclusive_group()
    answer_mode.add_argument("--check-answers", type=Path, help="validate an answers file without applying it")
    answer_mode.add_argument("--approve", type=Path, help="a person applies a saved answers file; never run by an agent on real specs")
    parser.add_argument("--evidence", type=Path, help="existing clean capture folder (trace.json, replay.json, frames/)")
    parser.add_argument("--broken", action="append", default=[], metavar="NAME=FOLDER", help="existing broken-copy capture, repeatable")
    parser.add_argument("--recording", type=Path, help="recorded observer answers; no live model is called")
    parser.add_argument("--godot", type=Path, help="local pinned engine for an offline clean replay")
    parser.add_argument("--source", choices=(ACTIVE, PENDING), help="which init draft to review if both exist")
    parser.add_argument("--out", type=Path, help="new page (default: expectrail-review.html in the game)")
    try:
        args = parser.parse_args(argv)
        from expectrail import onboard_page, onboard_review
        if args.check_answers:
            if any((args.project, args.source, args.evidence, args.broken, args.recording, args.godot, args.out)):
                raise ValueError("Use --check-answers with the answers file alone.")
            try:
                result = onboard_review.check_answers(args.check_answers)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{exc}. Check the answers file path or save a fresh file from the review page.") from exc
            print(json.dumps(result, indent=2))
            return 0
        if args.approve:
            if args.project or args.source or args.evidence or args.broken or args.recording or args.godot:
                raise ValueError("Use --approve with the answers file alone.")
            result = onboard_review.approve_answers(args.approve)
            print(f"{len(result['approved'])} checks approved by {result['person']}. No unselected check was changed.")
            return 0
        if args.project is None:
            raise ValueError("--project is required unless a person supplies --approve FILE.")
        root = args.project.resolve()
        out = args.out or root / "expectrail-review.html"
        if out.suffix.lower() != ".html":
            raise ValueError("Use a new .html file for the review page.")
        if out.exists() or out.is_symlink():
            raise ValueError("The review page already exists; choose a new --out file.")
        if not out.parent.is_dir():
            raise ValueError(f"Create the --out directory {out.parent} or choose a file in an existing directory.")
        if args.source is None and (root / ACTIVE).exists() and (root / PENDING).exists():
            raise ValueError("Both draft files exist; select one with --source.")
        if args.source == PENDING or (not (root / ACTIVE).exists() and (root / PENDING).exists()):
            # Preserve the existing unresolved-binding chooser; it cannot approve any check.
            page = render(root, args.source)
            state = None
        else:
            state = Path(tempfile.mkdtemp(dir=out.parent, prefix=".expectrail-onboard-"))
            try:
                broken = []
                for item in args.broken:
                    label, separator, folder = item.partition("=")
                    if not separator or not label or not folder:
                        raise ValueError("Use --broken NAME=FOLDER.")
                    broken.append((label, Path(folder)))
                record, details = onboard_review.prepare(root, state, source=args.source, evidence=args.evidence,
                    broken=broken, recording=args.recording, godot=args.godot)
                manifest = state / "review.json"
                manifest.write_bytes(onboard_review.encoded(record))
                (state / "timing.json").write_bytes(onboard_review.encoded(record['timing']))
                page = onboard_page.render(record, details, state, manifest, onboard_review.sha(manifest.read_bytes()))
                if len(page.encode()) > onboard_review.MAX_PAGE_BYTES:
                    raise ValueError("Review previews exceed 120 KiB; use smaller frame previews or fewer draft checks.")
                if (state / "capture").exists():
                    __import__('shutil').rmtree(state / "capture")
            except BaseException:
                __import__('shutil').rmtree(state, ignore_errors=True)
                raise
        with tempfile.NamedTemporaryFile(dir=out.parent, delete=False) as tmp:
            path = Path(tmp.name)
        try:
            path.write_text(page, encoding="utf-8")
            os.link(path, out)
        finally:
            path.unlink(missing_ok=True)
        print(f"Open {out.resolve().as_uri()} to review the objects and checks.")
        return 0
    except ModuleNotFoundError as exc:
        if exc.name != "jsonschema":
            raise
        print("expectrail onboard: install the contracts extra: pip install 'expectrail[contracts]'", file=sys.stderr)
        return 5
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"expectrail onboard: {exc}", file=sys.stderr)
        return 5
