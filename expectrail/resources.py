"""Where Expectrail's own files are: the schemas, the harness, the bundled game and its sample bug.

In a clone they sit beside the ``expectrail`` package, at the repository's root. In an installed
copy (a wheel) they are inside it, under ``expectrail/_bundle``, laid out as the repository is:
``contracts/``, ``harness/``, ``game/platformer``, and the few other files a verification needs.
``ROOT`` is whichever of the two this copy has, so code names a file one way in both.

An installed copy also puts ``_bundle`` on the module path (``expectrail/__init__.py``), because the
harness is imported as ``harness`` and not yet as part of the ``expectrail`` package.
"""
from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
BUNDLE = PACKAGE / "_bundle"
INSTALLED = BUNDLE.is_dir()
ROOT = BUNDLE if INSTALLED else PACKAGE.parent
