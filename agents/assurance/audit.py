"""The OBAAF audit in CI: the lane inventory must hold, and every finding is reported (the baseline step in ci.yml fails on new ones).

``obaaf check`` classifies each job into a lane and applies the agent controls only to agent jobs.
It does not recognise our model entry points (``python -m agents.*``), so ``.github/obaaf.yml``
declares them. A declaration is only as good as its upkeep, so this fails CI when:

- a job declared as an agent is not classified as one,
- a job declared a probe names no job that was checked, or
- a job holds a model key (Meta's, or any bring-your-own provider's) and is none of: a declared
  agent, a known perception-only job (one that only sends frames to SAM or Glimmer and acts on
  nothing), or a declared probe (one that calls a model and acts only on whether it answered).

The probe lane exists for ``byo-smoke.yml``: it sends one short prompt to each configured provider
and checks that text came back, so it holds provider keys while running no fixer, replaying no game
and reading nothing the model says. Calling that an agent would overclaim what it does; calling it
perception would be wrong about what it talks to. Its credential findings are reported like any
other job's, never suppressed.

Everything else is reporting: the findings, by category and severity, as notices. They are not
suppressed and do not fail the build; gating comes when the agent jobs stop receiving provider
keys (integration spec, Phase C), not by ignoring findings to get a green check.

    obaaf check . --lanes > lanes.txt
    obaaf check . --format json --fail-on never --output obaaf-audit.json
    python3 -m agents.assurance.audit --lanes lanes.txt --report obaaf-audit.json
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from agents.keys import BYO_AGENT_KEY_ENVS
from expectrail.providers import PROVIDER_DEFAULTS
from harness.run import REPO

CONFIG = REPO / ".github" / "obaaf.yml"
WORKFLOWS = REPO / ".github" / "workflows"
# Secrets that reach a model: a job holding one either acts on a model's output (an agent) or only
# sends it frames to look at (perception). Derived from the two registries that already name every
# key Expectrail can send a model, rather than listed again here, so that adding a provider to
# expectrail/providers.py or a coding agent to agents/keys.py cannot leave this audit blind to it.
# A key named for a local endpoint (Ollama, vLLM) is included too: a job that holds one still acts
# on what the model says, so it still belongs in a lane.
_REGISTRY_KEYS = frozenset(
    {env for defaults in PROVIDER_DEFAULTS.values() for env in defaults["key_envs"]}
    | {env for envs in BYO_AGENT_KEY_ENVS.values() for env in envs}
)
# Keys no registry names: Glimmer's older key, and the vision role's key (agents/keys.py resolves it
# as EXPECTRAIL_VLM_API_KEY). Kept explicit so widening the registries can never narrow this set.
_EXTRA_KEYS = frozenset({"GLIMMER_API_KEY", "EXPECTRAIL_VLM_API_KEY"})
MODEL_KEYS = _REGISTRY_KEYS | _EXTRA_KEYS
# Every role's own override (EXPECTRAIL_<SPEC|TRIAGE|FIXER|VLM>_API_KEY, and any role added later)
# is a model key by construction, so match the shape instead of enumerating the roles.
MODEL_KEY_PATTERN = re.compile(r"^EXPECTRAIL_[A-Z0-9_]*API_KEY$")
# Jobs that only send frames to SAM 3.1 or Muse Glimmer and record what they say. Not agents, but
# they still hold model keys, and those findings are reported.
PERCEPTION = frozenset({
    ".github/workflows/fix-matrix.yml#sam-warm",
    ".github/workflows/glimmer-probe.yml#glimmer",
    ".github/workflows/sam-probe.yml#sam-probe",
    ".github/workflows/sam-probe.yml#sam-video",
    ".github/workflows/sam-probe.yml#sam-verify",
    ".github/workflows/sam-probe.yml#heldout-bench",
    # SAM on frames of an outside game. The frames come from another job of the same run, which
    # has no secret and is the only one that fetches and starts the outside project; this job
    # never does (tests/test_outside_trial.py holds that against the workflow file).
    ".github/workflows/outside-sam-probe.yml#probe",
    # The web detection bench: SAM on frames of the checkout page. Chromium runs the page's (patched)
    # scripts with the game's environment allowlist and every request outside the page's own origin
    # aborted (harness/web/run.py), so the key never reaches the page and the page reaches nothing.
    ".github/workflows/web-bench.yml#heldout-bench",
    ".github/workflows/web-bench.yml#web-judge",  # the same, on the judge benchmark's cases
    ".github/workflows/web-bench.yml#web-probe",  # the same, one frame a session, for prompt calibration
    ".github/workflows/web-fix.yml#plan",  # SAM on the clean page's private sessions, before Muse runs
    # Mutation bench: SAM on public checks only; never Muse Code, never the private set.
    ".github/workflows/mutation-bench.yml#run",
    ".github/workflows/mutation-bench.yml#sam-warm",  # the clean game's smoke frames, once per run
    ".github/workflows/mutation-fix.yml#sam-warm",  # the same, for Part 3's jobs
    # Reported-bug bench: SAM on frames of public bugs, only when dispatched from main with sam on
    # (the keyless reported-bench job judges from traces and holds no key).
    ".github/workflows/reported-bench.yml#reported-bench-sam",
})
LANE_LINE = re.compile(r"^(?P<job>\S+#\S+): (?P<lane>[a-z]+) \(")


def is_model_key(secret: str) -> bool:
    """Whether a ``secrets.NAME`` reference hands a job a key to a model."""
    return secret in MODEL_KEYS or bool(MODEL_KEY_PATTERN.match(secret))


def declared_lanes(config: Path = CONFIG, lane: str = "agent") -> set[str]:
    """The jobs .github/obaaf.yml declares in ``lane``."""
    doc = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    return {job for job, declared in (doc.get("lanes") or {}).items() if declared == lane}


def declared_agents(config: Path = CONFIG) -> set[str]:
    return declared_lanes(config, "agent")


def declared_probes(config: Path = CONFIG) -> set[str]:
    """Jobs that call a model and act only on whether it answered (see the module docstring)."""
    return declared_lanes(config, "probe")


def model_jobs(workflows: Path = WORKFLOWS) -> dict[str, set[str]]:
    """{workflow#job: model keys it references}, for every job that references one."""
    out: dict[str, set[str]] = {}
    for path in sorted(workflows.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rel = path.relative_to(workflows.parent.parent).as_posix()
        for name, job in (doc.get("jobs") or {}).items():
            keys = {s for s in re.findall(r"secrets\.([A-Z0-9_]+)", yaml.safe_dump(job)) if is_model_key(s)}
            if keys:
                out[f"{rel}#{name}"] = keys
    return out


def parse_lanes(text: str) -> dict[str, str]:
    """``obaaf check --lanes`` output as {workflow#job: lane}."""
    return {m["job"]: m["lane"] for m in map(LANE_LINE.match, text.splitlines()) if m}


def inventory_problems(lanes: dict[str, str], declared: set[str], models: dict[str, set[str]],
                       probes: set[str] | frozenset[str] = frozenset()) -> list[str]:
    problems = []
    for job in sorted(declared):
        if job not in lanes:
            problems.append(f"{job} is declared in .github/obaaf.yml but no such job was checked")
        elif lanes[job] != "agent":
            problems.append(f"{job} is declared as an agent but OBAAF classified it {lanes[job]}")
    for job in sorted(probes):
        # A probe is not held to OBAAF's classification: the checker may read it either way, and a
        # more conservative reading is not a disagreement worth failing. A name that matches no job
        # is, because a renamed or deleted job would otherwise keep its exemption silently.
        if job not in lanes:
            problems.append(f"{job} is declared a probe in .github/obaaf.yml but no such job was checked")
    for job, keys in sorted(models.items()):
        if lanes.get(job) != "agent" and job not in PERCEPTION and job not in probes:
            problems.append(f"{job} holds {', '.join(sorted(keys))} but is not a declared agent lane, a "
                            "perception-only job or a declared probe: declare it in .github/obaaf.yml or add "
                            "it to PERCEPTION, after review")
    return problems


def finding_lines(report: dict) -> list[str]:
    """A summary line and one line per rule (GitHub shows ten notices a step, so findings are grouped)."""
    findings = [f for f in report.get("findings") or [] if not f.get("suppressed")]
    counts = Counter((f["category"], f["severity"]) for f in findings)
    summary = "; ".join(f"{cat} {', '.join(f'{counts[(cat, s)]} {s}' for s in ('high', 'medium', 'low'))}"
                        for cat in ("authority", "hygiene"))
    lines = [(f"::notice title=OBAAF audit::{len(findings)} findings, reported; new ones fail the baseline step ({summary}); "
              f"{len(report.get('files') or [])} workflow files; {report.get('tool')}")]
    rules: dict[tuple[str, str, str], list[str]] = {}
    for f in findings:
        where = f["job"] or f"{f['path']}:{f.get('line') or 1}"
        rules.setdefault((f["severity"], f["rule"], f["title"]), []).append(where)
    order = {"high": 0, "medium": 1, "low": 2}
    for (severity, rule, title), where in sorted(rules.items(), key=lambda kv: (order.get(kv[0][0], 3), kv[0][1])):
        lines.append(f"::notice title=OBAAF {severity} {rule} x{len(where)}::{title}: {', '.join(where)}")
    for error in report.get("errors") or []:
        lines.append(f"::warning title=OBAAF error::{' '.join(str(error).split())[:300]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lanes", type=Path, required=True, help="output of obaaf check . --lanes")
    p.add_argument("--report", type=Path, help="output of obaaf check . --format json")
    args = p.parse_args(argv)
    lanes = parse_lanes(args.lanes.read_text(encoding="utf-8"))
    if not lanes:
        print("::error title=OBAAF lanes::no lanes in the obaaf check --lanes output")
        return 1
    probes = declared_probes()
    problems = inventory_problems(lanes, declared_agents(), model_jobs(), probes)
    agents = sorted(job for job, lane in lanes.items() if lane == "agent")
    if probes:
        print("::notice title=OBAAF probes::"
              + ", ".join(sorted(p.split("/")[-1] for p in probes))
              + " call a model and act only on whether it answered")
    print(f"::notice title=OBAAF lanes::{len(lanes)} jobs; {len(agents)} agent lanes: "
          + ", ".join(a.split("/")[-1] for a in agents))
    if args.report:
        import json

        for line in finding_lines(json.loads(args.report.read_text(encoding="utf-8"))):
            print(line)
    for problem in problems:
        print(f"::error title=OBAAF lane inventory::{problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
