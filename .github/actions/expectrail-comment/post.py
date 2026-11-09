"""Entry point for the comment action, run as ``python3 -I post.py``.

Isolated mode (-I) ignores PYTHON* environment variables and the user's site-packages and does not
put the current directory or this script's directory on the import path. The only path added is
this action's own repository root (three folders up), so the code that runs is the pinned
Expectrail commit's and nothing from the downloaded artifact or the workspace can be imported.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from expectrail.gate.comment import main  # noqa: E402

sys.exit(main())
