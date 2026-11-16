"""The replay's sandbox (harness/sandbox.py, #253).

Three kinds of test. The first needs nothing: the command that is built, the mode, what replay.json
says, and what is taken from the folder the game could write to. The second runs real processes
inside bubblewrap and is skipped where bubblewrap cannot run; the third does the same with the real
engine and a game copy that tries to get out. CI sets EXPECTRAIL_SANDBOX_TESTS=required in the job
that has bubblewrap and Godot, where a missing tool is a failure, not a skip.

Every escape test has a control: the same attempt outside the sandbox succeeds, so a refusal inside
is the sandbox's doing and not a mistake in the attempt.
"""
from __future__ import annotations

import json
import os
import pty
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import validate
from harness import run as hr
from harness import sandbox as box

REPO = Path(__file__).resolve().parent.parent
REQUIRED = os.environ.get("EXPECTRAIL_SANDBOX_TESTS") == "required"
SECRET = "EXPECTRAIL_TEST_SECRET"
FAKE = box.Tool("/usr/bin/bwrap", "0.9.0")


def real_tool(display: bool = False) -> box.Tool:
    tool, why = box.probe(display)
    if tool is None:
        if REQUIRED:
            raise AssertionError(f"this job must be able to run the sandbox: {why}")
        raise unittest.SkipTest(f"no sandbox on this machine: {why}")
    return tool


def real_godot() -> Path:
    from tests.tool_requirements import godot_binary
    return godot_binary(switch="EXPECTRAIL_SANDBOX_TESTS")


class CommandTest(unittest.TestCase):
    def build(self, **kwargs) -> list[str]:
        defaults = dict(game=Path("/srv/run/work"), out=Path("/srv/run/sandbox"),
                        inputs={"route.json": Path("/srv/repo/routes/smoke.json")},
                        engine=Path("/srv/repo/tools/godot/Godot"), env={"LANG": "C.UTF-8"})
        return box.command(FAKE, ["/engine/godot", "--path", "/game"], **{**defaults, **kwargs})

    def pairs(self, cmd: list[str], flag: str, width: int) -> list[tuple]:
        return [tuple(cmd[i + 1:i + 1 + width]) for i, arg in enumerate(cmd) if arg == flag]

    def test_no_network_own_processes_and_nothing_inherited(self):
        cmd = self.build()
        for flag in ("--unshare-net", "--unshare-pid", "--unshare-user", "--unshare-ipc", "--disable-userns",
                     "--clearenv", "--die-with-parent", "--new-session"):
            self.assertIn(flag, cmd)
        self.assertNotIn("--share-net", cmd)
        # xvfb-run waits forever when it is the first process of its namespace (seen November 11),
        # so bubblewrap must stay in that place.
        self.assertNotIn("--as-pid-1", cmd)
        self.assertEqual(cmd[cmd.index("--") + 1:], ["/engine/godot", "--path", "/game"])

    def test_only_the_work_copy_and_the_output_folder_are_writable(self):
        cmd = self.build()
        self.assertEqual(self.pairs(cmd, "--bind", 2), [("/srv/run/work", "/game"), ("/srv/run/sandbox", "/out")])
        read_only = dict((dst, src) for src, dst in self.pairs(cmd, "--ro-bind", 2))
        self.assertEqual(read_only["/in/route.json"], "/srv/repo/routes/smoke.json")
        self.assertEqual(read_only["/engine/godot"], "/srv/repo/tools/godot/Godot")
        self.assertNotIn("--dev-bind", cmd)
        for _src, dst in self.pairs(cmd, "--ro-bind", 2):
            self.assertTrue(dst.startswith(("/usr", "/bin", "/sbin", "/lib", "/etc/", "/in/", "/engine/")), dst)
        self.assertEqual([dst for (dst,) in self.pairs(cmd, "--tmpfs", 1)], ["/tmp", "/home/player"])
        self.assertEqual(self.pairs(cmd, "--size", 1), [(str(box.SCRATCH_BYTES),)] * 2)

    def test_the_repository_is_never_mounted(self):
        cmd = self.build(game=REPO / "runs" / "x" / "work", out=REPO / "runs" / "x" / "sandbox",
                         inputs={"route.json": REPO / "harness" / "routes" / "smoke.json"})
        sources = [src for src, _dst in self.pairs(cmd, "--bind", 2) + self.pairs(cmd, "--ro-bind", 2)]
        self.assertNotIn(str(REPO), sources)
        for inside in ("agents", "expectrail", "harness", ".git", ".github"):
            self.assertNotIn(str(REPO / inside), sources)
        for host in ("/", "/home", "/root", "/var", "/run", "/sys", "/etc", str(Path.home())):
            self.assertNotIn(host, sources)

    def test_the_environment_is_built_from_nothing(self):
        cmd = self.build(env={"LANG": "C.UTF-8", "LIBGL_ALWAYS_SOFTWARE": "1", "DISPLAY": ":0",
                              "XAUTHORITY": "/home/dev/.Xauthority", "HOME": "/home/dev", "PATH": "/home/dev/bin",
                              "XDG_RUNTIME_DIR": "/run/user/1000", "TMPDIR": "/var/tmp"})
        self.assertEqual(dict(self.pairs(cmd, "--setenv", 2)),
                         {"LANG": "C.UTF-8", "LIBGL_ALWAYS_SOFTWARE": "1", "HOME": "/home/player",
                          "PATH": "/usr/bin:/bin", "TMPDIR": "/tmp"})

    def test_an_input_name_cannot_place_a_file_elsewhere(self):
        for name in ("../etc/passwd", "a/b", "", ".", ".."):
            with self.subTest(name=name), self.assertRaises(box.SandboxError):
                self.build(inputs={name: Path("/srv/x")})


class ModeTest(unittest.TestCase):
    def test_mode_from_the_argument_then_the_environment_then_auto(self):
        with mock.patch.dict(os.environ, {box.ENV: "require"}):
            self.assertEqual(box.mode(), "require")
            self.assertEqual(box.mode("off"), "off")
        with mock.patch.dict(os.environ, {box.ENV: ""}):
            self.assertEqual(box.mode(), "auto")
        with self.assertRaises(box.SandboxError):
            box.mode("sometimes")

    def test_without_the_tool_auto_says_why_and_require_refuses(self):
        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")):
            tool, isolation = box.choose("auto", True)
            self.assertIsNone(tool)
            self.assertEqual((isolation["sandbox"], isolation["network"], isolation["filesystem"],
                              isolation["processes"]), (None, "host", "host", "host"))
            self.assertEqual(isolation["reason"], "bubblewrap (bwrap) is not installed")
            with self.assertRaisesRegex(box.SandboxError, "required and is not possible here: bubblewrap"):
                box.choose("require", True)

    def test_off_never_asks_the_machine_and_says_it_was_turned_off(self):
        with mock.patch.object(box, "probe", side_effect=AssertionError("not asked")):
            tool, isolation = box.choose("off", True)
        self.assertIsNone(tool)
        self.assertEqual((isolation["mode"], isolation["sandbox"]), ("off", None))
        self.assertIn("turned off", isolation["reason"])

    def test_with_the_tool_the_block_says_what_was_in_force(self):
        with mock.patch.object(box, "probe", return_value=(FAKE, None)):
            tool, isolation = box.choose("require", True)
        self.assertEqual(tool, FAKE)
        self.assertEqual(isolation, {
            "sandbox": {"tool": "bubblewrap", "version": "0.9.0"}, "mode": "require", "reason": None,
            "network": "none", "filesystem": "confined", "processes": "own", "environment": "allowlist",
            "limits": {"scratchBytes": box.SCRATCH_BYTES, "fileBytes": box.FILE_BYTES, "processes": box.PROCESSES,
                       "diskBytes": box.DISK_BYTES, "diskEntries": box.DISK_ENTRIES}})

    def test_a_replay_from_before_the_disk_bound_still_matches_the_contract(self):
        example = json.loads((REPO / "contracts" / "examples" / "replay.json").read_text(encoding="utf-8"))
        isolation = box.describe(FAKE, "auto", None)
        older = {**isolation, "limits": {k: v for k, v in isolation["limits"].items() if not k.startswith("disk")}}
        self.assertEqual(validate({**example, "isolation": older}), "replay")
        from expectrail.contracts import ContractError

        for bad in (0, -1, "8G", 1.5):
            with self.subTest(diskBytes=bad), self.assertRaises(ContractError):
                validate({**example, "isolation": {**isolation, "limits": {**isolation["limits"], "diskBytes": bad}}})

    def test_both_shapes_match_the_replay_contract_and_a_loose_one_does_not(self):
        example = json.loads((REPO / "contracts" / "examples" / "replay.json").read_text(encoding="utf-8"))
        for isolation in (box.describe(FAKE, "auto", None), box.describe(None, "auto", "no bubblewrap")):
            self.assertEqual(validate({**example, "isolation": isolation}), "replay")
        from expectrail.contracts import ContractError

        for broken in ({**box.describe(FAKE, "auto", None), "network": "some"},
                       {**box.describe(FAKE, "auto", None), "extra": 1},
                       {k: v for k, v in box.describe(None, "auto", "x").items() if k != "reason"}):
            with self.assertRaises(ContractError):
                validate({**example, "isolation": broken})

    def test_a_probe_that_cannot_start_reports_the_tools_own_words(self):
        box.probe.cache_clear()
        self.addCleanup(box.probe.cache_clear)
        refused = subprocess.CompletedProcess([], 1, "", "bwrap: setting up uid map: Permission denied\n")
        version = subprocess.CompletedProcess([], 0, "bubblewrap 0.9.0\n", "")
        with mock.patch.object(box.sys, "platform", "linux"), \
                mock.patch.object(box.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"), \
                mock.patch.object(box.subprocess, "run", side_effect=[version, refused]):
            tool, why = box.probe(True)
        self.assertIsNone(tool)
        self.assertEqual(why, "bubblewrap could not start a sandbox: bwrap: setting up uid map: Permission denied")

    def test_a_replay_with_frames_needs_a_display_it_can_start_inside(self):
        box.probe.cache_clear()
        self.addCleanup(box.probe.cache_clear)
        with mock.patch.object(box.sys, "platform", "linux"), \
                mock.patch.object(box.shutil, "which", side_effect=lambda name: None if name == "xvfb-run" else "/usr/bin/bwrap"):
            self.assertEqual(box.probe(True), (None, "xvfb-run is not installed, and the sandbox cannot use the host's display"))
        with mock.patch.object(box.sys, "platform", "darwin"):
            self.assertEqual(box.probe(False), (None, "bubblewrap runs on Linux only"))


class GateReasonTest(unittest.TestCase):
    """What the gate's record says of a replay the disk bound stopped: its own sentence, never text
    the game could have written, and the result is a replay error (never a pass)."""

    def judged(self, failure: BaseException) -> dict:
        from expectrail.gate import verify as gv

        def replay(path, game, out, frames):
            raise failure

        with tempfile.TemporaryDirectory() as tmp:
            results = gv.judge_arm(Path(tmp), [("smoke", Path(tmp) / "smoke.json", "0" * 64)], [{"id": "s"}],
                                   Path(tmp) / "out", replay, label="head")
        return results[("s", "smoke")]

    def test_a_replay_stopped_at_the_disk_bound_says_so_in_the_gates_words(self):
        try:
            try:
                raise box.DiskBoundError("the game wrote 9 bytes <img src=x> @sean")
            except box.DiskBoundError as exc:
                raise SystemExit(f"the replay was stopped: {exc}") from exc
        except SystemExit as stopped:
            result = self.judged(stopped)
        self.assertEqual(result["result"], "replay-error")
        self.assertEqual(result["reason"], "the head replay was stopped: the game wrote more to its folders than the "
                                           "replay sandbox allows")

    def test_any_other_stop_still_gives_only_its_kind(self):
        result = self.judged(SystemExit("text the game printed"))
        self.assertEqual((result["result"], result["reason"]), ("replay-error", "the head replay did not finish (SystemExit)"))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-collect-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out, self.staging = self.tmp / "run", self.tmp / "run" / "sandbox"
        (self.staging / "frames").mkdir(parents=True)
        self.secret = self.tmp / "secret.txt"
        self.secret.write_text("the approved checks", encoding="utf-8")

    def test_the_trace_and_the_frames_are_moved_and_nothing_else(self):
        (self.staging / "trace.json").write_text("{}", encoding="utf-8")
        (self.staging / "frames" / "f00000000.png").write_bytes(b"png0")
        (self.staging / "frames" / "f00000001.png").write_bytes(b"png1")
        (self.staging / "frames" / "f.wav").write_bytes(b"wav")
        (self.staging / "replay.json").write_text('{"forged": true}', encoding="utf-8")
        (self.staging / "findings.json").write_text('{"decision": "accept"}', encoding="utf-8")
        box.collect(self.staging, self.out, frames=True)
        self.assertEqual(sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*")),
                         ["frames", "frames/f00000000.png", "frames/f00000001.png", "trace.json"])

    def test_a_trace_that_is_a_link_is_refused_and_never_read(self):
        (self.staging / "trace.json").symlink_to(self.secret)
        with self.assertRaisesRegex(box.SandboxError, "plain file as its trace"):
            box.collect(self.staging, self.out, frames=False)
        self.assertFalse((self.out / "trace.json").exists())

    def test_a_frame_that_is_a_link_is_refused(self):
        (self.staging / "trace.json").write_text("{}", encoding="utf-8")
        (self.staging / "frames" / "f00000000.png").symlink_to(self.secret)
        with self.assertRaisesRegex(box.SandboxError, "plain file as frame f00000000.png"):
            box.collect(self.staging, self.out, frames=True)

    def test_a_frames_folder_that_is_a_link_gives_no_frames(self):
        (self.staging / "trace.json").write_text("{}", encoding="utf-8")
        (self.staging / "frames").rmdir()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "f00000000.png").write_bytes(b"not this run's")
        (self.staging / "frames").symlink_to(elsewhere)
        box.collect(self.staging, self.out, frames=True)
        self.assertEqual(list((self.out / "frames").iterdir()), [])
        self.assertTrue((elsewhere / "f00000000.png").exists())

    def test_no_trace_leaves_none_so_the_replay_fails(self):
        box.collect(self.staging, self.out, frames=True)
        self.assertFalse((self.out / "trace.json").exists())
        self.assertFalse(self.staging.exists())


class HarnessTest(unittest.TestCase):
    """harness.run.run with the engine replaced: what it starts, and what it writes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.game = self.tmp / "game"
        self.game.mkdir()
        (self.game / "project.godot").write_text('[application]\nconfig/name="t"\n', encoding="utf-8")
        self.godot = self.tmp / "godot"
        self.godot.write_bytes(b"not an engine")
        self.route = self.tmp / "route.json"
        self.route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1, "steps": []}),
                              encoding="utf-8")
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(self.tmp / "cache"), SECRET: "s3cret"})
        env.start()
        self.addCleanup(env.stop)
        self.calls: list[dict] = []

    def engine(self, tool, argv, *, timeout, game, out, inputs=None, engine=None, env=None):
        self.calls.append({"argv": list(argv), "game": Path(game), "out": Path(out), "inputs": inputs,
                           "engine": engine, "env": env})
        if "--import" in argv:
            (Path(game) / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
        else:
            (Path(out) / "trace.json").write_text('{"physicsTicksPerSecond": 60}', encoding="utf-8")
            if "--write-movie" in argv:
                (Path(out) / "frames" / "f00000000.png").write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "Godot Engine v4.7.2.stable.official\nUsing Device: fake\n", "")

    @mock.patch("sys.platform", "linux")
    def test_sandboxed_every_engine_start_goes_through_the_sandbox_with_inside_paths_only(self):
        out = self.tmp / "run"
        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=self.engine), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("started outside the sandbox")):
            replay = hr.run(self.route, out, game=self.game, godot=self.godot, sandbox="require")
        self.assertEqual(validate(replay), "replay")
        self.assertEqual(replay["isolation"]["sandbox"], {"tool": "bubblewrap", "version": "0.9.0"})
        self.assertEqual(json.loads((out / "replay.json").read_text(encoding="utf-8"))["isolation"], replay["isolation"])
        self.assertEqual(replay["capture"]["frames"], 1)
        self.assertFalse((out / "sandbox").exists())
        self.assertTrue((out / "trace.json").is_file())
        self.assertGreaterEqual(len(self.calls), 2)  # the import cache, then the replay
        for call in self.calls:
            self.assertEqual(call["engine"], self.godot)
            self.assertNotIn(SECRET, call["env"])
            for arg in call["argv"]:
                self.assertNotIn(str(self.tmp), arg)
        capture = self.calls[-1]
        self.assertEqual(capture["argv"][:4], ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"])
        self.assertEqual(capture["argv"][4], "/engine/godot")
        self.assertIn("--route=/in/route.json", capture["argv"])
        self.assertIn("--trace=/out/trace.json", capture["argv"])
        self.assertEqual(capture["argv"][capture["argv"].index("--write-movie") + 1], "/out/frames/f.png")
        self.assertEqual(capture["argv"][capture["argv"].index("--path") + 1], "/game")
        self.assertEqual((capture["game"], capture["out"]), (out / "work", out / "sandbox"))
        self.assertEqual(capture["inputs"], {"route.json": self.route})

    @mock.patch("sys.platform", "linux")
    def test_sandboxed_the_host_display_is_never_used(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=self.engine):
            hr.run(self.route, self.tmp / "run", game=self.game, godot=self.godot)
        self.assertEqual(self.calls[-1]["argv"][0], "xvfb-run")

    def test_required_and_impossible_stops_before_the_game_is_touched(self):
        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("the game was started")), \
                self.assertRaisesRegex(SystemExit, "required and is not possible here"):
            hr.run(self.route, self.tmp / "run", game=self.game, godot=self.godot, sandbox="require")
        self.assertFalse((self.tmp / "run" / "work").exists())

    @mock.patch("sys.platform", "linux")
    def test_a_replay_past_the_disk_bound_is_stopped_and_nothing_it_wrote_is_kept(self):
        out = self.tmp / "run"

        def greedy(tool, argv, **binds):
            if "--import" in argv:
                return self.engine(tool, argv, **binds)
            # What the sandbox raises once the game has written too much (see DiskBoundTest).
            (Path(binds["out"]) / "trace.json").write_text("{}", encoding="utf-8")
            (Path(binds["game"]) / "filler.bin").write_bytes(b"x" * 1024)
            raise box.DiskBoundError("the game wrote 9 bytes to its work copy and output folder, more than the 8 "
                                     "a replay may add; the sandbox was stopped")

        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=greedy), \
                self.assertRaisesRegex(SystemExit, "the replay was stopped: the game wrote 9 bytes"):
            hr.run(self.route, out, game=self.game, godot=self.godot, sandbox="require")
        self.assertFalse((out / "trace.json").exists())
        self.assertFalse((out / "replay.json").exists())
        self.assertFalse((out / "work").exists())
        self.assertFalse((out / "sandbox").exists())
        self.assertEqual(list((out / "frames").iterdir()), [])

    @mock.patch("sys.platform", "linux")
    def test_an_import_past_the_disk_bound_stops_the_replay_before_it_starts(self):
        out = self.tmp / "run"
        starts = []

        def greedy(tool, argv, **binds):
            starts.append(list(argv))
            if "--import" in argv:
                raise box.DiskBoundError("the game made more than 8 files and folders")
            return self.engine(tool, argv, **binds)

        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=greedy), \
                self.assertRaisesRegex(SystemExit, "the game's import was stopped: the game made more than 8"):
            hr.run(self.route, out, game=self.game, godot=self.godot, sandbox="require")
        self.assertTrue(starts)
        self.assertTrue(all("--import" in argv for argv in starts), "the replay ran after its import was stopped")
        self.assertFalse((out / "work").exists())
        self.assertFalse((out / "trace.json").exists())

    def test_warming_the_cache_with_the_sandbox_required_and_impossible_is_one_line(self):
        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")), \
                mock.patch.object(hr, "find_godot", return_value=self.godot), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("the game was started")), \
                self.assertRaisesRegex(SystemExit, "required and is not possible here"):
            hr.main(["--warm-cache", "--sandbox", "require", "--game", str(self.game)])

    def test_a_planted_link_fails_the_replay(self):
        def planting(tool, argv, **kwargs):
            done = self.engine(tool, argv, **kwargs)
            if "--import" not in argv:
                trace = Path(kwargs["out"]) / "trace.json"
                trace.unlink()
                trace.symlink_to(self.route)
            return done

        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=planting), \
                self.assertRaisesRegex(SystemExit, "output was refused"):
            hr.run(self.route, self.tmp / "run", game=self.game, godot=self.godot)
        self.assertFalse((self.tmp / "run" / "replay.json").exists())

    def test_a_trace_from_an_earlier_run_is_not_this_runs(self):
        out = self.tmp / "run"
        out.mkdir()
        (out / "trace.json").write_text('{"physicsTicksPerSecond": 60, "stale": true}', encoding="utf-8")

        def silent(tool, argv, **kwargs):
            if "--import" in argv:
                return self.engine(tool, argv, **kwargs)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=silent), self.assertRaises(SystemExit):
            hr.run(self.route, out, game=self.game, godot=self.godot)

    def test_unsandboxed_the_replay_says_so_and_why(self):
        def plain(argv, **kwargs):
            if "--import" in argv:
                (Path(argv[argv.index("--path") + 1]) / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
            else:
                trace = next(a for a in argv if a.startswith("--trace=")).split("=", 1)[1]
                Path(trace).write_text('{"physicsTicksPerSecond": 60}', encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "Godot Engine v4.7.2.stable.official\n", "")

        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")), \
                mock.patch.object(box, "run", side_effect=AssertionError("no sandbox to run in")), \
                mock.patch.object(hr.subprocess, "run", side_effect=plain):
            replay = hr.run(self.route, self.tmp / "run", game=self.game, godot=self.godot, capture_frames=False)
        self.assertEqual(validate(replay), "replay")
        self.assertEqual((replay["isolation"]["sandbox"], replay["isolation"]["mode"], replay["isolation"]["reason"]),
                         (None, "auto", "bubblewrap (bwrap) is not installed"))


# What a hostile program tries, written once and run inside and outside the sandbox.
ESCAPE = r'''
import json, os, socket
found = {}
def attempt(name, action):
    try:
        found[name] = action()
    except OSError as exc:
        found[name] = "refused: " + type(exc).__name__
def connect():
    with socket.create_connection(("127.0.0.1", PORT), timeout=3):
        return "done"
def write(path):
    def action():
        with open(path, "w") as handle:
            handle.write("planted")
        return "done"
    return action
def read(path):
    def action():
        with open(path, "rb") as handle:
            handle.read(1)
        return "done"
    return action
attempt("socket", connect)
attempt("writeOutside", write(OUTSIDE + "/planted.txt"))
attempt("readSpec", read(SPEC))
attempt("readVerifier", read(VERIFIER))
attempt("readParentEnvironment", read("/proc/%d/environ" % PARENT))
attempt("writeInput", write("/in/route.json"))
attempt("writeSystem", write("/usr/planted-by-expectrail-test.txt"))
attempt("writeGame", write("/game/made-by-game.txt"))
attempt("writeOut", write("/out/made-by-game.txt"))
attempt("readInput", read("/in/route.json"))
def new_user_namespace():
    # In a child: on Ubuntu 24.04 a process that makes one outside the sandbox is confined by
    # AppArmor from then on, and the rest of this program could no longer look around.
    child = os.fork()
    if child == 0:
        try:
            os.unshare(os.CLONE_NEWUSER)
        except OSError:
            os._exit(1)
        os._exit(0)
    if os.waitpid(child, 0)[1] != 0:
        raise PermissionError("no new user namespace")
    return "done"
attempt("newUserNamespace", new_user_namespace)
found["environment"] = sorted(os.environ)
found["processes"] = len([name for name in os.listdir("/proc") if name.isdigit()])
found["root"] = sorted(os.listdir("/"))
found["home"] = os.listdir(os.environ["HOME"])
found["sys"] = os.path.exists("/sys/class/net")
print(json.dumps(found))
'''


# A writer for the disk bound's tests: real processes, no sandbox needed. It writes CHUNK bytes at a
# time into a file in ROOT until it has written TOTAL (or forever when TOTAL is 0), and leaves its pid.
WRITER = """
import os, sys, time
root, total, files = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
open(os.path.join(root, "writer.pid"), "w").write(str(os.getpid()))
for n in range(files):
    open(os.path.join(root, f"f{n}"), "w").close()
written = 0
with open(os.path.join(root, "data.bin"), "wb") as out:
    while total == 0 or written < total:
        out.write(b"x" * 65536)
        out.flush()
        written += 65536
        if total == 0:
            time.sleep(0.01)
print("wrote", written)
"""


class DiskBoundTest(unittest.TestCase):
    """The bound on what a game adds to its two writable folders (``harness.sandbox.watched``), shown
    on real processes. The sandbox's own command is not needed for this: ``run`` hands its two bound
    folders to ``watched``, and EscapeTest shows the same through real bubblewrap."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-disk-"))
        self.addCleanup(self._cleanup)
        self.game, self.out = self.tmp / "game", self.tmp / "out"
        self.game.mkdir()
        self.out.mkdir()
        for name, value in (("DISK_BYTES", 1024 * 1024), ("DISK_ENTRIES", 50), ("DISK_INTERVAL", 0.05)):
            patch = mock.patch.object(box, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _cleanup(self):
        for root, dirs, _files in os.walk(self.tmp):
            for name in dirs:
                os.chmod(os.path.join(root, name), 0o700)
        shutil.rmtree(self.tmp, True)

    def write(self, total: int, files: int = 0, *, timeout: float = 30) -> subprocess.CompletedProcess:
        return box.watched([sys.executable, "-c", WRITER, str(self.out), str(total), str(files)],
                           roots=[self.game, self.out], timeout=timeout)

    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:   # a zombie has ended; only its entry is left
            return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
        except OSError:
            return False

    def test_control_within_the_bound_the_run_is_returned_as_it_ended(self):
        done = self.write(512 * 1024, files=10)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "wrote 524288"))
        self.assertEqual(done.stderr, "")

    def test_a_writer_that_never_stops_is_stopped_at_the_bound(self):
        started = time.monotonic()
        with self.assertRaisesRegex(box.DiskBoundError, r"more than the 1048576 a replay may add; the sandbox was stopped"):
            self.write(0, timeout=60)
        self.assertLess(time.monotonic() - started, 30, "the writer ran on to its time limit")
        pid = int((self.out / "writer.pid").read_text())
        deadline = time.monotonic() + 5
        while self.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.alive(pid), "the writer outlived the stop")
        # It was stopped soon after the bound: well under what it would have written by its time limit.
        self.assertLess((self.out / "data.bin").stat().st_size, 64 * 1024 * 1024)

    def test_too_many_files_is_past_the_bound_too(self):
        with self.assertRaisesRegex(box.DiskBoundError, "more than 50 files and folders"):
            self.write(0, files=200)

    def test_a_writer_that_ends_between_two_measurements_is_caught_after_it_ends(self):
        # No measurement falls while it runs; the one after the end still sees what it wrote.
        with mock.patch.object(box, "DISK_INTERVAL", 3600.0), \
                self.assertRaisesRegex(box.DiskBoundError, "^the game wrote [0-9]+ bytes"):
            self.write(4 * 1024 * 1024)

    def test_what_the_folders_held_before_the_start_does_not_count(self):
        (self.game / "assets.bin").write_bytes(b"a" * (4 * 1024 * 1024))
        done = self.write(512 * 1024)
        self.assertEqual(done.returncode, 0)

    def test_a_sparse_file_counts_as_its_full_length(self):
        script = f"open({str(self.out / 'sparse.bin')!r}, 'wb').truncate(64 * 1024 * 1024)"
        with self.assertRaisesRegex(box.DiskBoundError, "the game wrote"):
            box.watched([sys.executable, "-c", script], roots=[self.game, self.out], timeout=30)

    def test_a_link_is_counted_as_a_link_and_never_followed(self):
        big = self.tmp / "outside.bin"
        big.write_bytes(b"o" * (4 * 1024 * 1024))
        script = (f"import os\nos.symlink({str(big)!r}, {str(self.out / 'link')!r})\n"
                  f"os.symlink({str(self.tmp)!r}, {str(self.out / 'loop')!r})")
        done = box.watched([sys.executable, "-c", script], roots=[self.game, self.out], timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_folder_that_cannot_be_read_is_cannot_tell_never_a_pass(self):
        real = os.scandir

        def refusing(path):
            if os.fspath(path).endswith("hidden"):
                raise PermissionError(13, "Permission denied", os.fspath(path))
            return real(path)

        # The folder is made by the program, so the measurement before the start does not meet it.
        script = f"import os\nos.mkdir({str(self.out / 'hidden')!r})"
        with mock.patch.object(box.os, "scandir", side_effect=refusing), \
                self.assertRaisesRegex(box.DiskBoundError, "could not be measured.*PermissionError"):
            box.watched([sys.executable, "-c", script], roots=[self.game, self.out], timeout=30)

    def test_a_folder_the_game_makes_unreadable_is_cannot_tell(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any folder; the mocked refusal above covers this case here")
        script = (f"import os\nd = {str(self.out / 'hidden')!r}\nos.mkdir(d)\n"
                  f"open(os.path.join(d, 'big'), 'wb').write(b'x' * 4194304)\nos.chmod(d, 0)")
        with self.assertRaisesRegex(box.DiskBoundError, "could not be measured"):
            box.watched([sys.executable, "-c", script], roots=[self.game, self.out], timeout=30)

    def test_a_file_that_disappears_while_it_is_counted_is_skipped(self):
        (self.out / "gone").write_bytes(b"g")
        real = os.scandir

        class Vanishing:
            def __init__(self, it):
                self.it = it

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.it.close()

            def __iter__(self):
                return self

            def __next__(self):
                entry = next(self.it)
                if entry.name == "gone":
                    os.unlink(entry.path)
                return entry

        with mock.patch.object(box.os, "scandir", side_effect=lambda path: Vanishing(real(path))):
            used, entries = box.usage([self.game, self.out], 1000)
        self.assertEqual(entries, 1)
        self.assertEqual(used, 0)

    def test_the_time_limit_still_holds_and_keeps_the_output(self):
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            box.watched([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(300)"],
                        roots=[self.game, self.out], timeout=1)
        self.assertIn("started", caught.exception.stdout)

    def test_folders_that_cannot_be_measured_before_the_start_stop_it_before_it_starts(self):
        with mock.patch.object(box, "usage", side_effect=box._Unmeasurable("PermissionError on a folder")), \
                mock.patch.object(box.subprocess, "Popen", side_effect=AssertionError("it was started")), \
                self.assertRaisesRegex(box.SandboxError, "cannot be measured before it starts"):
            self.write(1)

    def test_the_bound_can_be_lowered_by_the_verifiers_environment_and_never_raised(self):
        with mock.patch.dict(os.environ, {box.DISK_ENV: "4096"}):
            self.assertEqual(box.disk_bytes(), 4096)
            self.assertEqual(box.describe(FAKE, "auto", None)["limits"]["diskBytes"], 4096)
            with self.assertRaisesRegex(box.DiskBoundError, "more than the 4096 a replay may add"):
                self.write(512 * 1024)
        with mock.patch.dict(os.environ, {box.DISK_ENV: ""}):
            self.assertEqual(box.disk_bytes(), box.DISK_BYTES)
        for asked in (str(box.DISK_BYTES + 1), "0", "-5", "8G", "1e9", " 12 34"):
            with self.subTest(asked=asked), mock.patch.dict(os.environ, {box.DISK_ENV: asked}), \
                    mock.patch.object(box.subprocess, "Popen", side_effect=AssertionError("it was started")), \
                    self.assertRaisesRegex(box.SandboxError, "must be a whole number of bytes"):
                self.write(1)

    def test_the_sandbox_hands_its_two_writable_folders_to_the_bound(self):
        seen = {}

        def capture(cmd, *, roots, timeout, **popen):
            seen.update(roots=roots, timeout=timeout, preexec=popen.get("preexec_fn"))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(box, "watched", side_effect=capture):
            box.run(FAKE, ["true"], timeout=7, game=self.game, out=self.out)
        self.assertEqual(seen, {"roots": [self.game, self.out], "timeout": 7, "preexec": box.limits})


class Listener:
    """A TCP port on this machine's loopback: reachable by any process that shares its network."""

    def __enter__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        return self.sock.getsockname()[1]

    def __exit__(self, *exc):
        self.sock.close()


class EscapeTest(unittest.TestCase):
    """Real processes: what a program can reach inside the sandbox, against the same program outside."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-escape-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("game", "out", "outside"):
            (self.tmp / name).mkdir()
        self.route = REPO / "harness" / "routes" / "smoke.json"
        self.spec = sorted((REPO / "agents" / "specs").glob("*.json"))[0]
        env = mock.patch.dict(os.environ, {SECRET: "s3cret"})
        env.start()
        self.addCleanup(env.stop)

    def script(self, port: int) -> str:
        head = (f"PORT = {port}\nOUTSIDE = {str(self.tmp / 'outside')!r}\nSPEC = {str(self.spec)!r}\n"
                f"VERIFIER = {str(REPO / 'harness' / 'run.py')!r}\nPARENT = {os.getpid()}\n")
        return head + ESCAPE

    def test_control_outside_the_sandbox_every_one_of_these_succeeds(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux /proc and os.unshare are required by this sandbox escape control")
        with Listener() as port:
            done = subprocess.run(["python3", "-c", self.script(port)], capture_output=True, text=True,
                                  timeout=60, env=hr.game_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        for name in ("socket", "writeOutside", "readSpec", "readVerifier", "readParentEnvironment"):
            self.assertEqual(found[name], "done", name)
        self.assertNotIn(SECRET, found["environment"])  # the environment was already narrowed (game_env)
        # Whether a user namespace can be made outside depends on the machine (Ubuntu 24.04 refuses by
        # default), so the control only requires that the attempt reported one way or the other.
        self.assertIn(found["newUserNamespace"], ("done", "refused: PermissionError"))
        (self.tmp / "outside" / "planted.txt").unlink()

    def test_inside_none_of_them_does(self):
        tool = real_tool()
        with Listener() as port:
            done = box.run(tool, ["python3", "-c", self.script(port)], timeout=60, game=self.tmp / "game",
                           out=self.tmp / "out", inputs={"route.json": self.route}, env=hr.game_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        for name in ("socket", "writeOutside", "readSpec", "readVerifier", "readParentEnvironment", "writeInput",
                     "writeSystem", "newUserNamespace"):
            self.assertTrue(found[name].startswith("refused: "), f"{name}: {found[name]}")
        for name in ("writeGame", "writeOut", "readInput"):
            self.assertEqual(found[name], "done", name)
        self.assertEqual((self.tmp / "game" / "made-by-game.txt").read_text(), "planted")
        self.assertEqual((self.tmp / "out" / "made-by-game.txt").read_text(), "planted")
        self.assertEqual(list((self.tmp / "outside").iterdir()), [])
        self.assertFalse(Path("/usr/planted-by-expectrail-test.txt").exists())
        for name in found["environment"]:
            # PWD is set by bubblewrap itself (to /game), not passed in.
            self.assertTrue(name in {"HOME", "PATH", "TMPDIR", "PWD", "LANG", "LANGUAGE", "TZ", "LIBGL_ALWAYS_SOFTWARE",
                                     "GALLIUM_DRIVER", "GALLIUM_OVERRIDE_CPU_CAPS"}
                            or name.startswith(("LC_", "MESA_", "LP_", "__GLX_", "__EGL_")), name)
        self.assertLessEqual(found["processes"], 3)  # bubblewrap and this program
        self.assertLessEqual(set(found["root"]), {"bin", "dev", "engine", "etc", "game", "home", "in", "lib", "lib32",
                                                  "lib64", "out", "proc", "sbin", "tmp", "usr"})
        self.assertEqual(found["home"], [])
        self.assertFalse(found["sys"])

    TERMINAL = ('import json\ntry:\n    open("/dev/tty", "r+b", buffering=0).close()\n    print(json.dumps("opened"))\n'
                'except OSError as exc:\n    print(json.dumps("refused: " + type(exc).__name__))\n')

    def from_a_terminal(self, start) -> str:
        """Run ``start`` (which returns a finished process) in a child that has a terminal of its
        own, as a harness started from a shell does, and return what the program inside printed."""
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

    def test_control_outside_the_sandbox_the_harness_terminal_can_be_opened(self):
        found = self.from_a_terminal(lambda: subprocess.run(
            ["python3", "-c", self.TERMINAL], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            env=hr.game_env()))
        self.assertEqual(found, "opened")

    def test_inside_the_harness_terminal_cannot_be_opened(self):
        tool = real_tool()
        found = self.from_a_terminal(lambda: box.run(
            tool, ["python3", "-c", self.TERMINAL], timeout=60, game=self.tmp / "game", out=self.tmp / "out"))
        self.assertTrue(found.startswith("refused: "), found)

    def test_a_time_limit_ends_everything_that_was_started_inside(self):
        tool = real_tool()
        mark = "297.3141"
        with self.assertRaises(subprocess.TimeoutExpired):
            box.run(tool, ["sh", "-c", f"sleep {mark} & sleep {mark} & wait"], timeout=2,
                    game=self.tmp / "game", out=self.tmp / "out")

        def running() -> list[str]:
            left = []
            for entry in Path("/proc").iterdir():
                if entry.name.isdigit():
                    try:
                        words = (entry / "cmdline").read_bytes().split(b"\0")
                    except OSError:
                        continue
                    if mark.encode() in words:
                        left.append(entry.name)
            return left

        deadline = time.monotonic() + 10
        while running() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(running(), [])

    def test_a_file_larger_than_the_limit_cannot_be_written(self):
        tool = real_tool()
        with mock.patch.object(box, "FILE_BYTES", 1024 * 1024):
            done = box.run(tool, ["sh", "-c", "head -c 4194304 /dev/zero > /out/big; echo status=$?"], timeout=60,
                           game=self.tmp / "game", out=self.tmp / "out")
        self.assertLessEqual((self.tmp / "out" / "big").stat().st_size, 1024 * 1024)
        self.assertNotIn("status=0", done.stdout)

    def test_the_scratch_folders_hold_only_so_much(self):
        tool = real_tool()
        with mock.patch.object(box, "SCRATCH_BYTES", 4 * 1024 * 1024):
            done = box.run(tool, ["sh", "-c", "head -c 16777216 /dev/zero > /tmp/big; echo status=$?; wc -c < /tmp/big"],
                           timeout=60, game=self.tmp / "game", out=self.tmp / "out")
        lines = done.stdout.split()
        self.assertNotEqual(lines[0], "status=0", done.stdout + done.stderr)
        self.assertLessEqual(int(lines[1]), 4 * 1024 * 1024)


    def test_the_work_copy_and_the_output_folder_hold_only_so_much(self):
        tool = real_tool()
        with mock.patch.object(box, "DISK_BYTES", 4 * 1024 * 1024), mock.patch.object(box, "DISK_INTERVAL", 0.05), \
                self.assertRaisesRegex(box.DiskBoundError, "a replay may add"):
            box.run(tool, ["sh", "-c", "i=0; while :; do head -c 1048576 /dev/zero > /game/part$i; "
                           "head -c 1048576 /dev/zero > /out/part$i; i=$((i+1)); sleep 0.01; done"],
                    timeout=120, game=self.tmp / "game", out=self.tmp / "out")
        written = sum(p.stat().st_size for d in ("game", "out") for p in (self.tmp / d).iterdir())
        self.assertLess(written, 256 * 1024 * 1024, "the sandbox ran on long after the bound")

    def test_control_within_the_disk_bound_the_sandbox_runs_to_its_end(self):
        tool = real_tool()
        with mock.patch.object(box, "DISK_BYTES", 4 * 1024 * 1024):
            done = box.run(tool, ["sh", "-c", "head -c 1048576 /dev/zero > /game/part; head -c 1048576 /dev/zero > /out/part; "
                                  "echo done"], timeout=60, game=self.tmp / "game", out=self.tmp / "out")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "done"), done.stderr)

# The same attempts from inside the game: an autoload added to a copy of the bundled game.
GAME_PROBE = '''extends Node


func _ready() -> void:
	var found := {}
	var tcp := StreamPeerTCP.new()
	var status: int = StreamPeerTCP.STATUS_ERROR
	if tcp.connect_to_host("127.0.0.1", %(port)d) == OK:
		for i in 200:
			tcp.poll()
			status = tcp.get_status()
			if status != StreamPeerTCP.STATUS_CONNECTING:
				break
			OS.delay_msec(10)
	found["socket"] = status == StreamPeerTCP.STATUS_CONNECTED
	var planted := FileAccess.open("%(outside)s/planted-by-game.txt", FileAccess.WRITE)
	found["writeOutside"] = planted != null
	if planted != null:
		planted.store_string("planted")
		planted.close()
	found["readSpec"] = FileAccess.open("%(spec)s", FileAccess.READ) != null
	found["readVerifier"] = FileAccess.open("%(verifier)s", FileAccess.READ) != null
	found["readParentEnvironment"] = FileAccess.open("/proc/%(parent)d/environ", FileAccess.READ) != null
	found["secret"] = OS.get_environment("%(secret)s")
	print("EXPECTRAIL_PROBE " + JSON.stringify(found))
'''


class GameEscapeTest(unittest.TestCase):
    """The real engine and a game that tries to get out: the four things #253 names."""

    @classmethod
    def setUpClass(cls):
        cls.godot = real_godot()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-game-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "outside").mkdir()
        self.route = REPO / "harness" / "routes" / "smoke.json"
        self.spec = sorted((REPO / "agents" / "specs").glob("*.json"))[0]
        env = mock.patch.dict(os.environ, {SECRET: "s3cret", "EXPECTRAIL_GODOT_CACHE": str(self.tmp / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def hostile_game(self, port: int) -> Path:
        game = self.tmp / "game"
        shutil.copytree(REPO / "game" / "platformer", game, ignore=shutil.ignore_patterns(".godot"))
        (game / "expectrail_probe.gd").write_text(GAME_PROBE % {
            "port": port, "outside": self.tmp / "outside", "spec": self.spec,
            "verifier": REPO / "harness" / "run.py", "parent": os.getpid(), "secret": SECRET}, encoding="utf-8")
        project = (game / "project.godot").read_text(encoding="utf-8")
        self.assertIn("[autoload]\n", project)
        (game / "project.godot").write_text(
            project.replace("[autoload]\n", '[autoload]\n\nEscapeProbe="*res://expectrail_probe.gd"\n', 1), encoding="utf-8")
        return game

    def replay(self, mode: str) -> tuple[dict, dict]:
        out = self.tmp / f"run-{mode}"
        with Listener() as port:
            replay = hr.run(self.route, out, game=self.hostile_game(port), godot=self.godot, capture_frames=False,
                            sandbox=mode)
        log = (out / "godot.log").read_text(encoding="utf-8")
        line = next(ln for ln in log.splitlines() if ln.startswith("EXPECTRAIL_PROBE "))
        return replay, json.loads(line.split(" ", 1)[1])

    def test_control_without_the_sandbox_the_game_reaches_all_four(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux /proc is required by this Godot sandbox escape control")
        replay, found = self.replay("off")
        self.assertIsNone(replay["isolation"]["sandbox"])
        self.assertEqual(found, {"socket": True, "writeOutside": True, "readSpec": True, "readVerifier": True,
                                 "readParentEnvironment": True, "secret": ""})
        self.assertTrue((self.tmp / "outside" / "planted-by-game.txt").is_file())

    def test_inside_the_game_reaches_none_and_the_replay_says_it_was_isolated(self):
        real_tool()
        replay, found = self.replay("require")
        self.assertEqual(found, {"socket": False, "writeOutside": False, "readSpec": False, "readVerifier": False,
                                 "readParentEnvironment": False, "secret": ""})
        self.assertEqual(list((self.tmp / "outside").iterdir()), [])
        self.assertEqual((replay["isolation"]["network"], replay["isolation"]["filesystem"],
                          replay["isolation"]["processes"]), ("none", "confined", "own"))
        self.assertEqual(validate(replay), "replay")



# Verdict regressions for the four operations in #253's "Done when". The seeded bug
# repairs itself only if its escape succeeds. Clean and escaped controls must pass,
# so an isolated rejection cannot be credited to a broken fixture or missing model.
GATE_PROBE = """extends Node

var _cheat := false

func _ready() -> void:
	var found := {}
%(attempt)s
	_cheat = found["success"]
	print("EXPECTRAIL_GATE_PROBE " + JSON.stringify(found))
	for node in get_tree().root.find_children("*", "CharacterBody2D", true, false):
		_on_node_added(node)
	get_tree().node_added.connect(_on_node_added)

func _on_node_added(node: Node) -> void:
	if _cheat and node is CharacterBody2D and node.scene_file_path.ends_with("player/player.tscn"):
		node.collision_mask = 30
"""


class GameVerdictTest(unittest.TestCase):
    """Real headless Godot, real bubblewrap, real engine-only gate; no visual model.

    The injected replay callback only disables PNG capture, which this position
    check does not need. It runs the ordinary harness with the requested sandbox,
    returns the real trace/tree/account, and never supplies a result or verdict.
    """

    @classmethod
    def setUpClass(cls):
        real_tool()  # no display needed: these are trace-based sandbox tests
        cls.godot = real_godot()

    def setUp(self):
        from expectrail.orchestrator.sample import checkout
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-verdict-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clean = checkout(self.tmp / "clean", bug=False)
        self.bug = checkout(self.tmp / "bug", bug=True)
        self.cache = mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(self.tmp / "cache")})
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def judge(self, repo, name, mode):
        from expectrail.gate import record, verify

        probes = []

        def replay(route, game, out, frames):
            self.assertTrue(frames)  # only capture is disabled, not the gate's check
            result = hr.run(route, out, game=game, godot=self.godot,
                            capture_frames=False, sandbox=mode, within=repo)
            for line in (out / "godot.log").read_text().splitlines():
                if line.startswith("EXPECTRAIL_GATE_PROBE "):
                    probes.append(json.loads(line.split(" ", 1)[1]))
            return dict(trace=json.loads((out / "trace.json").read_text()),
                        replaySha256=hr.sha256_file(out / "replay.json"), framesDir=None,
                        isolation=result["isolation"], tree=result["game"]["tree"])

        doc = verify.run_gate(repo=repo, game="game/platformer", routes=["harness/routes/smoke.json"],
                              specs="agents/specs", out=self.tmp / name, work=self.tmp / (name + "-work"),
                              replay=replay, rule=record.ENGINE_ONLY, require_sandbox=mode == "require")
        record.check_record(record.read_record(self.tmp / name / "findings.json"))
        return doc, probes

    def cheating(self, attempt):
        game = self.bug / "game/platformer"
        (game / "expectrail_gate_probe.gd").write_text(GATE_PROBE % dict(attempt=attempt))
        project = game / "project.godot"
        text = project.read_text()
        self.assertIn("[autoload]\n", text)
        project.write_text(text.replace("[autoload]\n", '[autoload]\nGateProbe="*res://expectrail_gate_probe.gd"\n', 1))
        return self.bug

    def assertBoundary(self, attempt, fields):
        clean, _ = self.judge(self.clean, "clean-in", "require")
        self.assertEqual(clean["decision"], "accept")  # boundary allows the unchanged game
        head = self.cheating(attempt)
        outside, before = self.judge(head, "probe-out", "off")
        self.assertEqual(outside["decision"], "accept")
        self.assertEqual(before, [dict.fromkeys((*fields, "success"), True)])
        inside, after = self.judge(head, "probe-in", "require")
        self.assertEqual(after, [dict.fromkeys((*fields, "success"), False)])
        self.assertEqual(inside["decision"], "reject")
        self.assertGreater(inside["counts"]["failed"], 0)
        self.assertEqual((inside["isolation"]["replays"], inside["isolation"]["sandboxed"],
                          inside["isolation"]["required"]), (1, 1, True))
        self.assertEqual(inside["checks"][0]["after"], "fail")

    def test_socket_denial_prevents_a_game_from_repairing_itself_into_accept(self):
        with Listener() as port:
            self.assertBoundary("\n".join([
                '\tvar tcp := StreamPeerTCP.new()',
                '\tvar status: int = StreamPeerTCP.STATUS_ERROR',
                f'\tif tcp.connect_to_host("127.0.0.1", {port}) == OK:',
                '\t\tfor i in 200:', '\t\t\ttcp.poll()', '\t\t\tstatus = tcp.get_status()',
                '\t\t\tif status != StreamPeerTCP.STATUS_CONNECTING:', '\t\t\t\tbreak',
                '\t\t\tOS.delay_msec(10)',
                '\tfound["socket"] = status == StreamPeerTCP.STATUS_CONNECTED',
                '\ttcp.disconnect_from_host()', '\tfound["success"] = found["socket"]']), ["socket"])

    def test_write_denial_prevents_a_game_from_repairing_itself_into_accept(self):
        outside = self.tmp / "outside";outside.mkdir()
        self.assertBoundary("\n".join([
            f'\tvar planted := FileAccess.open({json.dumps(str(outside / "planted.txt"))}, FileAccess.WRITE)',
            '\tfound["writeOutside"] = planted != null', '\tif planted != null:',
            '\t\tplanted.store_string("canary")', '\t\tplanted.close()',
            '\tfound["success"] = found["writeOutside"]']), ["writeOutside"])
        self.assertEqual((outside / "planted.txt").read_text(), "canary")  # the outside control

    def test_check_and_verifier_reads_cannot_repair_a_game_into_accept(self):
        spec = self.clean / "agents/specs/player-stays-above-ground.json"
        verifier = REPO / "expectrail/gate/record.py"
        self.assertBoundary("\n".join([
            f'\tfound["readSpec"] = FileAccess.open({json.dumps(str(spec))}, FileAccess.READ) != null',
            f'\tfound["readVerifier"] = FileAccess.open({json.dumps(str(verifier))}, FileAccess.READ) != null',
            '\tfound["success"] = found["readSpec"] and found["readVerifier"]']), ["readSpec", "readVerifier"])

    def test_environment_secret_cannot_repair_a_game_into_accept(self):
        # A fresh process really holds this fake value in /proc/PID/environ;
        # patching this Python process's os.environ alone would not prove that.
        canary = "EXPECTRAIL_SANDBOX_CANARY=repair-canary"
        with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                              env={"EXPECTRAIL_SANDBOX_CANARY": "repair-canary"}) as child:
            try:
                self.assertBoundary("\n".join([
                    f'\tvar host := FileAccess.open("/proc/{child.pid}/environ", FileAccess.READ)',
                    f'\tfound["readSecret"] = host != null and host.get_buffer({len(canary)}).get_string_from_utf8() == {json.dumps(canary)}',
                    '\tfound["success"] = found["readSecret"]']), ["readSecret"])
            finally:
                child.terminate()
                child.wait(timeout=10)


class SameReplayTest(unittest.TestCase):
    """The sandbox must not change what is measured: same frames, same trace, on the same machine."""

    def test_the_clean_game_gives_the_same_hashes_with_and_without(self):
        godot = real_godot()
        real_tool(display=True)
        route = REPO / "harness" / "routes" / "smoke.json"
        with tempfile.TemporaryDirectory(prefix="expectrail-same-") as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(Path(tmp) / "cache")}):
            plain = hr.run(route, Path(tmp) / "plain", godot=godot, sandbox="off")
            inside = hr.run(route, Path(tmp) / "inside", godot=godot, sandbox="require")
        self.assertIsNone(plain["isolation"]["sandbox"])
        self.assertEqual(inside["isolation"]["sandbox"]["tool"], "bubblewrap")
        self.assertGreater(inside["capture"]["frames"], 0)
        self.assertEqual(inside["frameSha256"], plain["frameSha256"])
        self.assertEqual(inside["trace"]["sha256"], plain["trace"]["sha256"])
        self.assertEqual(inside["engine"], plain["engine"])


def spawn_sandbox_worker(store, job):
    """This fixture tests process lifetime, with real Godot and no visual observer."""
    from expectrail.orchestrator import runner

    code = (
        "from pathlib import Path; import sys; "
        "from expectrail.orchestrator import engines, runner; "
        "from expectrail.orchestrator.store import JobStore; "
        "runner.work(JobStore(Path(sys.argv[1]), lease_seconds=float(sys.argv[3])), sys.argv[2], "
        "engines={'godot': engines.GodotGate(rule='engine-only')}, own_group=True)"
    )
    return runner.spawn(store, job, command=[sys.executable, "-c", code, str(store.root), job, str(store.lease_seconds)])


class LostWorkerTest(unittest.TestCase):
    """A verification job whose worker is killed while the game runs in the sandbox: nothing of the
    job may be left running (#307, gap 3). Needs the real tool and the real engine, so it runs in CI."""

    def test_a_killed_workers_sandboxed_replay_dies_with_it(self):
        import signal

        from expectrail.orchestrator import request as req
        from expectrail.orchestrator import store as st

        godot = real_godot()
        real_tool(display=True)
        tmp = Path(tempfile.mkdtemp(prefix="expectrail-lost-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        store = st.JobStore(tmp / "jobs", lease_seconds=2)
        request = req.build(adapter="godot", head=REPO, game="game/platformer", routes=["harness/routes/smoke.json"],
                            specs="agents/specs", execution_class="isolated")
        job = store.create(request)[0]["id"]
        self.addCleanup(st.stop_job, job)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT": str(godot), "EXPECTRAIL_GODOT_CACHE": str(tmp / "cache")}):
            worker = spawn_sandbox_worker(store, job)

        def programs() -> list[str]:
            names = []
            for pid in st.processes_of(job) or []:
                try:
                    names.append(Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0].decode().rsplit("/", 1)[-1])
                except OSError:
                    pass
            return sorted(names)

        def replaying() -> bool:
            """The sandbox tool is running the replay itself (it lasts seconds), not the short import."""
            for pid in st.processes_of(job) or []:
                try:
                    words = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                except OSError:
                    continue
                if words[0].endswith(b"bwrap") and b"--write-movie" in words:
                    return True
            return False

        deadline = time.monotonic() + 240
        while not replaying():
            self.assertIsNone(worker.poll(), f"the worker ended before the sandboxed replay started: {store.status(job)}")
            self.assertLess(time.monotonic(), deadline, f"no sandboxed replay was started: {programs()}")
            time.sleep(0.1)
        os.kill(worker.pid, signal.SIGKILL)   # the worker alone
        worker.wait(timeout=10)
        # Nobody is asked to stop anything here: the sandbox tool was started with --die-with-parent,
        # so the kernel kills it when the worker dies, and everything inside dies with it. (The first
        # version of this test expected the sandbox to outlive the worker, as an unsandboxed game
        # does, and real bubblewrap showed otherwise.)
        deadline = time.monotonic() + 10
        while programs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(programs(), [], "the sandboxed replay outlived its worker")
        deadline = time.monotonic() + 30
        while (status := store.status(job))["phase"] not in st.FINAL:
            self.assertLess(time.monotonic(), deadline, "the job was never declared lost")
            time.sleep(0.2)
        self.assertEqual((status["phase"], status["decision"], [d["code"] for d in status["diagnostics"]]),
                         ("failed", None, ["WORKER_LOST"]))
        self.assertEqual(st.processes_of(job), [])


@unittest.skipUnless(REQUIRED or os.environ.get('EXPECTRAIL_PLAYTEST_DIAGNOSTIC') == '1',
                     '#531 real Godot + Bubblewrap intake: run in seeded-bugs with EXPECTRAIL_SANDBOX_TESTS=required; explicit local diagnostic opt-in is available')
class PlaytestIngestRealEngineTest(unittest.TestCase):
    """Collected by CI's existing tests.test_replay_sandbox invocation; no workflow edit."""

    @classmethod
    def setUpClass(cls):
        if REQUIRED:
            real_tool(True)
        real_godot()
        from tools.playtest_fall_through import record
        target = Path(os.environ.get('EXPECTRAIL_PLAYTEST_EVIDENCE', str(REPO / 'runs/run-it/playtest-ingest')))
        cls.proof = record(target, sandbox='require' if REQUIRED else 'off')
        cls.cases = {r['case']: r for r in cls.proof['cases']}

    def test_approved_ground_check_reproduces_three_times(self):
        case = self.cases['reproduced']
        self.assertEqual(case['anchorReached'], [True] * 3)
        self.assertEqual(case['baseGroundCheck'], ['fail'] * 3)
        self.assertEqual(case['reproductionKind'], 'approved')
        self.assertEqual(case['reproductionLabel'], 'approved check')
        self.assertTrue(all(n == 0 for n in case['boundaries'].values()), case['boundaries'])
        self.assertEqual(case['decision'], 'reject')
        if REQUIRED:
            self.assertEqual(self.proof['sandboxRequested'], 'require')
            self.assertTrue(all(r['isolation']['sandbox'] is not None for r in self.proof['replays']))
        else:
            self.assertEqual(self.proof['sandboxRequested'], 'off')
            self.assertTrue(all(r['isolation']['sandbox'] is None for r in self.proof['replays']))

    def test_clean_base_is_not_reproduced_without_models(self):
        case = self.cases['not-reproduced']
        self.assertEqual(case['anchorReached'], [True] * 3)
        self.assertEqual(case['baseGroundCheck'], ['pass'] * 3)
        self.assertEqual(case['reproductionKind'], 'none')
        self.assertEqual(case['reasons'], ['not-reproduced'])
        self.assertTrue(all(n == 0 for n in case['boundaries'].values()), case['boundaries'])

    def test_anchor_beyond_tolerance_stops_without_models(self):
        case = self.cases['anchor-desync']
        self.assertEqual(case['anchorReached'], [False])
        self.assertEqual(case['baseGroundCheck'], [])
        self.assertEqual(case['reproductionKind'], 'none')
        self.assertEqual(case['reasons'], ['anchor-desync'])
        self.assertTrue(all(n == 0 for n in case['boundaries'].values()), case['boundaries'])


if __name__ == "__main__":
    unittest.main()
