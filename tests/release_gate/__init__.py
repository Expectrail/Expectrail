"""The release gate suite (#258): one control per row, each asserting that clearance is not granted.

The table of controls is ``controls.py``. The tests are in the ``gate_*.py`` modules of this folder;
they are named so that the main suite (``python3 -m unittest discover -s tests``) does not collect
them, because most start the real engine. Run them, and write the summary, with

    python3 -m tools.release_gate [--require] [--out docs/release-gate.md] [--json FILE]

``tests/test_release_gate.py`` (in the main suite) holds the table and the summary to their rules
without starting anything.
"""
