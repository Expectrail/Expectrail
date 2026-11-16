"""Prepare the branch-enforcement trial locally; print, never execute, push commands."""
from .build import script

if __name__ == "__main__":
    raise SystemExit(script('branch-enforcement'))
