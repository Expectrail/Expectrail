"""The macOS suite job's summary (#378): the count, the result line and every failing test, from the log.

    python3 -m tools.macos_suite_summary SUITE_LOG SUMMARY_FILE

It says only what the log shows. A log with no final result line (empty, cut off by the time limit, or
missing) is reported as a suite that did not finish, never as a pass. It always exits 0: the job reports
and does not gate.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_RAN = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s$", re.M)
_RESULT = re.compile(r"^(?:OK|FAILED)\b.*$", re.M)
_FAILING = re.compile(r"^((?:FAIL|ERROR): .+)$", re.M)


def summarize(log: str) -> dict:
    ran = _RAN.findall(log)
    results = _RESULT.findall(log)
    return {
        "ran": int(ran[-1][0]) if ran else None,
        "seconds": float(ran[-1][1]) if ran else None,
        "result": results[-1].strip() if results else None,
        "failing": sorted(set(line.strip() for line in _FAILING.findall(log))),
        "complete": bool(ran and results),
    }


def render(found: dict, *, missing: bool = False) -> str:
    lines = ["## The suite on macOS (report only, #378)", ""]
    if missing:
        lines.append("- The suite wrote no log: it did not run, so there is nothing to count.")
        return "\n".join(lines) + "\n"
    if found["ran"] is not None:
        lines.append(f"- Ran: {found['ran']} tests in {found['seconds']:.0f} s")
    else:
        lines.append("- Ran: the suite did not report a count")
    if found["complete"]:
        lines.append(f"- Result: `{found['result']}`")
    else:
        lines.append("- Result: none: the suite did not finish (no final OK or FAILED line)")
    lines.append(f"- Failing or erroring tests: {len(found['failing'])}")
    if found["failing"]:
        lines.append("")
        lines += [f"  - `{name}`" for name in found["failing"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 -m tools.macos_suite_summary SUITE_LOG SUMMARY_FILE", file=sys.stderr)
        return 0
    log, out = Path(argv[0]), Path(argv[1])
    if log.is_file():
        text = render(summarize(log.read_text(encoding="utf-8", errors="replace")))
    else:
        text = render({}, missing=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
