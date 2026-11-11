"""Verification as a job (#250): the request, the job store, the worker, and the command line.

What these tests hold:
- the orchestrator computes digests from the files, and the same key with other inputs is refused;
- two jobs never share a folder, and a status file is always whole;
- a final phase is never left: a cancelled job cannot become accept, whatever its worker does next;
- cancelling stops the worker and what it started; a worker that dies is reported failed; a job that
  runs out of time is needs-review;
- a missing tool or an unusable input is a diagnostic and needs-review, never a pass, and nothing in
  the orchestrator imports the fixer or the loop;
- for the same inputs the Godot engine gives the decision the CI gate gives.

The Godot engine is run here with the gate tests' stand-in replay; no game is started. Worker
processes are real, with stand-in engines (tests/orchestrator_worker.py). Not covered here: a real
Godot verification through the orchestrator (see the pull request for a recorded local run).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import jsonschema

from expectrail.gate import record as rec
from expectrail.gate import verify as gate
from expectrail.orchestrator import cli, engines, runner
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import request as req
from expectrail.orchestrator import store as st
from tests.orchestrator_worker import ENGINES as STAND_INS
from tests.test_ci_gate import FIXTURES, FakeReplay, make_repo

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "contracts" / "examples"


def wait_for(condition, seconds: float = 10.0, what: str = "the condition"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"{what} did not happen in {seconds} s")


def gone(pid: int) -> bool:
    return not st.alive(pid)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orch-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.head = make_repo(self.tmp / "head")
        self.store = st.JobStore(self.tmp / "jobs", lease_seconds=0.6)
        self.started: list[subprocess.Popen] = []
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        for proc in self.started:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)

    def request(self, adapter: str = "godot", **over) -> dict:
        fields = dict(adapter=adapter, head=self.head, game="game/platformer", routes=["routes/*.json"], specs="specs")
        fields.update(over)
        return req.build(**fields)

    def job(self, adapter: str = "godot", **over) -> str:
        status, created = self.store.create(self.request(adapter, **over))
        self.assertTrue(created)
        return status["id"]

    def spawn(self, job_id: str) -> subprocess.Popen:
        proc = runner.spawn(self.store, job_id, command=[
            sys.executable, "-m", "tests.orchestrator_worker", str(self.store.root), str(self.store.lease_seconds), job_id])
        self.started.append(proc)
        return proc

    def running(self, job_id: str) -> None:
        wait_for(lambda: (self.store.paths(job_id).work / "running").exists(), what="the slow engine starting")


class RequestTest(Case):
    def test_the_examples_match_their_schemas(self):
        for name, schema in (("verify-request", req.schema()), ("verify-job", st.schema())):
            doc = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(doc)
            rec.validate(doc, schema)   # the reader the orchestrator uses agrees
        req.check(json.loads((EXAMPLES / "verify-request.json").read_text(encoding="utf-8")))
        st.check_status(json.loads((EXAMPLES / "verify-job.json").read_text(encoding="utf-8")))

    def test_a_request_carries_no_digest_and_unknown_fields_are_refused(self):
        doc = self.request()
        self.assertNotIn("sha256", json.dumps(doc).lower())
        for bad in (dict(doc, policyDigest="0" * 64), dict(doc, format="expectrail.verify-request/v0"),
                    dict(doc, executionClass="protected"), dict(doc, limits={"timeoutSeconds": 0}),
                    dict(doc, project=dict(doc["project"], routes=[])),
                    dict(doc, head=dict(doc["head"], checkout="relative/path")),
                    dict(doc, idempotencyKey="has spaces")):
            with self.subTest(bad=sorted(set(map(str, bad.items())) - set(map(str, doc.items())))[:1]):
                with self.assertRaises(req.RequestError):
                    req.check(bad)

    def test_the_digests_come_from_the_files(self):
        doc = self.request()
        first = req.inputs(doc)
        self.assertEqual(first, req.inputs(doc))
        self.assertEqual(first["headTree"], req.tree_digest(self.head / "game" / "platformer"))
        self.assertIsNone(first["baseTree"])
        (self.head / "game" / "platformer" / "player.gd").write_text("# changed\n", encoding="utf-8")
        second = req.inputs(doc)
        self.assertNotEqual(first["headTree"], second["headTree"])
        self.assertEqual(first["policyDigest"], second["policyDigest"])
        spec = self.head / "specs" / "player-stays-above-ground.json"
        spec.write_text(spec.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        third = req.inputs(doc)
        self.assertNotEqual(second["policyDigest"], third["policyDigest"])
        self.assertEqual(len({first["requestDigest"], second["requestDigest"], third["requestDigest"]}), 3)

    def test_with_a_base_the_policy_is_read_from_the_base(self):
        base = make_repo(self.tmp / "base")
        doc = self.request(base=base)
        before = req.inputs(doc)
        spec = self.head / "specs" / "player-stays-above-ground.json"
        spec.write_text("{}", encoding="utf-8")   # the change edits the check that judges it
        self.assertEqual(req.inputs(doc)["policyDigest"], before["policyDigest"])
        (base / "specs" / "player-stays-above-ground.json").write_text("{}", encoding="utf-8")
        self.assertNotEqual(req.inputs(doc)["policyDigest"], before["policyDigest"])

    def test_where_a_checkout_sits_and_the_key_are_not_part_of_what_a_request_means(self):
        other = make_repo(self.tmp / "elsewhere")
        a = req.inputs(self.request(idempotency_key="k1"))
        b = req.inputs(self.request(head=other, idempotency_key="k2"))
        self.assertEqual(a["requestDigest"], b["requestDigest"])
        self.assertNotEqual(a["requestDigest"], req.inputs(self.request(timeout_seconds=5))["requestDigest"])


class StoreTest(Case):
    def test_two_jobs_never_share_a_folder(self):
        ids = [self.job() for _ in range(5)]
        self.assertEqual(len(set(ids)), 5)
        folders = [self.store.paths(i) for i in ids]
        self.assertEqual(len({p.root for p in folders}), 5)
        for paths in folders:
            self.assertTrue(paths.work.is_dir())
            self.assertEqual(paths.work.parent, paths.root)
            self.assertFalse(paths.output.exists())

    def test_only_a_job_id_names_a_job(self):
        for bad in ("../../etc", "", "0" * 31, "g" * 32, "0" * 32 + "/x", None):
            with self.subTest(bad=bad), self.assertRaises(st.UnknownJob):
                self.store.status(bad)
        with self.assertRaises(st.UnknownJob):
            self.store.status("0" * 32)

    def test_a_new_job_is_queued_with_its_inputs_and_no_result(self):
        status = self.store.status(self.job())
        self.assertEqual((status["phase"], status["decision"], status["output"], status["worker"]), ("queued", None, None, None))
        self.assertEqual(status["inputs"], req.inputs(self.request()))
        self.assertEqual([h["phase"] for h in status["history"]], ["queued"])

    def test_the_status_file_is_always_whole(self):
        job = self.job()
        self.store.claim(job, os.getpid(), os.getpgid(0))
        stop, problems = threading.Event(), []

        def read():
            while not stop.is_set():
                try:
                    st.check_status(json.loads(self.store.paths(job).status.read_text(encoding="utf-8")))
                except Exception as exc:  # noqa: BLE001
                    problems.append(repr(exc))

        readers = [threading.Thread(target=read) for _ in range(3)]
        for reader in readers:
            reader.start()
        try:
            for n in range(200):
                self.store.heartbeat(job)
                self.store.advance(job, ("preparing", "executing", "observing", "evaluating")[n % 4])
        finally:
            stop.set()
            for reader in readers:
                reader.join()
        self.assertEqual(problems, [])
        # Phases only go forward: asking for an earlier one again changed nothing.
        self.assertEqual([h["phase"] for h in self.store.status(job)["history"]],
                         ["queued", "preparing", "executing", "observing", "evaluating"])
        self.assertEqual([p.name for p in self.store.paths(job).root.glob(".status.json.*")], [])

    def test_a_final_phase_is_never_left(self):
        for first in ("cancelled", "failed"):
            with self.subTest(first=first):
                job = self.job()
                paths = self.store.paths(job)
                paths.staging.mkdir()
                (paths.staging / "evidence.txt").write_text("x", encoding="utf-8")
                ended = self.store.finish(job, first, reasons=["first"])
                late = self.store.finish(job, "completed", decision="accept", reasons=["late"], publish=True)
                self.assertEqual(late, ended)
                self.assertEqual((late["phase"], late["decision"], late["output"]), (first, None, None))
                self.assertFalse(paths.output.exists())
                self.assertFalse(paths.staging.exists())
                self.assertEqual(self.store.advance(job, "executing")["phase"], first)
                self.assertEqual(self.store.heartbeat(job)["phase"], first)
        done = self.job()
        self.store.finish(done, "completed", decision="reject", reasons=["a check fails"])
        self.assertEqual(self.store.finish(done, "completed", decision="accept")["decision"], "reject")
        self.assertEqual(self.store.cancel(done)["phase"], "completed")

    def test_a_decision_belongs_to_a_completed_job_only(self):
        job = self.job()
        for phase, decision in (("failed", "accept"), ("cancelled", "needs-review"), ("completed", None), ("completed", "maybe")):
            with self.subTest(phase=phase, decision=decision), self.assertRaises(st.StoreError):
                self.store.finish(job, phase, decision=decision)
        with self.assertRaises(st.StoreError):
            self.store.finish(job, "executing")
        with self.assertRaises(st.StoreError):
            self.store.advance(job, "completed")
        self.assertEqual(self.store.status(job)["phase"], "queued")

    def test_a_status_someone_edited_is_refused(self):
        job = self.job()
        path = self.store.paths(job).status
        good = json.loads(path.read_text(encoding="utf-8"))
        for edit in ({"decision": "accept"}, {"phase": "cancelled"}, {"output": "output"}, {"extra": 1},
                     {"phase": "completed", "decision": "accept", "finishedAt": good["createdAt"]}):
            with self.subTest(edit=edit):
                path.write_text(json.dumps(dict(good, **edit)), encoding="utf-8")
                with self.assertRaises(st.StoreError):
                    self.store.status(job)
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.store.status(job)["phase"], "queued")

    def test_output_appears_by_one_rename_for_a_completed_job(self):
        job = self.job()
        paths = self.store.paths(job)
        paths.staging.mkdir()
        (paths.staging / "evidence.txt").write_text("x", encoding="utf-8")
        status = self.store.finish(job, "completed", decision="accept", evidence_grade="diagnostic", publish=True)
        self.assertEqual((status["output"], status["evidenceGrade"]), ("output", "diagnostic"))
        self.assertEqual((paths.output / "evidence.txt").read_text(encoding="utf-8"), "x")
        self.assertFalse(paths.staging.exists())

    def test_the_same_key_and_inputs_give_the_same_job(self):
        first, created = self.store.create(self.request(idempotency_key="pr-7:abc"))
        again, created_again = self.store.create(self.request(idempotency_key="pr-7:abc"))
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(list((self.store.root / "jobs").iterdir())), 1)
        other, _ = self.store.create(self.request(idempotency_key="pr-8:abc"))
        self.assertNotEqual(other["id"], first["id"])

    def test_the_same_key_with_other_inputs_is_an_error(self):
        self.store.create(self.request(idempotency_key="pr-7:abc"))
        (self.head / "game" / "platformer" / "player.gd").write_text("# changed\n", encoding="utf-8")
        with self.assertRaises(st.IdempotencyConflict):
            self.store.create(self.request(idempotency_key="pr-7:abc"))
        self.assertEqual(len(list((self.store.root / "jobs").iterdir())), 1)

    def test_a_job_has_one_worker_whoever_records_it_first(self):
        # The process that starts a worker and the worker itself both record it. In CI the worker got
        # there first, the starter's call then failed, and the job was lost (the first run of #302).
        job = self.job()
        first = self.store.claim(job, 4242, 4242)
        self.assertEqual(first["worker"], {"pid": 4242, "pgid": 4242})
        self.assertIsNotNone(first["lease"])
        self.assertEqual(self.store.claim(job, 4242, 4242)["worker"], first["worker"])
        for other in ((4243, 4243), (4242, 1)):
            with self.subTest(other=other), self.assertRaises(st.StoreError):
                self.store.claim(job, *other)
        self.store.finish(job, "cancelled")
        self.assertEqual(self.store.claim(job, 9, 9)["phase"], "cancelled")


class Crash:
    def preflight(self, request):
        return []

    def execute(self, request, paths, advance):
        raise RuntimeError("a bug in the engine")


class NoTool:
    executed = False

    def preflight(self, request):
        return [st.diagnostic("TOOL_MISSING", stage="preparing", detail="Godot could not be found")]

    def execute(self, request, paths, advance):
        NoTool.executed = True
        return engines.Result("accept")


class BadInput(Crash):
    def execute(self, request, paths, advance):
        raise gate.ConfigError("routes must stay inside the checkout")


class TimesOut(Crash):
    def execute(self, request, paths, advance):
        raise subprocess.TimeoutExpired(["godot"], 600)


class WorkTest(Case):
    def work(self, job: str, table: dict) -> dict:
        with contextlib.redirect_stderr(io.StringIO()):
            return runner.work(self.store, job, engines=table)

    def test_a_job_that_works_is_completed_with_its_evidence_published(self):
        job = self.job("instant")
        status = self.work(job, STAND_INS)
        self.assertEqual((status["phase"], status["decision"], status["output"], status["evidenceGrade"]),
                         ("completed", "accept", "output", "diagnostic"))
        self.assertEqual([h["phase"] for h in status["history"]], ["queued", "preparing", "executing", "evaluating", "completed"])
        paths = self.store.paths(job)
        self.assertEqual((paths.output / "evidence.txt").read_text(encoding="utf-8"), f"evidence of {job}\n")
        self.assertFalse(paths.staging.exists())
        self.assertEqual(self.store.status(job), status)

    def test_a_missing_tool_is_a_diagnostic_and_needs_review_and_nothing_runs(self):
        job = self.job("notool")
        status = self.work(job, {"notool": NoTool()})
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("completed", "needs-review", None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["TOOL_MISSING"])
        self.assertTrue(status["diagnostics"][0]["fix"])
        self.assertFalse(NoTool.executed)
        self.assertFalse(self.store.paths(job).output.exists())

    def test_an_adapter_the_orchestrator_does_not_have_is_needs_review(self):
        status = self.work(self.job("unreal"), STAND_INS)
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))

    def test_an_unusable_input_and_a_timeout_are_explained_and_need_review(self):
        for engine, code in ((BadInput(), "INPUT_INVALID"), (TimesOut(), "EXECUTION_TIMEOUT")):
            with self.subTest(code=code):
                status = self.work(self.job("x"), {"x": engine})
                self.assertEqual((status["phase"], status["decision"]), ("completed", "needs-review"))
                self.assertEqual([d["code"] for d in status["diagnostics"]], [code])

    def test_a_crash_in_the_orchestrator_is_a_failed_job_with_no_decision(self):
        status = self.work(self.job("crash"), {"crash": Crash()})
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("failed", None, None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["INTERNAL_ERROR"])

    def test_a_job_belongs_to_one_worker(self):
        job = self.job("instant")
        self.store.claim(job, 1, 1)
        with self.assertRaises(st.StoreError):
            runner.work(self.store, job, engines=STAND_INS)

    def test_a_worker_recorded_before_it_starts_still_does_the_job(self):
        job = self.job("instant")
        self.store.claim(job, os.getpid(), os.getpgid(0))   # the starter got there first
        self.assertEqual(self.work(job, STAND_INS)["decision"], "accept")

    def test_a_job_cancelled_before_its_worker_starts_is_left_alone(self):
        job = self.job("instant")
        self.store.cancel(job)
        status = self.work(job, STAND_INS)
        self.assertEqual((status["phase"], status["decision"]), ("cancelled", None))
        self.assertFalse(self.store.paths(job).output.exists())


class GodotEngineTest(Case):
    """The engine against the gate itself, both on the gate tests' stand-in replay."""

    def decide(self, head: Path, base: Path | None = None, **over) -> dict:
        self.head = head
        job = self.job(base=base, **over)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return runner.work(self.store, job, engines={"godot": engines.GodotGate(replay=FakeReplay())})

    def gate(self, head: Path, base: Path | None, name: str) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return gate.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                                 out=self.tmp / name, work=self.tmp / f"{name}-work", base=base, replay=FakeReplay())

    def test_it_decides_as_the_gate_does(self):
        clean, bug = self.head, make_repo(self.tmp / "bug", bug=True)
        crash = make_repo(self.tmp / "crash", crash=True)
        for name, head, base, expected in (("clean", clean, None, "accept"), ("bug", bug, None, "reject"),
                                           ("fix", clean, bug, "accept"), ("regression", bug, clean, "reject"),
                                           ("crash", crash, clean, "needs-review")):
            with self.subTest(case=name):
                status = self.decide(head, base)
                record = self.gate(head, base, f"gate-{name}")
                self.assertEqual(record["decision"], expected)
                self.assertEqual((status["phase"], status["decision"]), ("completed", record["decision"]))
                self.assertEqual(status["reasons"], record["reasons"])
                published = rec.read_record(self.store.paths(status["id"]).output / "findings.json")
                self.assertEqual(published["decision"], record["decision"])
                self.assertEqual(published["counts"], record["counts"])

    def test_no_project_is_needs_review_before_anything_runs(self):
        replay = FakeReplay()
        job = self.job(game="game/missing")
        status = runner.work(self.store, job, engines={"godot": engines.GodotGate(replay=replay)})
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertEqual(replay.calls, [])

    def test_the_isolated_class_refuses_instead_of_running_unsandboxed(self):
        replay = FakeReplay()
        job = self.job(execution_class="isolated")
        status = runner.work(self.store, job, engines={"godot": engines.GodotGate(replay=replay)})
        self.assertEqual((status["phase"], status["decision"], status["evidenceGrade"]), ("completed", "needs-review", None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["TOOL_MISSING"])
        self.assertIn("sandbox", status["diagnostics"][0]["detail"])
        self.assertEqual(replay.calls, [])

    def test_the_orchestrator_imports_no_fixer_no_loop_and_no_saved_data(self):
        code = ("import sys, expectrail.orchestrator.cli, expectrail.orchestrator.engines, expectrail.gate.verify\n"
                "print('\\n'.join(sorted(sys.modules)))")
        loaded = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
        for forbidden in ("agents.fixer", "agents.loop", "agents.byo_fixer", "agents.keys", "agents.triage", "agents.muse"):
            self.assertNotIn(forbidden, loaded)
        for path in sorted((REPO / "expectrail" / "orchestrator").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for word in ("agents.fixer", "agents.loop", "agents.keys", "fixtures"):
                self.assertNotIn(word, source, f"{path.name} mentions {word}")


class ProcessTest(Case):
    """Real worker processes, each in a process group of its own."""

    def child_of(self, job: str) -> int:
        return int((self.store.paths(job).work / "child.pid").read_text(encoding="utf-8"))

    def test_two_jobs_at_once_keep_to_their_own_folders(self):
        jobs = [self.job("instant"), self.job("instant")]
        procs = [self.spawn(job) for job in jobs]
        statuses = [runner.wait(self.store, job, proc) for job, proc in zip(jobs, procs)]
        self.assertEqual([s["decision"] for s in statuses], ["accept", "accept"])
        for job in jobs:
            paths = self.store.paths(job)
            self.assertEqual((paths.output / "evidence.txt").read_text(encoding="utf-8"), f"evidence of {job}\n")
            self.assertEqual((paths.work / "scratch.txt").read_text(encoding="utf-8"), job)
            self.assertEqual(sorted(p.name for p in paths.root.iterdir()),
                             ["lock", "output", "request.json", "status.json", "work", "worker.log"])

    def test_a_cancelled_job_ends_cancelled_with_everything_it_started_stopped(self):
        job = self.job("slow")
        proc = self.spawn(job)
        self.running(job)
        child = self.child_of(job)
        self.assertEqual(self.store.status(job)["phase"], "executing")
        status = self.store.cancel(job, grace_seconds=2)
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("cancelled", None, None))
        proc.wait(timeout=5)
        wait_for(lambda: gone(child), what="the engine's own child stopping")
        self.assertTrue(gone(proc.pid))
        paths = self.store.paths(job)
        self.assertFalse(paths.output.exists())
        self.assertFalse(paths.staging.exists())
        self.assertEqual(self.store.status(job), status)
        self.assertEqual(self.store.cancel(job), status)

    def test_a_worker_that_is_killed_leaves_a_failed_job_once_its_lease_runs_out(self):
        job = self.job("slow")
        proc = self.spawn(job)
        self.running(job)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        status = wait_for(lambda: (s := self.store.status(job))["phase"] in st.FINAL and s, seconds=5,
                          what="the lease running out")
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("failed", None, None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["WORKER_LOST"])

    def test_a_worker_that_records_itself_before_its_starter_does_is_not_lost(self):
        # Start the worker by hand and let it finish before the starter records it.
        job = self.job("instant")
        with open(self.store.paths(job).log, "ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "tests.orchestrator_worker", str(self.store.root),
                                     str(self.store.lease_seconds), job], cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        self.started.append(proc)
        self.assertEqual(proc.wait(timeout=20), 0)
        status = self.store.claim(job, proc.pid, proc.pid)
        self.assertEqual((status["phase"], status["decision"], status["worker"]["pid"]), ("completed", "accept", proc.pid))

    def test_many_jobs_started_at_once_all_finish(self):
        jobs = [self.job("instant") for _ in range(8)]
        procs = [self.spawn(job) for job in jobs]
        decisions = [runner.wait(self.store, job, proc)["decision"] for job, proc in zip(jobs, procs)]
        self.assertEqual(decisions, ["accept"] * 8)

    def test_waiting_on_a_worker_that_died_reports_it_at_once(self):
        job = self.job("slow")
        proc = self.spawn(job)
        self.running(job)
        os.killpg(proc.pid, signal.SIGKILL)
        started = time.monotonic()
        status = runner.wait(self.store, job, proc, poll_seconds=0.05)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual((status["phase"], [d["code"] for d in status["diagnostics"]]), ("failed", ["WORKER_LOST"]))

    def test_a_job_that_runs_out_of_time_is_needs_review_and_is_stopped(self):
        job = self.job("slow", timeout_seconds=1)
        proc = self.spawn(job)
        status = runner.wait(self.store, job, proc, poll_seconds=0.05)
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("completed", "needs-review", None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["EXECUTION_TIMEOUT"])
        child = self.child_of(job)
        wait_for(lambda: gone(child), what="the engine's own child stopping")
        self.assertFalse(self.store.paths(job).output.exists())


class CliTest(Case):
    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--jobs-root", str(self.store.root), "--lease-seconds", "0.6", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_verify_with_a_real_worker_and_no_project_needs_review(self):
        code, out, _ = self.run_cli("verify", "--head", str(self.head), "--game", "game/missing",
                                    "--routes", "routes/*.json", "--specs", "specs", "--json")
        status = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual((status["phase"], status["decision"], [d["code"] for d in status["diagnostics"]]),
                         ("completed", "needs-review", ["INPUT_INVALID"]))
        self.assertIsNotNone(status["worker"])
        self.assertNotEqual(status["worker"]["pid"], os.getpid())

    def test_the_exit_code_says_what_happened(self):
        outcomes = {}
        for name, finish in (("accept", dict(phase="completed", decision="accept")),
                             ("reject", dict(phase="completed", decision="reject")),
                             ("needs-review", dict(phase="completed", decision="needs-review")),
                             ("failed", dict(phase="failed")), ("cancelled", dict(phase="cancelled"))):
            job = self.job()
            self.store.finish(job, finish.pop("phase"), **finish)
            outcomes[name] = self.run_cli("report", job)[0]
        self.assertEqual(outcomes, {"accept": 0, "reject": 1, "needs-review": 2, "failed": 3, "cancelled": 4})

    def test_status_cancel_and_report(self):
        job = self.job()
        code, out, _ = self.run_cli("status", job, "--json")
        self.assertEqual((code, json.loads(out)["phase"]), (0, "queued"))
        code, _, err = self.run_cli("report", job)
        self.assertEqual(code, 5)
        self.assertIn("no result yet", err)
        code, out, _ = self.run_cli("cancel", job)
        self.assertEqual(code, 4)
        self.assertIn("cancelled", out)
        code, _, err = self.run_cli("status", "0" * 32)
        self.assertEqual(code, 5)
        self.assertIn("no job", err)

    def test_the_same_key_with_other_inputs_is_refused_at_the_command_line(self):
        args = ("verify", "--head", str(self.head), "--game", "game/missing", "--routes", "routes/*.json",
                "--specs", "specs", "--idempotency-key", "k", "--detach")
        code, first, _ = self.run_cli(*args)
        self.assertEqual(code, 0)
        code, again, _ = self.run_cli(*args)
        self.assertEqual((code, again), (0, first))
        (self.head / "specs" / "extra.json").write_text("{}", encoding="utf-8")
        code, _, err = self.run_cli(*args)
        self.assertEqual(code, 5)
        self.assertIn("different inputs", err)
        runner.wait(self.store, first.strip())


class PatchedReplay:
    """The gate tests' two recorded traces, chosen by whether the sample's seeded bug is in the game:
    the bug's patch changes player/player.tscn, so a copy that differs from the repository's has it."""

    def __init__(self):
        self.calls = 0

    def __call__(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        self.calls += 1
        bug = (game / "player" / "player.tscn").read_bytes() != (REPO / smp.GAME / "player" / "player.tscn").read_bytes()
        out.mkdir(parents=True, exist_ok=True)
        trace = json.loads((FIXTURES / ("trace-fallthrough.json" if bug else "trace-fixed.json")).read_text(encoding="utf-8"))
        frames_dir = None
        if frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)
            for n in range(40):
                (frames_dir / f"f{n:08d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + f"{bug}:{n}".encode())
        return {"trace": trace, "replaySha256": "0" * 64, "framesDir": frames_dir}


class SampleTest(Case):
    def test_the_two_checkouts_differ_by_the_seeded_bug_only(self):
        clean = smp.checkout(self.tmp / "clean", bug=False)
        bug = smp.checkout(self.tmp / "bug", bug=True)
        changed = [p.relative_to(clean).as_posix() for p in sorted(clean.rglob("*"))
                   if p.is_file() and p.read_bytes() != (bug / p.relative_to(clean)).read_bytes()]
        self.assertEqual(changed, ["game/platformer/player/player.tscn"])
        self.assertEqual(sorted(p.relative_to(clean).as_posix() for p in clean.rglob("*") if p.is_file()),
                         sorted(p.relative_to(bug).as_posix() for p in bug.rglob("*") if p.is_file()
                                if not p.name.endswith((".orig", ".rej"))))
        project = {"game": smp.GAME, "routes": [smp.ROUTE], "specs": smp.SPECS}
        self.assertEqual(req.policy_digest(clean, project), req.policy_digest(bug, project))
        self.assertNotEqual(req.tree_digest(clean / smp.GAME), req.tree_digest(bug / smp.GAME))

    def test_the_three_runs_decide_accept_reject_accept(self):
        replay = PatchedReplay()
        seen = []
        with contextlib.redirect_stdout(io.StringIO()):
            results = smp.run(self.store, engines={"godot": engines.GodotGate(replay=replay)}, on_case=seen.append)
        self.assertEqual([(r["status"]["phase"], r["status"]["decision"]) for r in results],
                         [("completed", "accept"), ("completed", "reject"), ("completed", "accept")])
        self.assertEqual([r["expected"] for r in results], ["accept", "reject", "accept"])
        self.assertTrue(all(r["asExpected"] for r in results))
        self.assertEqual(seen, results)
        self.assertEqual(len({r["status"]["id"] for r in results}), 3)
        self.assertGreater(replay.calls, 3)   # the base is replayed too when there is one
        self.assertIn("as expected", smp.line(results[1]))

    def test_a_run_that_decides_otherwise_is_said_plainly(self):
        class Accepts:
            def preflight(self, request):
                return []

            def execute(self, request, paths, advance):
                return engines.Result("accept", ["accepts everything"])

        results = smp.run(self.store, engines={"godot": Accepts()})
        self.assertEqual([r["asExpected"] for r in results], [True, False, True])
        self.assertIn("NOT as expected (a working install gives reject)", smp.line(results[1]))

    def test_a_missing_tool_shows_its_fix_and_is_not_as_expected(self):
        results = smp.run(self.store, engines={"godot": NoTool()})
        self.assertEqual([r["asExpected"] for r in results], [False, False, False])
        text = smp.line(results[0])
        self.assertIn("needs-review, NOT as expected", text)
        self.assertIn("TOOL_MISSING", text)
        self.assertIn("Fix:", text)

    def test_the_command_exits_0_only_when_all_three_are_as_expected(self):
        def fake(decisions):
            return [{"case": n, "expected": e, "asExpected": d == e,
                     "status": {"phase": "completed", "decision": d, "diagnostics": []}}
                    for (n, _h, _b, e), d in zip(smp.CASES, decisions)]

        for decisions, code in ((("accept", "reject", "accept"), 0), (("accept", "accept", "accept"), 1)):
            with self.subTest(decisions=decisions), mock.patch.object(smp, "run", return_value=fake(decisions)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(cli.main(["--jobs-root", str(self.store.root), "sample", "--json"]), code)
                self.assertEqual(len(json.loads(out.getvalue())), 3)

    def test_a_copy_of_expectrail_without_the_sample_files_says_so(self):
        with self.assertRaises(smp.SampleError):
            smp.checkout(self.tmp / "x", bug=True, root=self.tmp)


if __name__ == "__main__":
    unittest.main()
