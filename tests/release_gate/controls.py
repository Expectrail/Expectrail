"""The release gate's controls (#258): every row of the issue's table, in its order.

A control is one way clearance could be granted when it must not be. Each row has either tests, which
start real processes and assert that clearance is not granted, or an ``open`` reason that says why it
has none yet. A row with tests and an ``open`` reason too is a control with a probe that shows it is
not defended today: its test is an expected failure (``unittest.expectedFailure``), so the day the
defence lands the probe passes unexpectedly, the suite fails, and someone moves the row to held.

What "clearance" means: ``expectrail verify`` (the orchestrator's command) exits 0, which it does for a
job that completed as accept and for nothing else, and the gate's record says ``accept``. On the
two-job pull-request gate (#254), it is the head's "Expectrail clearance" check completed as success,
which the trusted job gives only to an accept for the pull request's current head.

The summary (``tools.release_gate``) marks a row held only when every test it names ran and passed and
no ``open`` reason is given. A row is never held because nothing failed: a skipped test is "not run".
"""
from __future__ import annotations

GROUPS = ("Identity and authority", "Candidate interference", "Observation", "Coverage", "Intent", "Operations")

OPS = "tests.release_gate.gate_operations"
COV = "tests.release_gate.gate_coverage"
IDN = "tests.release_gate.gate_identity"
PRV = "tests.release_gate.gate_provider"
INT = "tests.release_gate.gate_interference"
ITN = "tests.release_gate.gate_intent"
SBX = "tests.release_gate.gate_sandbox"
BDL = "tests.release_gate.gate_bundle"

NEEDS_254 = "not written yet: it needs the trusted job that judges outside the candidate job (#254)"
NEEDS_255 = "not written yet: it needs the signed receipt (#255)"
NEEDS_257 = "not written yet: it needs the observation timeline (#257)"


def row(group: str, cid: str, control: str, tests=(), open: str | None = None, scope: str | None = None,
        baselines=()) -> dict:
    """``scope`` says what a held row covers and what it does not; it is printed beside the row and
    never changes its status. ``baselines`` are positive controls of this row's own path, which must
    pass besides ``BASELINES`` for the row to be held (the two-job rows: their path needs the replay
    sandbox, which a machine may lack while the other rows still run)."""
    return {"group": group, "id": cid, "control": control, "tests": list(tests), "open": open, "scope": scope,
            "baselines": list(baselines)}


# The positive controls of the two-job rows (#254): the trusted judge clears the unchanged game's
# capture and rejects the seeded bug's, through ``tests.release_gate.bundle``.
TWO_JOB_BASELINES = [
    "tests.release_gate.gate_bundle.BundleBaselineTest.test_the_trusted_judge_clears_the_unchanged_games_capture",
    "tests.release_gate.gate_bundle.BundleBaselineTest.test_the_trusted_judge_rejects_the_seeded_bugs_capture",
]


CONTROLS = [
    # --- Identity and authority -------------------------------------------------------------------
    row(GROUPS[0], "wrong-build-or-head", "wrong build or head", open=NEEDS_255),
    row(GROUPS[0], "unknown-signer", "unknown signer", open=NEEDS_255),
    row(GROUPS[0], "swapped-policy", "swapped policy",
        [f"{IDN}.IdentityTest.test_checks_swapped_between_the_request_and_the_run_judge_nothing",
         f"{IDN}.IdentityTest.test_the_base_checks_swapped_after_the_request_judge_nothing",
         f"{IDN}.IdentityTest.test_checks_swapped_and_put_back_exactly_are_the_checks_that_were_named"]),
    row(GROUPS[0], "expired-receipt", "expired receipt", open=NEEDS_255),
    row(GROUPS[0], "changed-head", "changed head",
        [f"{BDL}.HeadTest.test_control_the_head_that_was_judged_is_given_clearance",
         f"{BDL}.HeadTest.test_a_new_head_pushed_before_the_judge_finished_is_not_given_clearance",
         f"{BDL}.HeadTest.test_a_newer_attempt_of_the_candidate_run_takes_clearance_from_this_one",
         f"{BDL}.HeadTest.test_a_capture_made_for_the_old_head_is_refused_for_the_new_one"],
        scope="the two-job gate (#254): the capture and the trusted judge run as real processes with Godot in "
             "the replay sandbox, and the trusted job's step that completes the head checks runs against a "
             "stand-in for GitHub's API. The hosted run on a test pull request is not part of this suite",
        baselines=TWO_JOB_BASELINES),
    row(GROUPS[0], "approval-added-by-change", "an approval added by the change",
        [f"{IDN}.IdentityTest.test_an_approval_the_change_adds_to_its_own_checks_judges_nothing"]),
    # --- Candidate interference -------------------------------------------------------------------
    row(GROUPS[1], "writes-evidence-or-policy", "writes to evidence or policy",
        [f"{BDL}.EvidenceTest.test_an_intact_capture_from_a_different_base_game_is_refused",
         f"{BDL}.EvidenceTest.test_an_intact_capture_from_a_different_head_game_is_refused",
         f"{BDL}.EvidenceTest.test_a_frame_rewritten_between_the_jobs_is_refused",
         f"{BDL}.EvidenceTest.test_a_trace_rewritten_between_the_jobs_is_refused",
         f"{BDL}.EvidenceTest.test_a_trace_and_its_replay_record_rewritten_together_are_refused_by_the_manifest",
         f"{BDL}.EvidenceTest.test_a_run_taken_out_between_the_jobs_is_refused",
         f"{BDL}.EvidenceTest.test_a_capture_made_with_other_checks_is_refused",
         f"{BDL}.EvidenceTest.test_checks_the_change_rewrites_are_not_the_ones_that_judge_it"],
        scope="the two-job gate (#254): edits between the jobs, an archive consistent in itself whose "
             "recorded base or head game tree differs from its checkout, and checks the change carries. "
             "The artifact download needs GitHub and is not run here. What the game itself writes from inside its "
             "replay is the forged-trace and rewritten-frame rows",
        baselines=TWO_JOB_BASELINES),
    row(GROUPS[1], "forged-trace", "a forged trace", open="undefended: since #254 the judgment runs outside the "
        "candidate job, but the game still runs in the Godot process that writes the trace, inside the "
        "capture's sandbox, so it can write a trace that is not what happened. A capture the game cannot forge "
        "is #246 and #273"),
    row(GROUPS[1], "rewritten-frame", "a rewritten frame", open="undefended: the game draws the frames the "
        "visual observer reads, and no capture the game cannot forge exists yet (#246, #273). The positive "
        "control asserts the run's grade is `diagnostic`, never `protected`"),
    row(GROUPS[1], "poisoned-import-cache", "a poisoned import cache",
        [f"{INT}.ImportCacheTest.test_control_the_same_poison_in_the_verifiers_own_cache_changes_what_is_drawn",
         f"{INT}.ImportCacheTest.test_an_import_cache_the_change_carries_is_never_drawn_from",
         f"{INT}.ImportCacheTest.test_a_broken_change_that_carries_an_import_cache_is_still_rejected"],
        scope="the cache a change carries in its checkout; a run without the replay sandbox can still write "
             "the verifier's own cache, which the first test shows would change what is drawn"),
    row(GROUPS[1], "private-path-read", "reading a private path",
        [f"{SBX}.PrivatePathTest.test_control_without_the_sandbox_a_change_that_reads_a_private_file_is_cleared",
         f"{SBX}.PrivatePathTest.test_in_the_isolated_class_a_change_cannot_read_a_private_file_and_is_rejected",
         f"{SBX}.PrivatePathTest.test_the_isolated_class_clears_the_unchanged_game"],
        scope="the isolated class (`--execution-class isolated`), where every replay is in the sandbox. The "
             "default class sandboxes only where the machine can; without the sandbox the first test shows a "
             "broken change that reads a file outside its checkout repairing itself and being cleared"),
    row(GROUPS[1], "network-egress", "network egress",
        [f"{SBX}.EgressTest.test_control_without_the_sandbox_a_change_that_reaches_a_port_is_cleared",
         f"{SBX}.EgressTest.test_in_the_isolated_class_a_change_cannot_reach_a_port_and_is_rejected"],
        scope="the isolated class, as above; the port is on this machine's loopback, the nearest address a "
             "change could reach. Without the sandbox the first test shows a broken change that reaches it "
             "repairing itself and being cleared"),
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
    row(GROUPS[4], "intentional-change", "an approved intentional change passes as a contract change",
        [f"{ITN}.IntentTest.test_a_change_declared_intended_that_breaks_an_approved_check_is_rejected",
         f"{ITN}.IntentTest.test_a_change_declared_intended_that_rewrites_the_check_it_breaks_is_judged_by_the_approved_check"],
        scope="the pull-request gate's command, which reads the declared intent; the orchestrator's command "
             "takes no intent and judges every change as undeclared. The positive side, a contract change "
             "approved and merged first and the behaviour after it, is not run: the recorded vision answers "
             "cover only the samples' frames and checks"),
    row(GROUPS[4], "weakened-tolerance", "a weakened tolerance",
        [f"{ITN}.IntentTest.test_a_tolerance_the_change_weakens_in_its_own_check_is_not_the_one_that_judges_it"],
        scope="runs with a base, where the checks come from the base. Without a base a change's own checks "
             "judge it, and nothing yet binds an approval to the check's content (#420); such a run is "
             "needs-review in this suite only because the recorded answers do not cover the edited check"),
    row(GROUPS[4], "misleading-generated-check", "a misleading generated check stays advisory",
        [f"{ITN}.IntentTest.test_generated_checks_that_caught_nothing_do_not_clear_a_change_an_approved_check_rejects",
         f"{ITN}.IntentTest.test_a_generated_block_that_cannot_be_read_changes_nothing"],
        scope="the pull-request gate's command, the only one that reads a generated block; the orchestrator's "
             "command never reads one"),
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
    # The intent rows run the pull-request gate's command (tests.release_gate.pr_gate): it clears the
    # unchanged game declared an intended change.
    f"{ITN}.IntentBaselineTest.test_the_pull_request_gate_clears_the_unchanged_game_declared_an_intended_change",
]
# The two-job rows have their own positive controls besides these: TWO_JOB_BASELINES, named by those rows.


def by_id() -> dict[str, dict]:
    return {c["id"]: c for c in CONTROLS}


def row_baselines() -> list[str]:
    """The rows' own positive controls, each once, in the order the rows name them."""
    return list(dict.fromkeys(t for c in CONTROLS for t in c["baselines"]))


def all_tests() -> list[str]:
    return [t for c in CONTROLS for t in c["tests"]] + BASELINES + row_baselines()
