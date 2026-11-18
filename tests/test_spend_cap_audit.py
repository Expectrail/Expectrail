"""tools.spend_cap_audit: live workflow steps that may reach a capped sender without its cap (#267).

The synthetic repositories here are written by the tests: a stand-in ``expectrail.spend``, one sender
per role, entry modules that reach them in the ways real code does, and workflows that set or miss the
caps in the ways real workflows do. The last class runs the audit over this repository's own
workflows and holds it to ``tools/spend_cap_gaps.json``. Nothing here runs a workflow, a game or a
model."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools import spend_cap_audit as audit_mod
from tools.spend_cap_audit import Graph, audit, compare, drift, read_recorded

REPO = Path(__file__).resolve().parents[1]

MODULES = {
    "expectrail/__init__.py": "",
    "expectrail/spend.py": "def hold(role, *, live, usd=None):\n    pass\ndef require_cap(role):\n    return 1.0\n",
    # A sender, imported at the top.
    "expectrail/spec_sender.py": "from expectrail.spend import hold\n\ndef send():\n    hold('spec', live=True)\n",
    # A sender through the module, not the name.
    "expectrail/muse_sender.py": "from expectrail import spend\n\ndef send():\n    spend.require_cap('muse')\n",
    # Reaches the spec sender only inside a function, as most real code does.
    "expectrail/lazy_entry.py": "def main():\n    from expectrail import spec_sender\n    spec_sender.send()\n",
    # Starts the muse sender as a child process.
    "expectrail/child_entry.py": "import subprocess, sys\nCMD = [sys.executable, '-m', 'expectrail.muse_sender']\n",
    # Reaches nothing.
    "expectrail/quiet.py": "import json\n",
    # A relative import.
    "expectrail/sub/__init__.py": "",
    "expectrail/sub/rel_entry.py": "from ..spec_sender import send\n",
    # The console script.
    "expectrail/cli.py": "def main():\n    import expectrail.lazy_entry\n",
    "agents/__init__.py": "",
    "agents/sam_observations.py": "KEY_ENV = 'MODEL_API_KEY'\n",
    "agents/glimmer_client.py": "from expectrail.spend import hold\nhold('glimmer', live=True)\n",
    "agents/both.py": "import agents.sam_observations, agents.glimmer_client\n",
    # Calls a function named hold that is not the spend module's.
    "agents/not_spend.py": "def hold(a, b, c):\n    pass\nhold('spec', 1, 2)\n",
    "agents/broken.py": "def (:\n",
    "agents/uses_broken.py": "import agents.broken\n",
    "scripts/run.sh": "#!/bin/sh\npython -m expectrail.lazy_entry\n",
}


def job(steps: list[dict], *, env: dict | None = None, environment="spend") -> dict:
    out: dict = {"runs-on": "ubuntu-24.04", "steps": steps}
    if environment:
        out["environment"] = environment
    if env:
        out["env"] = env
    return out


KEY = {"MODEL_API_KEY": "${{ secrets.MODEL_API_KEY }}"}
SPEC_CAP = {"EXPECTRAIL_SPEC_USD_CAP": "${{ inputs.budget }}"}


def not_passed(row, cap: str) -> bool:
    """The audit did not pass ``cap`` for this step: a gap, or the step cannot be told."""
    return row is not None and (cap in row.missing or bool(row.cannot_tell))


SPEC = "EXPECTRAIL_SPEC_USD_CAP"


class Synthetic(unittest.TestCase):
    def repo(self, jobs: dict, *, wf_env: dict | None = None, extra: dict | None = None) -> Path:
        import yaml

        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
        for rel, text in {**MODULES, **(extra or {})}.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        doc: dict = {"name": "t", "on": "workflow_dispatch", "jobs": jobs}
        if wf_env:
            doc["env"] = wf_env
        (wf / "live.yml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return root

    def rows(self, steps: list[dict], **kw) -> dict:
        root = self.repo({"j": job(steps, env=kw.pop("job_env", None), environment=kw.pop("environment", "spend"))},
                         **kw)
        return {r.step: r for r in audit(root)}

    # ------------------------------------------------------------ what counts as reaching a sender

    def test_a_sender_reached_inside_a_function_is_a_gap(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_a_module_named_as_a_string_for_a_child_process_is_followed(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python3 -m expectrail.child_entry --x"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_MUSE_USD_CAP",))

    def test_a_relative_import_is_followed(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -m expectrail.sub.rel_entry"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_a_module_that_reaches_nothing_is_not_listed(self):
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": "python -m expectrail.quiet"}]), {})

    def test_a_function_called_hold_outside_the_spend_module_is_not_a_sender(self):
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": "python -m agents.not_spend"}]), {})

    def test_the_console_script_is_followed(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "set -e\nexpectrail verify --x"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_inline_python_with_c_and_in_a_command_substitution_is_read(self):
        run = "dest=\"$(python -c 'from expectrail import spec_sender; print(1)')\"\necho \"$dest\""
        got = self.rows([{"name": "s", "env": KEY, "run": run}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_a_here_document_is_read_as_python(self):
        run = "python - \"$X\" <<'PY'\nimport sys\nfrom expectrail.muse_sender import send\nPY\necho done"
        got = self.rows([{"name": "s", "env": KEY, "run": run}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_MUSE_USD_CAP",))

    def test_a_continued_command_line_is_one_command(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -m \\\n  expectrail.lazy_entry \\\n  --out x"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_a_script_path_and_a_shell_script_are_followed(self):
        got = self.rows([{"name": "a", "env": KEY, "run": "python expectrail/lazy_entry.py"},
                         {"name": "b", "env": KEY, "run": "bash scripts/run.sh"}])
        self.assertEqual(got["a"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))
        self.assertEqual(got["b"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_pip_and_a_venv_python_are_not_ours(self):
        run = 'python -m pip install -r r.txt\n"$RUNNER_TEMP/mitm/bin/python" -m pip install mitmproxy'
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": run}]), {})

    # ------------------------------------------------------------ cannot tell is never "no gap"

    def test_a_module_chosen_at_run_time_cannot_be_told(self):
        got = self.rows([{"name": "s", "env": KEY, "run": 'python -m "$module" "${args[@]}"'}])
        self.assertIn("chosen at run time", got["s"].cannot_tell[0])

    def test_unparseable_inline_python_cannot_be_told(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -c 'def (:'"}])
        self.assertIn("cannot parse", got["s"].cannot_tell[0])

    def test_python_from_standard_input_without_a_here_document_cannot_be_told(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "cat x.py | python -"}])
        self.assertIn("standard input", got["s"].cannot_tell[0])

    def test_a_missing_script_cannot_be_told(self):
        got = self.rows([{"name": "a", "env": KEY, "run": "python tools/gone.py"},
                         {"name": "b", "env": KEY, "run": "bash scripts/gone.sh"}])
        self.assertIn("cannot read the script", got["a"].cannot_tell[0])
        self.assertIn("cannot follow the shell script", got["b"].cannot_tell[0])

    def test_an_unreadable_module_on_the_way_cannot_be_told(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -m agents.uses_broken"}])
        self.assertEqual(got["s"].cannot_tell, ("cannot read the module agents.broken",))

    def test_a_shell_line_that_cannot_be_split_cannot_be_told(self):
        got = self.rows([{"name": "s", "env": KEY, "run": "python -m expectrail.quiet 'unterminated"}])
        self.assertIn("cannot read the command", got["s"].cannot_tell[0])

    # ------------------------------------------------------------ where a cap counts as set

    def test_a_cap_in_the_step_job_or_workflow_env_is_set(self):
        step = {"name": "s", "run": "python -m expectrail.lazy_entry"}
        self.assertEqual(self.rows([dict(step, env={**KEY, **SPEC_CAP})]), {})
        self.assertEqual(self.rows([dict(step, env=KEY)], job_env=SPEC_CAP), {})
        self.assertEqual(self.rows([dict(step, env=KEY)], wf_env=SPEC_CAP), {})

    def test_a_cap_written_to_github_env_earlier_is_set(self):
        earlier = {"name": "e", "run": 'echo "EXPECTRAIL_SPEC_USD_CAP=$CAP" >> "$GITHUB_ENV"'}
        later = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        self.assertEqual(self.rows([earlier, later]), {})
        # Written to $GITHUB_ENV in a later step, or in the same step, does not count: the runner
        # applies it from the next step on.
        self.assertIn("s", self.rows([later, earlier]))
        same = {"name": "s", "env": KEY,
                "run": 'echo "EXPECTRAIL_SPEC_USD_CAP=$CAP" >> "$GITHUB_ENV"\npython -m expectrail.lazy_entry'}
        self.assertTrue(not_passed(self.rows([same]).get("s"), SPEC))

    def test_a_script_that_names_a_needed_cap_cannot_be_told_for_it(self):
        # The script's own export is never counted: the order of its commands is not followed.
        exported = {"name": "s", "env": KEY, "run": 'export EXPECTRAIL_SPEC_USD_CAP="$CAP"\npython -m expectrail.lazy_entry'}
        row = self.rows([exported])["s"]
        self.assertEqual(row.missing, ())
        self.assertEqual(len(row.cannot_tell), 1)
        self.assertIn("exports EXPECTRAIL_SPEC_USD_CAP itself", row.cannot_tell[0])
        # Even with the cap in the step's env: the script may remove it.
        unset = {"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "unset EXPECTRAIL_SPEC_USD_CAP\npython -m expectrail.lazy_entry"}
        self.assertIn("names EXPECTRAIL_SPEC_USD_CAP itself", self.rows([unset])["s"].cannot_tell[0])
        # A cap the step does not need is not a reason.
        other = {"name": "s", "env": KEY, "run": "export EXPECTRAIL_TRIAGE_USD_CAP=1\npython -m expectrail.lazy_entry"}
        self.assertEqual(self.rows([other])["s"].cannot_tell, ())

    def test_a_shell_script_that_names_a_needed_cap_cannot_be_told_for_it(self):
        extra = {"scripts/unsets.sh": "unset EXPECTRAIL_SPEC_USD_CAP\npython -m expectrail.lazy_entry\n"}
        got = self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "bash scripts/unsets.sh"}], extra=extra)
        self.assertTrue(not_passed(got.get("s"), SPEC))

    # The merge guard's probes on ae89b5c: a start that may run without its cap is never passed.
    def test_each_ordering_probe_is_not_passed(self):
        C = SPEC
        start = "python -m expectrail.lazy_entry"
        for run, env in ((f"{start}\nexport {C}=5", KEY),
                         (f"{start}; export {C}=5", KEY),
                         (f"export {C}=5\nunset {C}\n{start}", KEY),
                         (f"export {C}=5\nexport -n {C}\n{start}", KEY),
                         (f"export {C}=5\nenv -u {C} {start}", KEY),
                         # With the cap from env:, a start that drops or may drop the environment.
                         (f"unset {C}\n{start}", {**KEY, **SPEC_CAP}),
                         (f"env -u {C} {start}", {**KEY, **SPEC_CAP}),
                         (f"env -i PATH=/usr/bin {start}", {**KEY, **SPEC_CAP}),
                         (f"sudo {start}", {**KEY, **SPEC_CAP}),
                         (f"exec -c {start}", {**KEY, **SPEC_CAP})):
            with self.subTest(run=run):
                self.assertTrue(not_passed(self.rows([{"name": "s", "env": env, "run": run}]).get("s"), C))
        # The probe "exit 0, then export" starts nothing, so nothing in it can send: not listed.
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": f"exit 0\nexport {C}=5"}]), {})

    def test_a_changed_environment_is_named_in_the_reason(self):
        got = self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "sudo -E python -m expectrail.lazy_entry"}])
        self.assertIn("changed environment", got["s"].cannot_tell[0])
        # pip under sudo starts nothing of ours.
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": "sudo python -m pip install x"}]), {})

    def test_a_plain_env_prefix_is_not_a_changed_environment(self):
        run = "env FOO=1 python -m expectrail.lazy_entry"
        self.assertEqual(self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": run}]), {})

    def test_an_empty_cap_is_not_a_cap(self):
        for value in ("", "''"):
            with self.subTest(value=value):
                got = self.rows([{"name": "s", "env": {**KEY, "EXPECTRAIL_SPEC_USD_CAP": value},
                                  "run": "python -m expectrail.lazy_entry"}])
                self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))
        got = self.rows([{"name": "s", "env": KEY, "run": "export EXPECTRAIL_SPEC_USD_CAP=\npython -m expectrail.lazy_entry"}])
        self.assertTrue(not_passed(got.get("s"), SPEC))

    # The merge guard's probes on #623, as whole workflows.
    def test_each_probe_is_a_gap(self):
        for run in ("# EXPECTRAIL_SPEC_USD_CAP=5 later\npython -m expectrail.lazy_entry",
                    "python -m expectrail.lazy_entry --note EXPECTRAIL_SPEC_USD_CAP=1",
                    'echo EXPECTRAIL_SPEC_USD_CAP=5 >> "$GITHUB_ENV"\npython -m expectrail.lazy_entry',
                    "python - <<'PY'\n# EXPECTRAIL_SPEC_USD_CAP=5\nimport expectrail.lazy_entry\nPY"):
            with self.subTest(run=run):
                got = self.rows([{"name": "s", "env": KEY, "run": run}])
                self.assertTrue(not_passed(got.get("s"), SPEC))

    def test_an_unquoted_github_env_write_counts_from_the_next_step(self):
        earlier = {"name": "e", "run": "echo EXPECTRAIL_SPEC_USD_CAP=5 >> $GITHUB_ENV"}
        later = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        self.assertEqual(self.rows([earlier, later]), {})

    # The merge guard's probes after #623 (#627), on the synthetic repository.

    def test_an_empty_step_value_overrides_a_cap_from_an_outer_level(self):
        start = "python -m expectrail.lazy_entry"
        five = {SPEC: "5"}
        for step_value in ("", "''", None):
            for level in ("job", "workflow"):
                with self.subTest(step_value=step_value, level=level):
                    step = {"name": "s", "env": {**KEY, SPEC: step_value}, "run": start}
                    kw = {"job_env": five} if level == "job" else {"wf_env": five}
                    got = self.rows([step], **kw)
                    self.assertTrue(not_passed(got.get("s"), SPEC))
        # An empty job value under a set workflow value, and a set step value over an empty job value.
        got = self.rows([{"name": "s", "env": KEY, "run": start}], job_env={SPEC: ""}, wf_env=five)
        self.assertTrue(not_passed(got.get("s"), SPEC))
        self.assertEqual(self.rows([{"name": "s", "env": {**KEY, SPEC: "5"}, "run": start}], job_env={SPEC: ""}), {})

    def test_an_empty_value_carried_from_an_earlier_step_overrides(self):
        start = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        set_ = {"name": "a", "run": f'echo "{SPEC}=5" >> "$GITHUB_ENV"'}
        empty = {"name": "b", "run": f'echo "{SPEC}=" >> "$GITHUB_ENV"'}
        self.assertTrue(not_passed(self.rows([set_, empty, start]).get("s"), SPEC))
        # Over a cap from the job's env, too.
        self.assertTrue(not_passed(self.rows([empty, start], job_env={SPEC: "5"}).get("s"), SPEC))
        # A later sure write sets it again.
        self.assertEqual(self.rows([empty, set_, start]), {})

    def test_a_github_env_write_the_audit_cannot_read_makes_the_cap_cannot_tell(self):
        start = {"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "python -m expectrail.lazy_entry"}
        for run in (f'printf "{SPEC}=\\n" >> "$GITHUB_ENV"',
                    f'echo "{SPEC}=" | tee -a "$GITHUB_ENV"',
                    f'{{ echo "{SPEC}="; }} >> "$GITHUB_ENV"',
                    f'if true; then echo "{SPEC}=" >> "$GITHUB_ENV"; fi',
                    f'false || echo "{SPEC}=" >> "$GITHUB_ENV"',
                    f'exec >> "$GITHUB_ENV"\necho "{SPEC}="',
                    f'echo "{SPEC}<<EOF" >> "$GITHUB_ENV"\necho >> "$GITHUB_ENV"\necho EOF >> "$GITHUB_ENV"',
                    f'echo "{SPEC}=\'unterminated >> "$GITHUB_ENV"'):
            with self.subTest(run=run):
                row = self.rows([{"name": "w", "run": run}, start]).get("s")
                self.assertTrue(not_passed(row, SPEC))
        # The reason names the earlier step.
        row = self.rows([{"name": "w", "run": f'echo "{SPEC}=" | tee -a "$GITHUB_ENV"'}, start])["s"]
        self.assertTrue(any("'w'" in why and SPEC in why for why in row.cannot_tell), row.cannot_tell)

    def test_a_here_document_write_in_either_order_is_read(self):
        start = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        for run in (f"cat >> \"$GITHUB_ENV\" <<EOF\n{SPEC}=5\nEOF", f"cat <<EOF >> \"$GITHUB_ENV\"\n{SPEC}=5\nEOF"):
            with self.subTest(run=run):
                self.assertEqual(self.rows([{"name": "e", "run": run}, start]), {})
        # A truncating write is not read as sure.
        got = self.rows([{"name": "e", "run": f'echo "{SPEC}=5" > "$GITHUB_ENV"'}, start])
        self.assertTrue(not_passed(got.get("s"), SPEC))

    def test_a_local_action_or_one_of_our_modules_that_writes_github_env_is_read(self):
        import yaml

        start = {"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "python -m expectrail.lazy_entry"}
        action = {"name": "a", "runs": {"using": "composite", "steps": [
            {"shell": "bash", "run": f'echo "{SPEC}=" >> "$GITHUB_ENV"'}]}}
        extra = {".github/actions/empties/action.yml": yaml.safe_dump(action)}
        got = self.rows([{"name": "a", "uses": "./.github/actions/empties"}, start], extra=extra)
        self.assertTrue(not_passed(got.get("s"), SPEC))
        # A local action that writes other names leaves the cap set.
        quiet = {"name": "a", "runs": {"using": "composite", "steps": [
            {"shell": "bash", "run": 'echo "GODOT=/opt/godot" >> "$GITHUB_ENV"'}]}}
        extra = {".github/actions/quiet/action.yml": yaml.safe_dump(quiet)}
        self.assertEqual(self.rows([{"name": "a", "uses": "./.github/actions/quiet"}, start], extra=extra), {})
        # A missing local action cannot be read.
        got = self.rows([{"name": "a", "uses": "./.github/actions/missing"}, start])
        self.assertTrue(not_passed(got.get("s"), SPEC))
        # One of our modules that names GITHUB_ENV, started by an earlier step.
        extra = {"expectrail/writes_env.py": "import os\nopen(os.environ['GITHUB_ENV'], 'a').write('X=1')\n"}
        got = self.rows([{"name": "w", "run": "python -m expectrail.writes_env"}, start], extra=extra)
        self.assertTrue(not_passed(got.get("s"), SPEC))

    def test_a_carried_cap_from_a_step_that_may_not_run_does_not_count(self):
        start = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        for extra in ({"if": "github.event_name == 'push'"}, {"continue-on-error": True}):
            with self.subTest(extra=extra):
                earlier = {"name": "e", "run": f'echo "{SPEC}=5" >> "$GITHUB_ENV"', **extra}
                self.assertTrue(not_passed(self.rows([earlier, start]).get("s"), SPEC))

    def test_a_start_inside_a_shell_command_string_is_seen(self):
        for run in ("bash -c 'python -m expectrail.lazy_entry'",
                    'sh -c "python -m expectrail.lazy_entry"',
                    "bash -ec 'cd . && python -m expectrail.lazy_entry'",
                    "bash -e -c 'python -m expectrail.lazy_entry'",
                    "bash -e scripts/run.sh",
                    "/bin/bash -c 'bash -c \"python -m expectrail.lazy_entry\"'"):
            with self.subTest(run=run):
                got = self.rows([{"name": "s", "env": KEY, "run": run}])
                self.assertEqual(got["s"].missing, (SPEC,))
        # With its cap, it is not listed.
        self.assertEqual(self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP},
                                     "run": "bash -c 'python -m expectrail.lazy_entry'"}]), {})
        # A cap named inside the string is named by the script.
        got = self.rows([{"name": "s", "env": KEY,
                          "run": f"bash -c 'export {SPEC}=5; python -m expectrail.lazy_entry'"}])
        self.assertTrue(not_passed(got.get("s"), SPEC))
        # Under a changed environment.
        got = self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP},
                          "run": "sudo bash -c 'python -m expectrail.lazy_entry'"}])
        self.assertIn("changed environment", " ".join(got["s"].cannot_tell))

    # The merge guard's probes on 3aba1bc (#629): a shell name is never "nothing here".
    def test_a_shell_after_a_command_with_options_is_still_read(self):
        extra = {"scripts/x.sh": "python -m expectrail.lazy_entry\n"}
        for run in ("bash scripts/x.sh",
                    "nice -n 5 bash scripts/x.sh",
                    "timeout -s KILL 10 bash scripts/x.sh",
                    "echo a | xargs -n1 bash scripts/x.sh",
                    "ionice -c 3 sh scripts/x.sh",
                    "sudo -u x bash scripts/x.sh",
                    "nice -n 5 bash -c 'python -m expectrail.lazy_entry'"):
            with self.subTest(run=run):
                got = self.rows([{"name": "s", "env": KEY, "run": run}], extra=extra)
                self.assertTrue(not_passed(got.get("s"), SPEC), got)
        # With the cap, xargs and sudo -u are still not passed.
        for run in ("echo a | xargs -n1 bash scripts/x.sh", "sudo -u x bash scripts/x.sh"):
            with self.subTest(run=run):
                got = self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": run}], extra=extra)
                self.assertTrue(got.get("s") is not None and got["s"].cannot_tell, got)

    def test_a_command_string_the_audit_cannot_read_cannot_be_told(self):
        for run in ("eval 'python -m expectrail.quiet'",
                    'eval "$CMD"',
                    "echo expectrail.lazy_entry | xargs python -m",
                    "echo x | xargs -I{} python -m expectrail.quiet {}",
                    "bash -c \"$SCRIPT\"",
                    "bash -c",
                    "bash \"$SCRIPT_PATH\"",
                    "bash scripts/missing.sh"):
            with self.subTest(run=run):
                got = self.rows([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": run}])
                self.assertTrue(got.get("s") is not None and got["s"].cannot_tell, got)
        # A shell that only runs a command with no Python is not listed.
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": "bash -c 'echo hi'"}]), {})

    # ------------------------------------------------------------ only steps that can send

    def test_a_step_with_no_model_key_is_not_listed(self):
        self.assertEqual(self.rows([{"name": "s", "run": "python -m expectrail.lazy_entry"}]), {})

    def test_a_step_with_no_model_key_is_not_listed_even_when_it_cannot_be_told(self):
        self.assertEqual(self.rows([{"name": "s", "run": 'python -m "$module"'}]), {})

    def test_a_job_with_no_protected_environment_is_not_listed(self):
        self.assertEqual(self.rows([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}],
                                   environment=None), {})

    def test_a_role_is_listed_only_when_the_step_holds_a_key_that_role_can_use(self):
        run = "python -m agents.both"
        vision_key = self.rows([{"name": "s", "env": KEY, "run": run}])
        self.assertEqual(vision_key["s"].missing, ("EXPECTRAIL_SAM_USD_CAP",))
        glimmer_key = self.rows([{"name": "s", "env": {"EXPECTRAIL_GLIMMER_API_KEY": "${{ secrets.G }}"}, "run": run}])
        self.assertEqual(glimmer_key["s"].missing, ("EXPECTRAIL_GLIMMER_USD_CAP",))
        provider_key = self.rows([{"name": "s", "env": {"ANTHROPIC_API_KEY": "${{ secrets.A }}"},
                                   "run": "python -m expectrail.lazy_entry"}])
        self.assertEqual(provider_key["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))
        role_key = self.rows([{"name": "s", "env": {"EXPECTRAIL_SPEC_API_KEY": "${{ secrets.S }}"},
                               "run": "python -m expectrail.lazy_entry"}])
        self.assertEqual(role_key["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    # ------------------------------------------------------------ the recorded list

    def test_compare_names_a_new_step_and_a_fixed_step(self):
        root = self.repo({"j": job([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"},
                                    {"name": "t", "env": KEY, "run": 'python -m "$m"'}])})
        rows = audit(root)
        self.assertEqual(compare(rows, {"live.yml::j::s": {"EXPECTRAIL_SPEC_USD_CAP": "unreviewed"},
                                        "live.yml::j::t": {"cannotTell": [rows[1].cannot_tell[0]]}}), [])
        problems = compare(rows, {"live.yml::j::s": {"EXPECTRAIL_SPEC_USD_CAP": "unreviewed"},
                                  "live.yml::j::gone": {"EXPECTRAIL_SPEC_USD_CAP": "unreviewed"}})
        self.assertEqual([p.split(":")[0] for p in problems], ["new step", "fixed"])
        self.assertIn("live.yml::j::t", problems[0])
        self.assertIn("live.yml::j::gone", problems[1])

    def test_a_listed_step_whose_caps_or_reasons_move_is_a_note_not_a_failure(self):
        root = self.repo({"j": job([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}])})
        rows = audit(root)
        recorded = {"live.yml::j::s": {"EXPECTRAIL_MUSE_USD_CAP": "unreviewed", "cannotTell": ["old"]}}
        self.assertEqual(compare(rows, recorded), [])
        notes = drift(rows, recorded)
        self.assertTrue(any("may now also miss EXPECTRAIL_SPEC_USD_CAP" in n for n in notes))
        self.assertTrue(any("no longer misses EXPECTRAIL_MUSE_USD_CAP" in n for n in notes))
        self.assertTrue(any("cannot tell: found [], listed ['old']" in n for n in notes))

    def test_the_recorded_list_is_read_strictly(self):
        bad = [[], {"a::b": {}}, {"w::j::s": {"EXPECTRAIL_NOPE_USD_CAP": "unreviewed"}},
               {"w::j::s": {"EXPECTRAIL_SPEC_USD_CAP": ""}}, {"w::j::s": {"cannotTell": "x"}}]
        for doc in bad:
            with self.subTest(doc=doc):
                path = Path(tempfile.mkdtemp()) / "gaps.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_recorded(path)

    def test_main_exits_1_on_a_gap_and_0_when_there_is_none(self):
        gap = self.repo({"j": job([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}])})
        clean = self.repo({"j": job([{"name": "s", "env": {**KEY, **SPEC_CAP}, "run": "python -m expectrail.lazy_entry"}])})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(audit_mod.main(["--root", str(gap)]), 1)
            self.assertEqual(audit_mod.main(["--root", str(clean)]), 0)
        self.assertIn("GAP  live.yml::j::s: may reach a sender with no EXPECTRAIL_SPEC_USD_CAP", out.getvalue())

    def test_check_with_an_unreadable_list_cannot_tell(self):
        root = self.repo({"j": job([])})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(audit_mod.main(["--root", str(root), "--check"]), 1)
        self.assertIn("cannot tell", out.getvalue())


class HeldToTheCode(unittest.TestCase):
    """The audit's tables are copies; these hold them to what the senders read."""

    def test_cap_names_match_expectrail_spend(self):
        from expectrail import spend

        self.assertEqual(audit_mod.CAP_ENV, spend.CAP_ENV)

    def test_role_keys_match_the_senders(self):
        from agents import glimmer_client, sam_observations

        self.assertEqual(audit_mod.ROLE_KEYS["vision"], {sam_observations.KEY_ENV})
        self.assertEqual(audit_mod.ROLE_KEYS["glimmer"], set(glimmer_client.KEY_ENVS))

    def test_provider_keys_cover_every_provider_key(self):
        from expectrail import providers

        keys = {k for spec in providers.PROVIDER_DEFAULTS.values() for k in spec["key_envs"]}
        self.assertLessEqual(keys, audit_mod.PROVIDER_KEYS)

    def test_every_known_sender_is_found(self):
        graph = Graph.build(REPO)
        known = {"expectrail.spec_writer": "spec", "expectrail.providers": "spec", "expectrail.jit.ingest": "spec",
                 "agents.feedback": "spec", "expectrail.repair": "muse", "expectrail.fixer_budget": "muse",
                 "agents.sandbox": "muse", "agents.glimmer_client": "glimmer", "agents.triage": "triage",
                 "agents.sam_observations": "vision"}
        for module, role in known.items():
            with self.subTest(module=module):
                self.assertIn(role, graph.senders.get(module, set()))
        self.assertFalse([m for m in graph.senders if m.startswith("tests.")])
        self.assertNotIn("tools.playtester.producer", graph.senders)


class CapsReadAsCommands(unittest.TestCase):
    """The merge guard's review of #623: a cap counts as set only from a parsed command that surely
    exports it in the step's own shell, never from text that merely looks like ``NAME=value``."""

    CAP = "EXPECTRAIL_SPEC_USD_CAP"

    def caps(self, script: str) -> set[str]:
        return audit_mod.caps_set_in_script(textwrap.dedent(script))

    def carried(self, script: str) -> set[str]:
        return audit_mod.caps_to_github_env(textwrap.dedent(script))

    # The guard's three probes, and the comment inside a here-document.
    def test_a_comment_is_not_a_cap(self):
        self.assertEqual(self.caps("# EXPECTRAIL_SPEC_USD_CAP=5 later\npython -m x"), set())
        self.assertEqual(self.caps("python -m x  # EXPECTRAIL_SPEC_USD_CAP=5"), set())

    def test_an_argument_is_not_a_cap(self):
        self.assertEqual(self.caps("python -m x --note EXPECTRAIL_SPEC_USD_CAP=1"), set())
        self.assertEqual(self.caps("echo export EXPECTRAIL_SPEC_USD_CAP=1"), set())

    def test_a_github_env_write_is_not_a_cap_in_its_own_step(self):
        for line in ('echo EXPECTRAIL_SPEC_USD_CAP=5 >> "$GITHUB_ENV"',
                     'echo EXPECTRAIL_SPEC_USD_CAP=5 >>$GITHUB_ENV',
                     'echo "EXPECTRAIL_SPEC_USD_CAP=$CAP" >> "${GITHUB_ENV}"',
                     'cat >> "$GITHUB_ENV" <<EOF\nEXPECTRAIL_SPEC_USD_CAP=5\nEOF'):
            with self.subTest(line=line):
                self.assertEqual(self.caps(line + "\npython -m x"), set())
                self.assertEqual(self.carried(line), {self.CAP})

    def test_a_here_document_body_is_not_a_cap(self):
        self.assertEqual(self.caps("python - <<'PY'\n# EXPECTRAIL_SPEC_USD_CAP=5\nEXPECTRAIL_SPEC_USD_CAP=5\nPY"), set())
        self.assertEqual(self.caps("cat > notes.txt <<EOF\nexport EXPECTRAIL_SPEC_USD_CAP=5\nEOF"), set())

    # The rest of the class: whatever does not surely export does not count.
    def test_a_quoted_operator_does_not_start_a_command(self):
        self.assertEqual(self.caps("echo ';' export EXPECTRAIL_SPEC_USD_CAP=1"), set())
        self.assertEqual(self.caps('echo "&&" export EXPECTRAIL_SPEC_USD_CAP=1'), set())
        self.assertEqual(self.caps(r"echo \; export EXPECTRAIL_SPEC_USD_CAP=1"), set())

    def test_a_prefix_or_a_bare_assignment_is_not_a_cap(self):
        self.assertEqual(self.caps("EXPECTRAIL_SPEC_USD_CAP=1 true\npython -m x"), set())
        self.assertEqual(self.caps("EXPECTRAIL_SPEC_USD_CAP=1 python -m x"), set())
        self.assertEqual(self.caps("EXPECTRAIL_SPEC_USD_CAP=1\npython -m x"), set())

    def test_an_export_that_might_not_run_is_not_a_cap(self):
        for script in ('[[ -n "$X" ]] && export EXPECTRAIL_SPEC_USD_CAP=1',
                       'false || export EXPECTRAIL_SPEC_USD_CAP=1',
                       'export EXPECTRAIL_SPEC_USD_CAP=1 | cat',
                       'export EXPECTRAIL_SPEC_USD_CAP=1 &',
                       '( export EXPECTRAIL_SPEC_USD_CAP=1 )',
                       '(export EXPECTRAIL_SPEC_USD_CAP=1); python -m x',
                       'if [[ -n "$X" ]]; then\n  export EXPECTRAIL_SPEC_USD_CAP=1\nfi',
                       'for x in a; do export EXPECTRAIL_SPEC_USD_CAP=1; done',
                       'f() {\n  export EXPECTRAIL_SPEC_USD_CAP=1\n}',
                       'export EXPECTRAIL_SPEC_USD_CAP=1 > /dev/null',
                       '"export" EXPECTRAIL_SPEC_USD_CAP=1',
                       'export -n EXPECTRAIL_SPEC_USD_CAP=1',
                       'declare EXPECTRAIL_SPEC_USD_CAP=1',
                       'declare +x EXPECTRAIL_SPEC_USD_CAP=1'):
            with self.subTest(script=script):
                self.assertEqual(self.caps(script), set())

    def test_an_unreadable_or_unbalanced_script_sets_nothing(self):
        self.assertEqual(self.caps("export EXPECTRAIL_SPEC_USD_CAP=1\necho 'unterminated"), set())
        self.assertEqual(self.caps("export EXPECTRAIL_SPEC_USD_CAP=1\nfi"), set())
        self.assertEqual(self.caps("export EXPECTRAIL_SPEC_USD_CAP=1\nif true; then"), set())

    def test_an_empty_export_unsets(self):
        self.assertEqual(self.caps("export EXPECTRAIL_SPEC_USD_CAP=\npython -m x"), set())
        self.assertEqual(self.caps('export EXPECTRAIL_SPEC_USD_CAP=""\npython -m x'), set())
        self.assertEqual(self.caps("export EXPECTRAIL_SPEC_USD_CAP=1\nexport EXPECTRAIL_SPEC_USD_CAP="), set())

    def test_a_plain_export_counts(self):
        for script in ('export EXPECTRAIL_SPEC_USD_CAP="$CAP"',
                       "export EXPECTRAIL_SPEC_USD_CAP=1 OTHER=2",
                       "declare -x EXPECTRAIL_SPEC_USD_CAP=1",
                       "EXPECTRAIL_SPEC_USD_CAP=1\nexport EXPECTRAIL_SPEC_USD_CAP",
                       "set -e; export EXPECTRAIL_SPEC_USD_CAP=1",
                       # The forms the real workflows use around their exports still count.
                       '[[ "$CAP" =~ ^[0-9]+(\\.[0-9]{1,2})?$ ]] || { echo "::error::bad"; exit 1; }\n'
                       'args=(--a "$X" --b)\nexport EXPECTRAIL_SPEC_USD_CAP="$CAP"',
                       'if [[ ! -d x ]]; then\n  exit 0\nfi\nleft=$(python -m y)\nexport EXPECTRAIL_SPEC_USD_CAP="$left"',
                       'python - "$CAP" <<\'PY\'\nimport sys\nPY\nexport EXPECTRAIL_SPEC_USD_CAP="$CAP"'):
            with self.subTest(script=script):
                self.assertEqual(self.caps(script), {self.CAP})

    def test_a_github_env_write_that_might_not_run_is_not_carried(self):
        self.assertEqual(self.carried('[[ -n "$X" ]] && echo "EXPECTRAIL_SPEC_USD_CAP=1" >> "$GITHUB_ENV"'), set())
        self.assertEqual(self.carried('echo "EXPECTRAIL_SPEC_USD_CAP=1" >> "$OTHER"'), set())
        self.assertEqual(self.carried('echo "EXPECTRAIL_SPEC_USD_CAP=" >> "$GITHUB_ENV"'), set())

    def test_model_keys_are_still_found_loosely(self):
        # Keys over-report on purpose: finding a key that is not there only audits one more step.
        self.assertIn("MODEL_API_KEY", audit_mod.names_in_script("FOO=1 MODEL_API_KEY=x python -m y"))


class ThisRepository(unittest.TestCase):
    def test_the_workflows_gaps_are_exactly_the_recorded_list(self):
        problems = compare(audit(REPO), read_recorded())
        self.assertEqual(problems, [], "\n".join(problems))

    def test_every_listed_cap_says_unreviewed_or_what_was_found(self):
        for key, entry in read_recorded().items():
            for cap, why in entry.items():
                if cap != "cannotTell":
                    self.assertTrue(why == "unreviewed" or why.startswith(("not sent: ", "open: ")), (key, cap, why))


if __name__ == "__main__":
    unittest.main()
