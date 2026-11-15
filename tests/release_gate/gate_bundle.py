"""Release gate, the rows that waited on the two-job gate (#254): writes to evidence or policy, and a
changed head.

Since #254 a pull request is judged in two jobs. The candidate job (``expectrail-capture.yml``, no
secret) replays the base and the head in the replay sandbox with the base's routes and writes the
runs to one archive with a manifest of digests. The trusted job (``expectrail-comment.yml``) never
runs the change: it takes the archive as data, checks it against the base, judges it with the base's
checks and both observers, and only then completes the head's "Expectrail clearance" check. These
tests run both halves as separate processes (``tests.release_gate.bundle``) with real Godot replays
in the sandbox, so they need bubblewrap: CI's ``release-gate`` job has it.

Writes to evidence or policy. Between the two jobs, the archive is data that could have been written
by anyone who can reach it. A frame, a trace or a replay record rewritten in it, a run taken out, or a
manifest that names another commit or other checks: the judge refuses each with ``EVIDENCE_MISMATCH``
and decides nothing, so there is no clearance. And the checks a change carries are not the ones that
judge it: the seeded bug with its check weakened is judged by the base's check, and rejected.

A changed head. Clearance is given to one head commit by one run. When the pull request has a new head
by the time the judge finishes, or the candidate workflow has a newer attempt for the head, the judged
accept is not clearance: the check fails as "superseded". A capture made for the old head is refused
for the new one. GitHub's API is a stand-in in these tests (``bundle.GitHub``); the hosted run on a
test pull request is the rest of #254 and Sean's.

The judge also compares each recorded game tree to the corresponding checkout. The separate
GitHub artifact download and its digest check need GitHub and are not run here.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.release_gate.common import REPO, REQUIRED, ROUTE, SPEC_FILE, GateCase, edit_json
from tests.release_gate.gate_sandbox import sandbox_missing
from tools import ci_checks

GITHUB_REPO = "Expectrail/Expectrail"
BASE_SHA, HEAD_SHA, NEW_HEAD_SHA = "a" * 40, "b" * 40, "c" * 40
PR = {"number": 1, "baseSha": BASE_SHA, "headSha": HEAD_SHA}
MISMATCH = 3


def weaken(doc: dict) -> None:
    doc["assertion"]["boundary"]["tolerancePx"] = 100000


def driver(*argv: str, timeout: float = 600) -> tuple[int, str, str]:
    done = subprocess.run([sys.executable, "-m", "tests.release_gate.bundle", *argv], cwd=REPO,
                          capture_output=True, text=True, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


def rewrite(source: Path, target: Path, change) -> None:
    """A copy of an archive with its members passed through ``change(name, data)``, which returns the
    new bytes, or None to leave the member out. Members are stored, as the capture writes them."""
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "x", zipfile.ZIP_STORED) as new:
        for info in old.infolist():
            data = change(info.filename, old.read(info))
            if data is not None:
                new.writestr(info.filename, data)


def head_run(names) -> str:
    """The folder of the head's run of the smoke route in an archive: ``head-1/<route sha256>``."""
    route = hashlib.sha256((REPO / ROUTE).read_bytes()).hexdigest()
    folder = f"head-1/{route}"
    assert any(n.startswith(folder + "/") for n in names), names
    return folder


_CAPTURES: dict[str, Path] = {}   # made once for the module: the archives do not depend on a class
_ROOTS: list[Path] = []


def tearDownModule():
    for root in _ROOTS:
        shutil.rmtree(root, ignore_errors=True)


class BundleCase(GateCase):
    """Two captures, made once for the module: the unchanged game against itself, and the seeded bug
    against the unchanged game."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        why = sandbox_missing()
        if why:
            shutil.rmtree(cls.root, ignore_errors=True)
            if REQUIRED:
                raise AssertionError(f"EXPECTRAIL_RELEASE_GATE=required and the replay sandbox cannot run here: {why}")
            raise unittest.SkipTest(f"the capture needs the replay sandbox, which cannot run here ({why})")
        if not _CAPTURES:
            _ROOTS.append(Path(tempfile.mkdtemp(prefix="release-gate-captures-")))
            _CAPTURES["clean"] = cls.captured("clean", cls.clean, folder=_ROOTS[0])
            _CAPTURES["bug"] = cls.captured("bug", cls.bug, folder=_ROOTS[0])
        cls.clean_bundle, cls.bug_bundle = _CAPTURES["clean"], _CAPTURES["bug"]

    @classmethod
    def captured(cls, name: str, head: Path, folder: Path | None = None) -> Path:
        """The capture of ``head`` against the unchanged game, as the candidate job makes it."""
        out = (folder or cls.root) / f"{name}.zip"
        code, _out, err = driver("capture", "--base", str(cls.clean), "--head", str(head),
                                 "--routes", ROUTE, "--pr", json.dumps(PR), "--out", str(out))
        if code != 0:
            raise AssertionError(f"the capture of {name} failed: {err[-3000:]}")
        return out

    def judge(self, bundle: Path, pr: dict = PR, base: Path | None = None,
              head: Path | None = None) -> tuple[int, dict, Path]:
        out = self.tmp / f"judged-{bundle.stem}"
        code, stdout, err = driver("judge", "--base", str(base or self.clean), "--head", str(head or self.clean),
                                   "--routes", ROUTE,
                                   "--pr", json.dumps(pr), "--bundle", str(bundle), "--out", str(out))
        self.assertTrue(stdout.strip(), err[-3000:])
        return code, json.loads(stdout.strip().splitlines()[-1]), out

    def assertRefused(self, bundle: Path, why: str, **kw) -> None:
        code, result, _out = self.judge(bundle, **kw)
        self.assertNotEqual(code, 0, "exit 0 is clearance")
        self.assertEqual((code, result["decision"]), (MISMATCH, None), result)
        self.assertTrue(result["problem"].startswith("EVIDENCE_MISMATCH: "), result)
        self.assertIn(why, result["problem"])

    def edited(self, name: str, change) -> Path:
        target = self.tmp / f"{name}.zip"
        rewrite(self.clean_bundle, target, change)
        return target


class BundleBaselineTest(BundleCase):
    def test_the_trusted_judge_clears_the_unchanged_games_capture(self):
        code, result, _out = self.judge(self.clean_bundle)
        self.assertEqual((code, result["decision"]), (0, "accept"), result)

    def test_the_trusted_judge_rejects_the_seeded_bugs_capture(self):
        code, result, _out = self.judge(self.bug_bundle, head=self.bug)
        self.assertEqual((code, result["decision"]), (1, "reject"), result)


class EvidenceTest(BundleCase):
    """Writes to evidence or policy."""

    def test_an_intact_capture_from_a_different_base_game_is_refused(self):
        self.assertRefused(self.clean_bundle, "base game tree", base=self.bug)

    def test_an_intact_capture_from_a_different_head_game_is_refused(self):
        self.assertRefused(self.bug_bundle, "head game tree", head=self.clean)

    def test_a_frame_rewritten_between_the_jobs_is_refused(self):
        def change(name, data):
            if name.startswith(self.folder) and name.endswith("/frames/f00000010.png"):
                with zipfile.ZipFile(self.clean_bundle) as z:
                    return z.read(name.replace("f00000010", "f00000000"))   # another real frame
            return data
        with zipfile.ZipFile(self.clean_bundle) as z:
            self.folder = head_run(z.namelist())
        self.assertRefused(self.edited("frame", change), "frame 10 differs from replay.json")

    def test_a_trace_rewritten_between_the_jobs_is_refused(self):
        with zipfile.ZipFile(self.clean_bundle) as z:
            folder = head_run(z.namelist())

        def change(name, data):
            if name == f"{folder}/trace.json":
                trace = json.loads(data)
                trace["rows"][30]["player"][1] -= 50   # the player lifted 50 px in one tick
                return json.dumps(trace).encode()
            return data
        self.assertRefused(self.edited("trace", change), "trace differs from replay.json")

    def test_a_trace_and_its_replay_record_rewritten_together_are_refused_by_the_manifest(self):
        with zipfile.ZipFile(self.clean_bundle) as z:
            folder = head_run(z.namelist())
            trace = json.loads(z.read(f"{folder}/trace.json"))
        trace["rows"][30]["player"][1] -= 50
        new_trace = json.dumps(trace).encode()

        def change(name, data):
            if name == f"{folder}/trace.json":
                return new_trace
            if name == f"{folder}/replay.json":
                replay = json.loads(data)
                replay["trace"]["sha256"] = hashlib.sha256(new_trace).hexdigest()
                return json.dumps(replay).encode()
            return data
        self.assertRefused(self.edited("trace-and-record", change), "replay digest differs")

    def test_a_run_taken_out_between_the_jobs_is_refused(self):
        with zipfile.ZipFile(self.clean_bundle) as z:
            folder = head_run(z.namelist())
        bundle = self.edited("run-removed", lambda name, data: None if name.startswith(folder + "/") else data)
        self.assertRefused(bundle, "unexpected or missing capture files")

    def test_a_capture_made_with_other_checks_is_refused(self):
        base = self.copy("base-weakened")
        edit_json(base / SPEC_FILE, weaken)
        # The archive was captured under the unchanged base's checks; the base now holds other ones.
        self.assertRefused(self.clean_bundle, "pull request, commit, intent or base policy differs", base=base)

    def test_checks_the_change_rewrites_are_not_the_ones_that_judge_it(self):
        head = self.copy("bug-weakened", self.bug)
        edit_json(head / SPEC_FILE, weaken)
        bundle = self.captured(f"bug-weakened-{self._testMethodName}", head)
        with zipfile.ZipFile(bundle) as z:
            manifest = json.loads(z.read("manifest.json"))
        self.assertEqual(manifest["changed"]["specs"], 1, manifest["changed"])
        code, result, _out = self.judge(bundle, head=head)
        self.assertNotEqual(code, 0, "exit 0 is clearance")
        self.assertEqual((code, result["decision"]), (1, "reject"), result)


class HeadTest(BundleCase):
    """A changed head."""

    def setUp(self):
        super().setUp()
        code, result, out = self.judge(self.clean_bundle)
        self.assertEqual((code, result["decision"]), (0, "accept"), result)
        self.findings = out / "findings.json"

    def finish(self, pr_head: str = HEAD_SHA, attempts=((111, 1),)) -> dict:
        def pull(head):
            return {"number": 1, "body": "", "labels": [],
                    "base": {"sha": BASE_SHA, "ref": "main", "repo": {"full_name": GITHUB_REPO}},
                    "head": {"sha": head, "repo": {"full_name": GITHUB_REPO}}}
        state = {
            "repo": GITHUB_REPO, "intent": "none",
            "checkIds": {ci_checks.CLEARANCE: 1, ci_checks.EVIDENCE: 2},
            "run": {"id": 111, "run_attempt": 1, "workflow_id": 7, "path": ci_checks.CALLER,
                    "event": "pull_request", "conclusion": "success", "head_sha": HEAD_SHA,
                    "head_branch": "change", "repository": {"full_name": GITHUB_REPO},
                    "head_repository": {"full_name": GITHUB_REPO, "owner": {"login": "Expectrail"}}},
            "judgedPullRequest": pull(HEAD_SHA),
            "pullRequest": pull(pr_head),
            "candidateRuns": [{"id": i, "run_attempt": a} for i, a in attempts],
        }
        github = self.tmp / "github.json"
        github.write_text(json.dumps(state), encoding="utf-8")
        code, out, err = driver("finish", "--findings", str(self.findings), "--github", str(github))
        self.assertEqual(code, 0, err[-3000:])
        return json.loads(out.strip().splitlines()[-1])

    def test_control_the_head_that_was_judged_is_given_clearance(self):
        self.assertEqual(self.finish(), {ci_checks.EVIDENCE: "success", ci_checks.CLEARANCE: "success"})

    def test_a_new_head_pushed_before_the_judge_finished_is_not_given_clearance(self):
        checks = self.finish(pr_head=NEW_HEAD_SHA)
        self.assertEqual(checks[ci_checks.CLEARANCE], "failure", checks)

    def test_a_newer_attempt_of_the_candidate_run_takes_clearance_from_this_one(self):
        checks = self.finish(attempts=((111, 1), (111, 2)))
        self.assertEqual(checks[ci_checks.CLEARANCE], "failure", checks)

    def test_a_capture_made_for_the_old_head_is_refused_for_the_new_one(self):
        self.assertRefused(self.clean_bundle, "pull request, commit, intent or base policy differs",
                           pr={**PR, "headSha": NEW_HEAD_SHA})
