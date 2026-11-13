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
import unittest.mock
from pathlib import Path
from unittest import mock

import jsonschema

from expectrail.gate import record as rec
from expectrail.gate import verify as gate
from expectrail.orchestrator import cli, engines, runner
from expectrail.orchestrator import request as req
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st
from tests.orchestrator_worker import ENGINES as STAND_INS
from tests.test_ci_gate import FIXTURES, FakeReplay, make_repo

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "contracts" / "examples"

# Every file this process opens while WATCHING is non-empty, by any route (an audit hook cannot be
# removed, so it is added once and switched by the list).
OPENED: list[str] = []
WATCHING: list[bool] = []


def _note_opens(event: str, args: tuple) -> None:
    if WATCHING and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        OPENED.append(os.fsdecode(args[0]))


sys.addaudithook(_note_opens)


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

    def evidence(self, job_id: str) -> None:
        """What an engine leaves before it decides: a staging folder with something in it."""
        staging = self.store.paths(job_id).staging
        staging.mkdir(exist_ok=True)
        (staging / "evidence.txt").write_text("x", encoding="utf-8")

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
        self.evidence(done)
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
        ended = [{"phase": "queued", "at": good["createdAt"]}, {"phase": "completed", "at": good["createdAt"]}]
        for edit in ({"decision": "accept"}, {"phase": "cancelled"}, {"output": "output"}, {"extra": 1},
                     {"phase": "completed", "decision": "accept", "finishedAt": good["createdAt"]},
                     # everything a completed accept has, except the evidence
                     {"phase": "completed", "decision": "accept", "finishedAt": good["createdAt"], "history": ended},
                     {"phase": "completed", "decision": "reject", "finishedAt": good["createdAt"], "history": ended}):
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
            return runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=FakeReplay())})

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
        status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=replay)})
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertEqual(replay.calls, [])

    def test_the_isolated_class_refuses_instead_of_running_unsandboxed(self):
        from harness import sandbox as box

        replay = FakeReplay()
        job = self.job(execution_class="isolated")
        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")):
            status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=replay)})
        self.assertEqual((status["phase"], status["decision"], status["evidenceGrade"]), ("completed", "needs-review", None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["TOOL_MISSING"])
        self.assertIn("bubblewrap (bwrap) is not installed", status["diagnostics"][0]["detail"])
        self.assertIn("nothing was run unsandboxed", status["diagnostics"][0]["detail"])
        self.assertEqual(replay.calls, [])

    def test_the_isolated_class_runs_with_the_sandbox_required(self):
        from harness import sandbox as box
        from tests.test_ci_gate import INSIDE, Accounting

        with mock.patch.object(box, "probe", return_value=(box.Tool("/usr/bin/bwrap", "0.9.0"), None)):
            # Every replay says it ran inside: the job completes, and the evidence says so.
            job = self.job(execution_class="isolated")
            status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=Accounting(INSIDE))})
            self.assertEqual((status["phase"], status["decision"]), ("completed", "accept"))
            record = rec.read_record(self.store.paths(job).output / "findings.json")
            self.assertEqual((record["isolation"]["required"], record["isolation"]["sandboxed"], record["isolation"]["replays"]),
                             (True, 2, 2))
            # The ledger's `isolated` grade also needs a trusted job that judges and signs: not yet.
            self.assertEqual(status["evidenceGrade"], "diagnostic")
            # A replay that does not say it ran inside cannot give an accept in this class.
            job = self.job(execution_class="isolated")
            status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=FakeReplay())})
            self.assertEqual((status["phase"], status["decision"]), ("completed", "needs-review"))
            self.assertTrue(any("outside the sandbox" in reason for reason in status["reasons"]), status["reasons"])

    def test_the_checks_that_judge_are_the_ones_the_job_names(self):
        # The engine reads the specs and routes once, holds their digest against the job's, and the
        # gate judges with what was read. Whatever is done to the checkout afterwards does not reach
        # the verdict, and each replay plays a copy of its route made from the bytes that were read.
        import hashlib

        specs, routes = self.head / "specs", self.head / "routes"
        played: list[str] = []

        class SpoilsTheChecksMidRun(FakeReplay):
            def __call__(self, route, game, out, frames):
                for spec in specs.glob("*.json"):
                    spec.write_text("{}", encoding="utf-8")      # no longer a spec at all
                for file in routes.glob("*.json"):
                    file.unlink()
                played.append(hashlib.sha256(Path(route).read_bytes()).hexdigest())
                self.assertNotInTheCheckout(route)
                return super().__call__(route, game, out, frames)

            def assertNotInTheCheckout(self, route):
                assert routes.resolve() not in Path(route).resolve().parents, route

        expected = self.gate(self.head, None, "gate-before")     # the gate on the checkout as it was
        job = self.job()
        named = self.store.status(job)["inputs"]["policyDigest"]
        with contextlib.redirect_stdout(io.StringIO()):
            status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=SpoilsTheChecksMidRun())})
        self.assertEqual((status["phase"], status["decision"]), ("completed", "accept"))
        record = rec.read_record(self.store.paths(job).output / "findings.json")
        self.assertEqual((record["specs"], record["routes"], record["checks"]),
                         (expected["specs"], expected["routes"], expected["checks"]))
        self.assertEqual(sorted(set(played)), sorted(r["sha256"] for r in record["routes"]))
        self.assertNotEqual(req.inputs(self.request())["policyDigest"], named)   # the checkout has moved on

    def test_checks_that_changed_before_the_engine_reads_them_stop_the_job(self):
        # There is one source for the checks, the engine's one reading. If it is not what the job
        # names, there is no verdict; nothing is read a second time and nothing is fallen back to
        # (second review of #321: an engine that lost its copy went back to the checkout in silence).
        spec = self.head / "specs" / "player-stays-above-ground.json"

        class EditsTheSpecFirst(engines.GodotGate):
            def execute(self, request, paths, advance):
                spec.write_text(spec.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return super().execute(request, paths, advance)

        replay = FakeReplay()
        job = self.job()
        status = runner.work(self.store, job, engines={"godot": EditsTheSpecFirst(rule="engine-only", replay=replay)})
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertIn("the checks changed after the job was created", status["diagnostics"][0]["detail"])
        self.assertEqual(replay.calls, [])
        self.assertIsNone(status["output"])

    def test_a_verdict_judged_with_other_checks_than_the_jobs_is_not_given(self):
        # The worker's own hold, for any engine: the digest of the checks the engine says it judged
        # with must be the job's.
        case = self

        class JudgedWithOtherChecks:
            def preflight(self, request):
                return []

            def execute(self, request, paths, advance):
                case.evidence(paths.root.name)
                return engines.Result("accept", policy="0" * 64)

        job = self.job()
        status = runner.work(self.store, job, engines={"godot": JudgedWithOtherChecks()})
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertIn("the checks changed while the job was running", status["diagnostics"][0]["detail"])
        self.assertIsNone(status["output"])

    def test_a_spec_the_gate_refuses_is_refused_the_same_way_in_a_job_and_never_opened(self):
        # One reader for the checks, the gate's. Whatever form a spec file takes, a job says what
        # the plain gate says about the same checkout, and what a link leads to is not opened
        # (first review of #321: a copy made by another reader followed links the gate refuses).
        second = json.loads((self.head / "specs" / "player-stays-above-ground.json").read_text(encoding="utf-8"))
        second["id"] = "second-check"
        text = json.dumps(second)
        forms = {
            "a file": lambda repo, spec: spec.write_text(text, encoding="utf-8"),
            "a link to a file inside the checkout": lambda repo, spec: (
                (repo / "kept").mkdir(), (repo / "kept" / "target.json").write_text(text, encoding="utf-8"),
                spec.symlink_to(repo / "kept" / "target.json")),
            "a link to a file outside the checkout": lambda repo, spec: (
                (repo.parent / f"outside-{repo.name}").mkdir(),
                (repo.parent / f"outside-{repo.name}" / "target.json").write_text(text, encoding="utf-8"),
                spec.symlink_to(repo.parent / f"outside-{repo.name}" / "target.json")),
            "a link to nothing": lambda repo, spec: spec.symlink_to(repo / "kept" / "missing.json"),
            "a link to something that is not JSON": lambda repo, spec: (
                (repo / "kept").mkdir(), (repo / "kept" / "target.json").write_text("not json", encoding="utf-8"),
                spec.symlink_to(repo / "kept" / "target.json")),
            "a file over the size cap": lambda repo, spec: spec.write_text(text + " " * (gate.SPEC_CAP + 1), encoding="utf-8"),
        }
        checks_expected = {"a file": 4}
        for n, (name, make) in enumerate(forms.items()):
            with self.subTest(two_json=name):
                repo = make_repo(self.tmp / f"form-{n}")
                spec = repo / "specs" / "two.json"
                make(repo, spec)
                target = os.path.abspath(os.readlink(spec)) if spec.is_symlink() else None
                plain = self.gate(repo, None, f"gate-form-{n}")
                self.head = repo
                OPENED.clear()
                WATCHING.append(True)
                try:
                    job = self.job(idempotency_key=f"form-{n}")
                    with contextlib.redirect_stdout(io.StringIO()):
                        status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=FakeReplay())})
                finally:
                    WATCHING.clear()
                self.assertEqual((status["phase"], status["decision"], status["reasons"]),
                                 ("completed", plain["decision"], plain["reasons"]))
                record = rec.read_record(self.store.paths(job).output / "findings.json")
                self.assertEqual((len(record["checks"]), record["specs"], record["drafts"]),
                                 (len(plain["checks"]), plain["specs"], plain["drafts"]))
                self.assertEqual(len(record["checks"]), checks_expected.get(name, 2))
                opened = {os.path.abspath(p) for p in OPENED}
                self.assertIn(str(repo / "specs" / "player-stays-above-ground.json"), opened)   # the watch does see opens
                if target is not None:
                    self.assertNotIn(target, opened)   # what the link leads to was never opened, by anything
                if name not in ("a file", "a link to nothing"):
                    self.assertTrue(any("two.json" in reason for reason in status["reasons"]), status["reasons"])

    def test_the_digest_of_the_checks_covers_what_the_gate_reads_and_nothing_a_link_leads_to(self):
        project = self.request()["project"]
        before = req.policy_digest(self.head, project)
        self.assertEqual(before, gate.read_checks(self.head, "specs", ["routes/*.json"]).digest)
        # A file that only looks like a check is neither read nor digested, and neither is a link
        # to nothing or to a folder where a route would be.
        (self.head / "specs" / "notes.txt").write_text("not a spec\n", encoding="utf-8")
        (self.head / "specs" / "deeper").mkdir()
        (self.head / "specs" / "deeper" / "nested.json").write_text("{}", encoding="utf-8")
        (self.head / "routes" / "nowhere.json").symlink_to("missing.json")
        (self.head / "routes" / "folder.json").symlink_to(".")
        self.assertEqual(req.policy_digest(self.head, project), before)
        # A route that is a link to a file is in the digest by its name and its refusal, as a spec
        # that is a link is (#340; until then it was left out and nothing said so). What it leads
        # to is not in the digest.
        (self.head / "routes" / "linked.json").symlink_to("smoke.json")
        route_linked = req.policy_digest(self.head, project)
        self.assertNotEqual(route_linked, before)
        (self.head / "routes" / "linked.json").unlink()
        (self.head / "routes" / "linked.json").symlink_to("combat.json")
        self.assertEqual(req.policy_digest(self.head, project), route_linked)
        (self.head / "routes" / "linked.json").unlink()
        self.assertEqual(req.policy_digest(self.head, project), before)
        # A draft is read by the gate (and counted), so it is in the digest.
        with_draft = make_repo(self.tmp / "with-draft", draft=True)
        self.assertNotEqual(req.policy_digest(with_draft, project), before)
        # A spec that is a link is in the digest by its name and its refusal: adding it changes the
        # digest, what it leads to does not, and making it a real file does.
        (self.head / "kept").mkdir()
        target = self.head / "kept" / "target.json"
        target.write_text("{}", encoding="utf-8")
        (self.head / "specs" / "two.json").symlink_to(target)
        linked = req.policy_digest(self.head, project)
        self.assertNotEqual(linked, before)
        target.write_text('{"something": "else"}', encoding="utf-8")
        self.assertEqual(req.policy_digest(self.head, project), linked)
        (self.head / "specs" / "two.json").unlink()
        (self.head / "specs" / "two.json").write_text('{"something": "else"}', encoding="utf-8")
        self.assertNotEqual(req.policy_digest(self.head, project), linked)
        # No checks at all: no digest.
        empty = self.tmp / "empty"
        (empty / "specs").mkdir(parents=True)
        self.assertIsNone(req.policy_digest(empty, project))

    def test_a_game_that_changes_after_the_workers_read_gives_no_decision(self):
        # The window the worker's second read leaves: the files are right when the worker checks
        # them and different when the engine reads them to run them.
        game = self.head / "game" / "platformer"

        class ChangesFirst(engines.GodotGate):
            def execute(self, request, paths, advance):
                (game / "swapped.gd").write_text("# written after the worker's check\n", encoding="utf-8")
                return super().execute(request, paths, advance)

        replay = FakeReplay()
        job = self.job()
        asked = self.store.status(job)["inputs"]["headTree"]
        with contextlib.redirect_stdout(io.StringIO()):
            status = runner.work(self.store, job, engines={"godot": ChangesFirst(rule="engine-only", replay=replay)})
        self.assertTrue(replay.calls)   # the changed game did run, and would have been accepted
        self.assertNotEqual(req.inputs(self.request())["headTree"], asked)
        self.assertEqual((status["phase"], status["decision"], [d["code"] for d in status["diagnostics"]]),
                         ("completed", "needs-review", ["INPUT_INVALID"]))
        self.assertIn("the head game changed while the job was running", status["diagnostics"][0]["detail"])
        # A record that decides about another game is not published as this job's evidence.
        self.assertIsNone(status["output"])
        self.assertFalse(self.store.paths(job).output.exists())

    def test_the_evidence_names_the_trees_the_job_asked_about(self):
        bug = make_repo(self.tmp / "bug", bug=True)
        status = self.decide(self.head, bug)
        record = rec.read_record(self.store.paths(status["id"]).output / "findings.json")
        self.assertEqual((record["game"]["headTree"], record["game"]["baseTree"]),
                         (status["inputs"]["headTree"], status["inputs"]["baseTree"]))
        self.assertEqual(status["decision"], "accept")

    def test_the_diagnostic_class_records_isolation_and_does_not_require_it(self):
        job = self.job()
        status = runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=FakeReplay())})
        record = rec.read_record(self.store.paths(job).output / "findings.json")
        self.assertEqual((status["decision"], record["isolation"]["required"], record["isolation"]["sandboxed"]), ("accept", False, 0))

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
            self.evidence(job)
            self.store.finish(job, finish.pop("phase"), **finish)
            outcomes[name] = self.run_cli("report", job)[0]
        self.assertEqual(outcomes, {"accept": 0, "reject": 1, "needs-review": 2, "failed": 3, "cancelled": 4})

    def test_status_cancel_and_report(self):
        job = self.job()
        code, out, _ = self.run_cli("status", job, "--json")
        self.assertEqual((code, json.loads(out)["phase"]), (6, "queued"))   # not finished: never 0, which is accept
        code, _, err = self.run_cli("report", job)
        self.assertEqual(code, 6)
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



class TreeTest(Case):
    """headTree describes what a replay reads: the harness's copy of the game folder (harness.run.prepare).
    The first review of #300 found a second skip list here that the replay did not share."""

    def setUp(self):
        super().setUp()
        self.game = self.head / "game" / "platformer"

    def tree(self) -> str | None:
        return req.inputs(self.request())["headTree"]

    def copied(self) -> dict[str, bytes]:
        """What the copy a replay runs holds, made by the harness's own function (harness.run.prepare
        without its patches and scripts): links followed, .godot and .git left out."""
        from harness import tree

        work = self.tmp / "copy"
        shutil.rmtree(work, ignore_errors=True)
        tree.copy(self.game, work, within=self.head, skip=tree.GODOT_SKIP)
        return {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob("*") if p.is_file()}

    def test_without_links_it_is_the_harness_digest(self):
        from harness.run import tree_digest

        (self.game / "levels").mkdir()
        (self.game / "levels" / "one.tscn").write_text("[node]\n", encoding="utf-8")
        self.assertEqual(self.tree(), tree_digest(self.game))
        # Sibling folders where one name continues the other with a character below "/": as one
        # string "a-b/x.gd" sorts before "a/y.gd", part by part it sorts after. The harness goes
        # part by part, and so must this (second review of #300).
        for a, b in (("a", "a-b"), ("a", "a.b"), ("a", "a b"), ("lvl", "lvl+1")):
            for folder, name in ((a, "y.gd"), (b, "x.gd")):
                (self.game / folder).mkdir(exist_ok=True)
                (self.game / folder / name).write_text(f"# {folder}\n", encoding="utf-8")
            with self.subTest(pair=(a, b)):
                self.assertEqual(self.tree(), tree_digest(self.game))
        self.assertEqual([name for name, _ in req.tree_files(self.game, self.head)],
                         [p.relative_to(self.game).as_posix() for p in sorted(q for q in self.game.rglob("*") if q.is_file())])

    def test_whenever_the_copy_changes_the_digest_changes(self):
        from harness.run import tree_digest

        # Every folder name any skip list has had. Two are not part of a game, for the copy and every
        # digest alike (harness.tree): .godot, the engine's cache, and .git, version control.
        for folder in (".git", ".expectrail", "__pycache__", "addons", ".godot"):
            with self.subTest(folder=folder):
                (self.game / folder).mkdir()
                (self.game / folder / "logic.gd").write_text("# one\n", encoding="utf-8")
                copy, harness, tree = self.copied(), tree_digest(self.game), self.tree()
                (self.game / folder / "logic.gd").write_text("# two\n", encoding="utf-8")
                copy_changed, harness_changed = self.copied() != copy, tree_digest(self.game) != harness
                self.assertEqual(copy_changed, folder not in (".godot", ".git"))
                self.assertEqual(harness_changed, copy_changed)
                self.assertEqual(self.tree() != tree, copy_changed)

    def test_a_linked_folder_inside_the_checkout_is_part_of_the_game(self):
        (self.head / "ext").mkdir()
        (self.head / "ext" / "lvl.tscn").write_text("[one]\n", encoding="utf-8")
        (self.game / "linked").symlink_to(Path("..") / ".." / "ext")
        (self.game / "notes.txt").symlink_to(Path("..") / ".." / "ext" / "lvl.tscn")
        self.assertEqual(sorted(name for name, _ in req.tree_files(self.game, self.head)), sorted(self.copied()))
        self.assertIn("linked/lvl.tscn", self.copied())
        first, created = self.store.create(self.request(idempotency_key="pr-9"))
        (self.head / "ext" / "lvl.tscn").write_text("[two]\n", encoding="utf-8")
        self.assertNotEqual(req.inputs(self.request())["headTree"], first["inputs"]["headTree"])
        with self.assertRaises(st.IdempotencyConflict):   # not the earlier job, which replayed other files
            self.store.create(self.request(idempotency_key="pr-9"))

    def test_a_link_that_leaves_the_checkout_is_never_read_and_stops_the_job(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("not part of the change", encoding="utf-8")
        for name, target in (("folder", outside), ("file.txt", outside / "secret.txt"), ("nothing", self.head / "absent")):
            with self.subTest(link=name):
                link = self.game / name
                link.symlink_to(target)
                self.addCleanup(link.unlink, missing_ok=True)
                with self.assertRaisesRegex(req.TreeProblem, f"{name} is a link"):
                    req.tree_digest(self.game, self.head)
                found = req.problems(self.request())
                self.assertEqual(len(found), 1)
                self.assertIn("leaves the checkout" if name != "nothing" else "link to nothing", found[0])
                job = self.job("instant")
                self.assertIsNone(self.store.status(job)["inputs"]["headTree"])
                with contextlib.redirect_stderr(io.StringIO()):
                    status = runner.work(self.store, job, engines=STAND_INS)
                self.assertEqual((status["phase"], status["decision"], [d["code"] for d in status["diagnostics"]]),
                                 ("completed", "needs-review", ["INPUT_INVALID"]))
                self.assertIsNone(status["output"])   # the engine never ran
                link.unlink()

    def test_a_pipe_in_the_game_is_named_not_left_out(self):
        os.mkfifo(self.game / "pipe")
        with self.assertRaisesRegex(req.TreeProblem, "pipe is not a file, a folder or a link"):
            req.tree_digest(self.game, self.head)
        job = self.job("instant")
        self.assertIsNone(self.store.status(job)["inputs"]["headTree"])
        with contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, job, engines=STAND_INS)
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]], status["output"]),
                         ("needs-review", ["INPUT_INVALID"], None))

    def test_a_link_that_loops_is_refused(self):
        (self.game / "again").symlink_to(".")
        with self.assertRaisesRegex(req.TreeProblem, "loops"):
            req.tree_digest(self.game, self.head)

    def test_a_tree_that_cannot_be_used_is_not_the_same_request_as_one_that_can(self):
        usable = req.inputs(self.request())
        (self.game / "out").symlink_to("/etc")
        broken = req.inputs(self.request())
        self.assertIsNone(broken["headTree"])
        self.assertNotEqual(broken["requestDigest"], usable["requestDigest"])
        jsonschema.validate(self.store.create(self.request())[0], st.schema())

    def test_files_changed_between_the_request_and_the_run_stop_the_job(self):
        job = self.job("instant")
        (self.game / "player.gd").write_text("# changed after the job was created\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, job, engines=STAND_INS)
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertIn("changed after the job was created", status["diagnostics"][0]["detail"])
        self.assertIsNone(status["output"])

    def test_the_jobs_folder_may_not_be_where_the_checks_are_read(self):
        # With --head . and the default runs/jobs, a pattern like **/*.json read each job's own
        # request.json and status.json as routes, and every job ended INPUT_INVALID with a message
        # about the game having changed (second review of #300).
        for root, over, words in (
                (self.head / "runs" / "jobs", dict(routes=["**/*.json"]), "route pattern '\\*\\*/\\*.json'"),
                (self.head / "runs" / "jobs", dict(routes=["routes/*.json", "runs/**/request.json"]), "route pattern 'runs/"),
                (self.head / "routes" / "jobs", dict(routes=["routes/**/*.json"]), "route pattern"),
                (self.head / "specs" / "jobs", {}, "inside the head specs folder")):
            with self.subTest(root=root.relative_to(self.head).as_posix(), **over), self.assertRaisesRegex(st.StoreError, words):
                st.JobStore(root).create(self.request(**over))
            self.assertFalse(root.exists())
        # Beside the checks, not among them: allowed, and the job's inputs are the same on a second read.
        store = st.JobStore(self.head / "runs" / "jobs")
        status, _ = store.create(self.request())
        self.assertEqual(req.inputs(self.request()), status["inputs"])

    def test_a_route_pattern_reaches_a_folder_or_does_not(self):
        for pattern, folder, reaches in (
                ("**/*.json", "runs/jobs", True), ("*.json", "runs/jobs", False), ("routes/*.json", "runs/jobs", False),
                ("routes/*.json", "routes", True), ("routes/*.json", "routes/jobs", False), ("routes/**", "routes/jobs", True),
                ("r*/**/*.json", "runs/jobs", True), ("runs/jobs/a/request.json", "runs/jobs", True),
                ("harness/routes/smoke.json", "runs/jobs", False), ("**", "x", True), ("*/*/*/*.json", "runs/jobs", True),
                # Without regard to case: on a file system that ignores it, RUNS/** is runs/**.
                ("RUNS/**", "runs/jobs", True), ("runs/JOBS/*/request.json", "runs/jobs", True), ("Routes/*.json", "runs/jobs", False),
                # A range that holds "r" as written and not once its case is folded (first review of #313).
                ("[S-s]uns/**", "runs/jobs", True), ("[Z-s]uns/jobs/*/request.json", "runs/jobs", True),
                ("[!R]uns/**", "runs/jobs", True), ("[!A-Z]*/**", "runs/jobs", True)):
            with self.subTest(pattern=pattern, folder=folder):
                self.assertEqual(req.pattern_reaches(pattern, folder), reaches)

    def test_no_pattern_that_really_matches_below_the_folder_is_missed(self):
        # The property, not only cases: the check errs towards yes, so over a generated set of
        # patterns, every one whose real glob finds a file below the jobs folder must be reported as
        # reaching it. A change that widens the check has to keep this (it is how the range mistake
        # in #313 was caught).
        import itertools

        root = self.tmp / "tree"
        for name in ("runs/jobs/abc/request.json", "runs/jobs/abc/status.json", "runs/jobs/keys/k.json",
                     "runs/jobs/abc/output/findings.json", "runs/other.json", "routes/smoke.json", "top.json"):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("{}", encoding="utf-8")
        below = (root / "runs" / "jobs").resolve()
        parts = ("**", "*", "r*", "*.json", "?obs", "[rj]*", "[S-s]uns", "[Z-s]*", "[!R]uns", "[!A-Z]*", "runs", "jobs",
                 "abc", "request.json", "routes")
        checked = matched = 0
        for length in (1, 2, 3, 4):
            combos = itertools.product(parts, repeat=length)
            if length == 4:
                combos = itertools.islice(combos, 0, None, 7)   # one in seven of the longest
            for combo in combos:
                pattern = "/".join(combo)
                checked += 1
                # What the gate would find as routes: its own matcher, the same on every Python
                # (Path.glob is not: on 3.12 a last "**" gives no file, and this count was 421).
                really = any(below in found.resolve().parents for found in gate.find_routes(root, [pattern]))
                if really:
                    matched += 1
                    self.assertTrue(req.pattern_reaches(pattern, "runs/jobs"), pattern)
        self.assertGreater(matched, 500, (checked, matched))

    def test_the_jobs_folder_may_not_be_inside_the_game(self):
        store = st.JobStore(self.game / "runs" / "jobs")
        with self.assertRaisesRegex(st.StoreError, "inside the head game folder"):
            store.create(self.request())
        self.assertFalse((self.game / "runs").exists())


class OutsidePathsTest(Case):
    """A request names paths inside the checkout only, and nothing it names is opened before that is
    checked. The first review of #300 hashed ../.. and crashed on /etc/*.json with exit 1 (reject)."""

    BAD = (dict(game="/etc"), dict(game="../.."), dict(game="game/../../.."), dict(specs="/etc"), dict(specs="../specs"),
           dict(routes=["/etc/*.json"]), dict(routes=["../**/*.json"]), dict(routes=["routes/*.json", "/etc/*.json"]),
           dict(game="game\\platformer"), dict(specs=""))

    def test_they_are_refused_as_text_before_any_file_is_read(self):
        opened = []
        with unittest.mock.patch.object(req, "tree_files", side_effect=lambda *a: opened.append(a) or []), \
                unittest.mock.patch.object(req, "policy_digest", side_effect=lambda *a: opened.append(a)):
            for over in self.BAD:
                with self.subTest(**over), self.assertRaises(req.RequestError):
                    self.request(**over)
                # A request that did not come through build() is refused by the store and by inputs() too.
                doc = self.request()
                doc["project"].update(over)
                for use in (self.store.create, req.inputs):
                    with self.subTest(use=use.__name__, **over), self.assertRaises(req.RequestError):
                        use(doc)
        self.assertEqual(opened, [])
        self.assertFalse((self.store.root / "jobs").exists())

    def test_the_game_at_the_checkout_root_is_allowed(self):
        self.assertEqual(self.request(game=".")["project"]["game"], ".")

    def test_a_refusal_names_the_request_not_another_record(self):
        doc = self.request()
        doc["surprise"] = 1
        with self.assertRaisesRegex(req.RequestError, "verify-request.v1.schema.json") as caught:
            req.check(doc)
        self.assertNotIn("findings", str(caught.exception))


class ExitCodeTest(Case):
    """1 means a job that completed as reject, and nothing else."""

    run_cli = CliTest.run_cli

    def verify(self, **over) -> tuple[int, str, str]:
        fields = {"--game": "game/platformer", "--routes": "routes/*.json", "--specs": "specs", **over}
        return self.run_cli("verify", "--head", str(self.head), "--detach", *[x for pair in fields.items() for x in pair])

    VERIFY = ("--game", "game/platformer", "--routes", "routes/*.json", "--specs", "specs")

    def test_zero_is_a_completed_accept_and_nothing_else(self):
        # `status` used to exit 0 for a job with no result, so `status "$JOB" && deploy` passed on a
        # queued job and on one that later ended in reject (second review of #300).
        def make(state: str) -> str:
            status, _ = self.store.create(self.request(idempotency_key=f"key-{state}"))
            job = status["id"]
            if state in ("preparing", "executing"):
                stand_in = subprocess.Popen(["sleep", "600"], start_new_session=True)   # a worker to stop
                self.started.append(stand_in)
                self.store.claim(job, stand_in.pid, stand_in.pid)
                self.store.advance(job, state)
            elif state in ("accept", "reject", "needs-review"):
                self.evidence(job)
                self.store.finish(job, "completed", decision=state, publish=True)
            elif state in ("failed", "cancelled"):
                self.store.finish(job, state)
            return job

        expected = {"queued": 6, "preparing": 6, "executing": 6, "accept": 0, "reject": 1, "needs-review": 2,
                    "failed": 3, "cancelled": 4}
        seen = {}
        for state, code in expected.items():
            job = make(state)
            for command in ("status", "report"):
                seen[(command, state)] = self.run_cli(command, job)[0]
                self.assertEqual(seen[(command, state)], code, (command, state))
            if code != 6:   # the same key gives the same job back, and `verify` reports it
                seen[("verify", state)] = self.run_cli("verify", "--head", str(self.head), *self.VERIFY,
                                                       "--idempotency-key", f"key-{state}")[0]
                self.assertEqual(seen[("verify", state)], code, ("verify", state))
            seen[("cancel", state)] = self.run_cli("cancel", job)[0]
            self.assertEqual(seen[("cancel", state)], 4 if code == 6 else code, ("cancel", state))
        self.assertEqual({key for key, code in seen.items() if code == 0},
                         {(command, "accept") for command in ("status", "report", "verify", "cancel")})

    def test_the_two_stated_exceptions_for_zero(self):
        code, out, _ = self.run_cli("verify", "--head", str(self.head), "--game", "game/missing", "--routes", "routes/*.json",
                                    "--specs", "specs", "--detach")
        self.assertEqual(code, 0)   # the job was started; it says nothing about the result
        job = out.strip()
        wait_for(lambda: self.store.status(job)["phase"] in st.FINAL, what="the job finishing")
        self.assertEqual(self.run_cli("status", job)[0], 2)   # no project there: needs review
        text = Path(cli.__file__).read_text(encoding="utf-8") + (REPO / "docs" / "orchestrator.md").read_text(encoding="utf-8")
        for words in ("`verify --detach` exits 0 when the job was", "`sample` exits 0"):
            self.assertIn(words, " ".join(text.split()))

    def test_paths_outside_the_checkout_are_exit_5_with_one_line(self):
        for over in ({"--routes": "/etc/*.json"}, {"--game": "/etc"}, {"--game": "../.."}, {"--routes": "../**/*.json"}):
            with self.subTest(**over):
                code, out, err = self.verify(**over)
                self.assertEqual((code, out), (5, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)
                self.assertNotIn("Traceback", err)
        self.assertFalse((self.store.root / "jobs").exists())

    def test_a_crash_in_the_command_is_exit_5_never_1(self):
        for command in (("verify", "--head", str(self.head), "--game", "game/platformer", "--routes", "routes/*.json",
                         "--specs", "specs"), ("status", "0" * 32), ("cancel", "0" * 32), ("report", "0" * 32)):
            with self.subTest(command=command[0]), \
                    unittest.mock.patch.object(st.JobStore, "create", side_effect=NotImplementedError("Non-relative patterns")), \
                    unittest.mock.patch.object(st.JobStore, "status", side_effect=ZeroDivisionError("x")), \
                    unittest.mock.patch.object(st.JobStore, "cancel", side_effect=KeyError("y")):
                code, out, err = self.run_cli(*command)
                self.assertEqual((code, out), (5, ""))
                self.assertIn("no job result was produced", err)
                self.assertNotIn("Traceback", err)


class NobodyWaitsForEverTest(Case):
    def test_a_job_no_worker_takes_is_failed_when_its_first_lease_runs_out(self):
        status, _ = self.store.create(self.request(idempotency_key="pr-11"))
        self.assertIsNotNone(status["lease"])
        self.assertEqual(self.store.status(status["id"])["phase"], "queued")
        time.sleep(self.store.lease_seconds * 1.5)
        lost = self.store.status(status["id"])
        self.assertEqual((lost["phase"], [d["code"] for d in lost["diagnostics"]], lost["reasons"]),
                         ("failed", ["WORKER_LOST"], ["no worker took the job in time"]))

    def test_asking_again_with_the_same_key_returns_instead_of_waiting(self):
        args = ("verify", "--head", str(self.head), "--game", "game/platformer", "--routes", "routes/*.json",
                "--specs", "specs", "--idempotency-key", "pr-12", "--json")
        first, _ = self.store.create(self.request(idempotency_key="pr-12"))   # a starter that died before spawning
        result: dict = {}

        def ask():
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                result["code"] = cli.main(["--jobs-root", str(self.store.root), "--lease-seconds", "0.6", *args])
            result["status"] = json.loads(out.getvalue())

        thread = threading.Thread(target=ask, daemon=True)
        thread.start()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "verify with the same key is still waiting")
        self.assertEqual((result["code"], result["status"]["id"], result["status"]["phase"]), (3, first["id"], "failed"))

    def test_a_worker_that_takes_the_job_in_time_renews_the_lease(self):
        job = self.job("slow")
        self.spawn(job)
        self.running(job)
        time.sleep(self.store.lease_seconds * 2)
        self.assertEqual(self.store.status(job)["phase"], "executing")


class LostWorkerTest(Case):
    """A worker that is killed cannot stop what it started, so the store does, and finds it by the
    job's id in each process's environment, never by a process or group number (#307, gap 3)."""

    def child_of(self, job: str) -> int:
        return int((self.store.paths(job).work / "child.pid").read_text())

    def test_a_worker_and_what_it_starts_carry_the_jobs_id(self):
        job = self.job("slow")
        proc = self.spawn(job)
        self.running(job)
        self.assertEqual(st.processes_of(job), sorted([proc.pid, self.child_of(job)]))
        self.assertEqual(st.processes_of("0" * 32), [])

    def test_killing_only_the_worker_leaves_nothing_of_the_job_running(self):
        for engine in ("slow", "detached"):
            with self.subTest(engine=engine):
                job = self.job(engine)
                proc = self.spawn(job)
                self.running(job)
                child = self.child_of(job)
                os.kill(proc.pid, signal.SIGKILL)   # the worker alone: its child lives on
                proc.wait(timeout=5)
                self.assertTrue(st.alive(child))
                status = wait_for(lambda: (s := self.store.status(job))["phase"] in st.FINAL and s, seconds=5,
                                  what="the lease running out")
                self.assertEqual((status["phase"], [d["code"] for d in status["diagnostics"]]), ("failed", ["WORKER_LOST"]))
                wait_for(lambda: gone(child), what="the worker's child stopping")
                self.assertIn("stopped 1 process(es) it had started", status["reasons"])
                self.assertEqual(st.processes_of(job), [])
                self.assertEqual(self.store.status(job), status)   # and asking again changes nothing

    def test_waiting_on_a_killed_worker_stops_its_child_at_once(self):
        job = self.job("slow")
        proc = self.spawn(job)
        self.running(job)
        child = self.child_of(job)
        os.kill(proc.pid, signal.SIGKILL)
        status = runner.wait(self.store, job, proc, poll_seconds=0.05)
        self.assertEqual((status["phase"], [d["code"] for d in status["diagnostics"]]), ("failed", ["WORKER_LOST"]))
        wait_for(lambda: gone(child), what="the worker's child stopping")

    def test_cancel_also_stops_what_left_the_workers_group(self):
        job = self.job("detached")
        proc = self.spawn(job)
        self.running(job)
        child = self.child_of(job)
        self.assertNotEqual(os.getpgid(child), proc.pid)
        self.assertEqual(self.store.cancel(job, grace_seconds=1.0)["phase"], "cancelled")
        wait_for(lambda: proc.poll() is not None and gone(child), what="the worker and its detached child stopping")

    def test_only_processes_that_name_this_job_are_stopped(self):
        job, other = self.job("slow"), "f" * 32
        self.assertNotEqual(job, other)

        def sleeper(**env) -> subprocess.Popen:
            proc = subprocess.Popen(["sleep", "600"], env={"PATH": os.environ["PATH"], **env}, start_new_session=True)
            self.started.append(proc)
            return proc

        mine = sleeper(**{st.JOB_ENV: job})
        bystanders = [sleeper(), sleeper(**{st.JOB_ENV: other}), sleeper(**{st.JOB_ENV: job + "0"}),
                      sleeper(**{st.JOB_ENV: job[:-1]}), sleeper(NOTE=f"{st.JOB_ENV}={job}"),
                      sleeper(**{"X" + st.JOB_ENV: job})]
        wait_for(lambda: st.processes_of(job) == [mine.pid], what="the marked process showing up")
        self.assertEqual(st.stop_job(job, grace_seconds=1.0), (1, 1))
        wait_for(lambda: mine.poll() is not None, what="the marked process stopping")
        time.sleep(0.2)
        self.assertEqual([p.poll() for p in bystanders], [None] * len(bystanders))
        self.assertNotIn(os.getpid(), st.processes_of(job) or [])

    def test_a_call_from_inside_the_job_does_not_stop_its_own_callers(self):
        # A status or a cancel asked from a script that itself runs inside the job: the script's shell
        # carries the job's id too, and stopping it would stop the asking (first review of #314).
        job = self.job()
        other = subprocess.Popen(["sleep", "600"], env={"PATH": os.environ["PATH"], st.JOB_ENV: job}, start_new_session=True)
        self.started.append(other)
        ask = (f"import sys; sys.path.insert(0, {str(REPO)!r}); from expectrail.orchestrator import store as st; "
               f"print('stopped', st.stop_job({job!r}, grace_seconds=1.0))")
        done = subprocess.run(["sh", "-c", f'{sys.executable} -c "{ask}"; echo survived'], capture_output=True, text=True,
                              timeout=30, env={"PATH": os.environ["PATH"], st.JOB_ENV: job})
        self.assertEqual((done.returncode, done.stdout.split()[-1]), (0, "survived"), done.stdout + done.stderr)
        self.assertIn("stopped (1, 1)", done.stdout)   # the other process of the job, and not the asking shell
        wait_for(lambda: other.poll() is not None, what="the job's other process stopping")

    def test_a_process_is_signalled_only_while_it_still_names_the_job(self):
        # Between the look and the signal a process number can pass to another program. The signal goes
        # to a handle on the process, after its environment is read again through that hold.
        job = self.job()
        proc = subprocess.Popen(["sleep", "600"], env={"PATH": os.environ["PATH"], st.JOB_ENV: job}, start_new_session=True)
        self.started.append(proc)
        wait_for(lambda: st.processes_of(job) == [proc.pid], what="the marked process showing up")
        marker = f"{st.JOB_ENV}={job}".encode()
        with mock.patch.object(st, "_names_job", return_value=False):   # as if the number now named something else
            st._signal(proc.pid, marker, signal.SIGKILL)
        time.sleep(0.2)
        self.assertIsNone(proc.poll())
        with mock.patch.object(st.os, "kill", side_effect=AssertionError("signalled by number")):
            st._signal(proc.pid, marker, signal.SIGKILL)
        wait_for(lambda: proc.poll() is not None, what="the process stopping through its handle")
        st._signal(proc.pid, marker, signal.SIGKILL)   # gone: nothing happens, nothing is raised

    def marked(self, job: str) -> subprocess.Popen:
        proc = subprocess.Popen(["sleep", "600"], env={"PATH": os.environ["PATH"], st.JOB_ENV: job}, start_new_session=True)
        self.started.append(proc)
        wait_for(lambda: st.processes_of(job) == [proc.pid], what="the marked process showing up")
        return proc

    def test_where_no_handle_can_be_had_the_jobs_processes_are_still_stopped(self):
        # The handle is the better way, and the process number stays as the way for every system the
        # handle does not cover: an older kernel (no such call), a container that refuses it (review
        # of #316: with the handle alone, a lost job's processes ran on there, and main stopped them).
        import errno

        for name, missing in (("no such function", AttributeError("module 'os' has no attribute 'pidfd_open'")),
                              ("no such system call", OSError(errno.ENOSYS, "Function not implemented")),
                              ("refused by the container", PermissionError(errno.EPERM, "Operation not permitted"))):
            with self.subTest(handles=name):
                job = self.job(idempotency_key=f"no-handles-{type(missing).__name__}")
                proc = self.marked(job)
                with mock.patch.object(st.os, "pidfd_open", side_effect=missing, create=True), \
                        mock.patch.object(st.signal, "pidfd_send_signal", side_effect=AssertionError("no handle to signal"),
                                          create=True):
                    self.assertFalse(st.process_handles())
                    status = self.store.lose(job, "the worker stopped before the job finished", stage="queued")
                wait_for(lambda: proc.poll() is not None, what="the marked process stopping, signalled by number")
                self.assertIn("stopped 1 process(es) it had started; by process number: this system has no process handles",
                              status["reasons"])
        # And stop_job counts it as it does with handles.
        job = self.job(idempotency_key="no-handles-count")
        proc = self.marked(job)
        with mock.patch.object(st.os, "pidfd_open", side_effect=OSError(errno.ENOSYS, "Function not implemented"), create=True):
            self.assertEqual(st.stop_job(job, grace_seconds=1.0), (1, 1))

    def test_without_a_handle_a_number_is_signalled_only_while_it_still_names_the_job(self):
        import errno

        job = self.job()
        proc = self.marked(job)
        marker = f"{st.JOB_ENV}={job}".encode()
        with mock.patch.object(st.os, "kill", side_effect=AssertionError("signalled by number")):
            # The process went away between the look and the signal: nothing is signalled.
            with mock.patch.object(st.os, "pidfd_open", side_effect=ProcessLookupError(errno.ESRCH, "No such process"), create=True):
                st._signal(proc.pid, marker, signal.SIGKILL)
            # No handles, and the number no longer names the job: nothing is signalled.
            with mock.patch.object(st.os, "pidfd_open", side_effect=OSError(errno.ENOSYS, "x"), create=True), \
                    mock.patch.object(st, "_names_job", return_value=False):
                st._signal(proc.pid, marker, signal.SIGKILL)
        time.sleep(0.2)
        self.assertIsNone(proc.poll())

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "this system has no process handles")
    def test_a_handle_whose_process_has_exited_is_not_signalled(self):
        job = self.job()
        proc = subprocess.Popen(["true"])
        handle = os.pidfd_open(proc.pid)
        self.addCleanup(os.close, handle)
        wait_for(lambda: st._exited(handle), what="the handle saying its process has exited")
        proc.wait()
        live = self.marked(job)
        live_handle = os.pidfd_open(live.pid)
        self.addCleanup(os.close, live_handle)
        self.assertFalse(st._exited(live_handle))
        # As if the number had passed to a program that names the job after the handle's process went.
        with mock.patch.object(st.os, "pidfd_open", return_value=os.dup(handle)), \
                mock.patch.object(st, "_names_job", return_value=True), \
                mock.patch.object(st.signal, "pidfd_send_signal", side_effect=AssertionError("signalled a dead handle")), \
                mock.patch.object(st.os, "kill", side_effect=AssertionError("signalled by number")):
            st._signal(live.pid, f"{st.JOB_ENV}={job}".encode(), signal.SIGKILL)
        self.assertIsNone(live.poll())

    def test_a_caller_holding_many_open_files_still_stops_a_lost_jobs_processes(self):
        # A long-lived caller with a thousand files open gets a handle numbered 1024 or higher.
        # `select` refuses such a number; asked that way, the stop raised and the job's processes ran
        # on, where the way before handles stopped them (second review of #316).
        import fcntl
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        need = 1100
        if soft != resource.RLIM_INFINITY and soft < need:
            if hard != resource.RLIM_INFINITY and hard < need:
                self.skipTest(f"this system allows only {hard} open files")
            resource.setrlimit(resource.RLIMIT_NOFILE, (need, hard))
            self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE, (soft, hard))
        real_open, handed = os.pidfd_open, []

        def a_high_handle(pid: int) -> int:
            low = real_open(pid)
            try:
                high = fcntl.fcntl(low, fcntl.F_DUPFD_CLOEXEC, 1024)
            finally:
                os.close(low)
            handed.append(high)
            return high

        job = self.job()
        proc = self.marked(job)
        with mock.patch.object(st.os, "pidfd_open", side_effect=a_high_handle), \
                mock.patch.object(st.os, "kill", side_effect=AssertionError("signalled by number")):
            status = self.store.lose(job, "the worker stopped before the job finished", stage="queued")
        self.assertTrue(handed and min(handed) >= 1024, handed)
        wait_for(lambda: proc.poll() is not None, what="the marked process stopping through a high-numbered handle")
        self.assertEqual(status["reasons"][-1], "stopped 1 process(es) it had started")

    def test_any_failure_of_the_handle_path_falls_to_the_process_number(self):
        # One fallback for the whole first way: whichever step fails, and however, the process is
        # stopped as it was before handles. Only "no such process" ends it.
        import errno

        ways = {
            "the liveness check raises": lambda: mock.patch.object(st, "_exited", side_effect=ValueError("filedescriptor out of range")),
            "the signal to the handle is refused": lambda: mock.patch.object(
                st.signal, "pidfd_send_signal", side_effect=OSError(errno.EINVAL, "Invalid argument")),
            "the signal to the handle is not allowed": lambda: mock.patch.object(
                st.signal, "pidfd_send_signal", side_effect=PermissionError(errno.EPERM, "Operation not permitted")),
            "no handle: too many open files": lambda: mock.patch.object(
                st.os, "pidfd_open", side_effect=OSError(errno.EMFILE, "Too many open files")),
        }
        for n, (name, broken) in enumerate(ways.items()):
            with self.subTest(failure=name):
                job = self.job(idempotency_key=f"handle-path-{n}")
                proc = self.marked(job)
                with broken():
                    status = self.store.lose(job, "the worker stopped before the job finished", stage="queued")
                wait_for(lambda: proc.poll() is not None, what=f"the marked process stopping by number ({name})")
                self.assertEqual(status["phase"], "failed")
                # Why is said too: "a process handle could not be used", or "this system has no
                # process handles" when none can be opened at all.
                self.assertTrue(status["reasons"][-1].startswith("stopped 1 process(es) it had started; by process number: "),
                                status["reasons"])
                self.assertEqual("could not be used" in status["reasons"][-1], not name.startswith("no handle"))
        # "No such process" from the handle is the end of it: nothing is signalled by number.
        job = self.job(idempotency_key="handle-path-gone")
        proc = self.marked(job)
        with mock.patch.object(st.signal, "pidfd_send_signal", side_effect=ProcessLookupError(errno.ESRCH, "No such process")), \
                mock.patch.object(st.os, "kill", side_effect=AssertionError("signalled by number")):
            self.assertIsNone(st._signal(proc.pid, f"{st.JOB_ENV}={job}".encode(), signal.SIGKILL))
        self.assertIsNone(proc.poll())

    def test_an_error_while_stopping_is_said_on_the_job_and_not_raised(self):
        # The job is final before the stop, so nothing tries again: the error must be on the job.
        job = self.job()
        with mock.patch.object(st, "stop_job", side_effect=RuntimeError("the stop itself broke")):
            status = self.store.lose(job, "the worker stopped before the job finished", stage="queued")
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["reasons"], ["the worker stopped before the job finished",
                                             "could not stop what it had started: RuntimeError: the stop itself broke"])
        self.assertEqual(self.store.status(job)["reasons"], status["reasons"])
        job = self.job(idempotency_key="cancel-stop-error")
        with mock.patch.object(st, "stop_job", side_effect=RuntimeError("the stop itself broke")):
            status = self.store.cancel(job)
        self.assertEqual((status["phase"], status["reasons"][-1]),
                         ("cancelled", "could not stop what it had started: RuntimeError: the stop itself broke"))

    def test_a_process_started_after_the_first_look_is_counted(self):
        job = self.job()
        looks = iter([[101], [101, 202]])   # the job starts one more between the first look and the next

        def look(_job):
            return next(looks, [])

        with mock.patch.object(st, "processes_of", side_effect=look), mock.patch.object(st, "_signal", return_value="handle") as sent:
            ways: set = set()
            self.assertEqual(st.stop_job(job, grace_seconds=0.1, ways=ways), (2, 2))
        self.assertEqual(sorted(call.args[0] for call in sent.call_args_list), [101, 202])
        self.assertEqual(ways, {"handle"})
        # And one that is still there at the end is found and not counted as gone.
        looks = iter([[101]])
        with mock.patch.object(st, "processes_of", side_effect=lambda _job: next(looks, [303])), mock.patch.object(st, "_signal"):
            self.assertEqual(st.stop_job(job, grace_seconds=0.1), (2, 1))

    def test_a_cancel_that_leaves_something_running_says_so(self):
        job = self.job()
        proc = self.marked(job)
        with mock.patch.object(st, "_signal"):   # a process that cannot be signalled
            status = self.store.cancel(job)
        self.assertEqual(status["phase"], "cancelled")
        self.assertEqual(status["reasons"], ["cancelled on request",
                                             "found 1 process(es) it had started and stopped 0; the rest are still running"])
        self.assertIsNone(proc.poll())
        # One that stops everything says nothing more.
        job = self.job(idempotency_key="cancel-clean")
        proc = self.marked(job)
        self.assertEqual(self.store.cancel(job)["reasons"], ["cancelled on request"])
        wait_for(lambda: proc.poll() is not None, what="the marked process stopping")

    def test_processes_left_because_they_are_the_callers_own_are_said(self):
        job = self.job()
        ask = (f"import sys; sys.path.insert(0, {str(REPO)!r}); from expectrail.orchestrator import store as st; "
               f"print(st._stopped_note({job!r}, st.stop_job({job!r})))")
        done = subprocess.run([sys.executable, "-c", ask], capture_output=True, text=True, timeout=30,
                              env={"PATH": os.environ["PATH"], st.JOB_ENV: job})
        self.assertRegex(done.stdout.strip(), r"^left [1-9]\d* running: they are the caller's own$", done.stdout + done.stderr)
        self.assertIsNone(st._stopped_note(job, (0, 0)))   # asked from outside the job: nothing to say

    def test_what_could_not_be_stopped_is_said_not_counted_as_stopped(self):
        job = self.job()
        proc = subprocess.Popen(["sleep", "600"], env={"PATH": os.environ["PATH"], st.JOB_ENV: job}, start_new_session=True)
        self.started.append(proc)
        wait_for(lambda: st.processes_of(job) == [proc.pid], what="the marked process showing up")
        with mock.patch.object(st, "_signal"):   # a process that cannot be signalled
            self.assertEqual(st.stop_job(job, grace_seconds=0.1), (1, 0))
            status = self.store.lose(job, "the worker stopped before the job finished", stage="queued", grace_seconds=0.1)
        self.assertIn("found 1 process(es) it had started and stopped 0; the rest are still running", status["reasons"])
        self.assertIsNone(proc.poll())

    def test_where_processes_cannot_be_looked_for_the_job_says_so(self):
        job = self.job()
        with mock.patch.object(st, "processes_of", return_value=None):
            self.assertIsNone(st.stop_job(job))
            status = self.store.lose(job, "the worker stopped before the job finished", stage="queued")
        self.assertEqual(status["phase"], "failed")
        self.assertIn("could not be looked for on this system", " ".join(status["reasons"]))

    def test_the_harness_passes_the_jobs_id_on_and_nothing_else_new(self):
        from harness import run as hr
        from harness import sandbox as box

        self.assertEqual(st.JOB_ENV, "EXPECTRAIL_JOB")
        env = hr.game_env({"PATH": "/usr/bin", st.JOB_ENV: "a" * 32, "MODEL_API_KEY": "k", "EXPECTRAIL_HELDOUT_DIR": "/p"})
        self.assertEqual((env.get(st.JOB_ENV), "MODEL_API_KEY" in env, "EXPECTRAIL_HELDOUT_DIR" in env), ("a" * 32, False, False))
        seen = {}

        def fake(cmd, **kwargs):
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.dict(os.environ, {st.JOB_ENV: "b" * 32, "MODEL_API_KEY": "k"}), \
                mock.patch.object(box.subprocess, "run", side_effect=fake):
            box.run(box.Tool("/usr/bin/bwrap", "0.9.0"), ["true"], timeout=5, game=self.tmp, out=self.tmp)
        self.assertEqual(seen, {"PATH": "/usr/bin:/bin", st.JOB_ENV: "b" * 32})


class CancelOrderTest(Case):
    def test_a_worker_that_records_itself_as_cancel_begins_is_still_stopped(self):
        # The order the first review of #300 forced: cancel reads the status (no worker yet), the worker
        # records itself, cancel makes the job final. The worker must be the one that gets stopped.
        job = self.job("slow")
        read = self.store.status

        def status_then_the_worker_arrives(job_id):
            doc = read(job_id)
            if not self.started:
                self.spawn(job_id)
                self.running(job_id)
            return doc

        with unittest.mock.patch.object(self.store, "status", side_effect=status_then_the_worker_arrives):
            status = self.store.cancel(job, grace_seconds=1.0)
        worker = self.started[0]
        child = int((self.store.paths(job).work / "child.pid").read_text())
        self.assertEqual(status["phase"], "cancelled")
        self.assertEqual(status["worker"]["pid"], worker.pid)
        wait_for(lambda: worker.poll() is not None and gone(child), what="the worker and its child stopping")

    def test_a_worker_that_arrives_after_the_cancel_does_nothing(self):
        job = self.job("instant")
        self.store.cancel(job)
        with contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, job, engines=STAND_INS)
        self.assertEqual((status["phase"], status["worker"], status["output"]), ("cancelled", None, None))
        self.assertFalse(self.store.paths(job).staging.exists())


class EvidenceTest(Case):
    def test_an_accept_or_a_reject_with_no_evidence_is_a_failed_job(self):
        for decision in ("accept", "reject"):
            with self.subTest(decision=decision):
                job = self.job()
                status = self.store.finish(job, "completed", decision=decision, publish=True)
                self.assertEqual((status["phase"], status["decision"], status["output"], status["evidenceGrade"]),
                                 ("failed", None, None, None))
                self.assertEqual([d["code"] for d in status["diagnostics"]], ["INTERNAL_ERROR"])
                self.assertIn("wrote no evidence", status["diagnostics"][0]["detail"])

    def test_an_engine_that_decides_and_writes_nothing_fails_the_job(self):
        class Silent:
            def preflight(self, request):
                return []

            def execute(self, request, paths, advance):
                return engines.Result("accept", ["nothing to show for it"])

        job = self.job("silent")
        with contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, job, engines={"silent": Silent()})
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("failed", None, None))

    def test_needs_review_needs_no_evidence_and_a_decision_with_evidence_is_published(self):
        job = self.job()
        self.assertEqual(self.store.finish(job, "completed", decision="needs-review", publish=True)["phase"], "completed")
        job = self.job()
        self.evidence(job)
        status = self.store.finish(job, "completed", decision="reject", publish=True)
        self.assertEqual((status["phase"], status["decision"], status["output"]), ("completed", "reject", "output"))

    def test_leaving_publish_out_does_not_let_a_decision_stand_without_evidence(self):
        for decision in ("accept", "reject"):
            with self.subTest(decision=decision, staging="none"):
                status = self.store.finish(self.job(), "completed", decision=decision)
                self.assertEqual((status["phase"], status["decision"], status["output"]), ("failed", None, None))
                self.assertEqual([d["code"] for d in status["diagnostics"]], ["INTERNAL_ERROR"])
            with self.subTest(decision=decision, staging="with a file"):
                job = self.job()
                self.evidence(job)
                status = self.store.finish(job, "completed", decision=decision)   # publish left out
                self.assertEqual((status["phase"], status["decision"], status["output"]), ("completed", decision, "output"))
                self.assertTrue((self.store.paths(job).output / "evidence.txt").is_file())

    def test_an_empty_evidence_folder_is_not_evidence(self):
        for layout in ("empty", "folders only", "a link", "an empty file"):
            with self.subTest(layout=layout):
                job = self.job()
                staging = self.store.paths(job).staging
                staging.mkdir()
                if layout == "folders only":
                    (staging / "verdicts" / "head").mkdir(parents=True)
                if layout == "an empty file":
                    (staging / "findings.json").write_bytes(b"")
                if layout == "a link":
                    (staging / "findings.json").symlink_to(self.head / "specs" / "player-stays-above-ground.json")
                status = self.store.finish(job, "completed", decision="accept", publish=True)
                self.assertEqual((status["phase"], status["decision"], status["output"]), ("failed", None, None))
                self.assertFalse(self.store.paths(job).output.exists())


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
            results = smp.run(self.store, engines={"godot": engines.GodotGate(rule="engine-only", replay=replay)}, on_case=seen.append)
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
                paths.staging.mkdir()
                (paths.staging / "evidence.txt").write_text("accepted without looking\n", encoding="utf-8")
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

        # Never 1: that is a job that completed as reject, and the sample is a check of the install.
        for decisions, code in ((("accept", "reject", "accept"), 0), (("accept", "accept", "accept"), 3)):
            with self.subTest(decisions=decisions), mock.patch.object(smp, "run", return_value=fake(decisions)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(cli.main(["--jobs-root", str(self.store.root), "sample", "--json"]), code)
                self.assertEqual(len(json.loads(out.getvalue())), 3)

    def test_a_copy_of_expectrail_without_the_sample_files_says_so(self):
        with self.assertRaises(smp.SampleError):
            smp.checkout(self.tmp / "x", bug=True, root=self.tmp)

    def test_a_machine_without_the_patch_program_gets_one_line_and_exit_5(self):
        with mock.patch.object(smp.subprocess, "run", side_effect=FileNotFoundError("patch")):
            with self.assertRaisesRegex(smp.SampleError, "patch program is not installed"):
                smp.checkout(self.tmp / "y", bug=True)
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = cli.main(["--jobs-root", str(self.store.root), "sample", "--json"])
        self.assertEqual(code, 5)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
