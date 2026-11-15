"""Capture spike (#246): can a supervisor capture Godot frames the game cannot forge, frame-aligned?

Research code, not product code: nothing in Expectrail calls this. It replays the bundled game on a
route the way ``harness.run`` does (same copy of the game, same Godot command, Movie Maker on), but:

- the virtual display (Xvfb) is started by this process, the supervisor, and keeps its screen in a
  file (``-fbdir``) inside a folder only the supervisor's user can open;
- Godot runs as another user (``setpriv``, uid 65534 by default), so it cannot open that folder,
  signal the display server or read its memory;
- the supervisor reads the screen from that file.

Three ways to run (``--mode``):

``plain``   the game as another user on the supervisor's display; nothing grabbed (the baseline time)
``step``    approach 1: an autoload (``step.gd``) holds the engine after each drawn frame until the
            supervisor has grabbed the screen, once at once and once after ``--settle`` ms
``sample``  approach 2: no holding; the supervisor grabs the screen at random moments while the game
            runs, and each grab is looked for among the frames Movie Maker wrote

``--forge`` adds ``forge.gd``, a stand-in for a change that rewrites ten of Movie Maker's frames
after they were written. ``--reach`` makes the game try to read, write and plant files beside the
supervisor's screen file.

Each run writes ``spike.json`` (and the supervisor's grabs as PNG) under ``--out``. Requires root
(to start the game as another user), Xvfb, setpriv and Godot. Nothing here calls a model.
"""
