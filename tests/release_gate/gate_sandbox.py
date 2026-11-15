"""Release gate, candidate interference (#258): reading a private path, and network egress; and,
under operations, the disk quota (``DiskQuotaTest`` at the end).

The change here is the seeded fall-through bug carrying a cheat: an autoload added to the game that
tries to read a file outside its checkout, or to connect to a port on this machine, and repairs the
bug at run time (the player's collision mask put back to the unchanged game's value as the player
enters the scene) only when it succeeds. Such a build behaves like the unchanged game exactly when
something outside the change tells it to: a held-out route it could read, a server that tells it it
is being watched.

The control is the same command with the replay sandbox turned off (``EXPECTRAIL_SANDBOX=off``):
the cheat reads the file, or reaches the port, repairs itself, draws the unchanged game's frames, and
is cleared. So the cheat works where there is no boundary, and a refusal inside is the sandbox's
doing. The tests then ask for the isolated class (``--execution-class isolated``: every replay in the
sandbox, or nothing runs): the cheat reaches nothing, the bug stays, and the change is rejected. The
probe's own line in the head replay's ``godot.log`` says what it reached, so the test also shows the
probe ran and was refused, not that it never ran.

What this covers and what it does not: the isolated class. The default class, ``diagnostic``,
sandboxes a replay only where the machine can; where it cannot, the control above is what a change
can do. The private file here is a stand-in kept beside the test's checkouts; no held-out material is
read by these tests.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import unittest
from pathlib import Path

from tests.release_gate.common import GAME, REQUIRED, GateCase

PROBE = "EXPECTRAIL_PROBE "

# An autoload: it tries both ways out, says what it reached, and repairs the seeded bug only when the
# one named by %(trigger)s succeeded.
CHEAT = '''extends Node

var _cheat := false


func _ready() -> void:
	var found := {}
	var private := FileAccess.open("%(private)s", FileAccess.READ)
	found["readPrivate"] = private != null and private.get_as_text().strip_edges() == "repair"
	var tcp := StreamPeerTCP.new()
	var status: int = StreamPeerTCP.STATUS_ERROR
	if tcp.connect_to_host("127.0.0.1", %(port)d) == OK:
		for i in 200:
			tcp.poll()
			status = tcp.get_status()
			if status != StreamPeerTCP.STATUS_CONNECTING:
				break
			OS.delay_msec(10)
	found["egress"] = status == StreamPeerTCP.STATUS_CONNECTED
	tcp.disconnect_from_host()
	_cheat = found["%(trigger)s"]
	print("%(marker)s" + JSON.stringify(found))
	# The player may be in the scene already, or may come later: repair it either way.
	for node in get_tree().root.find_children("*", "CharacterBody2D", true, false):
		_on_node_added(node)
	get_tree().node_added.connect(_on_node_added)


func _on_node_added(node: Node) -> void:
	if _cheat and node is CharacterBody2D and node.scene_file_path.ends_with("player/player.tscn"):
		node.collision_mask = 30
'''


def sandbox_missing() -> str | None:
    """Why the replay sandbox (with a display inside) cannot run here, or None when it can."""
    from harness import sandbox as box

    tool, why = box.probe(True)
    return None if tool is not None else (why or "the sandbox could not be started")


class Listener:
    """A port on this machine's loopback that accepts every connection (and counts them)."""

    def __enter__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.accepted = 0
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.accepted += 1
            conn.close()

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def __exit__(self, *exc):
        self._stop = True
        self.sock.close()


class SandboxCase(GateCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        why = sandbox_missing()
        if why:
            if REQUIRED:
                raise AssertionError(f"EXPECTRAIL_RELEASE_GATE=required and the replay sandbox cannot run here: {why}")
            raise unittest.SkipTest(f"the replay sandbox cannot run here ({why}); see `expectrail doctor --isolated`")

    def cheating(self, name: str, trigger: str, port: int) -> Path:
        """The seeded bug, carrying the cheat; the private file it looks for is written beside it."""
        private = self.tmp / "private" / "held-out.txt"
        private.parent.mkdir(exist_ok=True)
        private.write_text("repair\n", encoding="utf-8")
        head = self.copy(name, self.bug)
        game = head / GAME
        (game / "expectrail_cheat.gd").write_text(CHEAT % {
            "private": private, "port": port, "trigger": trigger, "marker": PROBE}, encoding="utf-8")
        project = (game / "project.godot").read_text(encoding="utf-8")
        self.assertIn("[autoload]\n", project)
        (game / "project.godot").write_text(
            project.replace("[autoload]\n", '[autoload]\n\nCheat="*res://expectrail_cheat.gd"\n', 1), encoding="utf-8")
        return head

    def probes(self, status: dict) -> list[dict]:
        """What the cheat said it reached, from every replay of the job that ran it."""
        found = []
        logs = [p for p in self.jobs.rglob("godot.log") if status["id"] in p.parts]
        for log in sorted(logs):
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(PROBE):
                    found.append(json.loads(line[len(PROBE):]))
        return found

    def run_cheat(self, trigger: str, sandboxed: bool) -> tuple[int, dict | None, str, list[dict], int]:
        with Listener() as listener:
            head = self.cheating(f"cheat-{trigger}-{'in' if sandboxed else 'out'}", trigger, listener.port)
            if sandboxed:
                code, status, err = self.verify(head, "--execution-class", "isolated", base=self.clean)
            else:
                code, status, err = self.verify(head, base=self.clean, env={"EXPECTRAIL_SANDBOX": "off"})
            accepted = listener.accepted
        self.assertIsNotNone(status, err)
        return code, status, err, self.probes(status), accepted

    def assertCheatWorked(self, trigger: str) -> None:
        code, status, err, probes, accepted = self.run_cheat(trigger, sandboxed=False)
        self.assertTrue(probes, f"the cheat's line is in no replay's log. {err}")
        self.assertTrue(all(p[trigger] for p in probes), probes)
        if trigger == "egress":
            self.assertGreater(accepted, 0)
        # Without the boundary the cheat repairs the bug and the change is cleared: the frames are
        # the unchanged game's, so every vision question is answered from its recording.
        self.assertEqual((code, status["decision"]), (0, "accept"), err)

    def assertCheatRefused(self, trigger: str) -> None:
        code, status, err, probes, accepted = self.run_cheat(trigger, sandboxed=True)
        self.assertNotCleared(code, status, err)
        self.assertTrue(probes, f"the cheat's line is in no replay's log, so it is not shown to have run. {err}")
        self.assertEqual([p[trigger] for p in probes], [False] * len(probes), probes)
        if trigger == "egress":
            self.assertEqual(accepted, 0)
        self.assertEqual((code, status["decision"]), (1, "reject"), err)


class PrivatePathTest(SandboxCase):
    def test_the_isolated_class_clears_the_unchanged_game(self):
        # The positive control for both rows: in the sandbox the unchanged game is cleared, so a
        # reject there is the bug's, not the sandbox's.
        code, status, err = self.verify(self.clean, "--execution-class", "isolated", base=self.clean)
        self.assertEqual((code, status["phase"], status["decision"]), (0, "completed", "accept"), err)

    def test_control_without_the_sandbox_a_change_that_reads_a_private_file_is_cleared(self):
        self.assertCheatWorked("readPrivate")

    def test_in_the_isolated_class_a_change_cannot_read_a_private_file_and_is_rejected(self):
        self.assertCheatRefused("readPrivate")


class EgressTest(SandboxCase):
    def test_control_without_the_sandbox_a_change_that_reaches_a_port_is_cleared(self):
        self.assertCheatWorked("egress")

    def test_in_the_isolated_class_a_change_cannot_reach_a_port_and_is_rejected(self):
        self.assertCheatRefused("egress")



# An autoload for the disk quota: it writes FILLER_MB files of 1 MB into the game's own folder (the
# only place on the machine's disk the sandbox lets it write, besides its output folder), then says
# how much it wrote. It changes nothing else, so a game carrying it plays as the unchanged game.
FILLER = '''extends Node


func _ready() -> void:
	var root := ProjectSettings.globalize_path("res://")
	var chunk := PackedByteArray()
	chunk.resize(1048576)
	chunk.fill(120)
	var written := 0
	for i in %(megabytes)d:
		var f := FileAccess.open(root.path_join("filler-%%d.bin" %% i), FileAccess.WRITE)
		if f == null:
			break
		f.store_buffer(chunk)
		f.close()
		written += 1
	print("%(marker)s" + JSON.stringify({"megabytes": written}))
'''
FILLER_MB = 96
DISK_BOUND = 32 * 1024 * 1024   # lowered for the test through $EXPECTRAIL_SANDBOX_DISK_BYTES


class DiskQuotaTest(SandboxCase):
    """A change that fills the disk is stopped at the sandbox's bound and is not cleared.

    The change is the unchanged game carrying ``FILLER``. The control is the same change with the
    sandbox off, where nothing bounds what it writes: it writes all of it, plays as the unchanged
    game, and is cleared. So the stop inside is the bound's doing. The bound is lowered for the test
    (32 MB, where the default is 4 GiB) only so the test writes little; the mechanism is the same."""

    def filling(self, name: str) -> Path:
        head = self.copy(name)
        game = head / GAME
        (game / "expectrail_filler.gd").write_text(FILLER % {"megabytes": FILLER_MB, "marker": PROBE}, encoding="utf-8")
        project = (game / "project.godot").read_text(encoding="utf-8")
        self.assertIn("[autoload]\n", project)
        (game / "project.godot").write_text(
            project.replace("[autoload]\n", '[autoload]\n\nFiller="*res://expectrail_filler.gd"\n', 1), encoding="utf-8")
        return head

    def written(self) -> int:
        return sum(p.stat().st_size for p in self.jobs.rglob("filler-*.bin") if p.is_file())

    def test_control_without_the_sandbox_a_change_that_fills_the_disk_writes_it_all_and_is_cleared(self):
        code, status, err = self.verify(self.filling("fill-out"), base=self.clean,
                                        env={"EXPECTRAIL_SANDBOX": "off", "EXPECTRAIL_SANDBOX_DISK_BYTES": str(DISK_BOUND)})
        self.assertIsNotNone(status, err)
        probes = self.probes(status)
        self.assertTrue(probes, f"the filler's line is in no replay's log. {err}")
        self.assertEqual({p["megabytes"] for p in probes}, {FILLER_MB}, probes)
        self.assertEqual((code, status["decision"]), (0, "accept"), err)

    def test_in_the_isolated_class_a_change_that_fills_the_disk_is_stopped_and_not_cleared(self):
        code, status, err = self.verify(self.filling("fill-in"), "--execution-class", "isolated", base=self.clean,
                                        env={"EXPECTRAIL_SANDBOX_DISK_BYTES": str(DISK_BOUND)})
        self.assertIsNotNone(status, err)
        self.assertNotCleared(code, status, err)
        # Stopped near the bound, and what it wrote did not stay on the machine's disk.
        self.assertLess(self.written(), FILLER_MB * 1024 * 1024 // 2, "the filler's files were kept")
        record = next(self.jobs.rglob("findings.json"), None)
        self.assertIsNotNone(record, f"the job left no record. {err}")
        reasons = {f.get("reason") for f in json.loads(record.read_text(encoding="utf-8"))["findings"]}
        self.assertIn("the head replay was stopped: the game wrote more to its folders than the replay sandbox allows",
                      reasons, err)
