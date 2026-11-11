"""tools.merge_guard: each rule no agent may break, with a diff that keeps it and a diff that breaks it."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tools import merge_guard as mg
from tools.merge_guard import CHANGES, NEEDS_SEAN, Change

ROOT = Path(__file__).resolve().parent.parent
ROW = "| Nov 11 | what changed, what was run | `a.py` |\n"
LOG = Change("docs/new-work.md", "| Date | What | Files |\n", "| Date | What | Files |\n" + ROW)

# The words the guard looks for are assembled here, so that this file's own diff does not contain them.
SKIP = "@unittest." + "skip"
SKIP_IF = "@unittest." + "skipIf"
XFAIL = "@unittest." + "expectedFailure"
SKIP_CALL = "self." + "skipTest"
FRESH_3 = "fresh-" + "3"
PRIVATE = "Expectrail-" + "heldout"

WORKFLOW = """\
name: Example
on:
  pull_request:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - run: echo build
  report:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      pull-requests: write
    steps:
      - run: echo report
"""


def rules(reasons) -> list[tuple[str, str, str]]:
    return [(r.label, r.rule, r.path) for r in reasons]


def spec(approval=None, tolerance: int = 4) -> str:
    doc = {"format": "expectrail.test-spec/v0", "id": "s", "tolerancePx": tolerance}
    if approval is not None:
        doc["approval"] = approval
    return json.dumps(doc, indent=2)


class ApprovalTest(unittest.TestCase):
    BY_SEAN = {"by": "Sean", "at": "2026-11-01"}

    def test_editing_a_spec_without_touching_its_approval_passes(self):
        change = Change("specs/s.json", spec(self.BY_SEAN, 4), spec(self.BY_SEAN, 6))
        self.assertEqual(mg.check_approvals([change]), [])

    def test_a_draft_spec_with_no_approval_passes(self):
        self.assertEqual(mg.check_approvals([Change("specs/unity/new.json", None, spec())]), [])

    def test_adding_an_approval_needs_a_person(self):
        found = mg.check_approvals([Change("specs/s.json", spec(), spec(self.BY_SEAN))])
        self.assertEqual(rules(found), [(NEEDS_SEAN, "approval", "specs/s.json")])
        self.assertIn("added", found[0].message)

    def test_a_new_spec_that_arrives_approved_needs_a_person(self):
        found = mg.check_approvals([Change("apps/checkout/specs/new.json", None, spec(self.BY_SEAN))])
        self.assertEqual(rules(found), [(NEEDS_SEAN, "approval", "apps/checkout/specs/new.json")])

    def test_changing_or_removing_an_approval_needs_a_person(self):
        changed = mg.check_approvals([Change("contracts/examples/test-spec.json", spec(self.BY_SEAN),
                                             spec({"by": "an agent", "at": "2026-11-11"}))])
        removed = mg.check_approvals([Change("specs/s.json", spec(self.BY_SEAN), spec())])
        deleted = mg.check_approvals([Change("specs/s.json", spec(self.BY_SEAN), None)])
        self.assertIn("changed", changed[0].message)
        self.assertIn("removed", removed[0].message)
        self.assertIn("removed", deleted[0].message)

    def test_an_approval_nested_in_a_list_is_found(self):
        old = json.dumps({"specs": [{"id": "a"}]})
        new = json.dumps({"specs": [{"id": "a", "approval": self.BY_SEAN}]})
        found = mg.check_approvals([Change("contracts/set.json", old, new)])
        self.assertIn("/specs/0/approval", found[0].message)

    def test_a_file_that_is_not_json_is_judged_by_its_lines(self):
        ok = Change("specs/notes.txt", "a\n", "a\nb\n")
        bad = Change("specs/broken.json", '{"id": "s",\n', '{"id": "s",\n  "approval": {"by": "x"},\n')
        self.assertEqual(mg.check_approvals([ok]), [])
        self.assertEqual(rules(mg.check_approvals([bad])), [(NEEDS_SEAN, "approval", "specs/broken.json")])

    def test_an_approval_outside_specs_and_contracts_is_not_this_rules_business(self):
        change = Change("agents/fixtures/thing.json", spec(), spec(self.BY_SEAN))
        self.assertEqual(mg.check_approvals([change]), [])


class PathsTest(unittest.TestCase):
    def test_a_patch_against_the_game_passes(self):
        self.assertEqual(mg.check_paths([Change("bugs/new/v1.patch", None, "--- a/game/platformer/x\n")]), [])

    def test_editing_either_game_fails(self):
        found = mg.check_paths([Change("game/platformer/player/player.gd", "a\n", "b\n"),
                                Change("game/unity-platformer/Assets/x.cs", None, "x\n")])
        self.assertEqual(rules(found), [(CHANGES, "game", "game/platformer/player/player.gd"),
                                        (CHANGES, "game", "game/unity-platformer/Assets/x.cs")])

    def test_a_folder_that_only_starts_like_the_game_passes(self):
        self.assertEqual(mg.check_paths([Change("game/platformer-notes.md", None, "x\n")]), [])

    def test_the_rules_need_a_person(self):
        found = mg.check_paths([Change("AGENTS.md", "a\n", "b\n"), Change(".github/CODEOWNERS", "a\n", "b\n")])
        self.assertEqual(rules(found), [(NEEDS_SEAN, "rules", "AGENTS.md"), (NEEDS_SEAN, "rules", ".github/CODEOWNERS")])
        self.assertEqual(mg.check_paths([Change("docs/AGENTS.md", "a\n", "b\n")]), [])

    def test_adding_the_guard_passes_and_changing_or_deleting_it_needs_a_person(self):
        self.assertEqual(mg.check_paths([Change("tools/merge_guard.py", None, "x\n")]), [])
        init = mg.check_paths([Change("tools/__init__.py", "x\n", "import sys; sys.exit(0)\n")])
        self.assertEqual(rules(init), [(NEEDS_SEAN, "guard", "tools/__init__.py")])
        self.assertEqual(mg.check_paths([Change("tests/test_merge_guard.py", None, "x\n")]), [])
        own_tests = mg.check_paths([Change("tests/test_merge_guard.py", "x\n", "y\n")])
        self.assertEqual(rules(own_tests), [(NEEDS_SEAN, "guard", "tests/test_merge_guard.py")])
        changed = mg.check_paths([Change("tools/merge_guard.py", "x\n", "y\n")])
        deleted = mg.check_paths([Change(".github/workflows/merge-guard.yml", "x\n", None)])
        self.assertEqual(rules(changed), [(NEEDS_SEAN, "guard", "tools/merge_guard.py")])
        self.assertEqual(rules(deleted), [(NEEDS_SEAN, "guard", ".github/workflows/merge-guard.yml")])


class BaselineTest(unittest.TestCase):
    @staticmethod
    def baseline(*prints: str) -> str:
        return json.dumps({"format": "obaaf-baseline/v0.1", "findings": [
            {"fingerprint": p, "rule": "OBAAF-GHA-005", "message": "m"} for p in prints]}, indent=2)

    def test_removing_a_finding_passes(self):
        change = Change(mg.BASELINE, self.baseline("sha256:a", "sha256:b"), self.baseline("sha256:a"))
        self.assertEqual(mg.check_baseline([change]), [])

    def test_rewording_a_finding_that_keeps_its_fingerprint_passes(self):
        old = self.baseline("sha256:a")
        self.assertEqual(mg.check_baseline([Change(mg.BASELINE, old, old.replace('"m"', '"reworded"'))]), [])

    def test_adding_a_finding_needs_a_person(self):
        change = Change(mg.BASELINE, self.baseline("sha256:a"), self.baseline("sha256:a", "sha256:b", "sha256:c"))
        found = mg.check_baseline([change])
        self.assertEqual(rules(found), [(NEEDS_SEAN, "baseline", mg.BASELINE)])
        self.assertIn("2 finding(s)", found[0].message)

    def test_a_baseline_that_cannot_be_read_is_judged_by_its_added_lines(self):
        found = mg.check_baseline([Change(mg.BASELINE, self.baseline("sha256:a"), "not json\n")])
        self.assertEqual(rules(found), [(NEEDS_SEAN, "baseline", mg.BASELINE)])


class WorkflowTest(unittest.TestCase):
    PATH = ".github/workflows/example.yml"

    def found(self, new: str, old: str | None = WORKFLOW) -> list[str]:
        reasons = mg.check_workflows([Change(self.PATH, old, new)])
        self.assertTrue(all((r.label, r.rule, r.path) == (NEEDS_SEAN, "workflow", self.PATH) for r in reasons))
        return [r.message for r in reasons]

    NAMED = "the file names secrets more often than it did, where no job is read as gaining them: "

    def test_a_harmless_edit_passes(self):
        self.assertEqual(self.found(WORKFLOW.replace("echo build", "echo built  # a comment")), [])

    def test_a_comment_that_newly_names_a_secret_is_reported(self):
        # The words are counted in the raw text, so the guard need not know what is a comment and what is not.
        self.assertEqual(self.found(WORKFLOW.replace("echo build", "echo built  # a comment naming secrets.X")),
                         [self.NAMED + "X"])

    def test_a_new_read_only_job_passes(self):
        new = WORKFLOW + "  lint:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo lint\n"
        self.assertEqual(self.found(new), [])

    def test_a_new_workflow_that_only_reads_passes(self):
        self.assertEqual(self.found(WORKFLOW.replace("      pull-requests: write\n", ""), old=None), [])

    def test_a_job_that_gains_a_secret_needs_a_person(self):
        new = WORKFLOW.replace("      - run: echo build", "      - run: echo build\n        env:\n          KEY: ${{ secrets.META_API_KEY }}")
        self.assertEqual(self.found(new), ["job build gains secrets: META_API_KEY"])

    def test_a_secret_a_job_already_had_is_not_a_gain(self):
        old = WORKFLOW.replace("echo build", "echo ${{ secrets.META_API_KEY }}")
        self.assertEqual(self.found(old.replace("echo report", "echo done"), old=old), [])

    def test_every_way_of_reaching_secrets_is_seen(self):
        for text, name in (("${{ secrets['MODEL_API_KEY'] }}", "MODEL_API_KEY"),
                           ("${{ toJSON(secrets) }}", "(every secret)"),
                           ("${{ secrets[matrix.key] }}", "(every secret)")):
            new = WORKFLOW.replace("echo build", "echo " + text)
            self.assertEqual(self.found(new), [f"job build gains secrets: {name}"], text)
        # Uses that name no secret reach all of them; found in review of #278.
        for text in ("${{ join(secrets.*, ' ') }}", "${{ toJSON(secrets.*) }}", "${{ format('{0}', secrets) }}",
                     "${{ secrets }}", "${{ toJSON( secrets ) }}"):
            new = WORKFLOW.replace("echo build", "echo " + text)
            self.assertEqual(self.found(new), ["job build gains secrets: (every secret)"], text)
        guarded = WORKFLOW.replace("    steps:\n      - run: echo build", "    if: secrets != ''\n    steps:\n      - run: echo build")
        self.assertEqual(self.found(guarded), ["job build gains secrets: (every secret)"])
        inherit = WORKFLOW + "  call:\n    uses: ./.github/workflows/x.yml\n    secrets: inherit\n"
        self.assertEqual(self.found(inherit), ["job call gains secrets: (every secret)"])

    def test_the_repository_token_and_a_step_named_secrets_are_not_secrets(self):
        new = WORKFLOW.replace("echo build", "echo ${{ secrets.GITHUB_TOKEN }} ${{ steps.secrets.outputs.x }}")
        self.assertEqual(self.found(new), [])

    def test_the_word_in_a_name_or_a_script_is_not_read_as_a_use_but_is_reported_as_a_word(self):
        new = WORKFLOW.replace("      - run: echo build", "      - name: Check that no secrets leak\n        run: grep -r secrets docs || true")
        jobs, _ = mg.parse_workflow(new)
        self.assertEqual(jobs["build"].secrets, set())
        self.assertEqual(self.found(new), [self.NAMED + "(the word alone)"])
        self.assertEqual(self.found(new.replace("echo report", "echo done"), old=new), [])

    def test_a_secret_after_a_hash_in_a_block_scalar_is_reported(self):
        # Found in review of #278: in a block scalar a "#" is text, and GitHub fills in ${{ }} there.
        cases = {
            "an env value": ("- run: echo hi\n        env:\n          K: |\n            # ${{ secrets.X }}",
                             lambda d: d["jobs"]["a"]["steps"][0]["env"]["K"]),
            "a shell string over two lines": ("- run: |\n          printf '%s' \"\n          # ${{ secrets.X }}\" | base64",
                                              lambda d: d["jobs"]["a"]["steps"][0]["run"]),
            "after a command": ("- run: |\n          echo hi; echo x #${{ secrets.X }}",
                                lambda d: d["jobs"]["a"]["steps"][0]["run"]),
            "a line of its own": ("- run: |\n          echo hi\n          # ${{ secrets.X }}\n          cat \"$0\"",
                                  lambda d: d["jobs"]["a"]["steps"][0]["run"]),
        }
        for label, (step, value) in cases.items():
            new = self.BLOCK.replace("- run: echo hi", step)
            self.assertIn("secrets.X", value(yaml.safe_load(new)), label)  # PyYAML keeps it as text
            self.assertEqual(self.found(new, old=self.BLOCK), [self.NAMED + "X"], label)
            self.assertEqual(self.found(new, old=None), [self.NAMED + "X"], label + ", as a new workflow")
        folded = self.BLOCK.replace("    steps:", "    if: >-\n      true ||\n      # secrets.X\n      false\n    steps:")
        self.assertEqual(yaml.safe_load(folded)["jobs"]["a"]["if"], "true || # secrets.X false")
        self.assertEqual(self.found(folded, old=self.BLOCK), [self.NAMED + "X"])

    def test_a_hidden_use_of_a_secret_the_file_already_names_is_reported(self):
        # Counted, not listed: one more mention of a name the file already has is still a gain.
        old = self.BLOCK + "  b:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo ${{ secrets.X }}\n"
        new = old.replace("- run: echo hi", "- run: |\n          echo hi\n          # ${{ secrets.X }}")
        self.assertEqual(self.found(new, old=old), [self.NAMED + "X"])

    def test_a_new_job_reaches_a_secret_in_the_workflows_own_env(self):
        # Found in review of #278: the workflow's env reaches every job, so a new job gains what it holds.
        old = self.BLOCK.replace("permissions:", "env:\n  K: ${{ secrets.X }}\npermissions:")
        job = "  b:\n    runs-on: ubuntu-24.04\n    permissions:\n      contents: read\n    steps:\n      - run: echo \"$K\" | base64\n"
        self.assertEqual(self.found(old + job, old=old), ["job b gains secrets: X"])
        self.assertEqual(self.found(old.replace("echo hi", "echo hello"), old=old), [])  # an edit to a job that had it
        self.assertEqual(self.found(self.BLOCK + job, old=self.BLOCK), [])  # the same job where the workflow holds none

    ALIAS = "the file gains an alias (*name), which the guard does not follow; a person reads it"

    def test_an_alias_is_reported_not_followed(self):
        # Found in review of #278: an alias gives a new job another job's steps and permissions.
        plain = "on: push\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    permissions:\n      contents: write\n    steps:\n      - run: echo ${{ secrets.X }}\n"
        anchored = plain.replace("permissions:", "permissions: &p").replace("steps:", "steps: &s")
        new = anchored + "  b:\n    runs-on: ubuntu-24.04\n    permissions: *p\n    steps: *s\n"
        b = yaml.safe_load(new)["jobs"]["b"]
        self.assertEqual(b["permissions"], {"contents": "write"})
        self.assertIn("secrets.X", b["steps"][0]["run"])
        self.assertIn(self.ALIAS, self.found(new, old=plain))
        self.assertIn(self.ALIAS, self.found(new, old=anchored))  # the anchors were already there
        for value in ("<<: *defaults", "needs: [*a, *b]", "- *step"):
            self.assertEqual(mg.aliases("x:\n  " + value + "\n"), value.count("*"), value)
        self.assertEqual(mg.aliases("x: |\n  ls *.py *args\n  echo $((2 * 3))\ny: 2 * 3\n"), 0)  # a script, and arithmetic

    def test_an_edit_elsewhere_in_a_workflow_that_has_aliases_passes(self):
        path = ROOT / ".github" / "workflows" / "discovery.yml"
        text = path.read_text(encoding="utf-8")
        self.assertGreater(mg.aliases(text), 0)
        self.assertIn("timeout-minutes: ", text)
        edited = text.replace("timeout-minutes: ", "timeout-minutes:  ", 1)
        self.assertNotEqual(edited, text)
        self.assertEqual(mg.check_workflows([Change(".github/workflows/discovery.yml", text, edited)]), [])

    ODD = "the file gains a line among its keys that is not a plain key, which the guard does not read; a person reads it"

    def test_a_job_keyed_in_a_way_the_reader_does_not_split_is_reported(self):
        # "? b" is a job to YAML; the line reader would give its lines to the job above it.
        new = self.BLOCK + "  ? b\n  :\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n"
        self.assertEqual(sorted(yaml.safe_load(new)["jobs"]), ["a", "b"])
        self.assertEqual(self.found(new, old=self.BLOCK), [self.ODD])
        key = self.BLOCK.replace("    runs-on:", "    ? timeout-minutes\n    : 5\n    runs-on:")
        self.assertEqual(yaml.safe_load(key)["jobs"]["a"]["timeout-minutes"], 5)
        self.assertEqual(self.found(key, old=self.BLOCK), [self.ODD])
        steps_at_the_keys_indent = self.BLOCK.replace("      - run: echo hi", "    - run: echo hi")
        self.assertEqual(self.found(steps_at_the_keys_indent, old=self.BLOCK), [])

    def test_a_permissions_entry_that_is_not_scope_and_level_counts_as_write(self):
        job = "  a:\n"
        for label, block in (("an anchor on the value", "    permissions:\n      contents: &w write\n"),
                             ("a tag", "    permissions:\n      contents: !!str write\n"),
                             ("a block scalar", "    permissions:\n      contents: |-\n        write\n"),
                             ("the value on the next line", "    permissions:\n      contents:\n        write\n")):
            new = self.BLOCK.replace(job, job + block)
            self.assertEqual(yaml.safe_load(new)["jobs"]["a"]["permissions"], {"contents": "write"}, label)
            found = " | ".join(self.found(new, old=self.BLOCK))
            self.assertIn("job a gets wider permissions", found, label)
        # With a write word removed elsewhere, so that the file's count of the word does not rise.
        old = self.BLOCK + "  b:\n    runs-on: ubuntu-24.04\n    permissions:\n      issues: write\n    steps:\n      - run: echo\n"
        new = old.replace("issues: write", "issues: read").replace(job, job + "    permissions:\n      contents: &w write\n")
        self.assertIn("job a gets wider permissions", " | ".join(self.found(new, old=old)))
        flow = self.BLOCK.replace(job, job + "    permissions: {contents: read, issues: write}\n")
        self.assertEqual(self.found(flow, old=self.BLOCK), ["job a gets wider permissions: issues"])
        self.assertEqual(self.found(self.BLOCK.replace(job, job + "    permissions: {contents: read}\n"), old=self.BLOCK), [])

    def test_the_words_are_counted_wherever_they_are(self):
        for label, new, message in (
            ("a step's name", self.BLOCK.replace("- run: echo hi", "- name: Set up the environment\n        run: echo hi"),
             "the file gains the word environment that no job accounts for"),
            ("a key under matrix", self.BLOCK + "    strategy:\n      matrix:\n        include:\n          - environment: unity\n",
             "the file gains the word environment that no job accounts for"),
            ("a write value under another key", self.BLOCK.replace("jobs:", "x-extra:\n  contents: write\njobs:"),
             "the file gains a write permission that no job accounts for"),
            ("id-token in a comment", self.BLOCK.replace("echo hi", "echo hi  # id-token: none"),
             "the file gains the word id-token that no job accounts for"),
        ):
            self.assertEqual(self.found(new, old=self.BLOCK), [message], label)
        script = self.BLOCK.replace("- run: echo hi", "- run: python3 -c \"open('x', 'w').write('y')\"  # rewrite it")
        self.assertEqual(self.found(script, old=self.BLOCK), [])

    def test_no_workflow_in_the_repository_has_a_line_or_a_permissions_block_the_guard_would_not_read(self):
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(mg.odd_lines(text), 0, path.name)
            doc = yaml.safe_load(text)
            jobs, _ = mg.parse_workflow(text)
            for name, job in doc["jobs"].items():
                if job.get("permissions", doc.get("permissions")) != "write-all":
                    self.assertNotEqual(jobs[name].perms, {"*": 2}, f"{path.name}#{name}")

    def test_the_secret_patterns_agree_with_the_test_that_guards_the_protected_environment(self):
        # tests/test_main_only_environment.py names secrets with its own pattern; on today's workflows the two agree.
        from tests import test_main_only_environment as main_only

        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = "\n".join(mg._strip_comment(l) for l in path.read_text(encoding="utf-8").splitlines())
            theirs = {n for n in main_only.secret_refs(text) if n.upper() != "GITHUB_TOKEN"}
            self.assertEqual(mg.secret_names(text) - {"(every secret)"}, theirs, path.name)

    def test_a_secret_in_the_workflows_own_env_needs_a_person(self):
        new = WORKFLOW.replace("permissions:\n  contents: read\njobs:", "env:\n  KEY: ${{ secrets.K }}\npermissions:\n  contents: read\njobs:")
        self.assertEqual(self.found(new), ["the workflow gains secrets: K"])

    def test_an_environment_needs_a_person(self):
        new = WORKFLOW.replace("  build:\n", "  build:\n    environment: main-only\n")
        self.assertEqual(self.found(new), ["job build gains or changes an environment"])
        nested = WORKFLOW.replace("  build:\n", "  build:\n    environment:\n      name: unity\n")
        self.assertEqual(self.found(nested), ["job build gains or changes an environment"])
        self.assertEqual(self.found(new.replace("echo report", "echo x"), old=new), [])
        self.assertEqual(self.found(new.replace("main-only", "unity"), old=new), ["job build gains or changes an environment"])

    def test_pull_request_target_needs_a_person(self):
        self.assertEqual(self.found(WORKFLOW.replace("  pull_request:", "  pull_request_target:")),
                         ["pull_request_target was added"])
        flow = WORKFLOW.replace("on:\n  pull_request:", "on: [push, pull_request_target]")
        self.assertEqual(self.found(flow), ["pull_request_target was added"])
        # The word is counted in the raw text, so a comment that newly holds it is reported too.
        self.assertEqual(self.found(WORKFLOW.replace("echo build", "echo x  # not pull_request_target")),
                         ["pull_request_target was added"])
        self.assertEqual(self.found(WORKFLOW.replace("echo build", "echo x  # not that trigger")), [])

    def test_id_token_write_needs_a_person(self):
        new = WORKFLOW.replace("      pull-requests: write\n", "      pull-requests: write\n      id-token: write\n")
        self.assertEqual(self.found(new), ["job report gains id-token: write", "job report gets wider permissions: id-token"])

    def test_wider_permissions_need_a_person(self):
        self.assertEqual(self.found(WORKFLOW.replace("permissions:\n  contents: read\njobs", "permissions:\n  contents: write\njobs")),
                         ["job build gets wider permissions: contents"])
        self.assertEqual(self.found(WORKFLOW.replace("permissions:\n  contents: read\njobs", "permissions: write-all\njobs")),
                         ["job build gains id-token: write", "job build gets wider permissions: every other scope, contents"])
        more = WORKFLOW.replace("      pull-requests: write\n", "      pull-requests: write\n      issues: write\n")
        self.assertEqual(self.found(more), ["job report gets wider permissions: issues"])

    def test_narrower_permissions_pass(self):
        self.assertEqual(self.found(WORKFLOW.replace("      pull-requests: write\n", "      pull-requests: read\n")), [])
        self.assertEqual(self.found(WORKFLOW.replace("permissions:\n  contents: read\njobs", "permissions: {}\njobs")), [])

    def test_losing_the_permissions_block_needs_a_person(self):
        new = WORKFLOW.replace("permissions:\n  contents: read\njobs", "jobs")
        self.assertEqual(self.found(new), ["job build lost its permissions block, so its token gets the repository default"])

    def test_a_new_job_that_may_write_or_has_no_permissions_needs_a_person(self):
        writes = WORKFLOW + "  post:\n    runs-on: ubuntu-24.04\n    permissions:\n      issues: write\n    steps:\n      - run: echo\n"
        self.assertEqual(self.found(writes), ["new job post may write: issues"])
        bare = "on: push\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo\n"
        self.assertEqual(self.found(bare, old=None),
                         ["new job a has no permissions block, so its token gets the repository default"])

    def test_a_job_written_as_a_flow_mapping_is_reported_not_passed(self):
        # Found in review of #278: PyYAML reads each of these as an ordinary job; the line parser did not.
        base = "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n"
        head = "on: push\npermissions:\n  contents: read\njobs:\n"
        flow = "{runs-on: ubuntu-24.04, environment: unity, permissions: write-all, steps: [{run: echo hi}]}"
        cases = {
            "the job rewritten": head + "  a: " + flow + "\n",
            "a new job beside a block job": base + "  b: " + flow + "\n",
            "the whole map on one line": "on: push\npermissions:\n  contents: read\njobs: {a: {runs-on: ubuntu-24.04, steps: [{run: 'echo ${{ secrets.X }}'}]}}\n",
            "the map over three lines": "on: push\npermissions:\n  contents: read\njobs: {\n  a: {runs-on: ubuntu-24.04, environment: unity, steps: [{run: 'echo ${{ secrets.X }}'}]}\n}\n",
        }
        for label, new in cases.items():
            self.assertIsInstance(yaml.safe_load(new)["jobs"], dict, label)
            found = " | ".join(self.found(new, old=base))
            self.assertIn("flow mapping", found, label)
            if "secrets.X" in new:
                self.assertIn("secrets", found, label)
                self.assertIn("X", found, label)
            if "environment" in new:
                self.assertIn("environment", found, label)
            if "write-all" in new:
                self.assertIn("write permission", found, label)

    BLOCK = "on:\n  pull_request:\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n"
    ESCAPED = "the file gains an escaped character (\\x, \\u or \\U), which the guard does not read; a person reads it"
    OPEN = "the file gains a quoted string that runs over a line, which the guard does not read; a person reads it"

    def test_an_escape_that_spells_a_word_the_guard_looks_for_is_reported_not_passed(self):
        # Found in review of #278: YAML decodes these inside double quotes, so the word is never in the text.
        job = "  a:\n"
        cases = {
            "an environment key": (self.BLOCK.replace(job, job + '    "env\\x69ronment": prod\n'),
                                   lambda d: d["jobs"]["a"]["environment"] == "prod"),
            "a secret": (self.BLOCK.replace("- run: echo hi", '- run: "echo ${{ secr\\x65ts.X }}"'),
                         lambda d: "secrets.X" in d["jobs"]["a"]["steps"][0]["run"]),
            "a write value": (self.BLOCK.replace(job, job + '    permissions:\n      contents: "wr\\x69te"\n'),
                              lambda d: d["jobs"]["a"]["permissions"] == {"contents": "write"}),
            "a permissions key": (self.BLOCK.replace(job, job + '    "perm\\x69ssions":\n      contents: "write"\n'),
                                  lambda d: d["jobs"]["a"]["permissions"] == {"contents": "write"}),
            "id-token": (self.BLOCK.replace(job, job + '    permissions:\n      "id-tok\\x65n": "wr\\x69te"\n'),
                         lambda d: d["jobs"]["a"]["permissions"] == {"id-token": "write"}),
            "the trigger": (self.BLOCK.replace("  pull_request:", '  "pull_request_t\\x61rget":'),
                            lambda d: "pull_request_target" in d[True]),
            "a four-digit escape": (self.BLOCK.replace("- run: echo hi", '- run: "echo ${{ secr\\u0065ts.X }}"'),
                                    lambda d: "secrets.X" in d["jobs"]["a"]["steps"][0]["run"]),
            "an eight-digit escape": (self.BLOCK.replace("- run: echo hi", '- run: "echo ${{ secr\\U00000065ts.X }}"'),
                                      lambda d: "secrets.X" in d["jobs"]["a"]["steps"][0]["run"]),
        }
        for label, (new, means) in cases.items():
            self.assertTrue(means(yaml.safe_load(new)), label)  # PyYAML reads the word the text never spells
            self.assertIn(self.ESCAPED, self.found(new, old=self.BLOCK), label)

    def test_an_escape_the_file_already_had_is_not_a_gain(self):
        # fix-matrix.yml and web-fix.yml strip colour codes in a script with one; editing them must stay possible.
        old = self.BLOCK.replace("- run: echo hi", "- run: |\n          printf '\\x1b[0m'")
        self.assertEqual(self.found(old.replace("ubuntu-24.04", "ubuntu-22.04"), old=old), [])
        self.assertEqual(self.found(old + "      - run: printf '\\x1b[1m'\n", old=old), [self.ESCAPED])
        self.assertEqual(self.found(old, old=None), [self.ESCAPED])

    def test_a_quoted_string_that_runs_over_a_line_is_reported_not_passed(self):
        # A string left open can hold a line the reader takes for a comment, or join a word across a line's end.
        cases = {
            "a word joined by a backslash": '- run: "echo ${{ secr\\\n          ets.X }}"',
            "a line that looks like a comment": '- run: "echo\n        # ${{ secrets.X }}"',
            "the same in single quotes": "- run: 'echo\n        # ${{ secrets.X }}'",
            "after a line that only looks like a block scalar": '- name: x\n          - |\n        run: "echo\n        # ${{ secrets.X }}"',
        }
        for label, step in cases.items():
            new = self.BLOCK.replace("- run: echo hi", step)
            self.assertIn("secrets.X", yaml.safe_load(new)["jobs"]["a"]["steps"][0]["run"], label)
            self.assertIn(self.OPEN, self.found(new, old=self.BLOCK), label)

    def test_quotes_in_a_script_or_closed_on_their_line_are_not_reported(self):
        script = ('- run: |\n          echo "a\n          # b" \'c\n          d\' "e \\\n          f"\n'
                  '      - run: echo "it\'s" # don\'t\n      - name: "a # b \\" c"\n        run: echo it\'s\n'
                  "      - name: 'it''s'\n        run: >-\n          echo \"x\n          y\"")
        new = self.BLOCK.replace("- run: echo hi", script)
        yaml.safe_load(new)
        self.assertEqual(self.found(new, old=self.BLOCK), [])

    def test_no_workflow_in_the_repository_has_a_string_the_guard_would_not_read(self):
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(mg.open_strings(text), 0, path.name)
            # Whatever escapes there are sit in scripts: the parsed file, written back out plainly, says the same.
            jobs, _ = mg.parse_workflow(text)
            for name, job in yaml.safe_load(text)["jobs"].items():
                self.assertEqual(jobs[name].secrets, mg.secret_names(yaml.safe_dump(job, width=10_000)), f"{path.name}#{name}")

    def test_what_the_file_gains_is_reported_even_where_no_job_was_read(self):
        base = "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n"
        self.assertEqual(self.found(base.replace("echo hi", "echo hello"), old=base), [])
        nested = base + "    strategy:\n      matrix:\n        include: [{id-token: write}]\n"
        self.assertEqual(self.found(nested, old=base), ["job a gains id-token: write"])
        hidden = base.replace("jobs:", "x-extra: &p {contents: write}\njobs:")
        self.assertEqual(self.found(hidden, old=base), ["the file gains a write permission that no job accounts for"])

    def test_a_block_job_reports_each_gain_once(self):
        new = WORKFLOW.replace("  build:\n", "  build:\n    environment: main-only\n").replace("echo build", "echo ${{ secrets.K }}")
        self.assertEqual(self.found(new), ["job build gains secrets: K", "job build gains or changes an environment"])

    def test_a_file_outside_the_workflows_folder_is_not_a_workflow(self):
        change = Change("docs/example.yml", None, WORKFLOW.replace("pull_request:", "pull_request_target:"))
        self.assertEqual(mg.check_workflows([change]), [])

    def test_the_parser_agrees_with_pyyaml_on_every_workflow_in_the_repository(self):
        paths = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertGreater(len(paths), 20)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(text)
            jobs, _ = mg.parse_workflow(text)
            self.assertEqual(set(jobs) - {"(workflow)"}, set(doc["jobs"]), path.name)
            for name, job in doc["jobs"].items():
                perms = job.get("permissions", doc.get("permissions"))
                if isinstance(perms, dict):
                    perms = {"*": 0, **{k: {"none": 0, "read": 1, "write": 2}[v] for k, v in perms.items()}}
                elif perms is not None:
                    perms = {"*": {"read-all": 1, "write-all": 2}[perms]}
                self.assertEqual(jobs[name].perms, perms, f"{path.name}#{name}")
                self.assertEqual(bool(jobs[name].environment), bool(job.get("environment")), f"{path.name}#{name}")
                declared = mg.secret_names(yaml.safe_dump(job, width=10_000))
                self.assertEqual(jobs[name].secrets, declared, f"{path.name}#{name}")


class TestsRuleTest(unittest.TestCase):
    OLD = "import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n"

    def test_adding_a_test_passes(self):
        new = self.OLD + "    def test_b(self):\n        self.assertEqual(1, 1)\n"
        self.assertEqual(mg.check_tests([Change("tests/test_x.py", self.OLD, new)], ""), [])

    def test_deleting_a_test_file_fails(self):
        found = mg.check_tests([Change("tests/test_x.py", self.OLD, None)], "")
        self.assertEqual(rules(found), [(CHANGES, "tests", "tests/test_x.py")])

    def test_every_kind_of_skip_fails(self):
        for marker in (SKIP + '("later")', SKIP_IF + '(True, "x")', XFAIL, "        " + SKIP_CALL + '("no display")',
                       "        raise unittest." + "SkipTest" + '("x")', "from unittest import " + "skip",
                       "@pytest.mark." + "skip", "@pytest.mark." + "xfail",
                       # through an alias (import unittest as u), found in review of #278
                       "@u." + "skip" + "('x')", "@u." + "skipIf" + "(True, 'x')", "@u." + "expectedFailure",
                       "@testing.case." + "skipUnless" + "(False, 'x')", "        raise u." + "SkipTest" + "('x')",
                       "test_a = u." + "skip" + "('x')(test_a)",
                       # one name of a parenthesised import on its own line, found in the second review
                       "    " + "skip" + " as later,", "    " + "skipIf" + ",", "    " + "expectedFailure" + ")"):
            new = self.OLD.replace("    def test_a", f"    {marker.strip()}\n    def test_a")
            found = mg.check_tests([Change("tests/test_x.py", self.OLD, new)], "")
            self.assertEqual(rules(found), [(CHANGES, "tests", "tests/test_x.py")], marker)

    def test_moving_a_skip_that_was_already_there_passes(self):
        old = self.OLD.replace("    def test_a", f"    {SKIP}('x')\n    def test_a")
        new = "# a new first line\n" + old.replace("class T", "class Renamed")
        self.assertEqual(mg.check_tests([Change("tests/test_x.py", old, new)], ""), [])

    def test_the_stated_line_in_the_description_allows_it(self):
        change = Change("tests/test_x.py", self.OLD, None)
        self.assertEqual(mg.check_tests([change], "Closes #9\n\nGuard: test change intended (#9)\n"), [])
        for body in ("Guard: test change intended", "guard: test change intended (#9)",
                     "we say: Guard: test change intended (#9)", "Guard: test change intended (#nine)"):
            self.assertEqual(len(mg.check_tests([change], body)), 1, body)

    def test_the_stated_line_hidden_in_an_html_comment_does_not_count(self):
        # A comment does not show on the rendered page, so nobody reading the pull request would see the line.
        change = Change("tests/test_x.py", self.OLD, None)
        for body in ("<!--\nGuard: test change intended (#9)\n-->", "text\n<!-- note\nGuard: test change intended (#9)\n",
                     "<!-- a --> x\n<!--\nGuard: test change intended (#9)\n-->\n"):
            self.assertEqual(len(mg.check_tests([change], body)), 1, body)
        shown = "<!-- fill this in -->\nGuard: test change intended (#9)\n"
        self.assertEqual(mg.check_tests([change], shown), [])

    def test_a_word_that_only_contains_skip_and_a_file_that_is_not_a_test_pass(self):
        new = self.OLD + "    def test_skipping_rope(self):\n        self.assertIn('skip', 'skipped')\n"
        self.assertEqual(mg.check_tests([Change("tests/test_x.py", self.OLD, new)], ""), [])
        self.assertEqual(mg.check_tests([Change("agents/x.py", "a\n", SKIP + "('x')\n")], ""), [])

    def test_a_test_file_outside_the_tests_folder_counts(self):
        found = mg.check_tests([Change("harness/web/test_layout.py", self.OLD, None)], "")
        self.assertEqual(len(found), 1)


class HeldOutTest(unittest.TestCase):
    def test_counts_and_the_repository_name_pass(self):
        new = f"Blind set 3: 5 of 8 flagged.\nrepository: Expectrail/{PRIVATE}\nfresh-ness\n"
        self.assertEqual(mg.check_held_out([Change("bench/discovery/README.md", "", new)]), [])

    def test_naming_the_third_fresh_set_a_fresh_path_or_a_private_path_needs_a_person(self):
        for line in (f"see {FRESH_3} for the entries", "open fresh-" + "2/entry-04.patch", f"cat {PRIVATE}/routes/r1.json"):
            found = mg.check_held_out([Change("agents/x.py", "a\n", "a\n# " + line + "\n")])
            self.assertEqual(rules(found), [(NEEDS_SEAN, "held-out", "agents/x.py")], line)
            self.assertNotIn(line, found[0].message)

    def test_a_doc_that_already_names_them_may_say_more(self):
        old = f"Implementers never read `{FRESH_3}/`.\n"
        self.assertEqual(mg.check_held_out([Change("docs/jit.md", old, old + f"Nor `{FRESH_3}/notes`.\n")]), [])
        self.assertEqual(len(mg.check_held_out([Change("docs/other.md", "x\n", f"x\n`{FRESH_3}/`\n")])), 1)
        self.assertEqual(len(mg.check_held_out([Change("agents/x.py", old, old + f"# {FRESH_3}/b\n")])), 1)

    def test_removing_a_mention_passes(self):
        self.assertEqual(mg.check_held_out([Change("agents/x.py", f"# {FRESH_3}\nb\n", "b\n")]), [])


class NewWorkTest(unittest.TestCase):
    CODE = Change("agents/x.py", "a\n", "b\n")

    def test_code_with_its_row_passes(self):
        self.assertEqual(mg.check_new_work([self.CODE, LOG]), [])

    def test_docs_alone_need_no_row(self):
        self.assertEqual(mg.check_new_work([Change("docs/unity.md", "a\n", "b\n"), Change("README.md", "a\n", "b\n")]), [])

    def test_code_without_a_row_fails(self):
        found = mg.check_new_work([self.CODE])
        self.assertEqual(rules(found), [(CHANGES, "new-work", "docs/new-work.md")])
        self.assertIn("agents/x.py", found[0].message)

    def test_an_edit_to_the_log_that_adds_no_row_does_not_count(self):
        prose = Change("docs/new-work.md", "intro\n", "intro, reworded\n")
        self.assertEqual(len(mg.check_new_work([self.CODE, prose])), 1)

    def test_a_workflow_a_test_and_a_schema_are_code(self):
        for path in (".github/workflows/ci.yml", "tests/test_x.py", "contracts/x.schema.json", ".gitignore"):
            self.assertEqual(len(mg.check_new_work([Change(path, "a\n", "b\n")])), 1, path)


class WholeDiffTest(unittest.TestCase):
    def test_a_harmless_change_has_nothing_to_report(self):
        changes = [Change("agents/x.py", "a\n", "b\n"), Change("tests/test_x.py", None, "import unittest\n"), LOG]
        self.assertEqual(mg.check(changes, ""), [])
        self.assertEqual(mg.labels([]), [])

    def test_reasons_come_one_per_line_with_their_label_first(self):
        changes = [Change("specs/s.json", spec(), spec({"by": "x"})), Change("game/platformer/a.gd", "a\n", "b\n")]
        reasons = mg.check(changes, "")
        self.assertEqual([r.line().split(": ")[:2] for r in reasons],
                         [[NEEDS_SEAN, "approval"], [CHANGES, "game"], [CHANGES, "new-work"]])
        self.assertEqual(mg.labels(reasons), [CHANGES, NEEDS_SEAN])


class GitTest(unittest.TestCase):
    """The command, on a real repository: the diff is taken from where the branch left its base."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.write("agents/x.py", "a\n")
        self.write("docs/new-work.md", "| Date | What | Files |\n")
        self.write("game/platformer/player.gd", "extends Node\n")
        self.write("tests/test_old.py", "import unittest\n")
        self.base = self.commit("base")
        self.git("checkout", "-q", "-b", "work")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.test",
                               "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def write(self, path: str, text: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_guard(self, *extra: str) -> tuple[int, dict]:
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mg.main(["--repo", str(self.repo), "--base", "main", "--head", "work", "--json", *extra])
        return code, json.loads(out.getvalue())

    def test_a_harmless_branch_exits_zero(self):
        self.write("agents/x.py", "b\n")
        self.write("docs/new-work.md", "| Date | What | Files |\n" + ROW)
        self.commit("work")
        code, report = self.run_guard()
        self.assertEqual((code, report["reasons"], report["labels"], report["files"]), (0, [], [], 2))

    def test_a_branch_that_breaks_the_rules_exits_one_and_names_each(self):
        self.write("game/platformer/player.gd", "extends Node2D\n")
        (self.repo / "tests/test_old.py").unlink()
        self.commit("work")
        code, report = self.run_guard()
        self.assertEqual(code, 1)
        self.assertEqual([(r["rule"], r["path"]) for r in report["reasons"]],
                         [("game", "game/platformer/player.gd"), ("tests", "tests/test_old.py"), ("new-work", "docs/new-work.md")])
        self.assertEqual(report["labels"], [CHANGES])

    def test_the_description_comes_from_a_file(self):
        (self.repo / "tests/test_old.py").unlink()
        self.write("docs/new-work.md", "| Date | What | Files |\n" + ROW)
        self.commit("work")
        body = self.repo.parent / (self.repo.name + "-body.md")
        body.write_text("Part of #7\n\nGuard: test change intended (#7)\n", encoding="utf-8")
        self.addCleanup(body.unlink)
        self.assertEqual(self.run_guard()[0], 1)
        self.assertEqual(self.run_guard("--body-file", str(body))[0], 0)

    def test_what_main_gained_since_the_branch_left_is_not_the_branchs_change(self):
        self.write("agents/x.py", "b\n")
        self.write("docs/new-work.md", "| Date | What | Files |\n" + ROW)
        self.commit("work")
        self.git("checkout", "-q", "main")
        self.write("game/platformer/player.gd", "changed on main by a person\n")
        self.commit("main moves")
        self.assertEqual(self.run_guard()[0], 0)

    def test_a_commit_that_does_not_exist_exits_two(self):
        import contextlib
        import io

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = mg.main(["--repo", str(self.repo), "--base", "main", "--head", "no-such-branch"])
        self.assertEqual(code, 2)
        self.assertIn("merge guard: git merge-base", err.getvalue())


class WorkflowFileTest(unittest.TestCase):
    """The job that runs the guard holds nothing a pull request could take."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (ROOT / ".github" / "workflows" / "merge-guard.yml").read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)

    def test_it_runs_on_pull_requests_only_and_reads_only(self):
        self.assertEqual(list(self.doc[True]), ["pull_request"])  # PyYAML reads the key "on" as True
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertNotIn("pull_request_target", self.text)
        for job in self.doc["jobs"].values():
            self.assertNotIn("permissions", job)
            self.assertNotIn("environment", job)

    def test_it_holds_no_secret_and_passes_the_description_as_data(self):
        jobs, _ = mg.parse_workflow(self.text)
        self.assertEqual({name: job.secrets for name, job in jobs.items() if job.secrets}, {})
        step = self.doc["jobs"]["merge-guard"]["steps"][-1]
        self.assertIn("python3 -m tools.merge_guard", step["run"])
        self.assertNotIn("${{", step["run"])  # nothing a pull request wrote is pasted into the shell
        self.assertEqual(step["env"]["MERGE_GUARD_PR_BODY"], "${{ github.event.pull_request.body }}")

    def test_its_checkout_is_pinned_keeps_no_credentials_and_has_the_history(self):
        checkout = self.doc["jobs"]["merge-guard"]["steps"][0]
        self.assertRegex(checkout["uses"], r"^actions/checkout@[0-9a-f]{40}$")
        self.assertEqual(checkout["with"], {"persist-credentials": False, "fetch-depth": 0})

    def test_the_guard_passes_its_own_workflow_as_a_new_file(self):
        change = Change(".github/workflows/merge-guard.yml", None, self.text)
        self.assertEqual(mg.check_workflows([change]) + mg.check_paths([change]), [])

    def test_the_templates_are_there_and_name_the_rules(self):
        work = (ROOT / ".github" / "ISSUE_TEMPLATE" / "work.md").read_text(encoding="utf-8")
        pull = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        for heading in ("**Why.**", "**Build.**", "**Done when.**", "**Depends on.**", "**Start here.**"):
            self.assertIn(heading, work)
        for phrase in ("Part of #", "What was run", "What is left", "docs/new-work.md", "Guard: test change intended (#issue)"):
            self.assertIn(phrase, pull)
        self.assertIsNone(mg.INTENDED.search(pull))  # the template alone does not switch the tests rule off


if __name__ == "__main__":
    unittest.main()
