"""OBAAF proposals (agents/assurance/proposal.py): normalization, and the cases the integration
specification says must be refused before any game code runs.

The OBAAF checks run when ``obaaf`` is installed (the obaaf-audit CI job installs it from the
reviewed revision); normalization and Expectrail's own allowlist always run.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.assurance import proposal as ap
from harness.run import REPO

SEED = REPO / "bugs" / "physics-fall-through" / "v1.patch"
FIX = REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
HAS_OBAAF = bool(ap.obaaf_bin())


class NormalizeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_the_real_fix_becomes_a_repository_relative_git_diff(self):
        record = ap.normalize(FIX, [SEED], self.out)
        diff = (self.out / "proposal" / "patch.diff").read_text()
        self.assertTrue(diff.startswith("diff --git a/game/platformer/player/player.tscn "
                                        "b/game/platformer/player/player.tscn\n"))
        self.assertIn("-collision_mask = 14\n+collision_mask = 30", diff)
        self.assertEqual(record["changedPaths"], ["game/platformer/player/player.tscn"])
        self.assertEqual(sorted(p.name for p in (self.out / "proposal").iterdir()), ["meta.json", "patch.diff"])
        self.assertEqual((record["mode"], record["lineage"]), ("audit", "benchmark"))
        self.assertEqual(record["bundleDigest"], ap.bundle_digest(self.out / "proposal"))
        self.assertEqual(ap.editable_problems(record["changedPaths"], ap.DEFAULT_EDITABLE), [])

    def test_the_same_inputs_give_the_same_trees_and_bundle(self):
        first = ap.normalize(FIX, [SEED], self.out / "one")
        second = ap.normalize(FIX, [SEED], self.out / "two")
        for key in ("candidateTree", "patchFileSha256", "bundleDigest"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["base"]["tree"], second["base"]["tree"])

    def test_the_base_is_a_disposable_clone_with_the_defect_committed(self):
        record = ap.normalize(FIX, [SEED], self.out)
        self.assertNotEqual(record["base"]["commit"], record["base"]["sourceCommit"])  # the seed is a commit
        tscn = (self.out / "base" / ap.GAME_ROOT / "player" / "player.tscn").read_text()
        self.assertIn("collision_mask = 14", tscn)  # the base carries the defect, not the fix
        self.assertNotIn(str(self.out), json.dumps(record))  # no local paths in the record

    def test_a_relative_output_directory_works(self):
        # CI passes --out runs/...; git runs from inside it, so every path must be absolute by then.
        cwd = os.getcwd()
        os.chdir(self.out)
        try:
            record = ap.normalize(FIX, [SEED], Path("relative") / "out")
        finally:
            os.chdir(cwd)
        self.assertEqual(record["changedPaths"], ["game/platformer/player/player.tscn"])
        self.assertTrue((self.out / "relative" / "out" / "proposal" / "patch.diff").is_file())

    def test_a_candidate_that_does_not_apply_or_changes_nothing_is_an_error(self):
        with self.assertRaises(ap.ProposalError):
            ap.normalize(SEED, [SEED], self.out / "twice")  # the seed again: already applied
        empty = self.out / "empty.patch"
        empty.write_text("")
        with self.assertRaises(ap.ProposalError):
            ap.normalize(empty, [SEED], self.out / "empty")

    def test_the_editable_allowlist_is_expectrails_own_rule(self):
        problems = ap.editable_problems(["game/platformer/gui/pause_menu.gd", "README.md",
                                         "game/platformer/player/player.gd"], ap.DEFAULT_EDITABLE)
        self.assertEqual(len(problems), 2)
        self.assertIn("pause_menu.gd is not in the editable files", problems[0])
        self.assertIn("README.md is outside the game root", problems[1])


@unittest.skipUnless(HAS_OBAAF, "obaaf is not installed (the obaaf-audit CI job installs it)")
class ObaafCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def changed(self, edit, out: Path | None = None) -> tuple[dict, dict]:
        """Normalize the real fix, then let ``edit`` change the candidate tree further, and check."""
        out = out or self.out
        out.mkdir(parents=True, exist_ok=True)
        base = ap.materialize_base(out, [SEED])
        cand = out / "candidate-tree"
        ap._git(["clone", "--quiet", "--no-hardlinks", base["path"], str(cand)], out)
        ap.apply_patches(cand / ap.GAME_ROOT, [FIX])
        edit(cand)
        record = ap.bundle_from_tree(cand, base, out)
        return record, ap.check(out, record)

    def test_the_real_fix_passes_both_rule_sets(self):
        record = ap.normalize(FIX, [SEED], self.out)
        result = ap.check(self.out, record)
        self.assertTrue(result["ok"], result)
        self.assertEqual(json.loads((self.out / "proposal-check.json").read_text())["ok"], True)

    def test_a_fix_that_also_edits_a_workflow_is_refused_by_obaaf(self):
        def edit(cand):
            wf = cand / ".github" / "workflows" / "ci.yml"
            wf.write_text(wf.read_text() + "\n# harmless-looking comment\n")
        _record, result = self.changed(edit)
        self.assertFalse(result["ok"])
        self.assertTrue(any(".github/workflows/ci.yml" in p and "protected" in p for p in result["obaaf"]["problems"]))

    def test_a_fix_that_edits_the_verifier_or_a_spec_is_refused_by_expectrails_protected_paths(self):
        for rel in ("agents/verifier.py", "specs/coins-visible.json", "bugs/sinking/v1.patch"):
            with self.subTest(rel=rel):
                _record, result = self.changed(lambda cand, r=rel: (cand / r).write_text((cand / r).read_text() + "\n"),
                                               self.out / rel.replace("/", "_"))
                self.assertFalse(result["obaaf"]["ok"])
                self.assertTrue(any(rel in p and "protected" in p for p in result["obaaf"]["problems"]), result)

    def test_a_symlink_is_refused(self):
        def edit(cand):
            os.symlink("/etc/passwd", cand / ap.GAME_ROOT / "player" / "link.tscn")
        _record, result = self.changed(edit)
        self.assertFalse(result["ok"])
        self.assertTrue(result["obaaf"]["problems"])

    def test_the_raw_game_relative_fixture_is_refused_until_normalized(self):
        record = ap.normalize(FIX, [SEED], self.out)
        shutil.copyfile(FIX, self.out / "proposal" / "patch.diff")
        report = ap.obaaf_check(self.out / "proposal", self.out / "base")
        self.assertFalse(report["ok"])
        self.assertIn("player/player.tscn", json.dumps(record))

    def test_evidence_inside_the_bundle_is_refused(self):
        ap.normalize(FIX, [SEED], self.out)
        (self.out / "proposal" / "verification.json").write_text("{}\n")
        report = ap.obaaf_check(self.out / "proposal", self.out / "base")
        self.assertFalse(report["ok"])
        self.assertTrue(any("unexpected file" in p for p in report["problems"]))

    def test_a_bundle_changed_after_normalization_fails_its_digest(self):
        record = ap.normalize(FIX, [SEED], self.out)
        (self.out / "proposal" / "meta.json").write_text('{"note": "edited later"}\n')
        report = ap.obaaf_check(self.out / "proposal", self.out / "base", digest=record["bundleDigest"])
        self.assertFalse(report["ok"])

    def test_an_out_of_glob_game_file_passes_obaaf_but_not_expectrail(self):
        record = ap.normalize(REPO / "agents" / "fixtures" / "out-of-glob.patch", [SEED], self.out)
        result = ap.check(self.out, record)
        self.assertTrue(result["obaaf"]["ok"])
        self.assertFalse(result["editable"]["ok"])
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()


class LaneInventoryTest(unittest.TestCase):
    """agents/assurance/audit.py: the declarations in .github/obaaf.yml must match what holds model keys."""

    def setUp(self):
        from agents.assurance import audit
        self.audit = audit
        self.declared = audit.declared_agents()
        self.probes = audit.declared_probes()
        self.models = audit.model_jobs()

    def lanes(self, **overrides):
        jobs = set(self.models) | self.declared | self.probes
        lanes = {job: ("agent" if job in self.declared else "trusted") for job in jobs}
        lanes.update(overrides)
        return lanes

    def problems(self, lanes=None, models=None):
        return self.audit.inventory_problems(lanes or self.lanes(), self.declared,
                                             models or self.models, self.probes)

    def test_every_job_with_a_model_key_is_a_declared_agent_or_perception_only(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(len(self.declared), 16)
        for job in self.audit.PERCEPTION:
            self.assertIn(job, self.models, f"{job} no longer holds a model key; drop it from PERCEPTION")

    def test_the_byo_fixer_job_holds_its_providers_key_and_is_a_declared_agent(self):
        """byo-live runs Claude Code on the change under review, so it is an agent lane like any other."""
        job = ".github/workflows/byo-live.yml#byo-live"
        self.assertEqual(self.models.get(job), {"ANTHROPIC_API_KEY"})
        self.assertIn(job, self.declared)

    def test_the_gateway_probe_is_an_agent_lane_like_the_run_it_mirrors(self):
        """byo-gateway-probe runs a coding agent on the change under review, exactly as byo-live
        does. Putting it behind the key gateway changes what it holds, not what it is.

        It holds both providers' keys because the agent is an input: Anthropic for triage either
        way, OpenAI when the agent is codex. The agent process still receives only its own
        provider's key (agents/keys.py, BYO_AGENT_KEY_ENVS), which is what sandbox.json records.
        """
        job = ".github/workflows/byo-gateway-probe.yml#byo-gateway-probe"
        self.assertEqual(self.models.get(job), {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"})
        self.assertIn(job, self.declared)
        self.assertNotIn("MODEL_API_KEY", self.models[job])  # never the verifier's SAM key

    def test_the_live_provider_probe_is_a_declared_probe_not_an_agent(self):
        """byo-smoke holds every provider key but calls a model and acts only on whether it
        answered, so it is neither an agent lane nor perception (audit.py, the probe lane)."""
        job = ".github/workflows/byo-smoke.yml#byo-smoke"
        self.assertIn(job, self.models)  # it does hold model keys
        self.assertIn("ANTHROPIC_API_KEY", self.models[job])
        self.assertIn(job, self.audit.declared_probes())
        self.assertNotIn(job, self.declared)
        self.assertNotIn(job, self.audit.PERCEPTION)
        self.assertNotIn("MODEL_API_KEY", self.models[job])  # never the verifier's SAM key

    def test_a_probe_exempts_only_what_was_declared(self):
        probes = self.audit.declared_probes()
        lanes = self.lanes(**{job: "trusted" for job in probes})
        self.assertEqual(self.audit.inventory_problems(lanes, self.declared, self.models, probes), [])
        # undeclared, the same job is a finding: the exemption is the declaration, not the lane name
        problems = self.audit.inventory_problems(lanes, self.declared, self.models, frozenset())
        self.assertEqual(len(problems), len(probes))
        self.assertIn("byo-smoke", problems[0])
        self.assertIn("declared probe", problems[0])

    def test_a_probe_declaration_that_matches_no_job_fails(self):
        """A renamed or deleted job must not keep its exemption quietly."""
        problems = self.audit.inventory_problems(
            self.lanes(), self.declared, self.models,
            self.probes | {".github/workflows/gone.yml#probe"})
        self.assertEqual(len(problems), 1)
        self.assertIn("gone.yml#probe is declared a probe", problems[0])

    def test_a_new_model_job_that_nobody_declared_fails_the_audit(self):
        models = dict(self.models, **{".github/workflows/new.yml#fix-it": {"META_API_KEY"}})
        problems = self.problems(models=models)
        self.assertEqual(len(problems), 1)
        self.assertIn("new.yml#fix-it holds META_API_KEY", problems[0])

    def test_a_declared_agent_the_checker_did_not_classify_as_one_fails(self):
        job = ".github/workflows/fix-matrix.yml#run"
        problems = self.problems(lanes=self.lanes(**{job: "trusted"}))
        self.assertEqual(problems[0], f"{job} is declared as an agent but OBAAF classified it trusted")
        self.assertIn("holds META_API_KEY", problems[1])  # and it holds a model key outside an agent lane

    def test_lanes_output_and_findings_are_parsed(self):
        text = (".github/workflows/ci.yml#test: trusted (default)\n"
                ".github/workflows/fix-matrix.yml#run: agent (set in the checker configuration)\n")
        self.assertEqual(self.audit.parse_lanes(text), {".github/workflows/ci.yml#test": "trusted",
                                                        ".github/workflows/fix-matrix.yml#run": "agent"})
        report = {"tool": "obaaf 0.2.0", "files": ["a.yml"], "findings": [
            {"rule": "OBAAF-GHA-005", "title": "Secret available to an agent job", "severity": "high",
             "category": "authority", "path": "a.yml", "line": 3, "job": "run"},
            {"rule": "OBAAF-GHA-005", "title": "Secret available to an agent job", "severity": "high",
             "category": "authority", "path": "a.yml", "line": 9, "job": "demo-run"},
            {"rule": "OBAAF-GHA-020", "title": "Agent job without an egress restriction", "severity": "low",
             "category": "hygiene", "path": "a.yml", "line": 3, "job": "run", "suppressed": {"reason": "x"}}]}
        lines = self.audit.finding_lines(report)
        self.assertIn("2 findings, reported, not gated (authority 2 high, 0 medium, 0 low; "
                      "hygiene 0 high, 0 medium, 0 low)", lines[0])
        self.assertEqual(lines[1], "::notice title=OBAAF high OBAAF-GHA-005 x2::Secret available to an agent job: "
                                   "run, demo-run")
        self.assertEqual(len(lines), 2)  # a suppressed finding is not counted


class ModelKeyCoverageTest(unittest.TestCase):
    """audit.MODEL_KEYS comes from the provider and BYO-agent registries, so a provider added there
    cannot hand a job a key this audit does not recognise (which would pass the lane inventory by
    being invisible to it, not by being declared)."""

    def setUp(self):
        from agents.assurance import audit
        self.audit = audit

    def test_every_provider_key_env_is_a_model_key(self):
        from expectrail.providers import PROVIDER_DEFAULTS
        for provider, defaults in PROVIDER_DEFAULTS.items():
            for env in defaults["key_envs"]:
                self.assertTrue(self.audit.is_model_key(env),
                                f"{provider}'s {env} is not a model key: the OBAAF audit cannot see it")

    def test_every_byo_coding_agents_key_env_is_a_model_key(self):
        from agents.keys import BYO_AGENT_KEY_ENVS
        for agent, envs in BYO_AGENT_KEY_ENVS.items():
            for env in envs:
                self.assertTrue(self.audit.is_model_key(env),
                                f"{agent}'s {env} is not a model key: the OBAAF audit cannot see it")

    def test_the_legacy_meta_keys_are_still_model_keys(self):
        for env in ("META_API_KEY", "MODEL_API_KEY", "BASETEN_API_KEY", "FIREWORKS_API_KEY", "GLIMMER_API_KEY"):
            self.assertTrue(self.audit.is_model_key(env))

    def test_a_roles_own_key_is_a_model_key_without_being_listed(self):
        for env in ("EXPECTRAIL_SPEC_API_KEY", "EXPECTRAIL_TRIAGE_API_KEY", "EXPECTRAIL_FIXER_API_KEY",
                    "EXPECTRAIL_VLM_API_KEY", "EXPECTRAIL_JUDGE_API_KEY"):
            self.assertTrue(self.audit.is_model_key(env), env)

    def test_a_secret_that_is_not_a_model_key_is_not_matched(self):
        for env in ("HELDOUT_TOKEN", "GITHUB_TOKEN", "UNITY_EMAIL", "UNITY_LICENSE", "UNITY_PASSWORD",
                    "EXPECTRAIL_LLM_API_BASE", "EXPECTRAIL_FIXER_CMD", "OLLAMA_HOST"):
            self.assertFalse(self.audit.is_model_key(env), env)
