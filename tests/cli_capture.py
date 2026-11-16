"""Capture what a command run in-process prints, and nothing else (#561).

A test that sends a command's stdout and stderr into one buffer and parses it as JSON also catches
any warning Python prints while the command runs. A `ResourceWarning` for a socket another test left
open is printed when the garbage collector happens to run, which can be in the middle of this
command, and the buffer then starts with the warning instead of the JSON.

`command_output` records warnings while the command runs instead of printing them into the buffer,
then prints each one to the real stderr afterwards, so none is hidden. Whatever the command itself
writes, on either stream, still lands in the buffer, so a test that requires its output to be exactly
JSON still fails when the command prints anything else.
"""
import contextlib
import io
import warnings


@contextlib.contextmanager
def command_output(stdout: io.StringIO, stderr: io.StringIO | None = None):
    """Redirect stdout (and stderr, to the same buffer unless another is given) for the block."""
    caught: list[warnings.WarningMessage] = []
    try:
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stdout if stderr is None else stderr):
            yield
    finally:
        for w in caught:
            warnings.showwarning(w.message, w.category, w.filename, w.lineno, None, w.line)
