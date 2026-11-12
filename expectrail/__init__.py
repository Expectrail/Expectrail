"""Expectrail: shared contracts and the reference evaluator."""

__version__ = "0.1.0"

# An installed copy carries the harness and the bundled game inside the package, under `_bundle`
# (see expectrail.resources). The harness is imported as `harness`, so that folder goes on the module
# path, first: this package's own harness is the one it must run. A clone has no such folder.
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_bundle = _Path(__file__).resolve().parent / "_bundle"
if _bundle.is_dir() and str(_bundle) not in _sys.path:
    _sys.path.insert(0, str(_bundle))
del _sys, _Path, _bundle
