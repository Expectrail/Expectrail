"""Runs inside the Muse sandbox: the only way out of it is this bridge to the key gateway.

The sandbox has no network (bubblewrap --unshare-net), so Muse Code cannot ignore HTTPS_PROXY
and go elsewhere. This listens on 127.0.0.1 inside the sandbox, forwards every connection to the
gateway's Unix socket (bound in at /gateway), and runs the command after ``--`` as its child,
exiting with its status. Standard library only: it runs under the system Python in the sandbox.

    python3 /gateway/bridge.py --port 8899 --socket /gateway/gw.sock -- muse exec ...
"""
from __future__ import annotations

import argparse
import signal
import socket
import subprocess
import sys
import threading


def _pump(src: socket.socket, dst: socket.socket, pair: dict) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # The second direction to stop closes both sockets, so neither is left for the garbage
        # collector (#561) and neither is closed while the other direction still uses it.
        with pair["lock"]:
            pair["open"] -= 1
            last = pair["open"] == 0
        if last:
            src.close()
            dst.close()


def join(client: socket.socket, upstream: socket.socket) -> None:
    """Copy bytes both ways between two connected sockets; both are closed once both directions stop."""
    pair = {"lock": threading.Lock(), "open": 2}
    for a, b in ((client, upstream), (upstream, client)):
        threading.Thread(target=_pump, args=(a, b, pair), daemon=True).start()


def _serve(listener: socket.socket, socket_path: str) -> None:
    while True:
        try:
            client, _ = listener.accept()
        except OSError:
            return
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except OSError:
            client.close()
            continue
        try:
            upstream.connect(socket_path)
        except OSError:
            upstream.close()
            client.close()
            continue
        join(client, upstream)


def listen(port: int, socket_path: str) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(64)
    threading.Thread(target=_serve, args=(listener, socket_path), daemon=True).start()
    return listener


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("gateway bridge: missing -- before the command", file=sys.stderr)
        return 2
    cut = argv.index("--")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--socket", required=True)
    args = p.parse_args(argv[:cut])
    command = argv[cut + 1:]
    if not command:
        print("gateway bridge: no command after --", file=sys.stderr)
        return 2
    listen(args.port, args.socket)
    child = subprocess.Popen(command)
    signal.signal(signal.SIGTERM, lambda *_: child.terminate())
    return child.wait()


if __name__ == "__main__":
    sys.exit(main())
