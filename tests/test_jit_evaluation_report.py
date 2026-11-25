from itertools import product
import math
import unittest

from expectrail.jit import evaluation_report as report


TABLE = {
    "wrong": {"accept": 1, "reject": 14, "needs-review": 5},
    "correct": {"accept": 12, "reject": 2, "needs-review": 1},
    "intentional-or-harmless": {"accept": 4, "reject": 0, "needs-review": 1},
}


class EvaluationReportTest(unittest.TestCase):
    def test_exact_interval_matches_closed_form_small_samples(self):
        lower, upper = report.exact_interval(1, 2)
        self.assertAlmostEqual(lower, 1 - math.sqrt(0.975), places=12)
        self.assertAlmostEqual(upper, math.sqrt(0.975), places=12)

    def test_exact_interval_matches_zero_and_all_event_boundaries(self):
        low, high = report.exact_interval(0, 20)
        self.assertEqual(low, 0)
        self.assertAlmostEqual(high, 1 - 0.025 ** (1 / 20), places=12)
        low, high = report.exact_interval(20, 20)
        self.assertAlmostEqual(low, 0.025 ** (1 / 20), places=12)
        self.assertEqual(high, 1)

    def test_intermediate_exact_bounds_match_binomial_tails(self):
        events, trials = 3, 27
        lower, upper = report.exact_interval(events, trials)

        def tail(start, stop, p):
            return sum(math.comb(trials, k) * p ** k * (1 - p) ** (trials - k)
                       for k in range(start, stop))

        self.assertAlmostEqual(tail(events, trials + 1, lower), 0.025, places=12)
        self.assertAlmostEqual(tail(0, events + 1, upper), 0.025, places=12)

    def test_rates_render_zero_events_as_none_observed_and_show_exact_interval(self):
        self.assertEqual(report.render_rate(0, 20),
                         "None observed in 20. The rate is probably below 15.00% "
                         "(rule of three). Exact 95% interval 0.00%–16.84%.")
        self.assertIn("2/10 (20.00%)", report.render_rate(2, 10))

    def test_small_strata_show_raw_counts_even_for_zero_events(self):
        self.assertEqual(report.render_rate(0, 9), "0/9")
        self.assertEqual(report.render_rate(0, 0), "0/0")
        self.assertEqual(report.render_pair(0, 0, 9), "First only 0. Second only 0. Paired total 9.")
        self.assertIn("Exact 95% interval", report.render_rate(2, 6, stratum_size=12))

    def test_exact_paired_test_uses_discordance(self):
        self.assertEqual(report.exact_mcnemar(1, 3), 0.625)
        self.assertEqual(report.exact_mcnemar(3, 1), 0.625)
        self.assertEqual(report.exact_mcnemar(0, 3), 0.25)
        self.assertEqual(report.exact_mcnemar(2, 2), 1)
        self.assertEqual(report.exact_mcnemar(0, 0), 1)
        self.assertEqual(report.render_pair(1, 3, 20),
                         "First only 1. Second only 3. Paired total 20. Exact McNemar p = 0.625.")

    def test_truth_table_keeps_all_three_rows_and_denominators(self):
        rendered = report.render_truth_table(TABLE)
        for line in (
            "| Wrong fix | 1 | 14 | 5 | 20 |",
            "| Correct fix | 12 | 2 | 1 | 15 |",
            "| Intentional or harmless | 4 | 0 | 1 | 5 |",
            "| Total | 17 | 16 | 7 | 40 |",
        ):
            self.assertIn(line, rendered)

    def test_invalid_counts_fail_closed(self):
        for call, args in (
            (report.exact_interval, (0, 0)),
            (report.render_rate, (True, 20)),
            (report.render_rate, (-1, 20)),
            (report.render_rate, (21, 20)),
            (report.render_pair, (6, 5, 10)),
            (report.exact_mcnemar, (1.5, 3)),
        ):
            with self.subTest(call=call.__name__, args=args), self.assertRaises(ValueError):
                call(*args)
        with self.assertRaises(ValueError):
            report.render_rate(1, 10, stratum_size=9)
        with self.assertRaises(ValueError):
            report.render_truth_table({"wrong": TABLE["wrong"]})
        with self.assertRaises(ValueError):
            report.render_truth_table({**TABLE, "wrong": {"accept": 1, "reject": 14}})
        with self.assertRaises(ValueError):
            report.render_truth_table({**TABLE, "wrong": {**TABLE["wrong"], "accept": True}})


class RepeatStabilityTest(unittest.TestCase):
    def test_every_ordered_triple_counts_candidate_disagreement_and_any_accept(self):
        verdicts = ("accept", "reject", "needs-review")
        histogram = dict.fromkeys(product(verdicts, repeat=3), 1)

        summary = report.summarize_repeats(histogram, expected_candidates=27)

        self.assertEqual(summary.total, 27)
        self.assertEqual(summary.unstable, 24)
        self.assertEqual(summary.any_accept, 19)

    def test_histogram_counts_candidates_once_even_when_multiple_repeats_accept(self):
        histogram = {
            ("reject", "reject", "reject"): 5,
            ("reject", "needs-review", "needs-review"): 3,
            ("accept", "accept", "accept"): 2,
            ("reject", "needs-review", "accept"): 4,
            ("accept", "reject", "accept"): 2,
        }
        summary = report.summarize_repeats(histogram, expected_candidates=16)
        self.assertEqual((summary.total, summary.unstable, summary.any_accept), (16, 9, 8))

    def test_empty_population_has_no_unstable_or_accepted_candidates(self):
        summary = report.summarize_repeats({}, expected_candidates=0)
        self.assertEqual((summary.total, summary.unstable, summary.any_accept), (0, 0, 0))

    def test_incomplete_or_malformed_histograms_are_refused(self):
        complete = ("accept", "reject", "needs-review")
        for histogram, population in (
            ([], 0),
            ({("accept", "reject"): 1}, 1),
            ({("accept", "reject", "reject", "reject"): 1}, 1),
            ({("accept", "reject", "error"): 1}, 1),
            ({("accept", "reject", None): 1}, 1),
            ({complete: -1}, 0),
            ({complete: True}, 1),
            ({complete: 1}, 2),
            ({complete: 2}, 1),
            ({}, True),
        ):
            with self.subTest(histogram=histogram, population=population), self.assertRaises(ValueError):
                report.summarize_repeats(histogram, expected_candidates=population)
