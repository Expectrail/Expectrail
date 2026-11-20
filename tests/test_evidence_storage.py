"""Offline evidence transport, integrity, link and PR-budget checks (#566)."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import evidence_storage as storage


class EvidenceStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "main"
        self.root.mkdir()
        storage.git(self.root, "init", "-q", "-b", "main")
        storage.git(self.root, "config", "user.name", "Test")
        storage.git(self.root, "config", "user.email", "test@example.invalid")
        storage.git(self.root, "config", "commit.gpgsign", "false")
        self.write("docs/trial/raw/a.txt", "original\n")
        self.write("docs/trial/raw/nested/b.txt", "second\n")
        self.write("docs/trial/report.md", "[read](raw/a.txt)\n![image](raw/nested/b.txt)\n")
        self.write("docs/page.html", '<a href="trial/raw/a.txt">read</a>')
        self.base = self.commit()
        self.bundle = Path(self.temp.name) / "evidence.bundle"

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def commit(self):
        storage.git(self.root, "add", ".")
        storage.git(self.root, "commit", "-qm", "fixture")
        return storage.git(self.root, "rev-parse", "HEAD").decode().strip()

    def prepare(self, **kwargs):
        return storage.prepare(self.root, "docs/trial/raw", "trial-1", self.bundle,
                               new_branch=True, **kwargs)

    @property
    def manifest(self):
        return self.root / "docs/trial/raw" / storage.MANIFEST

    def checkout(self):
        target = Path(self.temp.name) / "fetched"
        storage.git(self.root, "clone", "-q", str(self.bundle), str(target))
        return target

    def test_prepare_bundle_fetch_digest_and_all_rewritten_links(self):
        doc = self.prepare()
        self.assertEqual(doc["sourceCommit"], self.base)
        self.assertEqual(doc["files"][0]["size"], 9)
        self.assertFalse((self.root / "docs/trial/raw/a.txt").exists())
        self.assertEqual(storage.git(self.root, "rev-parse", "HEAD").decode().strip(), self.base)
        fetched = self.checkout()
        self.assertEqual(storage.verify(self.manifest, repo=fetched), [])
        self.assertEqual(storage.verify(self.manifest, tree=fetched), [])
        self.assertEqual(storage.link_errors(self.root, self.manifest), [])
        self.assertIn("EVIDENCE.md#file-", (self.root / "docs/page.html").read_text())
        self.assertNotIn("![image]", (self.root / "docs/trial/report.md").read_text())
        # The bundle is standalone, with no source checkout objects required.
        self.assertEqual(storage.git(fetched, "rev-list", "--count", "HEAD").strip(), b"1")
        files = storage.git(fetched, "ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
        self.assertEqual(files, [doc["archive"] + "/a.txt", doc["archive"] + "/nested/b.txt"])

    def test_reader_names_every_missing_changed_extra_and_symlink_file(self):
        doc = self.prepare()
        fetched = self.checkout()
        raw = fetched / doc["archive"]
        (raw / "a.txt").write_text("changed and longer")
        (raw / "nested/b.txt").unlink()
        (raw / "extra.txt").write_text("extra")
        (raw / "link").symlink_to(raw / "a.txt")
        errors = storage.verify(self.manifest, tree=fetched)
        self.assertEqual(len(errors), 5, errors)
        for text in ("a.txt: size", "a.txt: SHA-256", "nested/b.txt: missing", "extra.txt: unexpected", "link: unexpected"):
            self.assertTrue(any(text in e for e in errors), errors)
        (raw / "a.txt").unlink()
        (raw / "a.txt").symlink_to(raw / "extra.txt")
        self.assertIn("symlink", "\n".join(storage.verify(self.manifest, tree=fetched)))

    def test_git_reader_detects_a_forged_digest_even_when_size_matches(self):
        self.prepare()
        doc = json.loads(self.manifest.read_text())
        doc["files"][0]["sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(doc))
        self.assertEqual(storage.verify(self.manifest, repo=self.checkout()), ["a.txt: SHA-256 mismatch"])

    def test_stale_docs_link_or_bad_index_anchor_fails(self):
        self.prepare()
        self.write("docs/stale.md", "[old](trial/raw/a.txt)\n[bad](trial/raw/EVIDENCE.md#gone)\n")
        errors = storage.link_errors(self.root, self.manifest)
        self.assertEqual(len(errors), 2)
        self.assertIn("stale link", errors[0])
        self.assertIn("missing evidence anchor", errors[1])
        self.write("docs/trial/raw/EVIDENCE.md", "wrong index")
        self.assertIn("index differs", storage.link_errors(self.root, self.manifest)[0])

    def test_links_are_checked_when_the_repository_is_reached_through_a_symlink(self):
        # The CI runners use a private temporary folder and every temporary folder on macOS is a
        # symlink. `safe_path` resolves the root, so comparing a link against the resolved index used
        # to match nothing and the anchor check passed by finding no pages at all.
        self.prepare()
        self.write("docs/stale.md", "[old](trial/raw/a.txt)\n[bad](trial/raw/EVIDENCE.md#gone)\n")
        link = Path(self.temp.name) / "through-a-symlink"
        link.symlink_to(self.root, target_is_directory=True)
        errors = storage.link_errors(link, link / "docs/trial/raw" / storage.MANIFEST)
        self.assertEqual(len(errors), 2, errors)
        self.assertIn("stale link", errors[0])
        self.assertIn("missing evidence anchor", errors[1])

    def test_parent_appends_and_refuses_reusing_a_run_id(self):
        first = self.prepare()
        storage.git(self.root, "fetch", "-q", str(self.bundle), "evidence-results")
        self.write("docs/another/raw/c.txt", "third")
        second_bundle = Path(self.temp.name) / "second.bundle"
        second = storage.prepare(self.root, "docs/another/raw", "trial-2", second_bundle, parent=first["commit"])
        clone = Path(self.temp.name) / "second"
        storage.git(self.root, "clone", "-q", str(second_bundle), str(clone))
        self.assertEqual(storage.git(clone, "rev-parse", "HEAD^").decode().strip(), first["commit"])
        self.assertEqual(storage.verify(self.manifest, repo=clone), [])
        self.assertEqual(storage.verify(self.root / "docs/another/raw" / storage.MANIFEST, repo=clone), [])
        self.write("docs/third/raw/d.txt", "fourth")
        with self.assertRaisesRegex(ValueError, "already exists"):
            storage.prepare(self.root, "docs/third/raw", "trial-1", Path(self.temp.name) / "bad.bundle", parent=first["commit"])
        self.assertTrue((self.root / "docs/third/raw/d.txt").is_file())
        self.assertNotEqual(first["commit"], second["commit"])

    def test_unsafe_source_and_manifest_paths_refused(self):
        (self.root / "docs/trial/raw/link").symlink_to(self.root / "docs/page.html")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare()
        self.assertFalse(self.bundle.exists())
        (self.root / "docs/trial/raw/link").unlink()
        self.prepare()
        original = json.loads(self.manifest.read_text())
        for path in ("../escape", "/absolute", "a/../../escape", "fresh-secret/a"):
            with self.subTest(path=path):
                doc = json.loads(json.dumps(original))
                doc["files"][0]["path"] = path
                self.manifest.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):
                    storage.read_manifest(self.manifest)
        original["files"].append(original["files"][0])
        self.manifest.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            storage.read_manifest(self.manifest)

    def test_manifest_rejects_newline_digest_commit_and_duplicate_json_keys(self):
        self.prepare()
        original = self.manifest.read_text()
        for field in ("commit", "sourceCommit", "sha256"):
            with self.subTest(field=field):
                doc = json.loads(original)
                target = doc["files"][0] if field == "sha256" else doc
                target[field] += "\n"
                self.manifest.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):
                    storage.read_manifest(self.manifest)
        # Duplicate keys must not hide arbitrary bulk inside an exempt manifest.
        self.manifest.write_text(original.replace('"files":', '"files":"hidden payload", "files":', 1))
        with self.assertRaisesRegex(ValueError, "duplicate key"):
            storage.read_manifest(self.manifest)
        self.assertTrue(storage.budget(self.root, self.base)["errors"])

    def test_manifest_read_is_bounded_and_a_symlink_is_never_exempt(self):
        self.prepare()
        original = self.manifest.read_bytes()
        self.manifest.write_bytes(original + b" " * storage.record.MAX_RECORD_BYTES)
        with self.assertRaisesRegex(ValueError, "byte cap"):
            storage.read_manifest(self.manifest)
        self.manifest.unlink()
        target = self.write("docs/copied-manifest.json", original.decode())
        self.manifest.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            storage.budget(self.root, self.base)

    def test_embedded_html_source_refuses_instead_of_rendering_a_markdown_index(self):
        self.write("docs/embed.html", '<img src="trial/raw/a.txt">')
        with self.assertRaisesRegex(ValueError, "replace embedded"):
            self.prepare()
        self.assertFalse(self.manifest.exists())
        self.assertFalse(self.bundle.exists())
        self.assertEqual((self.root / "docs/trial/raw/a.txt").read_text(), "original\n")

    def test_concurrent_source_edit_is_not_deleted(self):
        original_git = storage.git
        def edit(root, *args, **kwargs):
            result = original_git(root, *args, **kwargs)
            if args[:2] == ("bundle", "verify"):
                self.write("docs/trial/raw/a.txt", "updated while moving\n")
            return result
        with mock.patch.object(storage, "git", side_effect=edit):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.prepare()
        self.assertEqual((self.root / "docs/trial/raw/a.txt").read_text(), "updated while moving\n")
        self.assertFalse(self.manifest.exists())
        self.assertTrue(self.bundle.exists())

    def test_bundle_failure_leaves_source_and_links_untouched(self):
        original_git = storage.git
        def fail(root, *args, **kwargs):
            if args[:2] == ("bundle", "create"):
                raise ValueError("test disk failure")
            return original_git(root, *args, **kwargs)
        with mock.patch.object(storage, "git", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "disk failure"):
                self.prepare()
        self.assertEqual((self.root / "docs/trial/raw/a.txt").read_text(), "original\n")
        self.assertFalse(self.manifest.exists())
        self.assertIn("(raw/a.txt)", (self.root / "docs/trial/report.md").read_text())

    def test_cli_reports_all_mismatches_and_a_failing_exit(self):
        doc = self.prepare()
        fetched = self.checkout()
        (fetched / doc["archive"] / "a.txt").write_text("x")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = storage.main(["verify", str(self.manifest), "--tree", str(fetched)])
        self.assertEqual(code, 1)
        self.assertIn("size", output.getvalue())
        self.assertIn("SHA-256", output.getvalue())

    def test_non_manifest_limit_counts_all_extensions_and_full_replacements(self):
        for suffix in ("txt", "json", "png", "md", "html"):
            with self.subTest(suffix=suffix):
                path = self.write("docs/large." + suffix, "x" * (storage.LIMIT + 1))
                result = storage.budget(self.root, self.base)
                self.assertEqual(result["addedBytes"], storage.LIMIT + 1)
                self.assertIn("limit exceeded", result["errors"][0])
                path.unlink()
        # A large deletion cannot pay for a new capture; renaming it also counts.
        self.write("docs/old.log", "x" * storage.LIMIT)
        base = self.commit()
        (self.root / "docs/old.log").rename(self.root / "docs/new.log")
        self.write("docs/one.txt", "1")
        self.assertEqual(storage.budget(self.root, base)["addedBytes"], storage.LIMIT + 1)
        self.assertTrue(storage.budget(self.root, base)["errors"])

    def test_exact_limit_passes_but_invalid_manifest_is_not_an_escape(self):
        path = self.write("docs/raw.txt", "x" * storage.LIMIT)
        self.assertEqual(storage.budget(self.root, self.base)["errors"], [])
        path.unlink()
        self.write("docs/" + storage.MANIFEST, '{"payload":"' + "x" * storage.LIMIT + '"}')
        self.assertTrue(storage.budget(self.root, self.base)["errors"])
        (self.root / "docs" / storage.MANIFEST).unlink()
        self.prepare()
        result = storage.budget(self.root, self.base)
        self.assertEqual(result["errors"], [])
        self.assertTrue(any(x["reason"] == "validated manifest" for x in result["exempted"]))

    def test_exemption_requires_base_review_named_existing_reader_and_size_bound(self):
        self.write("tests/test_reads_fixture.py", "# reviewed fixture reader\n")
        policy = {"format": "expectrail.evidence-exemptions/v1", "files": [{
            "name": "fixture-for-offline-reader", "path": "docs/fixture.json",
            "reader": "tests/test_reads_fixture.py", "reason": "Offline reader needs all rows",
            "review": "https://github.com/Expectrail/Expectrail/pull/566", "maxBytes": storage.LIMIT + 1}]}
        self.write(storage.EXEMPTIONS, json.dumps(policy))
        self.write("docs/fixture.json", "x" * (storage.LIMIT + 1))
        self.assertTrue(storage.budget(self.root, self.base)["errors"], "a PR cannot exempt itself")
        (self.root / "docs/fixture.json").unlink()
        base = self.commit()
        self.write("docs/fixture.json", "x" * (storage.LIMIT + 1))
        self.assertEqual(storage.budget(self.root, base)["errors"], [])
        self.write("docs/fixture.json", "x" * (storage.LIMIT + 2))
        self.assertTrue(storage.budget(self.root, base)["errors"])
        policy["files"][0]["reader"] = "tests/missing.py"
        self.write(storage.EXEMPTIONS, json.dumps(policy))
        base = self.commit()
        with self.assertRaises(ValueError):
            storage.budget(self.root, base)

    def test_ci_uses_event_base_and_fetches_only_the_missing_commit(self):
        event = Path(self.temp.name) / "event.json"
        event.write_text(json.dumps({"pull_request": {"base": {"sha": self.base}}}))
        self.assertEqual(storage.base_commit(self.root, {"GITHUB_EVENT_PATH": str(event)}), self.base)
        self.write("docs/new.txt", "new")
        self.commit()
        clone = Path(self.temp.name) / "shallow"
        storage.git(self.root, "clone", "-q", "--depth=1", self.root.as_uri(), str(clone))
        with self.assertRaises(ValueError):
            storage.git(clone, "cat-file", "-e", self.base)
        self.assertEqual(storage.base_commit(clone, {"GITHUB_EVENT_PATH": str(event)}), self.base)
        self.assertEqual(storage.budget(clone, self.base)["addedBytes"], 3)
        event.write_text('{"pull_request":{"base":{"sha":"--bad"}}}')
        with self.assertRaisesRegex(ValueError, "full commit"):
            storage.base_commit(clone, {"GITHUB_EVENT_PATH": str(event)})
        event.write_text('{}')
        with self.assertRaisesRegex(ValueError, "no comparison base"):
            storage.base_commit(clone, {"GITHUB_EVENT_PATH": str(event)})

    def test_scheduled_and_manual_runs_have_no_base_but_other_events_still_refuse(self):
        event = Path(self.temp.name) / "event.json"
        event.write_text('{}')
        for name in ("schedule", "workflow_dispatch"):
            with self.subTest(event=name):
                self.assertIsNone(storage.base_commit(self.root, {"GITHUB_EVENT_PATH": str(event),
                                                                  "GITHUB_EVENT_NAME": name}))
        for name in ("pull_request", "push", ""):
            with self.subTest(event=name), self.assertRaisesRegex(ValueError, "no comparison base"):
                storage.base_commit(self.root, {"GITHUB_EVENT_PATH": str(event), "GITHUB_EVENT_NAME": name})
        event.write_text(json.dumps({"pull_request": {"base": {"sha": self.base}}}))
        self.assertEqual(storage.base_commit(self.root, {"GITHUB_EVENT_PATH": str(event),
                                                         "GITHUB_EVENT_NAME": "schedule"}), self.base)

    def test_import_without_numpy_or_pillow(self):
        result = subprocess.run([os.sys.executable, "-c", "import sys; sys.modules['numpy']=None; sys.modules['PIL']=None; from tools import evidence_storage"],
                                cwd=storage.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class RepositoryEvidenceTest(unittest.TestCase):
    def test_pr_docs_evidence_stays_within_reviewed_budget(self):
        base = storage.base_commit(storage.ROOT)
        if base is None:
            self.skipTest("scheduled or manual run: no pull request base, so the PR evidence limit does not apply")
        result = storage.budget(storage.ROOT, base)
        self.assertEqual(result["errors"], [], json.dumps(result, indent=2))

    def test_committed_evidence_indexes_and_doc_links_match_manifests(self):
        for path in sorted((storage.ROOT / "docs").rglob(storage.MANIFEST)):
            with self.subTest(manifest=str(path.relative_to(storage.ROOT))):
                self.assertEqual(storage.link_errors(storage.ROOT, path), [])

    def test_contract_examples(self):
        import jsonschema
        for name in ("evidence-manifest.v1", "evidence-exemptions.v1"):
            schema = json.loads((storage.ROOT / "contracts" / (name + ".schema.json")).read_text())
            example = json.loads((storage.ROOT / "contracts/examples" / (name + ".json")).read_text())
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(example)
        storage.read_manifest(storage.ROOT / "contracts/examples/evidence-manifest.v1.json")
