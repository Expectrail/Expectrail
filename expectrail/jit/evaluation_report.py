"""Statistical summaries of aggregate counts for the release evaluation (#282)."""

from collections.abc import Mapping
import math


_TAIL_95 = 0.025
_MIN_STRATUM = 10
_VERDICTS = ("accept", "reject", "needs-review")
_TRUTH = (
    ("wrong", "Wrong fix"),
    ("correct", "Correct fix"),
    ("intentional-or-harmless", "Intentional or harmless"),
)


def _check_counts(*values: int) -> None:
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("counts must be nonnegative integers")


def _check_rate(events: int, trials: int) -> None:
    _check_counts(events, trials)
    if events > trials:
        raise ValueError("event count exceeds its denominator")


def _upper_bound(events: int, trials: int) -> float:
    """Find the probability at which the inclusive lower binomial tail is 0.025."""
    if events == trials:
        return 1.0
    if events == 0:
        return -math.expm1(math.log(_TAIL_95) / trials)
    log_factorial = math.lgamma(trials + 1)
    log_coefficients = tuple(
        log_factorial - math.lgamma(observed + 1) - math.lgamma(trials - observed + 1)
        for observed in range(events + 1)
    )
    lo, hi = 0.0, 1.0
    for _ in range(55):
        mid = (lo + hi) / 2
        log_p, log_not_p = math.log(mid), math.log1p(-mid)
        tail = math.fsum(
            math.exp(coefficient + observed * log_p + (trials - observed) * log_not_p)
            for observed, coefficient in enumerate(log_coefficients)
        )
        if tail > _TAIL_95:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def exact_interval(events: int, trials: int) -> tuple[float, float]:
    """Return the two-sided 95% Clopper–Pearson interval as proportions."""
    _check_rate(events, trials)
    if trials == 0:
        raise ValueError("an exact interval requires at least one observation")
    # Interchanging successes and failures reflects the upper limit into the lower one.
    return 1 - _upper_bound(trials - events, trials), _upper_bound(events, trials)


def exact_mcnemar(first_only: int, second_only: int) -> float:
    """Return the two-sided exact McNemar p-value for paired discordances."""
    _check_counts(first_only, second_only)
    discordant = first_only + second_only
    if first_only == second_only:
        return 1.0
    tail_count = sum(math.comb(discordant, i) for i in range(min(first_only, second_only) + 1))
    return min(1.0, 2 * tail_count / (1 << discordant))


def render_rate(events: int, trials: int, *, stratum_size: int | None = None) -> str:
    """Render a rate for a supplied count and denominator, respecting the stratum minimum."""
    _check_rate(events, trials)
    population = trials if stratum_size is None else stratum_size
    _check_counts(population)
    if population < trials:
        raise ValueError("the stratum size is smaller than the rate denominator")
    if trials == 0 or population < _MIN_STRATUM:
        return f"{events}/{trials}"
    lower, upper = exact_interval(events, trials)
    interval = f"Exact 95% interval {lower:.2%}–{upper:.2%}."
    if events == 0:
        bound = min(1.0, 3 / trials)
        return (f"None observed in {trials}. The rate is probably below {bound:.2%} "
                f"(rule of three). {interval}")
    return f"{events}/{trials} ({events / trials:.2%}). {interval}"


def render_pair(first_only: int, second_only: int, paired_total: int) -> str:
    """Render the discordant counts and, for a large enough stratum, the exact paired test."""
    _check_counts(first_only, second_only, paired_total)
    if first_only + second_only > paired_total:
        raise ValueError("the discordances exceed the number of paired observations")
    counts = f"First only {first_only}. Second only {second_only}. Paired total {paired_total}."
    if paired_total < _MIN_STRATUM:
        return counts
    return f"{counts} Exact McNemar p = {exact_mcnemar(first_only, second_only):.6g}."


def render_truth_table(table: Mapping[str, Mapping[str, int]]) -> str:
    """Render one arm and stratum from its aggregate truth-by-verdict counts."""
    if not isinstance(table, Mapping) or set(table) != {key for key, _ in _TRUTH}:
        raise ValueError("the table must include the three public truth rows")
    rows = []
    for key, label in _TRUTH:
        values = table[key]
        if not isinstance(values, Mapping) or set(values) != set(_VERDICTS):
            raise ValueError("a truth row must include the three public verdicts")
        counts = tuple(values[verdict] for verdict in _VERDICTS)
        _check_counts(*counts)
        rows.append((label, counts))
    lines = ["| Truth | Accept | Reject | Needs review | Total |", "| --- | ---: | ---: | ---: | ---: |"]
    totals = tuple(map(sum, zip(*(counts for _, counts in rows))))
    for label, (accept, reject, review) in [*rows, ("Total", totals)]:
        lines.append(f"| {label} | {accept} | {reject} | {review} | {accept + reject + review} |")
    return "\n".join(lines) + "\n"
