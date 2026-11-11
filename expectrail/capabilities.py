"""The capability ledger: what each advertised mode has actually been shown to do.

``docs/capabilities.json`` (``expectrail.capabilities/v1``) holds one row per mode a user could
believe exists. This module reads it, checks it, and renders ``docs/capabilities.md`` from it.

    python3 -m expectrail.capabilities check     # exit 1 and one line per problem
    python3 -m expectrail.capabilities render    # rewrite docs/capabilities.md

``problems`` is what the test suite runs. It fails when a ``measured`` row has no CI run link, when
a measured or integrated row cites a run recorded as anything but success (any other row must say why
such a run is evidence), when a row points at
a file that is not there, and when the README or the site names a command, a switch, a workflow, a
doc page or a watched name that no row lists. A run's conclusion is the value recorded in the
ledger when the row was written; nothing here calls GitHub.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "capabilities.json"
PAGE = ROOT / "docs" / "capabilities.md"
SCHEMA = ROOT / "contracts" / "capabilities.v1.schema.json"
ADVERTS = ("README.md", "docs/index.html")
REPO_URL = "https://github.com/Expectrail/Expectrail"

# The modes issue #244 names. A ledger without one of them is incomplete, whatever else it lists.
REQUIRED = (
    "godot-verify", "ci-gate", "unity-harness", "web-checkout", "sam-observer", "byo-vision",
    "generated-checks", "discovery", "fix-loop", "signing", "mcp-tools", "key-gateway",
)

_COMMAND = re.compile(r"\bpython3? -m ([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)")
_SWITCH = re.compile(r"\bEXPECTRAIL_[A-Z_]+\*?")
_WORKFLOW = re.compile(r"(?<![A-Za-z0-9_-])([a-z0-9][a-z0-9-]*\.yml)\b")
_DOC = re.compile(r"\bdocs/([a-z0-9-]+\.md)\b")
_ONE = {"commands": "command", "switches": "switch", "workflows": "workflow", "docs": "doc"}
_RUN = re.compile(r"^https://github\.com/Expectrail/Expectrail/actions/runs/[0-9]+(/job/[0-9]+)?$")


class LedgerError(ValueError):
    pass


def load(path: Path = LEDGER) -> dict:
    """The ledger, checked against its schema. Raises LedgerError on the first schema error."""
    import jsonschema

    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise LedgerError(f"capabilities: {where}: {first.message}")
    return doc


def _number(run_url: str) -> str:
    return run_url.split("/runs/", 1)[1].split("/", 1)[0]


def _module_exists(module: str, root: Path) -> bool:
    base = root.joinpath(*module.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def row_problems(doc: dict, root: Path = ROOT) -> list[str]:
    """What is wrong with the rows themselves, one line each."""
    out: list[str] = []
    seen: set[str] = set()
    for row in doc["rows"]:
        rid = row["id"]
        if rid in seen:
            out.append(f"{rid}: listed twice")
        seen.add(rid)
        kinds = [e["kind"] for e in row["evidence"]]
        if row["status"] == "measured" and "run" not in kinds:
            out.append(f"{rid}: marked measured with no CI run link")
        if row["status"] in ("implemented", "integrated") and not ({"run", "test"} & set(kinds)):
            out.append(f"{rid}: marked {row['status']} with neither a test nor a run")
        if row["status"] == "measured" and row["grade"] == "fixture":
            out.append(f"{rid}: saved or synthetic data is not a measurement (grade fixture, status measured)")
        if row["grade"] == "protected":
            out.append(f"{rid}: the protected grade is reserved until capture the game cannot forge exists")
        runs = [e for e in row["evidence"] if e["kind"] == "run"]
        if row["status"] == "measured" and runs and not any(e.get("conclusion") == "success" for e in runs):
            out.append(f"{rid}: marked measured and no cited run ended in success")
        for ev in row["evidence"]:
            if ev["kind"] == "run":
                if not _RUN.match(ev["ref"]):
                    out.append(f"{rid}: not a CI run link: {ev['ref']}")
                elif "conclusion" not in ev:
                    out.append(f"{rid}: no recorded conclusion for {ev['ref']}")
                elif ev["conclusion"] != "success":
                    if row["status"] in ("measured", "integrated"):
                        out.append(f"{rid}: marked {row['status']} and cites run {_number(ev['ref'])}, "
                                   f"recorded as {ev['conclusion']}")
                    elif not ev.get("conclusionNote"):
                        out.append(f"{rid}: cites a run that ended in {ev['conclusion']} without saying why it is "
                                   f"evidence: {ev['ref']}")
            elif not (root / ev["ref"].split("#", 1)[0]).exists():
                out.append(f"{rid}: evidence file not found: {ev['ref']}")
        for module in row["entryPoints"]:
            if not _module_exists(module, root):
                out.append(f"{rid}: entry point not found: {module}")
        for wf in row.get("workflows", []):
            if not (root / ".github" / "workflows" / wf).is_file():
                out.append(f"{rid}: workflow not found: {wf}")
        for page in row.get("docs", []):
            if not (root / page).is_file():
                out.append(f"{rid}: doc not found: {page}")
    for timing in doc.get("timings", []):
        if timing.get("conclusion") != "success":
            out.append(f"timings: run {_number(timing['run'])} is recorded as {timing.get('conclusion', 'unread')}")
        if "phases" in timing:
            parts = sum(timing["phases"].values())
            if abs(parts - timing["seconds"]) > timing["resolutionSeconds"]:
                out.append(f"timings: run {_number(timing['run'])}: the phases add up to {parts:g} s and the whole "
                           f"is {timing['seconds']:g} s")
    for rid in REQUIRED:
        if rid not in seen:
            out.append(f"{rid}: a mode the ledger must cover has no row")
    return out


def _visible(name: str, text: str) -> str:
    """The text a reader sees: an HTML page without its scripts, styles and tags."""
    if not name.endswith(".html"):
        return text
    text = re.sub(r"<(script|style)\b[\s\S]*?</\1>", " ", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def claims(name: str, text: str, workflows: set[str]) -> dict[str, set[str]]:
    """What one advertising file names: commands, switches, workflows and doc pages."""
    return {
        "commands": set(_COMMAND.findall(text)),
        "switches": set(_SWITCH.findall(text)),
        "workflows": {w for w in _WORKFLOW.findall(text) if w in workflows},
        "docs": {"docs/" + d for d in _DOC.findall(text)},
    }


def meta_models(readme: str) -> list[str]:
    """The first cell of each row of the README's "Meta models" table."""
    m = re.search(r"^### Meta models\n(.*?)(?=^#{1,3} )", readme, re.S | re.M)
    cells = []
    for line in (m.group(1) if m else "").splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*(Model|-+)\s*\|", line):
            cells.append(line.split("|")[1].strip())
    return cells


def _switch_listed(switch: str, listed: set[str]) -> bool:
    if switch in listed:
        return True
    return any(w.endswith("*") and switch.startswith(w[:-1]) for w in listed)


def advert_problems(doc: dict, texts: dict[str, str], root: Path = ROOT) -> list[str]:
    """Modes the README or the site names that no row lists, one line each."""
    rows = doc["rows"]
    listed = {
        "commands": {m for r in rows for m in r["entryPoints"]} | set(doc["notModes"]["commands"]),
        "switches": {s for r in rows for s in r.get("switches", [])} | set(doc["notModes"]["switches"]),
        "workflows": {w for r in rows for w in r.get("workflows", [])} | set(doc["notModes"]["workflows"]),
        "docs": {d for r in rows for d in r.get("docs", [])} | set(doc["notModes"]["docs"]),
    }
    names = {n for r in rows for n in r.get("names", [])}
    wf_dir = root / ".github" / "workflows"
    workflows = {p.name for p in wf_dir.glob("*.yml")} if wf_dir.is_dir() else set()
    out: list[str] = []
    for name, text in sorted(texts.items()):
        found = claims(name, text, workflows)
        for kind in ("commands", "switches", "workflows", "docs"):
            for item in sorted(found[kind]):
                ok = _switch_listed(item, listed[kind]) if kind == "switches" else item in listed[kind]
                if not ok:
                    out.append(f"{name}: names the {_ONE[kind]} {item}, which no ledger row lists")
        seen = _visible(name, text)
        for watched in doc["nameWatch"]:
            if watched not in names and re.search(rf"(?<![A-Za-z0-9]){re.escape(watched)}(?![A-Za-z0-9])", seen):
                out.append(f"{name}: names {watched}, which no ledger row lists")
        if name == "README.md":
            for cell in meta_models(text):
                if not any(n in cell for n in names):
                    out.append(f"{name}: the Meta models table has {cell!r}, which no ledger row lists")
    return out


def read_adverts(root: Path = ROOT) -> dict[str, str]:
    return {name: (root / name).read_text(encoding="utf-8") for name in ADVERTS}


def problems(doc: dict, root: Path = ROOT, texts: dict[str, str] | None = None) -> list[str]:
    """Every problem: the rows, then what the README and the site advertise."""
    return row_problems(doc, root) + advert_problems(doc, read_adverts(root) if texts is None else texts, root)


def _link(ref: str) -> str:
    """A link from docs/capabilities.md to a repository path."""
    path = ref[len("docs/"):] if ref.startswith("docs/") else "../" + ref
    return f"[`{ref}`]({path})"


def _evidence(ev: dict) -> str:
    if ev["kind"] == "run":
        text = f"[run {_number(ev['ref'])}]({ev['ref']}): {ev['shows']}"
        if ev.get("conclusion", "success") != "success":
            text += f". The run ended in {ev['conclusion'].replace('_', ' ')}: {ev.get('conclusionNote', 'no reason given')}"
        return text
    return f"{_link(ev['ref'])}: {ev['shows']}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(doc: dict) -> str:
    """docs/capabilities.md, from the ledger."""
    counts = {s: sum(1 for r in doc["rows"] if r["status"] == s) for s in doc["statuses"]}
    grades = {g: sum(1 for r in doc["rows"] if r["grade"] == g) for g in doc["grades"]}
    lines = [
        "# What Expectrail can do, and how far each part is proven",
        "",
        "<!-- Rendered from docs/capabilities.json by `python3 -m expectrail.capabilities render`. Edit the JSON, not this file. -->",
        "",
        "One row for every mode a reader of the README or the site could believe exists. Each row says how",
        "far the mode is proven (its status), what kind of evidence its best recorded run produced (its",
        "grade), and links the test, the record or the CI run that shows it. The same data is in",
        "[`capabilities.json`](capabilities.json); `tests/test_capabilities.py` fails when a row marked",
        "measured has no run link, when a link points at a file that is not there, and when the README or",
        "the site names a command, a switch, a workflow, a doc page or a watched name that no row lists.",
        "",
        "Every run link carries the run's conclusion as GitHub's API gave it when the row was written. The",
        "test reads that recorded value, not GitHub. A measured or integrated row may cite only runs",
        "recorded as success. Any other row that cites a run that ended another way says so beside the",
        "link, with the reason it is evidence all the same.",
        "",
        f"Last changed {doc['updated']}. {len(doc['rows'])} rows: "
        + ", ".join(f"{counts[s]} {s}" for s in doc["statuses"]) + ". By grade: "
        + ", ".join(f"{grades[g]} {g}" for g in doc["grades"]) + ".",
        "",
        "## Status",
        "",
        "| Status | Means |",
        "| --- | --- |",
    ]
    lines += [f"| `{s}` | {_cell(t)} |" for s, t in doc["statuses"].items()]
    lines += ["", "## Evidence grade", "", "| Grade | Means |", "| --- | --- |"]
    lines += [f"| `{g}` | {_cell(t)} |" for g, t in doc["grades"].items()]
    lines += [
        "",
        "## The modes",
        "",
        "| Mode | Engine or profile | Observer | Entry point | Grade | Status | Shown by | Not shown |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in doc["rows"]:
        entry = ", ".join(f"`{m}`" for m in r["entryPoints"]) or "none"
        if r.get("workflows"):
            entry += "; " + ", ".join(f"`{w}`" for w in r["workflows"])
        shown = "<br>".join(_cell(_evidence(e)) for e in r["evidence"])
        lines.append(
            f"| <a id=\"{r['id']}\"></a>{_cell(r['mode'])} | {_cell(r['profile'])} | {_cell(r['observer'])} "
            f"| {entry} | `{r['grade']}` | `{r['status']}` | {shown} | {_cell(r['limits'])} |"
        )
    lines += ["", "## Wall time", ""]
    if doc["timings"]:
        lines += ["| What | Runner | Seconds | Per phase | Run | Not measured |", "| --- | --- | --- | --- | --- | --- |"]
        for t in doc["timings"]:
            number = t["run"].split("/runs/", 1)[1].split("/", 1)[0]
            phases = "not measured"
            if "phases" in t:
                phases = ", ".join(f"{name} {t['phases'][name]:g}" for name in ("import", "replay", "evaluate", "other"))
                phases += f" ({_cell(t['phasesFrom'])})"
            lines.append(
                f"| {_cell(t['what'])} (step \"{_cell(t['step'])}\") | {_cell(t['runner'])} "
                f"| {t['seconds']:g}, to the nearest {t['resolutionSeconds']:g} | {phases} | [run {number}]({t['run']}) "
                f"| {_cell(t['notMeasured'])} |"
            )
        lines += [
            "",
            "The phases are those of [`expectrail.timing`](../expectrail/timing.py): `import` is Godot's `--import`,",
            "`replay` is the Godot process playing the route, `evaluate` is everything the verifier does outside a",
            "harness run, and `other` is the harness copying the game, applying patches and hashing frames.",
        ]
    else:
        lines.append("Not measured.")
    lines += [
        "",
        "## Named in the README or the site, and not a mode",
        "",
        "| Kind | Name | Why it has no row |",
        "| --- | --- | --- |",
    ]
    for kind in ("commands", "switches", "docs", "workflows"):
        for name, why in doc["notModes"][kind].items():
            lines.append(f"| {_ONE[kind]} | `{name}` | {_cell(why)} |")
    lines += [
        "",
        "## Changing the ledger",
        "",
        "Edit [`capabilities.json`](capabilities.json), run `python3 -m expectrail.capabilities render`, and",
        "commit both files. Move a row to `measured` only with the link of the CI run that produced the",
        "number. The benches under [`bench/`](../bench/README.md) are records of runs, not modes: a row",
        "links to them, they have no rows of their own. The check on what the README and the site name is",
        "mechanical: it sees commands, `EXPECTRAIL_` switches, workflow files, doc pages, the Meta models",
        "table and the names under `nameWatch`. A mode described only in prose, under a name nobody",
        "added to that list, gets past it.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "render"))
    args = parser.parse_args(argv)
    try:
        doc = load()
    except LedgerError as err:
        print(err, file=sys.stderr)
        return 1
    if args.command == "render":
        PAGE.write_text(render(doc), encoding="utf-8")
        print(f"wrote {PAGE.relative_to(ROOT)}")
        return 0
    found = problems(doc)
    if PAGE.read_text(encoding="utf-8") != render(doc):
        found.append("docs/capabilities.md is not what docs/capabilities.json renders to; run render")
    for line in found:
        print(line, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
