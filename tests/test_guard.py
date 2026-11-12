"""Fixer guard: the Muse Code PreToolUse hook, its installer, and its wiring into run_fixer."""
from __future__ import annotations

import ast
import json
import os
import pty
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agents import guard
from agents.fixer import run_fixer
from agents.orchestrator import build_repair_request
from agents.patchutil import path_allowed
from harness.run import REPO
from expectrail.contracts import load

HOOK = REPO / "agents" / "fixer_guard_hook.py"
EDITABLE = ["player/**", "level/**"]


def _request():
    return build_repair_request(
        request_id="rr-guard",
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png"],
    )


def call_hook(work: Path, payload) -> tuple[int, dict | None, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run([sys.executable, str(work / guard.HOOK_REL)], input=raw, capture_output=True,
                          text=True, cwd=str(work), timeout=30)
    out = proc.stdout.strip()
    return proc.returncode, (json.loads(out) if out else None), proc.stderr


def denied(answer: dict | None) -> bool:
    return bool(answer) and answer["hookSpecificOutput"]["permissionDecision"] == "deny"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "fixer-work"
        (self.work / "player").mkdir(parents=True)
        (self.work / "player" / "player.tscn").write_text("x\n")
        self.installed = guard.install_guard(self.work, EDITABLE, root_as_muse_sees_it=str(self.work))

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, name, **tool_input):
        return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input,
                "tool_use_id": f"t-{name}", "cwd": str(self.work), "session_id": "s"}

    def test_hooks_json_has_only_the_documented_keys(self):
        cfg = json.loads((self.work / ".muse" / "hooks.json").read_text())
        self.assertEqual(list(cfg), ["hooks"])
        self.assertEqual(list(cfg["hooks"]), ["PreToolUse"])
        (group,) = cfg["hooks"]["PreToolUse"]
        self.assertEqual(list(group), ["hooks"])  # no matcher: every tool goes through the guard
        (handler,) = group["hooks"]
        self.assertEqual(set(handler), {"type", "command", "timeout"})
        self.assertEqual(handler["type"], "command")
        self.assertTrue(handler["command"].endswith(f"{self.work}/{guard.HOOK_REL}"))
        bwrap = guard.hooks_config("/fixer")["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(bwrap, "python3 /fixer/.muse/hooks/fixer_guard.py")

    def test_writes_inside_editable_globs_pass(self):
        for payload in (self.tool("write_file", path="player/player.tscn", content="y"),
                        self.tool("edit_file", path=str(self.work / "level" / "new.gd"), find="a", replace="b")):
            code, answer, _ = call_hook(self.work, payload)
            self.assertEqual(code, 0)
            self.assertEqual(answer, {})

    def test_writes_outside_are_denied(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (self.work / "player" / "escape").symlink_to(outside)
        cases = {
            "specs/player-stays-above-ground.json": "outside the editable files",
            "../verifier-host/key": "outside the fixer workspace",
            "/etc/passwd": "outside the fixer workspace",
            "player/escape/x.gd": "outside the fixer workspace",
            ".muse/fixer-guard.json": "off limits",
            ".fixer-guard-log/fixer-guard.jsonl": "off limits",
            "player/../project.godot": "outside the editable files",
        }
        for path, why in cases.items():
            with self.subTest(path=path):
                code, answer, _ = call_hook(self.work, self.tool("write_file", path=path, content="z"))
                self.assertEqual(code, 0)
                self.assertTrue(denied(answer))
                self.assertIn(why, answer["hookSpecificOutput"]["permissionDecisionReason"])

    def test_web_tools_denied_reads_and_shell_logged(self):
        self.assertTrue(denied(call_hook(self.work, self.tool("web_fetch", url="https://example.com"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("web_search", query="answer"))[1]))
        self.assertEqual(call_hook(self.work, self.tool("read_file", path="specs/x.json"))[1], {})
        self.assertEqual(call_hook(self.work, self.tool("bash", command="cat player/player.tscn"))[1], {})
        # an unknown tool that names a file under any common key is judged as a write
        self.assertTrue(denied(call_hook(self.work, self.tool("apply_patch", path="specs/x.json"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("create_file", file_path="specs/x.json"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("multi_write", paths=["player/a.gd", "x.cfg"]))[1]))
        self.assertEqual(call_hook(self.work, self.tool("create_file", file_path="player/new.gd"))[1], {})
        # an unknown tool with no file key passes, and the report names it
        self.assertEqual(call_hook(self.work, self.tool("apply_diff", input="*** patch"))[1], {})
        entries = guard.read_log(self.work / guard.LOG_REL)
        self.assertEqual(len(entries), 9)
        self.assertEqual(entries[3]["command"], "cat player/player.tscn")
        summary = guard.summarize(entries, self.installed)
        self.assertEqual(summary["unknownTools"], ["apply_diff", "apply_patch", "create_file", "multi_write"])

    def test_fails_closed(self):
        code, answer, _ = call_hook(self.work, "not json")
        self.assertEqual(code, 0)
        self.assertTrue(denied(answer))
        self.assertTrue(denied(call_hook(self.work, self.tool("write_file", content="no path"))[1]))
        (self.work / guard.POLICY_REL).unlink()
        answer = call_hook(self.work, self.tool("write_file", path="player/player.tscn", content="y"))[1]
        self.assertTrue(denied(answer))
        self.assertIn("policy missing", answer["hookSpecificOutput"]["permissionDecisionReason"])

    def test_collect_summarizes_the_log(self):
        call_hook(self.work, self.tool("write_file", path="player/player.tscn", content="y"))
        call_hook(self.work, self.tool("write_file", path="specs/a.json", content="y"))
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        summary = guard.collect_guard(self.work, out, self.installed)
        self.assertEqual((summary["installed"], summary["loaded"], summary["calls"]), (True, True, 2))
        self.assertEqual([b["rel"] for b in summary["blocked"]], ["specs/a.json"])
        self.assertTrue((out / "guard.json").is_file())
        self.assertTrue((out / "guard-log.jsonl").is_file())
        empty = Path(self.tmp.name) / "empty"
        (empty / ".muse").mkdir(parents=True)
        self.assertFalse(guard.collect_guard(empty, out, self.installed)["loaded"])


class BwrapGuardTest(unittest.TestCase):
    """Under bubblewrap the agent's shell cannot rewrite the guard. Runs where bwrap works (CI's
    agents-sandbox job sets EXPECTRAIL_REQUIRE_BWRAP=1 so a skip there is a failure)."""

    def test_bwrap_mounts_muse_read_only(self):
        from agents.sandbox import _bwrap_cmd

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "fixer-work"
            (work / "player").mkdir(parents=True)
            guard.install_guard(work, EDITABLE, root_as_muse_sees_it="/fixer")
            cmd = _bwrap_cmd(work, ["true"], network=False)
            i = cmd.index("--ro-bind")
            self.assertEqual(cmd[i:i + 3], ["--ro-bind", str((work / ".muse").resolve()), "/fixer/.muse"])
            self.assertLess(cmd.index("--bind"), i)  # the read-only mount lands on top of the workspace

    def test_bwrap_never_mounts_the_hosts_local_dirs(self):
        # Muse Code 1.4 writes its sessions under ~/.local/share/muse; once Godot has created the
        # host's ~/.local/share, a read-only bind of it made every Muse run fail (fix-matrix pilot).
        from agents.sandbox import _bwrap_cmd

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            for sub in (".local/share/godot", ".local/lib"):
                (home / sub).mkdir(parents=True)
            work = Path(tmp) / "fixer-work"
            work.mkdir()
            with mock.patch("pathlib.Path.home", return_value=home):
                cmd = _bwrap_cmd(work, ["true"], network=False)
            mounted = [cmd[i + 1] for i, a in enumerate(cmd) if a in ("--bind", "--ro-bind")]
            self.assertFalse([m for m in mounted if m.startswith(str(home / ".local"))], cmd)
            i = cmd.index("--tmpfs", cmd.index("/tmp") + 1)
            self.assertEqual(cmd[i + 1], str(home))  # a fresh, writable home

    def test_muse_can_create_its_session_dir_under_bwrap(self):
        from agents.sandbox import _bwrap_cmd, _bwrap_usable

        if not _bwrap_usable():
            if os.environ.get("EXPECTRAIL_REQUIRE_BWRAP") == "1":
                self.fail("bubblewrap is required here but not usable")
            self.skipTest("bubblewrap not usable here")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".local" / "share" / "godot").mkdir(parents=True)
            (home / ".local" / "share" / "godot" / "secret.txt").write_text("host data\n")
            work = Path(tmp) / "fixer-work"
            work.mkdir()
            script = ('mkdir -p "$HOME/.local/share/muse/sessions/2026/10/29/x" && echo session=ok; '
                      'cat "$HOME/.local/share/godot/secret.txt" 2>/dev/null || echo host=hidden')
            with mock.patch("pathlib.Path.home", return_value=home):
                cmd = _bwrap_cmd(work, ["sh", "-c", script], network=False)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
            self.assertIn("session=ok", proc.stdout, proc.stdout + proc.stderr)
            self.assertIn("host=hidden", proc.stdout, proc.stdout + proc.stderr)

    def test_shell_cannot_rewrite_guard_under_bwrap(self):
        from agents.sandbox import _bwrap_cmd, _bwrap_usable

        if not _bwrap_usable():
            if os.environ.get("EXPECTRAIL_REQUIRE_BWRAP") == "1":
                self.fail("bubblewrap is required here but not usable")
            self.skipTest("bubblewrap not usable here")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "fixer-work"
            (work / "player").mkdir(parents=True)
            guard.install_guard(work, EDITABLE, root_as_muse_sees_it="/fixer")
            policy_before = (work / guard.POLICY_REL).read_text()
            payload = json.dumps({"tool_name": "write_file", "tool_input": {"path": "specs/x.json"},
                                  "cwd": "/fixer"})
            script = (
                "echo '{\"editable\": [\"*\"]}' > .muse/fixer-guard.json; echo policy=$?; "
                "rm -rf .muse 2>/dev/null; echo rm=$?; mv .muse moved 2>/dev/null; echo mv=$?; "
                f"echo '{payload}' | python3 /fixer/{guard.HOOK_REL}"
            )
            proc = subprocess.run(_bwrap_cmd(work, ["sh", "-c", script], network=False), capture_output=True,
                                  text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
            self.assertIn("policy=", proc.stdout, proc.stdout + proc.stderr)
            self.assertNotIn("policy=0", proc.stdout, proc.stdout + proc.stderr)  # dash says 2, bash 1
            self.assertNotIn("rm=0", proc.stdout)
            self.assertNotIn("mv=0", proc.stdout)
            self.assertIn('"permissionDecision": "deny"', proc.stdout)
            self.assertEqual((work / guard.POLICY_REL).read_text(), policy_before)
            self.assertEqual(len(guard.read_log(work / guard.LOG_REL)), 1)


class GuardEvidenceTest(unittest.TestCase):
    def test_notices_and_warnings(self):
        from agents.guard_evidence import lines_for

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIn("::warning", lines_for([root])[0])  # nothing ran with the guard
            (root / "a").mkdir()
            (root / "a" / "guard.json").write_text(json.dumps({
                "installed": True, "loaded": True, "calls": 14, "source": "muse",
                "tools": {"edit_file": 2, "read_file": 11, "evil::\nset-env": 1},
                "blocked": [{"tool": "web_fetch"}]}))
            (root / "b").mkdir()
            (root / "b" / "guard.json").write_text(json.dumps({"installed": True, "loaded": False, "calls": 0}))
            out = lines_for([root])
            self.assertTrue(out[0].startswith("::notice title=Fixer guard::"))
            self.assertIn("loaded=True calls=14 blocked=1 (web_fetch)", out[0])
            self.assertEqual(sum(1 for l in out if l.startswith("::")), len(out))
            self.assertTrue(all("\n" not in l and "::set-env" not in l for l in out))
            self.assertIn("not have loaded", out[-1])


class HookSourceTest(unittest.TestCase):
    def test_hook_is_stdlib_only(self):
        tree = ast.parse(HOOK.read_text())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertLessEqual(mods, {"__future__", "fnmatch", "json", "os", "sys", "time"})

    def test_glob_rule_matches_patchutil(self):
        sys.path.insert(0, str(HOOK.parent))
        try:
            import fixer_guard_hook as hook
        finally:
            sys.path.pop(0)
        for rel in ("player/player.tscn", "player/a/b.gd", "level/x", "specs/s.json", "player", "project.godot"):
            for globs in (EDITABLE, ["player/"], ["*.gd"], ["**"]):
                self.assertEqual(hook.path_allowed(rel, globs), path_allowed(rel, globs), (rel, globs))

    def test_guard_switch(self):
        self.assertTrue(guard.guard_enabled({}))
        for off in ("0", "off", "false", "no"):
            self.assertFalse(guard.guard_enabled({guard.GUARD_ENV: off}))


class FixerWiringTest(unittest.TestCase):
    def _fake_muse(self, seen):
        def fake(prompt, *, work, env=None, timeout=0, require_sandbox=False, detected=None):
            seen["detected"] = detected
            seen["hooks"] = json.loads((work / ".muse" / "hooks.json").read_text()) \
                if (work / ".muse" / "hooks.json").is_file() else None
            if seen["hooks"] is not None:
                base = {"cwd": str(work), "hook_event_name": "PreToolUse"}
                calls = [
                    {"tool_name": "edit_file", "tool_input": {"path": "player/player.tscn"}},
                    {"tool_name": "write_file", "tool_input": {"path": "specs/player-stays-above-ground.json"}},
                    {"tool_name": "web_fetch", "tool_input": {"url": "https://example.com/answer"}},
                ]
                for call in calls:
                    call_hook(work, {**base, **call})
            tscn = work / "player" / "player.tscn"
            tscn.write_text(tscn.read_text().replace("collision_mask = 14", "collision_mask = 30"))
            return mock.Mock(returncode=0, stdout="ok", stderr=""), {"kind": "none"}
        return fake

    def _run(self, out, env):
        seen: dict = {}
        with mock.patch.dict(os.environ, env):
            with mock.patch("agents.fixer.muse_code_ready", return_value=True), \
                    mock.patch("agents.fixer.detect_sandbox", return_value="none"), \
                    mock.patch("agents.fixer.run_muse_sandboxed", side_effect=self._fake_muse(seen)):
                meta = run_fixer(_request(), out, candidate_patch=None)
        return meta, seen

    def test_run_fixer_installs_guard_and_records_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fix"
            meta, seen = self._run(out, {"META_API_KEY": "k", guard.GUARD_ENV: "1"})
            self.assertEqual(seen["detected"], "none")
            cmd = seen["hooks"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn(str((out / "fixer-work").resolve()), cmd)
            self.assertEqual(meta["guard"], {"installed": True, "loaded": True, "calls": 3, "blocked": 2})
            summary = json.loads((out / "guard.json").read_text())
            self.assertEqual(sorted(b["tool"] for b in summary["blocked"]), ["web_fetch", "write_file"])
            patch = (out / "candidate.patch").read_text()
            self.assertIn("player/player.tscn", patch)
            self.assertNotIn(".muse", patch)

    def test_guard_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fix"
            meta, seen = self._run(out, {"META_API_KEY": "k", guard.GUARD_ENV: "0"})
            self.assertIsNone(seen["hooks"])
            self.assertNotIn("guard", meta)
            self.assertFalse((out / "guard.json").exists())



def _processes_naming(mark: str) -> list[list[str]]:
    """The command line of every process that has ``mark`` as one of its words."""
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                words = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
            except OSError:
                continue
            if mark in words:
                found.append(words)
    return found


def _wait(test, done, what: str, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while not done():
        if time.monotonic() > deadline:
            test.fail(f"timed out waiting for {what}")
        time.sleep(0.1)


class BwrapSessionTest(unittest.TestCase):
    """The fixer runs in a session of its own (#309): it cannot open the terminal the loop was started
    from, and stopping the loop still ends it. The tests that start bubblewrap run where it works
    (CI's agents-sandbox job sets EXPECTRAIL_REQUIRE_BWRAP=1, so a skip there is a failure)."""

    TERMINAL = ('import json\ntry:\n    open("/dev/tty", "r+b", buffering=0).close()\n    print(json.dumps("opened"))\n'
                'except OSError as exc:\n    print(json.dumps("refused: " + type(exc).__name__))\n')
    ENV = {"PATH": "/usr/bin:/bin"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-fixer-session-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = self.tmp / "fixer-work"
        self.work.mkdir()

    def need_bwrap(self):
        from agents.sandbox import _bwrap_usable

        if not _bwrap_usable():
            if os.environ.get("EXPECTRAIL_REQUIRE_BWRAP") == "1":
                self.fail("bubblewrap is required here but not usable")
            self.skipTest("bubblewrap not usable here")

    def from_a_terminal(self, start) -> str:
        """Run ``start`` (which returns a finished process) in a child that has a terminal of its own,
        as a loop started from a shell does, and return what the program it started printed."""
        answer = self.tmp / "answer.json"
        child, terminal = pty.fork()
        if child == 0:
            try:
                answer.write_text(start().stdout, encoding="utf-8")
            finally:
                os._exit(0)
        try:
            while os.read(terminal, 4096):
                pass
        except OSError:
            pass  # the child has gone and its terminal with it
        os.waitpid(child, 0)
        os.close(terminal)
        return json.loads(answer.read_text(encoding="utf-8"))

    def test_the_fixer_and_the_probe_both_start_a_new_session(self):
        from agents import sandbox

        cmd = sandbox._bwrap_cmd(self.work, ["true"], network=False)
        self.assertIn("--new-session", cmd[:cmd.index("--")])
        self.assertIn("--die-with-parent", cmd[:cmd.index("--")])
        with mock.patch.object(sandbox.shutil, "which", return_value="/usr/bin/bwrap"), \
                mock.patch.object(sandbox.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(sandbox._bwrap_usable())
        probe = run.call_args.args[0]
        self.assertIn("--new-session", probe[:probe.index("--")])

    def test_the_fixer_is_given_no_input(self):
        from agents import sandbox

        with mock.patch.object(sandbox.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            sandbox.run_sandboxed(["true"], work=self.work, env=self.ENV, network=False, kind="bwrap")
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_control_outside_the_sandbox_the_starters_terminal_can_be_opened(self):
        found = self.from_a_terminal(lambda: subprocess.run(
            ["python3", "-c", self.TERMINAL], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            env=self.ENV))
        self.assertEqual(found, "opened")

    def test_inside_the_starters_terminal_cannot_be_opened(self):
        from agents.sandbox import run_sandboxed

        self.need_bwrap()
        found = self.from_a_terminal(lambda: run_sandboxed(
            ["python3", "-c", self.TERMINAL], work=self.work, env=self.ENV, network=False, kind="bwrap", timeout=60))
        self.assertTrue(found.startswith("refused: "), found)

    def test_a_time_limit_ends_everything_the_fixer_started(self):
        from agents.sandbox import run_sandboxed

        self.need_bwrap()
        mark = "311.2718"
        with self.assertRaises(subprocess.TimeoutExpired):
            run_sandboxed(["sh", "-c", f"sleep {mark} & sleep {mark} & wait"], work=self.work, env=self.ENV,
                          network=False, kind="bwrap", timeout=2)
        _wait(self, lambda: not _processes_naming(mark), "the fixer's processes to end after its time limit")

    def stopped_loop_leaves_nothing(self, mark: str, stop) -> None:
        """Start a loop that runs a long fixer, stop the loop with ``stop(loop)``, and expect the
        fixer and bubblewrap gone. The fixer is in a session of its own, so no signal sent to the
        loop or its process group reaches it: bubblewrap going is what ends it."""
        self.need_bwrap()
        code = ("import sys; from pathlib import Path; from agents.sandbox import run_sandboxed; "
                "run_sandboxed(['sleep', sys.argv[2]], work=Path(sys.argv[1]), env={'PATH': '/usr/bin:/bin'}, "
                "network=False, kind='bwrap')")
        loop = subprocess.Popen([sys.executable, "-c", code, str(self.work), mark], cwd=str(REPO),
                                start_new_session=True, stdin=subprocess.DEVNULL)
        try:
            _wait(self, lambda: any(words[0] == "sleep" for words in _processes_naming(mark)), "the fixer to start")
            inside = [words for words in _processes_naming(mark) if words[0] == "sleep"]
            self.assertEqual(len(inside), 1, inside)
            stop(loop)
            loop.wait(timeout=10)
            _wait(self, lambda: not _processes_naming(mark), "the fixer to end after its loop was stopped")
        finally:
            try:
                os.killpg(loop.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_a_loop_that_is_killed_leaves_no_fixer_running(self):
        self.stopped_loop_leaves_nothing("313.1414", lambda loop: loop.kill())

    def test_a_loop_whose_process_group_is_signalled_leaves_no_fixer_running(self):
        # A signal to the loop's process group (Ctrl-C in a terminal sends one the same way) reaches
        # the loop and bubblewrap and not the fixer.
        self.stopped_loop_leaves_nothing("317.1732", lambda loop: os.killpg(loop.pid, signal.SIGTERM))


if __name__ == "__main__":
    unittest.main()
