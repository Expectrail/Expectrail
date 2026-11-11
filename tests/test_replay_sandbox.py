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
    named = os.environ.get("EXPECTRAIL_GODOT")
    found = [Path(named)] if named else sorted((REPO / "tools" / "godot").glob("Godot_v*"))
    found = [p for p in found if p.is_file()]
    if not found:
        if REQUIRED:
            raise AssertionError("this job must have Godot: run harness/get_godot.sh first")
        raise unittest.SkipTest("Godot is not downloaded (harness/get_godot.sh)")
    return found[0]


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
            "limits": {"scratchBytes": box.SCRATCH_BYTES, "fileBytes": box.FILE_BYTES, "processes": box.PROCESSES}})

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


if __name__ == "__main__":
    unittest.main()
