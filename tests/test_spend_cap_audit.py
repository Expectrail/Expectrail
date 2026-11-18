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
from tools.spend_cap_audit import Graph, audit, compare, read_recorded

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

    def test_a_cap_exported_in_the_script_or_written_to_github_env_earlier_is_set(self):
        exported = {"name": "s", "env": KEY, "run": 'export EXPECTRAIL_SPEC_USD_CAP="$CAP"\npython -m expectrail.lazy_entry'}
        self.assertEqual(self.rows([exported]), {})
        earlier = {"name": "e", "run": 'echo "EXPECTRAIL_SPEC_USD_CAP=$CAP" >> "$GITHUB_ENV"'}
        later = {"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"}
        self.assertEqual(self.rows([earlier, later]), {})
        # Written to $GITHUB_ENV in a later step, or in the same step, does not count: the runner
        # applies it from the next step on.
        self.assertIn("s", self.rows([later, earlier]))
        same = {"name": "s", "env": KEY,
                "run": 'echo "EXPECTRAIL_SPEC_USD_CAP=$CAP" >> "$GITHUB_ENV"\npython -m expectrail.lazy_entry'}
        self.assertEqual(self.rows([same])["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

    def test_an_empty_cap_is_not_a_cap(self):
        for value in ("", "''"):
            with self.subTest(value=value):
                got = self.rows([{"name": "s", "env": {**KEY, "EXPECTRAIL_SPEC_USD_CAP": value},
                                  "run": "python -m expectrail.lazy_entry"}])
                self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))
        got = self.rows([{"name": "s", "env": KEY, "run": "export EXPECTRAIL_SPEC_USD_CAP=\npython -m expectrail.lazy_entry"}])
        self.assertEqual(got["s"].missing, ("EXPECTRAIL_SPEC_USD_CAP",))

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

    def test_compare_names_a_new_gap_a_fixed_gap_and_a_changed_cannot_tell(self):
        root = self.repo({"j": job([{"name": "s", "env": KEY, "run": "python -m expectrail.lazy_entry"},
                                    {"name": "t", "env": KEY, "run": 'python -m "$m"'}])})
        rows = audit(root)
        self.assertEqual(compare(rows, {"live.yml::j::s": {"EXPECTRAIL_SPEC_USD_CAP": "unreviewed"},
                                        "live.yml::j::t": {"cannotTell": [rows[1].cannot_tell[0]]}}), [])
        problems = compare(rows, {"live.yml::j::s": {"EXPECTRAIL_MUSE_USD_CAP": "unreviewed"}})
        self.assertTrue(any(p.startswith("new gap: live.yml::j::s") and "EXPECTRAIL_SPEC_USD_CAP" in p for p in problems))
        self.assertTrue(any(p.startswith("fixed: live.yml::j::s") and "EXPECTRAIL_MUSE_USD_CAP" in p for p in problems))
        self.assertTrue(any(p.startswith("cannot tell changed for live.yml::j::t") for p in problems))

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
