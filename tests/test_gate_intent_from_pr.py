"""Issue #284, second slice: the gate reads a change's intent from its pull request.

The untrusted verify job reads the declaration from the event file; the trusted comment job reads it
again from the pull request it fetched and refuses a record judged less strictly. Offline: a fake
GitHub API and event files the tests write; no engine, no model."""
from __future__ import annotations

import contextlib
import io
import itertools
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.gate import comment as gc
from expectrail.gate import intent as gi
from expectrail.gate import record as rec
from tests.test_ci_gate import HEAD, REPO, FakeGitHub, GateCase, ctx, head_example, make_repo

FIX_EXAMPLE = REPO / "contracts" / "examples" / "findings-fix-not-demonstrated.json"
ACTION = REPO / ".github" / "actions" / "expectrail-verify" / "action.yml"
VERIFY_WORKFLOW = REPO / ".github" / "workflows" / "expectrail-verify.yml"
COMMENT_WORKFLOW = REPO / ".github" / "workflows" / "expectrail-comment.yml"
STRICT = {"none": 0, "change": 1, "fix": 2}


def intent(labels=(), body=""):
    return gi.declared(list(labels), body).intent


class TheDeclaration(unittest.TestCase):
    def test_nothing_declared_is_none(self):
        self.assertEqual(gi.declared([], ""), gi.Declared("none"))
        self.assertEqual(gi.declared(None, None).intent, "none")
        self.assertEqual(intent(["P0", "agent-pr", "bug"], "Closes #12\n\nFixes the floor."), "none")
        self.assertIn("nothing is declared", gi.declared([], "").words())

    def test_a_label_declares(self):
        for value in ("fix", "change", "none"):
            self.assertEqual(intent([f"intent:{value}"]), value)
            self.assertEqual(intent([{"name": f"intent:{value}", "color": "fff"}]), value)
        self.assertEqual(intent(["Intent:Fix"]), "fix")

    def test_a_line_of_the_description_declares(self):
        for line in ("Expectrail-Intent: fix", "expectrail-intent:fix", "  EXPECTRAIL-INTENT :  change  ",
                     "Expectrail-Intent:\tnone"):
            want = re.search(r"(fix|change|none)", line).group(1)
            self.assertEqual(intent(body=f"Some text.\n{line}\nMore text."), want, line)
        self.assertEqual(intent(body="Expectrail-Intent: fix\r\nrest"), "fix")

    def test_a_line_must_be_the_whole_line(self):
        for body in ("We may add Expectrail-Intent: fix later.", "> Expectrail-Intent: fix",
                     "- Expectrail-Intent: fix", "Expectrail-Intent: fix please"):
            got = intent(body=body)
            # Either not a declaration at all, or (the last: a value that is not one of the three) a fix.
            self.assertIn(got, ("none", "fix"), body)
        self.assertEqual(intent(body="We may add Expectrail-Intent: fix later."), "none")
        self.assertEqual(intent(body="Expectrail-Intent: fix please"), "fix")

    def test_a_value_that_is_not_one_of_the_three_is_a_fix(self):
        for labels, body in ((["intent:bugfix"], ""), (["intent:"], ""), ([], "Expectrail-Intent: maybe"),
                             ([], "Expectrail-Intent:"), ([], "Expectrail-Intent: None!"),
                             (["intent:none", "intent:refactor"], "")):
            self.assertEqual(intent(labels, body), "fix", (labels, body))

    def test_the_strictest_declaration_wins(self):
        self.assertEqual(intent(["intent:none"], "Expectrail-Intent: fix"), "fix")
        self.assertEqual(intent(["intent:fix"], "Expectrail-Intent: none"), "fix")
        self.assertEqual(intent(["intent:none", "intent:change"]), "change")
        found = gi.declared(["intent:none"], "Expectrail-Intent: fix")
        self.assertEqual(found.sources, ("label intent:none", "line Expectrail-Intent: fix"))

    def test_no_declaration_can_make_a_change_less_strict(self):
        """Every combination of up to three declarations: adding one never lowers the intent."""
        pieces = [("label", "intent:fix"), ("label", "intent:change"), ("label", "intent:none"),
                  ("label", "intent:other"), ("line", "Expectrail-Intent: fix"), ("line", "Expectrail-Intent: none"),
                  ("line", "Expectrail-Intent: change"), ("line", "Expectrail-Intent: x"), ("label", "unrelated")]

        def of(chosen):
            labels = [v for k, v in chosen if k == "label"]
            body = "\n".join(v for k, v in chosen if k == "line")
            return STRICT[intent(labels, body)]

        for size in range(0, 3):
            for chosen in itertools.combinations(pieces, size):
                for extra in pieces:
                    if extra not in chosen:
                        self.assertGreaterEqual(of(chosen + (extra,)), of(chosen), (chosen, extra))

    def test_a_linked_bug_is_a_fix(self):
        self.assertEqual(gi.declared(["intent:none"], "", links_bug=True).intent, "fix")

    def test_sources_are_short_and_on_one_line(self):
        found = gi.declared(["intent:" + "x" * 500], "")
        self.assertEqual(found.intent, "fix")
        self.assertLessEqual(len(found.sources[0]), 80)
        many = gi.declared([f"intent:v{n}" for n in range(50)], "")
        self.assertEqual(len(many.sources), 10)

    def test_only_the_first_part_of_a_huge_description_is_read(self):
        self.assertEqual(intent(body="x" * gi.MAX_BODY + "\nExpectrail-Intent: fix"), "none")


class TheEvent(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-intent-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def event(self, doc) -> Path:
        path = self.tmp / "event.json"
        path.write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")
        return path

    def cli(self, path: Path) -> tuple[str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(gi.main(["--event", str(path)]), 0)
        return out.getvalue().strip(), err.getvalue()

    def test_the_pull_request_in_the_event_declares(self):
        path = self.event({"action": "labeled", "pull_request": {"labels": [{"name": "intent:fix"}], "body": None}})
        self.assertEqual(gi.of_event(path).intent, "fix")
        self.assertEqual(self.cli(path)[0], "fix")
        path = self.event({"pull_request": {"labels": [], "body": "Expectrail-Intent: change"}})
        self.assertEqual(self.cli(path)[0], "change")

    def test_another_event_is_none(self):
        self.assertEqual(self.cli(self.event({"ref": "refs/heads/main"}))[0], "none")
        self.assertEqual(self.cli(self.event([1, 2]))[0], "none")

    def test_an_event_that_cannot_be_read_is_a_fix_never_none(self):
        for path in (self.event("{not json"), self.tmp / "missing.json"):
            printed, said = self.cli(path)
            self.assertEqual(printed, "fix")
            self.assertIn("read as a fix", said)

    def test_the_command_prints_one_word_only(self):
        printed, said = self.cli(self.event({"pull_request": {"labels": ["intent:none"], "body": ""}}))
        self.assertEqual(printed, "none")
        self.assertIn("declared none by label intent:none", said)


def fix_record() -> dict:
    doc = json.loads(FIX_EXAMPLE.read_text(encoding="utf-8"))
    doc["pullRequest"] = dict(doc["pullRequest"], number=7, headSha=HEAD)
    return doc


class TheTrustedJob(GateCase):
    def accepted(self) -> dict:
        """A plain accept the gate wrote for pull request 7 with nothing declared."""
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"))
        self.assertEqual((doc["decision"], rec.intent_of(doc)), ("accept", "none"))
        return doc

    def run_with(self, doc: dict, labels=(), body=""):
        folder = self.tmp / "evidence"
        folder.mkdir(exist_ok=True)
        (folder / "findings.json").write_text(json.dumps(doc), encoding="utf-8")
        api = FakeGitHub(pulls=[{"number": 7, "head": {"sha": HEAD, "repo": {"full_name": "owner/game"}},
                                 "base": {"repo": {"full_name": "owner/game"}},
                                 "labels": [{"name": n} for n in labels], "body": body}])
        result = gc.run(api, ctx(), folder)
        return result, api.writes()[0][2]["body"]

    def readable(self, doc):
        try:
            rec.check_record(doc)
        except rec.RecordError as exc:      # the fixture itself must be a record the reader accepts
            self.fail(f"fixture does not read back: {exc}")
        return doc

    def test_an_accept_judged_as_none_is_refused_when_the_pull_request_declares_a_fix(self):
        doc = self.readable(self.accepted())
        for labels, body in ((["intent:fix"], ""), ([], "Text\nExpectrail-Intent: fix\n"), (["intent:typo"], "")):
            result, comment = self.run_with(doc, labels, body)
            self.assertEqual(result["decision"], "needs-review", (labels, body))
            self.assertIn("rule for a fix was not applied", result["problem"])
            self.assertIn("could not be used", comment)
            self.assertNotIn("Expectrail: accept", comment)

    def test_the_same_accept_is_shown_when_nothing_or_change_or_none_is_declared(self):
        doc = self.readable(self.accepted())
        for labels, body in (((), ""), (["intent:none"], ""), (["intent:change"], ""), (["bug", "P0"], "Closes #3")):
            result, comment = self.run_with(doc, labels, body)
            self.assertEqual((result["decision"], result["problem"]), ("accept", None), (labels, body))
            self.assertIn("### Expectrail: accept", comment)

    def test_a_record_judged_as_a_fix_is_shown_whatever_is_declared(self):
        doc = self.readable(fix_record())
        for labels in ((), ["intent:none"], ["intent:fix"]):
            result, comment = self.run_with(doc, labels)
            self.assertIsNone(result["problem"], labels)
            self.assertIn("No check reproduced the reported bug", comment)

    def test_a_reject_judged_as_none_is_still_shown_as_a_reject(self):
        doc = self.readable(head_example())
        self.assertEqual(doc["decision"], "reject")
        result, comment = self.run_with(doc, ["intent:fix"])
        self.assertEqual((result["decision"], result["problem"]), ("reject", None))
        self.assertIn("### Expectrail: reject", comment)

    def test_the_problem_line_is_inert_markdown(self):
        doc = self.readable(self.accepted())
        _result, comment = self.run_with(doc, ["intent:<script>@octocat"])
        self.assertNotIn("<script>", comment)


class TheActionAndWorkflows(unittest.TestCase):
    def test_the_verify_action_reads_the_intent_from_the_pull_request_by_default(self):
        text = ACTION.read_text(encoding="utf-8")
        block = text[text.index("  intent:"):text.index("outputs:")]
        self.assertIn("default: from-pull-request", block)
        self.assertIn('intent="$(python -m expectrail.gate.intent --event "$GITHUB_EVENT_PATH")"', text)
        self.assertIn('args+=(--intent "$intent")', text)
        self.assertIn("fix|change|none|from-pull-request", text)
        # the input reaches the scripts through env only
        uses = [line.strip() for line in text.splitlines() if "inputs.intent" in line]
        self.assertEqual(uses, ["INTENT: ${{ inputs.intent }}"] * 2)

    def test_the_verify_workflow_runs_again_when_a_declaration_changes(self):
        text = VERIFY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize, reopened, labeled, unlabeled, edited]", text)
        self.assertNotIn("pull_request_target", text)
        self.assertIn("permissions:\n  contents: read\n", text)

    def test_the_comment_job_needs_no_new_permission(self):
        text = COMMENT_WORKFLOW.read_text(encoding="utf-8")
        perms = text[text.index("    permissions:"):text.index("    steps:")]
        self.assertEqual(sorted(re.findall(r"^\s{6}([a-z-]+): ([a-z]+)$", perms, re.M)),
                         [("actions", "read"), ("contents", "read"), ("pull-requests", "write")])

    def test_the_comment_module_still_imports_only_the_standard_library_and_the_gate(self):
        text = (REPO / "expectrail" / "gate" / "intent.py").read_text(encoding="utf-8")
        imported = set(re.findall(r"^(?:from|import) ([a-z_.]+)", text, re.M))
        self.assertEqual(imported, {"__future__", "argparse", "json", "re", "sys", "dataclasses", "pathlib"})

    def test_the_intents_are_the_records(self):
        self.assertEqual(gi.INTENTS, rec.INTENTS)


if __name__ == "__main__":
    unittest.main()
