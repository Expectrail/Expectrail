"""The judge ladder: what the overnight loop does when the judge cannot answer.

There are two ladders, and they never mix (docs/fallbacks.md):

- **The fix is wrong** (the verifier rejected it): the fixer ladder in agents/escalation.py. The
  report first, the evidence after a rejection, then stop with the case unresolved for a person.
- **The judge did not answer** (SAM down, timing out, rate-limited or out of credit, so the
  verifier could only say needs-review): this ladder. It judges the *same* candidate again and
  never costs the fixer an attempt:

  1. the same judge again, after a short wait, in case the failure was passing. Skipped when the
     error says the key was refused or the credit is gone: waiting does not fix those;
  2. Muse Glimmer checked against the engine (``glimmer-engine``, never Glimmer alone), when a
     Glimmer deployment is configured and wakes in time. Its boxes are too loose for the ground
     check, so the ground is judged on the engine's position log, and the report says so;
  3. stop: the candidate stays needs-review, no further fix is attempted, and a person decides.

A rejection is final at every step. The ladder climbs only when the verifier failed no check and
an observer error says the vision model did not answer, so a second judge can never overturn a
first judge's rejection: it is asked only when the first gave no answer at all.

The benchmarks (agents/matrix.py, agents/heldout_bench.py) do not use this ladder: a result there
is one judge's answer, and an outage is recorded as needs-review rather than mixed with another
judge's answers in one table.
"""
from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from agents.sam_observations import BACKEND_ENV, SamError, vision_backend
from agents.verifier import sam_on, verify

UNAVAILABLE = "sam observations unavailable"  # agents/observations.py, on any vision client error
# Only what an error says outright: an unknown error keeps the retry (agents.sam_observations.SamError).
NO_RETRY_KINDS = ("auth", "credit", "budget")   # waiting fixes none of these
_KIND = re.compile(r"\(kind=([a-z-]+)\)")
FALLBACK = "glimmer-engine"
RETRY_WAIT_ENV = "EXPECTRAIL_JUDGE_RETRY_WAIT"
WARM_TIMEOUT_ENV = "EXPECTRAIL_GLIMMER_WARM_TIMEOUT"
DEFAULT_RETRY_WAIT_S = 30.0
DEFAULT_WARM_TIMEOUT_S = 600.0


def outage_error(verify_dir: Path) -> str | None:
    """The first observer error under ``verify_dir`` that says a vision model did not answer."""
    for path in sorted(verify_dir.rglob("observations*-error.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if UNAVAILABLE in text:
            return " ".join(text.split())[:200]
    return None


def outage_kind(verify_dir: Path) -> str | None:
    """The kind of outage under ``verify_dir``: auth or credit when any observer error says so (one
    dead key fails every request, and a passing error may sit beside it), else the first kind found."""
    kinds = []
    for path in sorted(verify_dir.rglob("observations*-error.txt")):
        try:
            kinds += _KIND.findall(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return next((k for k in NO_RETRY_KINDS if k in kinds), kinds[0] if kinds else None)


def judge_unavailable(verification: dict, verify_dir: Path) -> bool:
    """True when the verifier could not decide only because a vision model did not answer: the
    decision is needs-review, no check failed, and an observer error under ``verify_dir`` says so."""
    if verification.get("decision") != "needs-review":
        return False
    if any(c.get("result") == "fail" for c in verification.get("checks") or []):
        return False
    return outage_error(verify_dir) is not None


def current_judge() -> str:
    if not sam_on():
        return "engine"  # no vision model: nothing here can be unavailable
    try:
        return vision_backend()
    except SamError:
        return "sam"


def glimmer_problem(read_deployment: Callable | None = None) -> str | None:
    """Why the Glimmer step cannot run here, or None when it can.

    A Fireworks deployment is read through the control plane first, which sends no frame and wakes
    nothing. One scaled to 0 replicas (a person scaled it down, or the account was suspended) cannot
    answer, so it is skipped at once instead of waited on. The ladder never changes a deployment's
    scaling: that spends money, and it is a person's decision (agents/fireworks_deployment.py --restore).
    """
    from agents.glimmer_client import api_key

    key = api_key()
    if not key:
        return "no Glimmer key (EXPECTRAIL_GLIMMER_API_KEY or FIREWORKS_API_KEY)"
    model = os.environ.get("EXPECTRAIL_GLIMMER_MODEL", "").strip()
    if not model:
        return "no Glimmer deployment (EXPECTRAIL_GLIMMER_MODEL)"
    from agents import fireworks_deployment as fd

    target = fd.parse_deployment(model)
    if target is None:
        return None  # not a Fireworks deployment id (a self-hosted server): nothing to read
    try:
        dep = (read_deployment or fd.get)(target[0], target[1], key)
    except (fd.DeploymentError, OSError) as exc:
        return f"the Glimmer deployment could not be read: {' '.join(str(exc).split())[:160]}"
    if int(dep.get("maxReplicaCount") or 0) < 1:
        return (f"the Glimmer deployment is scaled to {dep.get('minReplicaCount', 0)}-{dep.get('maxReplicaCount', 0)} "
                "replicas, so it cannot answer; the ladder does not scale it up")
    return None


@contextmanager
def backend(name: str):
    old = os.environ.get(BACKEND_ENV)
    os.environ[BACKEND_ENV] = name
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(BACKEND_ENV, None)
        else:
            os.environ[BACKEND_ENV] = old


def _seconds(env: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(env, default)))
    except ValueError:
        return default


def judge(request: dict, candidate: Path, verify_dir: Path, *, verify_fn: Callable = verify,
          sleep: Callable[[float], None] = time.sleep, warm_fn: Callable | None = None,
          **verify_kwargs) -> tuple[dict, Path, dict]:
    """Verify a candidate, climbing the judge ladder only when the judge did not answer.

    Returns (verification, the directory it was written to, the ladder's record). The record says
    which judge decided (``judgedBy``), every step taken, and ``stopped`` when no judge answered.
    """
    first = current_judge()
    verification = verify_fn(request, candidate, verify_dir, **verify_kwargs)
    down = judge_unavailable(verification, verify_dir)
    steps = [{"judge": first, "decision": verification["decision"], "unavailable": down}]
    if down:
        steps[-1]["error"] = outage_error(verify_dir)
    if not down:
        return verification, verify_dir, {"judgedBy": first, "steps": steps, "stopped": False}

    # 1. The same judge again, after a short wait, unless the error says waiting cannot help.
    last_dir = verify_dir
    kind = outage_kind(verify_dir)
    if kind in NO_RETRY_KINDS:
        steps.append({"judge": first, "retry": True, "skipped": f"{kind} error: waiting does not fix it"})
    else:
        sleep(_seconds(RETRY_WAIT_ENV, DEFAULT_RETRY_WAIT_S))
        retry_dir = verify_dir.with_name(verify_dir.name + "-retry")
        verification = verify_fn(request, candidate, retry_dir, **verify_kwargs)
        down = judge_unavailable(verification, retry_dir)
        steps.append({"judge": first, "retry": True, "decision": verification["decision"], "unavailable": down})
        if down:
            steps[-1]["error"] = outage_error(retry_dir)
        if not down:
            return verification, retry_dir, {"judgedBy": f"{first} (retried)", "steps": steps, "stopped": False}
        last_dir = retry_dir

    # 2. Glimmer checked against the engine, never Glimmer alone, and only if it is not the judge
    #    that just failed to answer.
    if first != FALLBACK:
        problem = glimmer_problem()
        if problem is None:
            if warm_fn is None:
                from agents.glimmer_client import warm as warm_fn
            try:
                warm_fn(timeout_s=_seconds(WARM_TIMEOUT_ENV, DEFAULT_WARM_TIMEOUT_S))
            except (SamError, OSError) as exc:
                problem = f"the Glimmer deployment did not wake: {exc}"[:300]
        if problem is not None:
            steps.append({"judge": FALLBACK, "skipped": problem})
        else:
            glimmer_dir = verify_dir.with_name(verify_dir.name + "-glimmer")
            with backend(FALLBACK):
                verification = verify_fn(request, candidate, glimmer_dir, **verify_kwargs)
            down = judge_unavailable(verification, glimmer_dir)
            steps.append({"judge": FALLBACK, "decision": verification["decision"], "unavailable": down})
            if down:
                steps[-1]["error"] = outage_error(glimmer_dir)
            last_dir = glimmer_dir
            if not down:
                return verification, glimmer_dir, {"judgedBy": f"{FALLBACK} ({first} did not answer)",
                                                   "steps": steps, "stopped": False, "fallback": True}

    # 3. Stop: no judge answered. The candidate stays needs-review for a person.
    return verification, last_dir, {"judgedBy": None, "steps": steps, "stopped": True}


def report_note(record: dict) -> str | None:
    """The line the morning report carries for a person, or None when the first judge answered."""
    if record.get("stopped"):
        tried = "; ".join(f"{s['judge']}: " + (f"skipped ({s['skipped']})" if "skipped" in s else
                                               "no answer" if s.get("unavailable") else s.get("decision", "?"))
                          for s in record["steps"])
        return ("No vision judge answered, so this candidate was not judged and no further fix was attempted "
                f"(tried {tried}). A person must judge it.")
    if record.get("fallback"):
        return (f"Judged by {record['judgedBy']}: Glimmer's boxes are too loose for the ground check, so the "
                "ground was judged on the engine's position log, not on SAM's view of the robot. Look at the "
                "after frames for a robot drawn inside the ground before approving.")
    return None
