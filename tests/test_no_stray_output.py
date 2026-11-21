"""#561: a warning printed while a command runs in-process must not land in the buffer a test parses.

The nightly platform test saw `tests.test_ingest_generated` fail once in the full suite: the command
exited 2 (needs-review, as expected), but its captured output was not JSON at its first character.
Its stdout and stderr went into one buffer, and the suite printed `ResourceWarning: unclosed socket`
lines for the listening socket `agents/check_pages.py` never closed. Such a warning is printed when
the garbage collector runs, so it can land inside any later test's captured output.
"""
import contextlib
import gc
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock
import warnings

from tests import cli_capture


def _leak_a_socket_in_a_cycle() -> None:
    """An open socket only the garbage collector can free, as a leaked server's socket is."""
    holder: dict = {"socket": socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
    holder["self"] = holder


def _command(stdout_text: str, stderr_text: str = "", *, leak: bool = True) -> int:
    """A stand-in for `cli.main([... '--json'])` during which the garbage collector runs."""
    if leak:
        _leak_a_socket_in_a_cycle()
    gc.collect()
    if stderr_text:
        print(stderr_text, file=sys.stderr)
    print(stdout_text)
    return 2


class CommandOutput(unittest.TestCase):
    def setUp(self):
        gc.collect()  # nothing from earlier tests is collected inside the block under test

    def test_one_buffer_without_the_helper_shows_the_failure(self):
        # The pattern the tests used before: a warning printed mid-command breaks the JSON parse.
        output = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter("always", ResourceWarning)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                _command(json.dumps({"id": "job"}))
        self.assertIn("ResourceWarning", output.getvalue())
        with self.assertRaises(json.JSONDecodeError):
            json.loads(output.getvalue())

    def test_the_helper_keeps_the_buffer_to_the_command_and_still_shows_the_warning(self):
        output, real_stderr = io.StringIO(), io.StringIO()
        with warnings.catch_warnings(), contextlib.redirect_stderr(real_stderr):
            warnings.simplefilter("always", ResourceWarning)
            with cli_capture.command_output(output):
                code = _command(json.dumps({"id": "job"}))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue()), {"id": "job"})
        self.assertNotIn("ResourceWarning", output.getvalue())
        self.assertIn("ResourceWarning", real_stderr.getvalue())  # printed after the block, not hidden

    def test_what_the_command_writes_on_stderr_still_lands_in_the_buffer(self):
        # The tests that parse the buffer as JSON still fail if the command itself prints anything else.
        output = io.StringIO()
        with cli_capture.command_output(output):
            _command(json.dumps({"id": "job"}), stderr_text="expectrail: something went wrong", leak=False)
        self.assertIn("expectrail: something went wrong", output.getvalue())
        with self.assertRaises(json.JSONDecodeError):
            json.loads(output.getvalue())

    def test_a_separate_stderr_buffer_when_asked(self):
        out, err = io.StringIO(), io.StringIO()
        with cli_capture.command_output(out, err):
            _command("{}", stderr_text="note", leak=False)
        self.assertEqual((out.getvalue(), err.getvalue()), ("{}\n", "note\n"))


class PageCheckClosesItsServer(unittest.TestCase):
    def test_check_pages_leaves_no_socket_open(self):
        # The source of the warnings the suite printed: check() shut its server down but never closed
        # the listening socket. A site with no pages needs no browser, so a stand-in module will do.
        from agents import check_pages

        fake = types.ModuleType("playwright.sync_api")
        fake.sync_playwright = None
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                              "playwright.sync_api": fake}), \
                warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            self.assertEqual(check_pages.check(Path(tmp), offline=True, browser=object()), [])
            gc.collect()
        leaks = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(leaks, [])



class GatewayBridgeClosesItsSockets(unittest.TestCase):
    def test_both_sockets_of_a_finished_connection_are_closed(self):
        # The suite also printed unclosed-socket warnings from threads: the bridge's pumps shut both
        # sockets down but never closed them. Once both directions stop, both are now closed.
        import threading
        from agents import gateway_bridge

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            client, client_end = socket.socketpair()
            upstream, upstream_end = socket.socketpair()
            before = set(threading.enumerate())
            gateway_bridge.join(client, upstream)
            pumps = [t for t in threading.enumerate() if t not in before]
            client_end.sendall(b"ping")
            self.assertEqual(upstream_end.recv(4), b"ping")
            upstream_end.sendall(b"pong")
            self.assertEqual(client_end.recv(4), b"pong")
            client_end.close()
            for t in pumps:
                t.join(5)
            self.assertFalse(any(t.is_alive() for t in pumps))
            self.assertEqual((client.fileno(), upstream.fileno()), (-1, -1))  # closed
            upstream_end.close()
            gc.collect()
        self.assertEqual([str(w.message) for w in caught if issubclass(w.category, ResourceWarning)], [])

    def test_a_refused_upstream_leaves_no_socket_open(self):
        from agents import gateway_bridge

        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            socket_path = str(Path(tmp) / "gateway.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as bound:
                # A bound socket which has not started listening refuses connections.
                bound.bind(socket_path)
                upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.addCleanup(upstream.close)
                client, peer = socket.socketpair()
                self.addCleanup(client.close)
                self.addCleanup(peer.close)
                listener = mock.Mock()
                listener.accept.side_effect = [(client, None), OSError("listener closed")]

                with mock.patch.object(gateway_bridge.socket, "socket", return_value=upstream):
                    gateway_bridge._serve(listener, socket_path)

                self.assertEqual(listener.accept.call_count, 2)
                self.assertEqual((client.fileno(), upstream.fileno()), (-1, -1))


if __name__ == "__main__":
    unittest.main()
