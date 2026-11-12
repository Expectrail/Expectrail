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
    a count the evidence ties to the run's notices (``counts``) is not the count the notices give; a
      notice it rests on is missing, is there twice, or comes from a job that did not end in success
    the run, or the notices a count needs, could not be read: "cannot tell", which is a problem,
      never a pass

It reads a run's conclusion, its jobs and their steps, and, for a run whose evidence carries ``counts``,
the notices its jobs published (the annotations a workflow writes with ``::notice``, which the bench
jobs use for their public counts). It reads no logs and no artifacts. So a count is checked only where
the evidence ties it to notices; any other count a row quotes is still as its writer wrote it.

A count is tied to notices in one of two ways. ``count``: of the notices whose title matches ``titled``
(``*`` stands for any text; titles matching a pattern under ``not`` are left out), ``of`` is how many
there are and ``n`` is how many have ``count`` as one whole field of their message, the fields being
what lies between semicolons. Every such notice must say which side it is on: it has ``count``, or it
has the field the entry names under ``otherwise``, once and not both. A notice with neither is not a
"no"; the count is then "cannot tell". An entry without ``otherwise`` needs every notice to have
``count``. ``reads``: exactly one notice has the title, and one of its fields is
``reads`` with ``{n}`` and ``{of}`` filled in. Nothing is matched as a pattern inside a message: a
field is equal or it is not.

A re-run replaces a run's conclusion and jobs on GitHub. The latest attempt is what is read, and what
a row is held to.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from typing import Callable

REPO = "Expectrail/Expectrail"
PAGE_SIZE = 100
MAX_PAGES = 20
# A step's start and end are whole seconds, so a time read from them is good to a second either way.
STEP_RESOLUTION = 1.0

MAX_NOTICE_PAGES = 5

Reader = Callable[[str], dict]
# A job's id to the notices it published: [{"title": ..., "message": ...}].
Notices = Callable[[str], list]


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


def github_notices(call: Callable[[str], str] = _gh, repo: str = REPO) -> Notices:
    """A reader that asks GitHub for the notices one job published: ``[{"title", "message"}]``.

    A job's annotations are read a page of 100 at a time and only those of level ``notice`` are kept.
    Raises RunUnreadable when an answer is not a list of annotations, or the pages do not end.
    """
    def read(job_id: str) -> list:
        out = []
        try:
            for page in range(1, MAX_NOTICE_PAGES + 1):
                listing = json.loads(call(f"repos/{repo}/check-runs/{job_id}/annotations"
                                          f"?per_page={PAGE_SIZE}&page={page}"))
                if not isinstance(listing, list):
                    raise RunUnreadable(f"job {job_id}: the annotations are not a list")
                for item in listing:
                    if item["annotation_level"] == "notice":
                        message = item["message"]
                        if not isinstance(message, str):
                            raise RunUnreadable(f"job {job_id}: a notice's message is not text")
                        out.append({"title": item.get("title") or "", "message": message})
                if len(listing) < PAGE_SIZE:
                    return out
        except (ValueError, KeyError, TypeError) as exc:
            raise RunUnreadable(f"job {job_id}: not the answer expected: {type(exc).__name__}: {exc}") from exc
        raise RunUnreadable(f"job {job_id}: more than {MAX_NOTICE_PAGES * PAGE_SIZE} annotations")
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
                            "jobs": list(ev.get("jobs", [])), "counts": list(ev.get("counts", []))})
    for timing in doc.get("timings", []):
        out.append({"where": "timings", "ref": timing["run"], "conclusion": timing.get("conclusion"), "jobs": [], "counts": [],
                    "timing": timing})
    return out


def matches(pattern: str, title: str) -> bool:
    """Whether a notice's whole title is the pattern, ``*`` standing for any text and nothing else special."""
    return re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), title, re.S) is not None


def fields(message: str) -> list[str]:
    """A notice's message as its fields: what lies between semicolons, without the spaces around."""
    return [part.strip() for part in message.split(";")]


def _run_notices(run: dict, notices: Notices | None) -> list:
    """Every notice the run's jobs published, each with its job's name and how the job ended.

    A skipped job ran no step, so it is not asked about. Raises RunUnreadable when any other job's
    notices cannot be had: a count over some of the jobs would be a guess.
    """
    if notices is None:
        raise RunUnreadable("no reader for the run's notices was given")
    out = []
    for job in run["jobs"]:
        if job["conclusion"] == "skipped":
            continue
        try:
            found = notices(job["id"])
            out += [{"job": job["name"], "conclusion": job["conclusion"], "title": item["title"],
                     "message": item["message"]} for item in found]
        except RunUnreadable:
            raise
        except Exception as exc:  # noqa: BLE001 - whatever a reader does, unread notices are "cannot tell"
            raise RunUnreadable(f"the notices reader failed: {type(exc).__name__}: {exc}") from exc
    return out


def _stated(chosen: list, field: str, otherwise: str | None) -> tuple[int, list[str]]:
    """``(having, unclear)``: how many notices state ``field``, and why any notice cannot be counted.

    A notice is counted only when it says which side it is on: it has ``field`` once, or it has
    ``otherwise`` once, and not both. A notice with neither (a job that printed nothing for it, a
    field spelt another way), with both, or with one of them twice is not a "no": it is in ``unclear``,
    and the count is "cannot tell". Without ``otherwise`` every notice must have ``field``.
    """
    having = 0
    unclear = []
    for item in chosen:
        got = fields(item["message"])
        yes = got.count(field)
        no = got.count(otherwise) if otherwise is not None and otherwise != field else 0
        if yes + no == 1:
            having += yes
        elif yes and no:
            unclear.append(f"the notice {item['title']!r} has both the field {field!r} and the field {otherwise!r}")
        elif yes + no > 1:
            unclear.append(f"the notice {item['title']!r} has the field {field if yes else otherwise!r} "
                           f"{yes + no} times")
        elif otherwise is None:
            unclear.append(f"the notice {item['title']!r} has no field {field!r}, and the count names no field "
                           "('otherwise') that a notice not counted must have")
        elif otherwise == field:
            unclear.append(f"'otherwise' is the same field as 'count' ({field!r})")
        else:
            unclear.append(f"the notice {item['title']!r} has neither the field {field!r} nor the field "
                           f"{otherwise!r}")
    return having, unclear


def _counts(cite: dict, head: str, noticed: list | RunUnreadable) -> list[str]:
    """What is wrong with each count the evidence ties to the run's notices."""
    out = []
    for count in cite.get("counts", []):
        what = f"{head}: {count['says']!r}"
        if isinstance(noticed, RunUnreadable):
            out.append(f"{what}: cannot tell: {noticed}")
            continue
        chosen = [item for item in noticed if matches(count["titled"], item["title"])
                  and not any(matches(left_out, item["title"]) for left_out in count.get("not", []))]
        if not chosen:
            out.append(f"{what}: cannot tell: the run published no notice titled {count['titled']!r}")
            continue
        for item in chosen:
            if item["conclusion"] != "success":
                out.append(f"{what}: rests on the notice {item['title']!r} from job {item['job']!r}, which ended "
                           f"in {item['conclusion']}")
        titles = [item["title"] for item in chosen]
        twice = sorted({title for title in titles if titles.count(title) > 1})
        if twice:
            out.append(f"{what}: cannot tell: the run published the notice {twice[0]!r} {titles.count(twice[0])} "
                       "times, and a count takes each once")
            continue
        if "count" in count:
            having, unclear = _stated(chosen, count["count"], count.get("otherwise"))
            if unclear:
                more = f" (and {len(unclear) - 1} more)" if len(unclear) > 1 else ""
                out.append(f"{what}: cannot tell: {unclear[0]}{more}")
            elif (having, len(chosen)) != (count["n"], count["of"]):
                out.append(f"{what}: {count['n']} of {count['of']} is recorded and the run's notices give "
                           f"{having} of {len(chosen)} (titled {count['titled']!r}, with the field {count['count']!r})")
        elif len(chosen) != 1:
            out.append(f"{what}: cannot tell: {len(chosen)} notices are titled {count['titled']!r}, and a count read "
                       "from one notice takes exactly one")
        else:
            expected = count["reads"].replace("{n}", str(count["n"])).replace("{of}", str(count["of"]))
            if expected not in fields(chosen[0]["message"]):
                out.append(f"{what}: the notice {chosen[0]['title']!r} has no field {expected!r}")
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


def recheck(doc: dict, read: Reader, notices: Notices | None = None) -> tuple[list[str], list[str]]:
    """``(problems, checked)``: what disagrees with GitHub, and one line per run that was read.

    Each run is read once however many rows cite it. A run that cannot be read is a problem. The
    notices of a run are read once, and only when some evidence ties a count to them; without a
    ``notices`` reader every such count is "cannot tell".
    """
    problems: list[str] = []
    checked: list[str] = []
    answers: dict[str, dict | RunUnreadable] = {}
    noticed: dict[str, list | RunUnreadable] = {}
    counted = {_split(cite["ref"])[0] for cite in cited(doc) if cite.get("counts")}
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
                line = (f"run {number}: {run['status']}, {run['conclusion']}, attempt {run['attempt']}, "
                        f"{len(run['jobs'])} jobs")
                if number in counted and run["status"] == "completed":
                    try:
                        noticed[number] = _run_notices(run, notices)
                        line += f", {len(noticed[number])} notices"
                    except RunUnreadable as exc:
                        noticed[number] = exc
                        line += ", notices not read"
                checked.append(line)
        answer = answers[number]
        if isinstance(answer, RunUnreadable):
            problems.append(f"{cite['where']}: run {number}: cannot tell: {answer}")
        else:
            problems.extend(_one(cite, answer))
            if cite.get("counts") and number in noticed:
                problems.extend(_counts(cite, f"{cite['where']}: run {number}", noticed[number]))
    return problems, checked
