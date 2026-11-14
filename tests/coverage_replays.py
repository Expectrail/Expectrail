"""Complete successful replay stand-ins without changing their recorded positions or bug evidence."""
import copy


def complete_trace(trace: dict, ticks: int) -> dict:
    """Hold each fixture sample until the next sample; emit one real row per requested tick.

    The old fixtures are sparse keyframes, not successful full replays. Only stand-ins claiming
    to finish a route use this helper. Truncation tests deliberately keep their short records.
    """
    samples = sorted(trace["rows"], key=lambda row: row["tick"])
    rows, index = [], 0
    for tick in range(ticks):
        while index + 1 < len(samples) and samples[index + 1]["tick"] <= tick:
            index += 1
        rows.append(dict(copy.deepcopy(samples[index]), tick=tick))
    return dict(trace, rows=rows, ticks=ticks, unknownActions=[])
