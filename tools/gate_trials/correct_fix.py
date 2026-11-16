"""Prepare the correct-fix trial locally; print, never execute, push commands."""
from .build import script

if __name__ == "__main__":
    raise SystemExit(script('correct-fix'))
