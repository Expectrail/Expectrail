"""The private scan on a pull request without pull_request_target (#247).

Two halves. `private-scan-collect.yml` runs on the pull request with no secret and uploads the files
the scan reads. `private-scan.yml` runs from main when that finishes (workflow_run), in the
main-only environment, and scans them with main's scanner. These tests hold the two properties the
design rests on:

- the trusted half takes nothing from the pull request on trust: `agents.scan_handoff` writes a file
  only when its bytes are the head commit's, and fails when a file of the commit is missing;
- the workflows stay the shape that makes that true: no secret in the collector, no pull request
  ref checked out and no event value pasted into a script in the trusted half.

Nothing here reads the private set or calls GitHub; the tree GitHub would return is built from a
temporary repository with `git ls-tree`.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from agents import scan_handoff
from agents.scan_handoff import HandoffError, blob_sha, check_run, expected, fetch_tree, post_check, unpack
from harness.run import REPO

WORKFLOWS = REPO / ".github" / "workflows"
COLLECT = WORKFLOWS / "private-scan-collect.yml"
SCAN = WORKFLOWS / "private-scan.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"

FILES = {
    "README.md": b"# A project\n",
    "docs/index.html": b"<p>hello</p>\n",
    "docs/a page with spaces.md": b"spaces\n",
    "docs/déjà/vu.md": "déjà\n".encode(),
    "bench/run-1/result.json": b'{"outcome": "fixed"}\n',
    "bench/empty.txt": b"",
    "bench/binary.bin": bytes(range(256)),
    "apps/checkout/site/index.html": b"<html></html>\n",
    "apps/tool.sh": b"#!/bin/sh\necho hi\n",
    "agents/not_scanned.py": b"print('outside the scanned paths')\n",
    "docsx/also-outside.md": b"a folder whose name only starts like one\n",
}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(doc: dict) -> dict:
    return doc.get("on", doc.get(True))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.quotepath=off",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def tree_of(repo: Path) -> dict:
    """What GET /repos/{repo}/git/trees/{sha}?recursive=1 returns, for the blobs of HEAD."""
    entries = []
    for line in git(repo, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            mode, kind, sha = meta.split()
            entries.append({"path": path, "mode": mode, "type": kind, "sha": sha})
    return {"sha": SHA, "tree": entries, "truncated": False}


def make_tar(path: Path, members: list) -> Path:
    """members: (name, bytes) for a file, or a ready TarInfo for anything else."""
    with tarfile.open(path, "w") as tar:
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                tar.addfile(member)
            else:
                info = tarfile.TarInfo(member[0])
                info.size = len(member[1])
                tar.addfile(info, io.BytesIO(member[1]))
    return path


def tree_for(files: dict[str, bytes]) -> dict:
    return {"tree": [{"path": p, "mode": "100644", "type": "blob", "sha": blob_sha(d)} for p, d in files.items()],
            "truncated": False}


class HandoffFromARealRepository(unittest.TestCase):
    """The collector's own pack command, run on a temporary repository, then unpacked."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.tmp = Path(tmp.name)
        cls.repo = cls.tmp / "repo"
        cls.repo.mkdir()
        git(cls.repo, "init", "-q")
        for name, data in FILES.items():
            (cls.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (cls.repo / name).write_bytes(data)
        os.chmod(cls.repo / "apps" / "tool.sh", 0o755)
        git(cls.repo, "add", "-A")
        git(cls.repo, "commit", "-q", "-m", "files")
        (cls.repo / "docs" / "untracked.md").write_text("never committed, so never packed\n")
        pack = next(s["run"] for s in load(COLLECT)["jobs"]["private-scan-collect"]["steps"]
                    if s.get("name") == "Pack the files the scan reads")
        cls.runner_temp = cls.tmp / "runner"
        cls.runner_temp.mkdir()
        subprocess.run(["bash", "-euo", "pipefail", "-c", pack], cwd=cls.repo, check=True, capture_output=True,
                       env={**os.environ, "RUNNER_TEMP": str(cls.runner_temp)})
        cls.archive = cls.runner_temp / "private-scan-input" / "files.tar"
        cls.tree = tree_of(cls.repo)

    def out(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "scanned"

    def test_the_packed_files_are_exactly_the_commits_files_under_the_scanned_paths(self):
        out = self.out()
        want = {n: d for n, d in FILES.items() if scan_handoff.scanned(n)}
        self.assertEqual(len(want), 9)
        self.assertEqual(unpack(self.archive, self.tree, out), len(want))
        got = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        self.assertEqual(got, want)

    def test_the_upload_step_sends_the_file_the_pack_step_wrote(self):
        steps = load(COLLECT)["jobs"]["private-scan-collect"]["steps"]
        upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/private-scan-input/files.tar")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertTrue(self.archive.is_file())

    def test_a_file_changed_after_the_commit_fails_and_nothing_is_left(self):
        members = []
        with tarfile.open(self.archive) as tar:
            for m in tar:
                data = tar.extractfile(m).read()
                members.append((m.name, data + b"edited\n" if m.name == "docs/index.html" else data))
        out = self.out()
        with self.assertRaisesRegex(HandoffError, "differs from the commit"):
            unpack(make_tar(self.tmp / "changed.tar", members), self.tree, out)
        self.assertFalse(out.exists())

    def test_a_file_held_back_from_the_archive_fails(self):
        with tarfile.open(self.archive) as tar:
            members = [(m.name, tar.extractfile(m).read()) for m in tar if m.name != "bench/run-1/result.json"]
        out = self.out()
        with self.assertRaisesRegex(HandoffError, "1 file.s. of the commit are missing"):
            unpack(make_tar(self.tmp / "short.tar", members), self.tree, out)
        self.assertFalse(out.exists())

    def test_an_empty_archive_fails_when_the_commit_has_files(self):
        with self.assertRaisesRegex(HandoffError, "9 file.s. of the commit are missing"):
            unpack(make_tar(self.tmp / "empty.tar", []), self.tree, self.out())


class Handoff(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.out = self.tmp / "scanned"
        self.files = {"README.md": b"readme\n", "docs/a.md": b"a\n"}
        self.tree = tree_for(self.files)

    def refuse(self, members: list, pattern: str, tree: dict | None = None) -> None:
        with self.assertRaisesRegex(HandoffError, pattern):
            unpack(make_tar(self.tmp / "in.tar", members), tree or self.tree, self.out)
        self.assertFalse(self.out.exists(), "a refused archive must leave nothing to scan")

    def test_the_plain_case_passes(self):
        self.assertEqual(unpack(make_tar(self.tmp / "in.tar", list(self.files.items())), self.tree, self.out), 2)
        self.assertEqual((self.out / "docs" / "a.md").read_bytes(), b"a\n")

    def test_a_commit_with_nothing_to_scan_gives_an_empty_folder(self):
        tree = tree_for({"agents/x.py": b"x\n"})
        self.assertEqual(unpack(make_tar(self.tmp / "in.tar", []), tree, self.out), 0)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_file_the_commit_does_not_have_is_refused(self):
        self.refuse([*self.files.items(), ("docs/extra.md", b"x\n")], "does not have under the scanned paths")

    def test_a_file_outside_the_scanned_paths_is_refused_even_if_the_commit_has_it(self):
        tree = tree_for({**self.files, "agents/x.py": b"x\n"})
        self.refuse([*self.files.items(), ("agents/x.py", b"x\n")], "does not have under the scanned paths", tree)

    def test_a_path_that_leaves_the_folder_is_refused(self):
        for name in ("../escape.md", "docs/../../escape.md", "/etc/passwd", "docs\\a.md"):
            with self.subTest(name=name):
                self.refuse([*self.files.items(), (name, b"x\n")], "leaves the folder")
        self.assertFalse((self.tmp / "escape.md").exists())

    def test_links_and_devices_are_refused(self):
        for kind, target in ((tarfile.SYMTYPE, "/etc/passwd"), (tarfile.LNKTYPE, "README.md"),
                             (tarfile.CHRTYPE, ""), (tarfile.FIFOTYPE, "")):
            with self.subTest(kind=kind):
                info = tarfile.TarInfo("docs/a.md")
                info.type, info.linkname = kind, target
                self.refuse([("README.md", b"readme\n"), info], "not a plain file")

    def test_the_same_file_twice_is_refused(self):
        self.refuse([*self.files.items(), ("docs/a.md", b"a\n")], "twice")

    def test_a_folder_entry_is_ignored(self):
        folder = tarfile.TarInfo("docs")
        folder.type = tarfile.DIRTYPE
        self.assertEqual(unpack(make_tar(self.tmp / "in.tar", [folder, *self.files.items()]), self.tree, self.out), 2)

    def test_something_that_is_not_an_archive_is_refused(self):
        (self.tmp / "in.tar").write_bytes(b"not a tar file" * 100)
        with self.assertRaisesRegex(HandoffError, "could not be read"):
            unpack(self.tmp / "in.tar", self.tree, self.out)
        self.assertFalse(self.out.exists())

    def test_a_compressed_archive_is_refused(self):
        with tarfile.open(self.tmp / "in.tar", "w:gz") as tar:
            info = tarfile.TarInfo("README.md")
            info.size = 7
            tar.addfile(info, io.BytesIO(b"readme\n"))
        with self.assertRaisesRegex(HandoffError, "could not be read"):
            unpack(self.tmp / "in.tar", self.tree, self.out)

    def test_the_size_limits_hold(self):
        with mock.patch.object(scan_handoff, "MAX_FILES", 1):
            self.refuse(list(self.files.items()), "over the size limits")
        with mock.patch.object(scan_handoff, "MAX_BYTES", 8):
            self.refuse(list(self.files.items()), "over the size limits")

    def test_an_existing_folder_is_not_reused(self):
        self.out.mkdir()
        (self.out / "left-over.md").write_text("from an earlier step")
        with self.assertRaisesRegex(HandoffError, "already exists"):
            unpack(make_tar(self.tmp / "in.tar", list(self.files.items())), self.tree, self.out)

    def test_a_truncated_or_unreadable_tree_is_refused(self):
        self.refuse(list(self.files.items()), "truncated", {**self.tree, "truncated": True})
        self.refuse(list(self.files.items()), "could not be read", {"message": "Not Found"})

    def test_a_link_in_the_commit_under_the_scanned_paths_is_refused(self):
        tree = {"tree": [*self.tree["tree"], {"path": "docs/link", "mode": "120000", "type": "blob", "sha": "0" * 40}],
                "truncated": False}
        self.refuse(list(self.files.items()), "a link under the scanned paths", tree)
        outside = {"tree": [*self.tree["tree"], {"path": "agents/link", "mode": "120000", "type": "blob",
                                                 "sha": "0" * 40}], "truncated": False}
        self.assertEqual(len(expected(outside)), 2)

    def test_folders_and_submodules_in_the_tree_are_not_expected_as_files(self):
        tree = {"tree": [*self.tree["tree"], {"path": "docs", "mode": "040000", "type": "tree", "sha": "1" * 40},
                         {"path": "bench/sub", "mode": "160000", "type": "commit", "sha": "2" * 40}],
                "truncated": False}
        self.assertEqual(sorted(expected(tree)), ["README.md", "docs/a.md"])

    def test_the_blob_name_is_gits(self):
        self.assertEqual(blob_sha(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        self.assertEqual(blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_no_message_repeats_a_file_name_or_its_content(self):
        cases = [[*self.files.items(), ("docs/secret-name.md", b"x\n")], [("README.md", b"other bytes\n")],
                 [("../secret-name.md", b"x\n")]]
        for members in cases:
            with self.assertRaises(HandoffError) as caught:
                unpack(make_tar(self.tmp / "in.tar", members), self.tree, self.out)
            self.assertNotRegex(str(caught.exception), "secret-name|README|other bytes")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Api(unittest.TestCase):
    def setUp(self):
        self.requests = []

    def opener(self, reply: dict):
        def open_(request, timeout=None):
            self.requests.append(request)
            return FakeResponse(json.dumps(reply).encode())
        return open_

    def test_the_tree_is_asked_for_by_commit_with_the_token_in_a_header(self):
        with mock.patch.dict(os.environ, {"GITHUB_API_URL": "https://api.github.com"}):
            tree = fetch_tree("Expectrail/Expectrail", SHA, "t0ken", opener=self.opener({"tree": [], "truncated": False}))
        self.assertEqual(tree, {"tree": [], "truncated": False})
        request = self.requests[0]
        self.assertEqual(request.full_url, f"https://api.github.com/repos/Expectrail/Expectrail/git/trees/{SHA}?recursive=1")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer t0ken")
        self.assertNotIn("t0ken", request.full_url)

    def test_only_a_full_commit_id_and_a_plain_repository_name_reach_the_url(self):
        for repo, sha in (("Expectrail/Expectrail", "main"), ("Expectrail/Expectrail", SHA[:12]),
                          ("Expectrail/Expectrail", SHA + "/../../x"), ("Expectrail/Expectrail/../x", SHA),
                          ("Expectrail/Expectrail?x=", SHA), ("Expectrail", SHA)):
            with self.subTest(repo=repo, sha=sha), self.assertRaises(HandoffError):
                fetch_tree(repo, sha, "t", opener=self.opener({}))
            with self.subTest(repo=repo, sha=sha), self.assertRaises(HandoffError):
                post_check(repo, sha, "success", "https://example.invalid/run", "t", opener=self.opener({}))
        self.assertEqual(self.requests, [])

    def test_the_check_is_posted_on_the_commit_under_the_scans_name(self):
        post_check("Expectrail/Expectrail", SHA, "success", "https://example.invalid/run/1", "t0ken",
                   opener=self.opener({"id": 1}))
        request = self.requests[0]
        self.assertTrue(request.full_url.endswith("/repos/Expectrail/Expectrail/check-runs"))
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)
        self.assertEqual((body["name"], body["head_sha"], body["status"], body["conclusion"], body["details_url"]),
                         ("private-export-scan", SHA, "completed", "success", "https://example.invalid/run/1"))

    def test_only_a_clean_success_is_reported_as_a_pass(self):
        self.assertEqual(check_run(SHA, "success", "u")["conclusion"], "success")
        self.assertEqual(check_run(SHA, "cancelled", "u")["conclusion"], "cancelled")
        for status in ("failure", "skipped", "", "Success", "neutral", "anything"):
            with self.subTest(status=status):
                run = check_run(SHA, status, "u")
                self.assertEqual(run["conclusion"], "failure")
                self.assertIn("did not pass", run["output"]["title"])

    def test_the_command_fails_plainly_when_no_archive_arrived(self):
        buf = io.StringIO()
        with redirect_stdout(buf), tempfile.TemporaryDirectory() as tmp:
            code = scan_handoff.main(["unpack", "--archive", f"{tmp}/files.tar", "--out", f"{tmp}/scanned",
                                      "--repo", "Expectrail/Expectrail", "--sha", SHA])
        self.assertEqual(code, 1)
        self.assertIn("::error title=Private scan::no archive arrived", buf.getvalue())

    def test_an_api_failure_is_reported_without_the_response(self):
        def refuse(request, timeout=None):
            raise OSError("a response body that might quote a token: t0ken")
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(scan_handoff.urllib.request, "urlopen", refuse), \
                mock.patch.dict(os.environ, {"GH_TOKEN": "t0ken"}):
            code = scan_handoff.main(["report", "--repo", "Expectrail/Expectrail", "--sha", SHA,
                                      "--status", "success", "--run-url", "https://example.invalid"])
        self.assertEqual(code, 1)
        self.assertNotIn("t0ken", buf.getvalue())

    def test_the_handoff_needs_only_the_standard_library(self):
        """The workflow runs it with python -I, where the repository is not importable."""
        done = subprocess.run(["python3", "-I", str(REPO / "agents" / "scan_handoff.py"), "unpack", "--archive",
                               "/nonexistent/files.tar", "--out", "/nonexistent/out", "--repo", "a/b", "--sha", SHA],
                              capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("no archive arrived", done.stdout)


class Collector(unittest.TestCase):
    """The half a pull request can edit: it must hold nothing worth taking."""

    def setUp(self):
        self.doc = load(COLLECT)
        self.text = COLLECT.read_text(encoding="utf-8")

    def test_it_runs_on_pull_requests_with_read_access_and_no_secret(self):
        self.assertEqual(set(triggers(self.doc)), {"pull_request"})
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(list(self.doc["jobs"]), ["private-scan-collect"])
        job = self.doc["jobs"]["private-scan-collect"]
        self.assertNotIn("permissions", job)
        self.assertNotIn("environment", job)
        self.assertNotRegex(self.text, re.compile(r"secrets|id-token", re.I))

    def test_same_repository_pull_requests_only(self):
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository",
                      self.doc["jobs"]["private-scan-collect"]["if"])

    def test_it_packs_the_paths_the_scan_reads(self):
        pack = next(s["run"] for s in self.doc["jobs"]["private-scan-collect"]["steps"] if "git ls-files" in s.get("run", ""))
        listed = re.search(r"git ls-files -z -- ([^\\|\n]+)", pack).group(1).split()
        self.assertEqual(sorted(listed), sorted(scan_handoff.ROOTS))
        scan = next(s["run"] for s in load(SCAN)["jobs"]["private-export-scan"]["steps"]
                    if "agents.export_scan" in s.get("run", ""))
        self.assertEqual(sorted(re.findall(r"scanned/(\S+)", scan)), sorted(scan_handoff.ROOTS))

    def test_no_event_value_is_pasted_into_a_script(self):
        for step in self.doc["jobs"]["private-scan-collect"]["steps"]:
            self.assertNotIn("${{", step.get("run", ""))


class TrustedHalf(unittest.TestCase):
    """The half that holds HELDOUT_TOKEN: it must take the pull request only as checked data."""

    def setUp(self):
        self.doc = load(SCAN)
        self.job = self.doc["jobs"]["private-export-scan"]
        self.steps = self.job["steps"]

    def step(self, fragment: str) -> dict:
        return next(s for s in self.steps if fragment in (s.get("name") or ""))

    def test_it_starts_when_the_collector_finishes_or_by_hand_and_never_on_a_pull_request_event(self):
        on = triggers(self.doc)
        self.assertEqual(set(on), {"workflow_run", "workflow_dispatch"})
        self.assertEqual(on["workflow_run"], {"workflows": [load(COLLECT)["name"]], "types": ["completed"]})
        self.assertEqual(list(self.doc["jobs"]), ["private-export-scan"])
        self.assertEqual(self.job["environment"], "main-only")

    def test_only_the_collector_at_its_own_path_for_a_pull_request_from_this_repository(self):
        cond = " ".join(self.job["if"].split())
        self.assertTrue(cond.startswith("github.event_name == 'workflow_dispatch' || ("), cond)
        self.assertTrue(cond.endswith(")"), cond)
        inner = cond.split("|| (", 1)[1]
        self.assertNotIn("||", inner)
        for clause in ("github.event.workflow_run.event == 'pull_request'",
                       "github.event.workflow_run.path == '.github/workflows/private-scan-collect.yml'",
                       "github.event.workflow_run.head_repository.full_name == github.repository",
                       "github.event.workflow_run.conclusion != 'cancelled'"):
            self.assertIn(clause, inner)
        self.assertNotRegex(cond, r"always|failure\s*\(")

    def test_its_token_can_read_and_post_a_check_and_nothing_else(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(self.job["permissions"], {"actions": "read", "contents": "read", "checks": "write"})

    def test_the_held_out_token_reaches_one_step_only(self):
        with_token = [s for s in self.steps if "secrets" in yaml.safe_dump(s)]
        self.assertEqual([s["name"] for s in with_token], ["Fetch the private held-out set"])
        self.assertEqual(with_token[0]["with"]["token"], "${{ secrets.HELDOUT_TOKEN }}")
        self.assertIs(with_token[0]["with"]["persist-credentials"], False)
        self.assertEqual(self.job["env"], {"HELDOUT_TOKEN_SET": "${{ secrets.HELDOUT_TOKEN != '' }}"})

    def test_the_pull_requests_ref_is_never_checked_out(self):
        checkouts = [s for s in self.steps if "actions/checkout" in s.get("uses", "")]
        self.assertEqual(len(checkouts), 3)
        for step in checkouts:
            self.assertIs(step["with"]["persist-credentials"], False)
            self.assertNotIn("workflow_run", yaml.safe_dump(step.get("with")))
            self.assertNotIn("pull_request", yaml.safe_dump(step.get("with")))
        scanner, manual, private = checkouts
        self.assertNotIn("ref", scanner["with"])
        self.assertNotIn("path", scanner["with"])
        self.assertEqual((manual["with"]["ref"], manual["with"]["path"]), ("${{ inputs.ref }}", "scanned"))
        self.assertEqual(manual["if"], "github.event_name == 'workflow_dispatch'")
        self.assertEqual(private["with"]["path"], "heldout-set")

    def test_the_archive_is_downloaded_outside_the_workspace_and_checked_before_the_private_set_arrives(self):
        names = [s.get("name") for s in self.steps]
        download, check = self.step("Download the pull request's files"), self.step("Check the files against")
        self.assertLess(names.index(download["name"]), names.index(check["name"]))
        self.assertLess(names.index(check["name"]), names.index("Fetch the private held-out set"))
        self.assertEqual(download["with"]["run-id"], "${{ github.event.workflow_run.id }}")
        self.assertEqual(download["with"]["name"], "private-scan-input")
        self.assertTrue(download["with"]["path"].startswith("${{ runner.temp }}/"))
        for step in (download, check):
            self.assertEqual(step["if"], "github.event_name == 'workflow_run'")
        run = " ".join(check["run"].split())
        self.assertTrue(run.startswith("python -I agents/scan_handoff.py unpack "), run)
        self.assertIn('--sha "$HEAD_SHA"', run)
        self.assertIn("--out scanned", run)
        self.assertEqual(check["env"]["HEAD_SHA"], "${{ github.event.workflow_run.head_sha }}")
        self.assertNotIn("continue-on-error", check)

    def test_no_event_value_is_pasted_into_a_script_and_no_action_is_unpinned(self):
        for step in self.steps:
            self.assertNotIn("${{", step.get("run", ""), step.get("name"))
            if "uses" in step:
                self.assertRegex(step["uses"], r"^actions/[a-z-]+@[0-9a-f]{40}$")
        for step in load(COLLECT)["jobs"]["private-scan-collect"]["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^actions/[a-z-]+@[0-9a-f]{40}$")

    def test_the_scan_runs_mains_scanner_on_the_unpacked_folder(self):
        scan = self.step("Export scan of the pull request")
        self.assertEqual(scan["run"], "python -m agents.export_scan scanned/bench scanned/docs scanned/README.md "
                                      "scanned/apps --private heldout-set")
        self.assertNotIn("if", scan)
        self.assertNotIn("continue-on-error", scan)

    def test_the_result_is_posted_on_the_head_commit_whatever_happened(self):
        report = self.steps[-1]
        self.assertEqual(report["if"], "always() && github.event_name == 'workflow_run'")
        self.assertEqual(report["env"]["HEAD_SHA"], "${{ github.event.workflow_run.head_sha }}")
        self.assertEqual(report["env"]["STATUS"], "${{ job.status }}")
        run = " ".join(report["run"].split())
        self.assertTrue(run.startswith("python3 -I agents/scan_handoff.py report "), run)
        self.assertIn('--sha "$HEAD_SHA" --status "$STATUS"', run)
        # A missing token must fail after the scanner is checked out, or there is nothing to report with.
        names = [s.get("name") for s in self.steps]
        self.assertLess(names.index("Check out the scanner (this branch, never the pull request's code)"),
                        names.index("Require the held-out token"))

    def test_obaaf_no_longer_carries_the_pull_request_target_exceptions(self):
        config = yaml.safe_load((REPO / ".github" / "obaaf.yml").read_text(encoding="utf-8"))
        self.assertEqual([i for i in config["ignore"] if "private-scan" in i["path"]], [])
        self.assertNotIn("pull_request_target", yaml.safe_dump(config))


if __name__ == "__main__":
    unittest.main()
