"""The release gate's controls (#258): every row of the issue's table, in its order.

A control is one way clearance could be granted when it must not be. Each row has either tests, which
start real processes and assert that clearance is not granted, or an ``open`` reason that says why it
has none yet. A row with tests and an ``open`` reason too is a control with a probe that shows it is
not defended today: its test is an expected failure (``unittest.expectedFailure``), so the day the
defence lands the probe passes unexpectedly, the suite fails, and someone moves the row to held.

What "clearance" means today: ``expectrail verify`` (the orchestrator's command) exits 0, which it does
for a job that completed as accept and for nothing else, and the gate's record says ``accept``. The
separate "Expectrail clearance" check comes with #254; until then the exit code and the record are
what a merge rule can read.

The summary (``tools.release_gate``) marks a row held only when every test it names ran and passed and
no ``open`` reason is given. A row is never held because nothing failed: a skipped test is "not run".
"""
from __future__ import annotations

GROUPS = ("Identity and authority", "Candidate interference", "Observation", "Coverage", "Intent", "Operations")

OPS = "tests.release_gate.gate_operations"
COV = "tests.release_gate.gate_coverage"
IDN = "tests.release_gate.gate_identity"
PRV = "tests.release_gate.gate_provider"

NEEDS_254 = "not written yet: it needs the trusted job that judges outside the candidate job (#254)"
NEEDS_255 = "not written yet: it needs the signed receipt (#255)"
NEEDS_257 = "not written yet: it needs the observation timeline (#257)"
NOT_YET = "not written yet in this suite"


def row(group: str, cid: str, control: str, tests=(), open: str | None = None) -> dict:
    return {"group": group, "id": cid, "control": control, "tests": list(tests), "open": open}


CONTROLS = [
    # --- Identity and authority -------------------------------------------------------------------
    row(GROUPS[0], "wrong-build-or-head", "wrong build or head", open=NEEDS_255),
    row(GROUPS[0], "unknown-signer", "unknown signer", open=NEEDS_255),
    row(GROUPS[0], "swapped-policy", "swapped policy", open=NOT_YET + " (the orchestrator refuses checks that "
        "change after a job is created, tests/test_orchestrator.py, with a stand-in replay; a real-process "
        "test is the next slice)"),
    row(GROUPS[0], "expired-receipt", "expired receipt", open=NEEDS_255),
    row(GROUPS[0], "changed-head", "changed head", open=NEEDS_254),
    row(GROUPS[0], "approval-added-by-change", "an approval added by the change",
        [f"{IDN}.IdentityTest.test_an_approval_the_change_adds_to_its_own_checks_judges_nothing"]),
    # --- Candidate interference -------------------------------------------------------------------
    row(GROUPS[1], "writes-evidence-or-policy", "writes to evidence or policy", open=NEEDS_254),
    row(GROUPS[1], "forged-trace", "a forged trace", open=NEEDS_254 + "; until then the game writes the trace "
        "the gate reads, in the same job"),
    row(GROUPS[1], "rewritten-frame", "a rewritten frame", open="undefended: the game draws the frames the "
        "visual observer reads, and no capture the game cannot forge exists yet (#246, #273). The positive "
        "control asserts the run's grade is `diagnostic`, never `protected`"),
    row(GROUPS[1], "poisoned-import-cache", "a poisoned import cache", open=NOT_YET),
    row(GROUPS[1], "private-path-read", "reading a private path", open=NOT_YET + " (the replay sandbox's own "
        "tests cover it with bubblewrap: tests/test_replay_sandbox.py)"),
    row(GROUPS[1], "network-egress", "network egress", open=NOT_YET + " (the replay sandbox's own tests cover "
        "it with bubblewrap: tests/test_replay_sandbox.py)"),
    # --- Observation ------------------------------------------------------------------------------
    row(GROUPS[2], "dropped-frames", "dropped frames", open=NEEDS_257),
    row(GROUPS[2], "duplicated-frames", "duplicated frames", open=NEEDS_257),
    row(GROUPS[2], "out-of-order-frames", "out-of-order frames", open=NEEDS_257),
    row(GROUPS[2], "tick-phase-error", "tick phase error", open=NEEDS_257),
    row(GROUPS[2], "resolution-change", "resolution change", open=NEEDS_257),
    row(GROUPS[2], "two-same-class-targets", "two same-class targets", open=NEEDS_257),
    row(GROUPS[2], "occlusion", "occlusion", open=NEEDS_257),
    # --- Coverage ---------------------------------------------------------------------------------
    row(GROUPS[3], "empty-suite", "empty suite",
        [f"{COV}.CoverageTest.test_no_approved_spec_at_all_is_not_clearance"]),
    row(GROUPS[3], "unreachable-route", "unreachable route",
        [f"{COV}.CoverageTest.test_a_route_pattern_that_matches_no_file_is_not_clearance",
         f"{COV}.CoverageTest.test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance"]),
    row(GROUPS[3], "zero-evaluations", "zero evaluations",
        [f"{COV}.CoverageTest.test_specs_that_are_all_drafts_judge_nothing_and_are_not_clearance"]),
    row(GROUPS[3], "skipped-required-observer", "skipped required observer",
        [f"{COV}.CoverageTest.test_under_two_observers_a_missing_visual_observer_is_not_clearance"]),
    row(GROUPS[3], "missing-private-suite", "missing private suite",
        [f"{COV}.CoverageTest.test_held_out_routes_that_cannot_be_read_are_not_clearance"]),
    # --- Intent -----------------------------------------------------------------------------------
    row(GROUPS[4], "intentional-change", "an approved intentional change passes as a contract change", open=NOT_YET),
    row(GROUPS[4], "weakened-tolerance", "a weakened tolerance", open=NOT_YET),
    row(GROUPS[4], "misleading-generated-check", "a misleading generated check stays advisory", open=NOT_YET),
    # --- Operations -------------------------------------------------------------------------------
    row(GROUPS[5], "timeout", "timeout",
        [f"{OPS}.OperationsTest.test_a_job_that_runs_out_of_time_is_not_clearance_and_leaves_nothing_running"]),
    row(GROUPS[5], "cancellation", "cancellation",
        [f"{OPS}.OperationsTest.test_a_cancelled_job_is_not_clearance_and_leaves_nothing_running"]),
    row(GROUPS[5], "worker-killed", "worker killed",
        [f"{OPS}.OperationsTest.test_a_killed_worker_is_not_clearance_and_leaves_nothing_running"]),
    row(GROUPS[5], "retry", "retry",
        [f"{OPS}.OperationsTest.test_asking_again_after_a_lost_worker_returns_the_failure_not_a_new_verdict"]),
    row(GROUPS[5], "duplicate-request", "duplicate request",
        [f"{OPS}.OperationsTest.test_a_key_used_for_one_change_does_not_clear_another",
         f"{OPS}.OperationsTest.test_the_same_request_twice_at_once_is_one_job_with_one_verdict"]),
    row(GROUPS[5], "disk-quota", "disk quota", open="undefended: a replay's files are capped one by one, and "
        "nothing bounds a job's total disk use yet (#253)"),
    row(GROUPS[5], "provider-outage", "provider outage",
        [f"{PRV}.ProviderTest.test_a_provider_outage_is_not_clearance_and_does_not_hide_a_broken_build"]),
    row(GROUPS[5], "budget-exhausted", "budget exhausted",
        [f"{PRV}.ProviderTest.test_a_cap_of_nothing_sends_nothing_and_is_not_clearance",
         f"{PRV}.ProviderTest.test_a_cap_spent_part_way_stops_the_requests_and_is_not_clearance",
         f"{PRV}.ProviderTest.test_a_provider_out_of_credit_is_not_clearance"]),
]

# The positive controls: without them every "not clearance" assertion could hold because nothing is
# ever cleared. They are part of the suite and of the summary, and belong to no row.
BASELINES = [
    f"{OPS}.BaselineTest.test_the_unchanged_game_is_cleared_through_the_same_command",
    # The provider rows run the real command with its live visual observer against a stand-in provider
    # on this machine: with the stand-in answering from the recorded answers, that command clears.
    f"{PRV}.ProviderBaselineTest.test_with_the_provider_answering_the_live_observer_clears_the_unchanged_game",
]


def by_id() -> dict[str, dict]:
    return {c["id"]: c for c in CONTROLS}


def all_tests() -> list[str]:
    return [t for c in CONTROLS for t in c["tests"]] + BASELINES
