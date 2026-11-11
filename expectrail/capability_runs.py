"""Re-read every CI run the capability ledger cites, and say where the ledger and GitHub disagree.

    python3 -m expectrail.capabilities recheck

The ledger records how each cited run ended when its row was written. This asks GitHub again, through
``gh api`` (read-only: the run, then its jobs a page of 100 at a time), and reports one line per problem:

    the run's conclusion is not the one recorded
    a job the evidence rests on (``jobs``, or the job its link names) is not in the run or did not
      end in success
    a wall time's step is not in its job or did not end in success; a time read from the step's
      timestamps is not the time the step lasted, to the second; a time measured inside the step
      (one with ``phases``) is longer than the step. A shorter one passes: the step does other work
    the run could not be read: "cannot tell", which is a problem, never a pass

It reads a run's conclusion, its jobs and their steps, and nothing else: no logs and no artifacts. So
it shows that a run and its jobs ended the way a row says. It does not show that a count a row quotes
("8 of 8") is the count the run printed; that still takes a person or a record written by the run.

A re-run replaces a run's conclusion and jobs on GitHub. The latest attempt is what is read, and what
a row is held to.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Callable

REPO = "Expectrail/Expectrail"
PAGE_SIZE = 100
MAX_PAGES = 20
# A step's start and end are whole seconds, so a time read from them is good to a second either way.
STEP_RESOLUTION = 1.0

Reader = Callable[[str], dict]


class RunUnreadable(Exception):
    """GitHub's answer for a run could not be had or could not be understood."""


def _gh(path: str) -> str:
    try:
        done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunUnreadable(f"gh api did not run: {type(exc).__name__}: {exc}") from exc
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise RunUnreadable(f"gh api exited {done.returncode}: {lines[-1] if lines else 'no output'}")
    return done.stdout


def github_reader(call: Callable[[str], str] = _gh, repo: str = REPO) -> Reader:
    """A reader that asks GitHub for one run: ``{"status", "conclusion", "attempt", "jobs": [...]}``.

    Raises RunUnreadable when an answer is missing a field, or lists fewer jobs than it counts.
    """
    def read(number: str) -> dict:
        try:
            run = json.loads(call(f"repos/{repo}/actions/runs/{number}"))
            listed: list[dict] = []
            total = None
            for page in range(1, MAX_PAGES + 1):
                listing = json.loads(call(f"repos/{repo}/actions/runs/{number}/jobs?per_page={PAGE_SIZE}&page={page}"))
                total = listing["total_count"]
                seen = {job["id"] for job in listed}
                fresh = [job for job in listing["jobs"] if job["id"] not in seen]
                listed += fresh
                if len(listed) >= total or not fresh:  # a page with nothing new: asking again will not help
                    break
            jobs = [
                {"id": str(job["id"]), "name": job["name"], "conclusion": job["conclusion"],
                 "steps": [{"name": step["name"], "conclusion": step["conclusion"],
                            "startedAt": step.get("started_at"), "completedAt": step.get("completed_at")}
                           for step in job.get("steps") or []]}
                for job in listed
            ]
            if total != len(jobs):
                raise RunUnreadable(f"GitHub counts {total} jobs and listed {len(jobs)}")
            return {"status": run["status"], "conclusion": run["conclusion"], "attempt": run["run_attempt"],
                    "jobs": jobs}
        except (ValueError, KeyError, TypeError) as exc:
            raise RunUnreadable(f"not the answer expected: {type(exc).__name__}: {exc}") from exc
    return read


def _split(ref: str) -> tuple[str, str | None]:
    """The run number and, when the link names one, the job id."""
    tail = ref.split("/runs/", 1)[1]
    number, _, job = tail.partition("/job/")
    return number, job or None


def _seconds(step: dict) -> float | None:
    try:
        started = datetime.fromisoformat(step["startedAt"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(step["completedAt"].replace("Z", "+00:00"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return (ended - started).total_seconds()


def cited(doc: dict) -> list[dict]:
    """Every run the ledger cites: each row's run evidence, then each wall time."""
    out = []
    for row in doc["rows"]:
        for ev in row["evidence"]:
            if ev["kind"] == "run":
                out.append({"where": row["id"], "ref": ev["ref"], "conclusion": ev.get("conclusion"),
                            "jobs": list(ev.get("jobs", []))})
    for timing in doc.get("timings", []):
        out.append({"where": "timings", "ref": timing["run"], "conclusion": timing.get("conclusion"), "jobs": [],
                    "timing": timing})
    return out


def _one(cite: dict, run: dict) -> list[str]:
    number, job_id = _split(cite["ref"])
    head = f"{cite['where']}: run {number}"
    if run["status"] != "completed":
        return [f"{head}: cannot tell: the run is {run['status']}, not completed"]
    out = []
    if run["conclusion"] != cite["conclusion"]:
        out.append(f"{head}: recorded as {cite['conclusion'] or 'nothing'} and GitHub says {run['conclusion']}")
    by_name: dict[str, list[dict]] = {}
    for job in run["jobs"]:
        by_name.setdefault(job["name"], []).append(job)
    for name in cite["jobs"]:
        found = by_name.get(name, [])
        if not found:
            out.append(f"{head}: the evidence rests on job {name!r} and the run has no job of that name")
        for job in found:
            if job["conclusion"] != "success":
                out.append(f"{head}: the evidence rests on job {name!r}, which ended in {job['conclusion']}")
    linked = None
    if job_id is not None:
        linked = next((job for job in run["jobs"] if job["id"] == job_id), None)
        if linked is None:
            out.append(f"{head}: the link names job {job_id} and the run's latest attempt has no such job")
        elif linked["conclusion"] != "success" and cite["conclusion"] == "success":
            out.append(f"{head}: the link names job {linked['name']!r}, which ended in {linked['conclusion']}")
    timing = cite.get("timing")
    if timing is not None:
        if linked is None:
            if job_id is None:
                out.append(f"{head}: cannot tell: a wall time must link the job whose step it timed")
            return out
        steps = [step for step in linked["steps"] if step["name"] == timing["step"]]
        if len(steps) != 1:
            out.append(f"{head}: job {linked['name']!r} has {len(steps)} steps named {timing['step']!r}, not one")
            return out
        step = steps[0]
        if step["conclusion"] != "success":
            out.append(f"{head}: the step {timing['step']!r} ended in {step['conclusion']}")
        lasted = _seconds(step)
        if lasted is None:
            out.append(f"{head}: cannot tell: the step {timing['step']!r} has no start or end time")
        elif "phases" in timing:
            # The time came from timing.json, written inside the step: it cannot exceed the step.
            if timing["seconds"] > lasted + STEP_RESOLUTION:
                out.append(f"{head}: {timing['seconds']:g} s is recorded for a verification inside a step that "
                           f"lasted {lasted:g} s")
        elif abs(timing["seconds"] - lasted) > STEP_RESOLUTION:
            # The ledger's own resolutionSeconds is not the tolerance: a row could then excuse itself.
            out.append(f"{head}: {timing['seconds']:g} s is recorded and the step lasted {lasted:g} s by its "
                       "timestamps")
    return out


def recheck(doc: dict, read: Reader) -> tuple[list[str], list[str]]:
    """``(problems, checked)``: what disagrees with GitHub, and one line per run that was read.

    Each run is read once however many rows cite it. A run that cannot be read is a problem.
    """
    problems: list[str] = []
    checked: list[str] = []
    answers: dict[str, dict | RunUnreadable] = {}
    for cite in cited(doc):
        number, _ = _split(cite["ref"])
        if number not in answers:
            try:
                answers[number] = read(number)
            except RunUnreadable as exc:
                answers[number] = exc
            except Exception as exc:  # noqa: BLE001 - whatever a reader does, an unread run is "cannot tell"
                answers[number] = RunUnreadable(f"the reader failed: {type(exc).__name__}: {exc}")
            else:
                run = answers[number]
                checked.append(f"run {number}: {run['status']}, {run['conclusion']}, attempt {run['attempt']}, "
                               f"{len(run['jobs'])} jobs")
        answer = answers[number]
        if isinstance(answer, RunUnreadable):
            problems.append(f"{cite['where']}: run {number}: cannot tell: {answer}")
        else:
            problems.extend(_one(cite, answer))
    return problems, checked
