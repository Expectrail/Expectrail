"""The CI gate (docs/ci-gate.md): finding ids, the findings record read as data, the comment's
escaping, size caps and held-out redaction, and the trusted job's YAML. No live Godot run: replays
are faked with the agents/fixtures traces, which the real observations and evaluator judge."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import jsonschema
import yaml

from expectrail.gate import comment as gc
from expectrail.gate import record as rec
from expectrail.gate import verify as gv

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "contracts" / "examples" / "findings.json"
FIXTURES = REPO / "agents" / "fixtures"
SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
ROUTES = REPO / "harness" / "routes"
VERIFY_WF = REPO / ".github" / "workflows" / "expectrail-verify.yml"
COMMENT_WF = REPO / ".github" / "workflows" / "expectrail-comment.yml"
VERIFY_ACTION = REPO / ".github" / "actions" / "expectrail-verify" / "action.yml"
COMMENT_ACTION = REPO / ".github" / "actions" / "expectrail-comment" / "action.yml"
SECRET_NAMES = ("zz-hidden-ledge-probe", "zz-hidden-gap-probe")
HEAD = "1" * 40
BASE = "2" * 40


def example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


# --- a fake replay: the fixture traces, judged by the real observations and evaluator --------------

class FakeReplay:
    """A game whose folder holds a file named BUG falls through the floor (trace-fallthrough.json);
    any other game does not (trace-fixed.json). A game holding CRASH fails to replay."""

    def __init__(self):
        self.calls: list[tuple[str, str, bool]] = []

    def __call__(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        self.calls.append((route.name, str(game), frames))
        if (game / "CRASH").exists():
            raise SystemExit("godot failed (139); see godot.log")
        name = "trace-fallthrough.json" if (game / "BUG").exists() else "trace-fixed.json"
        out.mkdir(parents=True, exist_ok=True)
        trace = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        frames_dir = None
        if frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)
            for n in range(0, 40):
                (frames_dir / f"f{n:08d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + f"{name}:{n}".encode())
        sha = hashlib.sha256(json.dumps(trace).encode() + str(game).encode()).hexdigest()
        return {"trace": trace, "replaySha256": sha, "framesDir": frames_dir}


def make_repo(root: Path, *, bug: bool = False, crash: bool = False, spec_edit: dict | None = None,
              draft: bool = False, routes=("smoke", "combat")) -> Path:
    (root / "game" / "platformer").mkdir(parents=True)
    (root / "game" / "platformer" / "project.godot").write_text("[application]\n", encoding="utf-8")
    if bug:
        (root / "game" / "platformer" / "BUG").write_text("1", encoding="utf-8")
    if crash:
        (root / "game" / "platformer" / "CRASH").write_text("1", encoding="utf-8")
    (root / "specs").mkdir()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec_edit:
        spec.update(spec_edit)
    (root / "specs" / "player-stays-above-ground.json").write_text(json.dumps(spec), encoding="utf-8")
    if draft:
        d = dict(spec, id="player-draft-check")
        d.pop("approval", None)
        (root / "specs" / "draft.json").write_text(json.dumps(d), encoding="utf-8")
    (root / "routes").mkdir()
    for r in routes:
        shutil.copy(ROUTES / f"{r}.json", root / "routes" / f"{r}.json")
    return root


def make_heldout(root: Path, *, broken: bool = False) -> Path:
    """A stand-in held-out set built from public routes under names that must never leave."""
    (root / "routes").mkdir(parents=True)
    entries = []
    for src, name in zip(("coins", "traversal"), SECRET_NAMES):
        doc = json.loads((ROUTES / f"{src}.json").read_text(encoding="utf-8"))
        doc["name"] = name
        (root / "routes" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
        entries.append({"file": f"routes/{name}.json", "name": name, "minDeltaX": 10})
    if broken:
        entries.append({"file": f"routes/{SECRET_NAMES[0]}-missing.json"})
    (root / "manifest.json").write_text(json.dumps({"routes": entries}), encoding="utf-8")
    return root


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.replay = FakeReplay()

    def gate(self, head: Path, base: Path | None = None, heldout: Path | None = None, out_name: str = "out",
             pr: dict | None = None, **kw) -> dict:
        pr = pr if pr is not None else {"number": 7, "headSha": HEAD, "baseSha": BASE if base else None}
        with contextlib.redirect_stdout(io.StringIO()) as log:
            doc = gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                              out=self.tmp / out_name, work=self.tmp / (out_name + "-work"), base=base,
                              heldout=heldout, pr=pr, replay=self.replay, **kw)
        self.log = log.getvalue()
        return doc


# --- finding ids --------------------------------------------------------------------------------

class FindingIdTest(GateCase):
    def test_the_id_is_twelve_hex_digits_of_sha256_of_spec_route_and_kind(self):
        want = hashlib.sha256(b"player-stays-above-ground\nsmoke\nfail").hexdigest()[:12]
        self.assertEqual(rec.finding_id("player-stays-above-ground", "smoke", "fail"), want)
        self.assertRegex(want, r"^[0-9a-f]{12}$")

    def test_the_documented_shell_line_gives_the_same_id(self):
        if not shutil.which("sha256sum"):
            self.skipTest("no sha256sum")
        out = subprocess.run("printf '%s\\n%s\\n%s' player-stays-above-ground smoke fail | sha256sum | cut -c1-12",
                             shell=True, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, rec.finding_id("player-stays-above-ground", "smoke", "fail"))

    def test_each_part_changes_the_id(self):
        ids = {rec.finding_id(s, r, k) for s in ("a", "b") for r in ("smoke", "combat") for k in rec.KINDS}
        self.assertEqual(len(ids), 2 * 2 * len(rec.KINDS))

    def test_parts_must_be_single_line_and_non_empty(self):
        for bad in (("", "r", "fail"), ("s", "r\nx", "fail"), ("s", "r", None)):
            with self.assertRaises(ValueError):
                rec.finding_id(*bad)

    def test_the_same_failure_keeps_its_id_across_pushes(self):
        base = make_repo(self.tmp / "base")
        first = self.gate(make_repo(self.tmp / "push1", bug=True), base, out_name="o1",
                          pr={"number": 7, "headSha": "a" * 40, "baseSha": BASE})
        push2 = make_repo(self.tmp / "push2", bug=True)
        (push2 / "game" / "platformer" / "unrelated.gd").write_text("extends Node\n", encoding="utf-8")
        second = self.gate(push2, base, out_name="o2", pr={"number": 7, "headSha": "b" * 40, "baseSha": BASE})
        self.assertNotEqual(first["game"]["headTree"], second["game"]["headTree"])
        self.assertEqual([f["id"] for f in first["findings"]], [f["id"] for f in second["findings"]])
        self.assertEqual(len(first["findings"]), 2)

    def test_a_different_failure_kind_gets_a_different_id(self):
        base = make_repo(self.tmp / "base")
        failing = self.gate(make_repo(self.tmp / "bug", bug=True), base, out_name="o1")
        crashing = self.gate(make_repo(self.tmp / "crash", crash=True), base, out_name="o2")
        self.assertEqual({f["kind"] for f in crashing["findings"]}, {"replay-error"})
        self.assertFalse({f["id"] for f in failing["findings"]} & {f["id"] for f in crashing["findings"]})


# --- the record read as data ----------------------------------------------------------------------

class RecordTest(GateCase):
    def test_the_example_matches_the_schema_with_both_validators_and_is_consistent(self):
        doc = example()
        jsonschema.Draft202012Validator(rec.schema()).validate(doc)
        rec.check_record(doc)
        self.assertEqual(doc["format"], rec.FORMAT)

    def test_the_schema_itself_is_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(rec.schema())

    def mutants(self) -> list[tuple[str, dict]]:
        out = []

        def m(label, fn):
            doc = example()
            fn(doc)
            out.append((label, doc))

        m("extra root key", lambda d: d.update(extra=1))
        m("held-out route names smuggled in", lambda d: d["heldOut"].update(names=list(SECRET_NAMES)))
        m("held-out reasons smuggled in", lambda d: d["findings"][0].update(heldOutRoute=SECRET_NAMES[0]))
        m("bad decision word", lambda d: d.update(decision="maybe"))
        m("id not hex", lambda d: d["findings"][0].update(id="ZZZZZZZZZZZZ"))
        m("negative count", lambda d: d["counts"].update(failed=-1))
        m("bool for an integer", lambda d: d["counts"].update(failed=True))
        m("reason too long", lambda d: d["findings"][0].update(reason="x" * 301))
        m("spec id with markup", lambda d: d["checks"][0].update(spec="<b>x</b>"))
        m("route name with a newline", lambda d: d["findings"][0].update(route="smoke\n@octocat"))
        m("review page elsewhere", lambda d: d.update(reviewPage="https://evil.example/x.html"))
        m("missing heldOut", lambda d: d.pop("heldOut"))
        m("pullRequest number zero", lambda d: d["pullRequest"].update(number=0))
        m("short sha", lambda d: d["pullRequest"].update(headSha="abc"))
        m("too many reasons", lambda d: d.update(reasons=["r"] * 21))
        m("float frame", lambda d: d["findings"][0].update(frame=1.5))
        return out

    def test_the_stdlib_validator_agrees_with_jsonschema(self):
        schema = rec.schema()
        validator = jsonschema.Draft202012Validator(schema)
        cases = [("example", example())] + self.mutants()
        for label, doc in cases:
            with self.subTest(label):
                self.assertEqual(not rec.errors(doc, schema), validator.is_valid(doc))
        for kind, sample in (("test-spec", "test-spec.json"), ("route", "route.json")):
            schema = json.loads((REPO / "contracts" / f"{kind}.schema.json").read_text(encoding="utf-8"))
            validator = jsonschema.Draft202012Validator(schema)
            base = json.loads((REPO / "contracts" / "examples" / sample).read_text(encoding="utf-8"))
            variants = [base, dict(base, extra=1), {k: v for k, v in base.items() if k != "format"},
                        dict(base, format="expectrail.other/v0")]
            if kind == "test-spec":
                variants += [dict(base, assertion={"type": "looks-fine", "object": "player"}),
                             dict(base, objects={}), dict(base, id="Bad Id"),
                             dict(base, objects={"player": {"prompt": "robot", "minScore": 2}})]
            else:
                variants += [dict(base, ticks=0), dict(base, events=[{"tick": -1, "action": "x", "pressed": True}]),
                             dict(base, events=[{"tick": 1, "action": "x"}])]
            for n, doc in enumerate(variants):
                with self.subTest(kind=kind, variant=n):
                    self.assertEqual(not rec.errors(doc, schema), validator.is_valid(doc))

    def test_every_mutant_is_refused(self):
        for label, doc in self.mutants():
            with self.subTest(label), self.assertRaises(rec.RecordError):
                rec.check_record(doc)

    def test_derived_values_are_recomputed(self):
        def broken(fn):
            doc = example()
            fn(doc)
            return doc

        cases = {
            "a finding id that is not sha256(spec, route, kind)":
                broken(lambda d: (d["findings"][0].update(id="0" * 12), d["checks"][0].update(findingId="0" * 12))),
            "a passing check given a finding id": broken(lambda d: d["checks"].__setitem__(
                0, dict(d["checks"][0], after="pass", comparison="PRESERVED"))),
            "a comparison that does not follow": broken(lambda d: d["checks"][0].update(comparison="REPAIRED")),
            "counts that do not match": broken(lambda d: d["counts"].update(passed=5)),
            "an accept that the counts do not support": broken(lambda d: d.update(decision="accept")),
            "held-out counts that do not add up": broken(lambda d: d["heldOut"].update(passed=9)),
            "a finding without its check": broken(lambda d: d["findings"].pop()),
            "a check judged twice": broken(lambda d: d["checks"].append(dict(d["checks"][0]))),
            "a check on an unlisted route": broken(lambda d: d["routes"].pop()),
        }
        for label, doc in cases.items():
            with self.subTest(label), self.assertRaises(rec.RecordError):
                rec.check_record(doc)

    def test_reading_refuses_duplicates_nan_size_symlinks_and_bad_bytes(self):
        good = EXAMPLE.read_text(encoding="utf-8")
        cases = {
            "dup.json": '{"format": "a", "format": "b"}',
            "nan.json": good.replace('"drafts": 0', '"drafts": NaN'),
            "deep.json": "[" * 40 + "]" * 40,
            "notjson.json": "{",
        }
        for name, text in cases.items():
            path = self.tmp / name
            path.write_text(text, encoding="utf-8")
            with self.subTest(name), self.assertRaises(rec.RecordError):
                rec.read_record(path)
        big = self.tmp / "big.json"
        big.write_text(good[:-2] + " " * rec.MAX_RECORD_BYTES + "}\n", encoding="utf-8")
        with self.assertRaisesRegex(rec.RecordError, "cap"):
            rec.read_record(big)
        latin = self.tmp / "latin.json"
        latin.write_bytes(b'{"format": "\xff"}')
        with self.assertRaisesRegex(rec.RecordError, "UTF-8"):
            rec.read_record(latin)
        real = self.tmp / "real.json"
        real.write_text(good, encoding="utf-8")
        link = self.tmp / "findings.json"
        link.symlink_to(real)
        with self.assertRaisesRegex(rec.RecordError, "symlink"):
            rec.read_record(link)
        self.assertEqual(rec.read_record(real)["format"], rec.FORMAT)
        with self.assertRaisesRegex(rec.RecordError, "no findings.json"):
            rec.read_record(self.tmp / "absent.json")

    def test_an_unknown_schema_keyword_fails_closed(self):
        with self.assertRaises(rec.SchemaError):
            rec.errors("x", {"type": "string", "format": "email"})

    def test_the_comparison_table_is_the_reviews(self):
        from expectrail.change_evidence import compare

        for before in rec.RESULTS + (None,):
            for after in rec.RESULTS + (None,):
                self.assertEqual(rec.compare(before, after), compare(before, after))

    def test_the_decision_rule(self):
        zero = {"status": "not-used", "routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
        ok = {"checks": 2, "passed": 2, "failed": 0, "needsReview": 0}
        self.assertEqual(rec.decide(ok, zero)[0], "accept")
        self.assertEqual(rec.decide({"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}, zero)[0], "needs-review")
        self.assertEqual(rec.decide(dict(ok, passed=1, needsReview=1), zero)[0], "needs-review")
        self.assertEqual(rec.decide(dict(ok, passed=1, failed=1), zero)[0], "reject")
        held_fail = dict(zero, status="judged", routes=1, checks=1, failed=1)
        self.assertEqual(rec.decide(ok, held_fail)[0], "reject")
        self.assertEqual(rec.decide(ok, dict(zero, status="unavailable"))[0], "needs-review")


# --- the verify side ------------------------------------------------------------------------------

class VerifyTest(GateCase):
    def test_a_change_that_breaks_the_floor_is_a_regression_with_frames_and_verdicts(self):
        doc = self.gate(make_repo(self.tmp / "head", bug=True), make_repo(self.tmp / "base"))
        self.assertEqual(doc["decision"], "reject")
        self.assertEqual({(c["route"], c["before"], c["after"], c["comparison"]) for c in doc["checks"]},
                         {("smoke", "pass", "fail", "REGRESSION"), ("combat", "pass", "fail", "REGRESSION")})
        out = self.tmp / "out"
        self.assertEqual(rec.read_record(out / "findings.json"), doc)
        for f in doc["findings"]:
            self.assertEqual(f["frame"], 30)
            self.assertTrue((out / "review" / "assets" / f"{f['id']}-after.png").is_file())
            self.assertTrue((out / "review" / "assets" / f"{f['id']}-before.png").is_file())
        page = (out / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("REGRESSION", page)
        self.assertNotIn("<script", page)
        for arm in ("head", "base"):
            verdict = json.loads((out / "verdicts" / arm / "smoke" / "player-stays-above-ground.json").read_text())
            self.assertEqual(verdict["format"], "expectrail.verdict/v0")

    def test_an_unchanged_game_is_accepted_and_preserved(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"))
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"PRESERVED"})
        self.assertEqual(doc["findings"], [])

    def test_a_repair_is_accepted_as_repaired(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base", bug=True))
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"REPAIRED"})

    def test_the_checks_come_from_the_base_so_a_change_cannot_weaken_them(self):
        weakened = {"assertion": {"type": "visible", "object": "player", "minFraction": 0}}
        head = make_repo(self.tmp / "head", bug=True, spec_edit=weakened, routes=("smoke", "combat", "coins"))
        doc = self.gate(head, make_repo(self.tmp / "base"))
        self.assertEqual(doc["checksFrom"], "base")
        self.assertEqual(doc["decision"], "reject")
        self.assertEqual(doc["checksChanged"], {"specs": 1, "routes": 1})
        self.assertEqual(sorted(r["name"] for r in doc["routes"]), ["combat", "smoke"])
        base_spec = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertEqual(doc["specs"][0]["sha256"], rec_digest(base_spec))
        self.assertTrue(any("judge changes once it merges" in r for r in doc["reasons"]))

    def test_without_a_base_the_heads_own_checks_are_used_and_said_so(self):
        doc = self.gate(make_repo(self.tmp / "head", bug=True))
        self.assertEqual(doc["checksFrom"], "head")
        self.assertEqual({c["before"] for c in doc["checks"]}, {None})
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"INCONCLUSIVE"})
        self.assertEqual(doc["decision"], "reject")

    def test_draft_specs_never_judge(self):
        doc = self.gate(make_repo(self.tmp / "head", draft=True), make_repo(self.tmp / "base", draft=True))
        self.assertEqual(doc["drafts"], 1)
        self.assertEqual([s["id"] for s in doc["specs"]], ["player-stays-above-ground"])

    def test_a_replay_that_does_not_finish_needs_review_never_passes(self):
        doc = self.gate(make_repo(self.tmp / "head", crash=True), make_repo(self.tmp / "base"))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual({(f["kind"], f["comparison"]) for f in doc["findings"]}, {("replay-error", "INCONCLUSIVE")})

    def test_held_out_routes_leave_as_counts_only(self):
        heldout = make_heldout(self.tmp / "heldout")
        doc = self.gate(make_repo(self.tmp / "head", bug=True), make_repo(self.tmp / "base"), heldout=heldout)
        self.assertEqual(doc["heldOut"], {"status": "judged", "routes": 2, "checks": 2, "passed": 0, "failed": 2,
                                          "needsReview": 0})
        self.assertEqual(sum(1 for c in self.replay.calls if not c[2]), 2)  # held-out replays: no frames
        leaked = [str(p) for p in (self.tmp / "out").rglob("*") if p.is_file()
                  and any(n.encode() in p.read_bytes() for n in SECRET_NAMES)]
        self.assertEqual(leaked, [])
        self.assertFalse(any(n in self.log for n in SECRET_NAMES))
        self.assertFalse(any(n in json.dumps(doc) for n in SECRET_NAMES))
        body = gc.render(doc, ctx())
        self.assertFalse(any(n in body for n in SECRET_NAMES))
        self.assertIn("2 routes, 2 checks: 0 pass, 2 fail", body)
        self.assertEqual(list(Path(tempfile.gettempdir()).glob("expectrail-heldout-runs-*")), [])

    def test_unreadable_held_out_routes_need_review_and_say_nothing_about_them(self):
        heldout = make_heldout(self.tmp / "heldout", broken=True)
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"), heldout=heldout)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["heldOut"]["status"], "unavailable")
        self.assertFalse(any(n in json.dumps(doc) + self.log for n in SECRET_NAMES))

    def test_inputs_outside_the_repository_are_refused(self):
        for bad in ("../game", "/etc", "game/../../x", "-rf", "a\\b"):
            with self.subTest(bad), self.assertRaises(gv.ConfigError):
                gv.safe_relative(bad, "game-path")
        self.assertEqual(gv.safe_relative(".", "game-path", root_ok=True), ".")
        self.assertEqual(gv.safe_relative("routes/*.json", "routes", glob=True), "routes/*.json")

    def test_no_game_or_no_routes_needs_review_with_a_reason(self):
        head = make_repo(self.tmp / "head")
        (head / "game" / "platformer" / "project.godot").unlink()
        doc = self.gate(head, make_repo(self.tmp / "base"))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertTrue(any("project.godot" in r for r in doc["reasons"]))
        self.assertEqual(doc["checks"], [])

    def test_the_command_line_exit_codes_and_a_stopped_run_still_leaves_a_record(self):
        head = make_repo(self.tmp / "head", bug=True)
        with contextlib.redirect_stdout(io.StringIO()):
            code = gv.main(["--repo", str(head), "--game", "../escape", "--routes", "routes/*.json", "--specs",
                            "specs", "--out", str(self.tmp / "cli"), "--pr", "3", "--head-sha", HEAD])
        self.assertEqual(code, 2)
        doc = rec.read_record(self.tmp / "cli" / "findings.json")
        self.assertEqual((doc["decision"], doc["game"]["path"]), ("needs-review", "unknown"))
        self.assertTrue(doc["reasons"][0].startswith("the gate's inputs cannot be used"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gv.main(["--repo", str(head), "--game", "game", "--routes", "r", "--specs", "s",
                                      "--out", str(self.tmp / "cli")]), 3)  # never overwrites a record


INSIDE = {"sandbox": {"tool": "bubblewrap", "version": "0.9.0"}, "mode": "require", "reason": None, "network": "none",
          "filesystem": "confined", "processes": "own", "environment": "allowlist",
          "limits": {"scratchBytes": 1, "fileBytes": 1, "processes": 1}}
OUTSIDE = {"sandbox": None, "mode": "auto", "reason": "bubblewrap (bwrap) is not installed", "network": "host",
           "filesystem": "host", "processes": "host", "environment": "allowlist", "limits": None}


class Accounting(FakeReplay):
    """FakeReplay whose replays also say what the game could reach, as harness_replay's do: one
    account per replay, taken in turn from ``accounts`` (the last one repeats)."""

    def __init__(self, *accounts):
        super().__init__()
        self.accounts = list(accounts)

    def __call__(self, route, game, out, frames):
        run = super().__call__(route, game, out, frames)
        account = self.accounts[min(len(self.calls) - 1, len(self.accounts) - 1)]
        return run if account is None else dict(run, isolation=account)


class IsolationTest(GateCase):
    """The record says whether the game ran in the replay sandbox, and the sandbox can be required (#253)."""

    def test_every_finished_replay_is_counted_head_base_and_held_out(self):
        self.replay = Accounting(INSIDE)
        doc = self.gate(make_repo(self.tmp / "head"), base=make_repo(self.tmp / "base"),
                        heldout=make_heldout(self.tmp / "held"), require_sandbox=True)
        held = doc["heldOut"]["routes"]
        self.assertEqual(doc["isolation"], {"replays": 4 + held, "sandboxed": 4 + held, "required": True,
                                            "sandbox": {"tool": "bubblewrap", "version": "0.9.0"}, "reasons": []})
        self.assertEqual(len(self.replay.calls), 4 + held)
        self.assertEqual(doc["decision"], "accept")
        rec.check_record(rec.read_record(self.tmp / "out" / "findings.json"))
        page = (self.tmp / "out" / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"all {4 + held}, in bubblewrap 0.9.0", page)

    def test_a_replay_that_says_nothing_is_counted_as_outside(self):
        doc = self.gate(make_repo(self.tmp / "head"))
        self.assertEqual(doc["isolation"], {"replays": 2, "sandboxed": 0, "required": False, "sandbox": None,
                                            "reasons": [rec.NOT_SAID]})
        self.assertEqual(doc["decision"], "accept")   # not required: recorded, and the decision is as before
        self.assertIn("0 of 2", rec.isolation_words(doc["isolation"]))

    def test_the_reason_a_replay_ran_outside_is_kept_once(self):
        self.replay = Accounting(INSIDE, OUTSIDE)
        doc = self.gate(make_repo(self.tmp / "head"), base=make_repo(self.tmp / "base"))
        self.assertEqual((doc["isolation"]["replays"], doc["isolation"]["sandboxed"], doc["isolation"]["reasons"]),
                         (4, 1, ["bubblewrap (bwrap) is not installed"]))
        self.assertEqual(doc["decision"], "accept")

    def test_naming_the_tool_is_not_enough(self):
        for label, account in (("network", dict(INSIDE, network="host")), ("files", dict(INSIDE, filesystem="host")),
                               ("processes", dict(INSIDE, processes="host")), ("no tool", dict(INSIDE, sandbox=None)),
                               ("a word", "sandboxed"), ("a list", [INSIDE])):
            with self.subTest(label):
                self.assertEqual(rec.isolation_summary([account], True)["sandboxed"], 0)
        self.assertEqual(rec.isolation_summary([INSIDE], True)["sandboxed"], 1)

    def test_required_and_outside_is_never_an_accept(self):
        for label, replay in (("says nothing", FakeReplay()), ("says outside", Accounting(OUTSIDE)),
                              ("one of two outside", Accounting(INSIDE, OUTSIDE))):
            with self.subTest(label):
                self.replay = replay
                doc = self.gate(make_repo(self.tmp / label / "head"), out_name=f"out-{label}", require_sandbox=True)
                self.assertEqual(doc["decision"], "needs-review")
                self.assertTrue(any("ran outside the sandbox, which was required" in r for r in doc["reasons"]), doc["reasons"])
                rec.check_record(doc)
                self.assertRaises(rec.RecordError, rec.check_record, dict(doc, decision="accept"))

    def test_required_does_not_turn_a_failing_check_into_needs_review(self):
        doc = self.gate(make_repo(self.tmp / "head", bug=True), base=make_repo(self.tmp / "base"), require_sandbox=True)
        self.assertEqual(doc["decision"], "reject")

    def test_a_replay_that_did_not_finish_is_not_counted(self):
        self.replay = Accounting(INSIDE)
        doc = self.gate(make_repo(self.tmp / "head", crash=True), require_sandbox=True)
        self.assertEqual((doc["isolation"]["replays"], doc["decision"]), (0, "needs-review"))

    def test_required_where_the_machine_cannot_sandbox_replays_nothing(self):
        from harness import sandbox as box

        head = make_repo(self.tmp / "head")
        with mock.patch.object(box, "probe", return_value=(None, "bubblewrap (bwrap) is not installed")), \
                mock.patch("harness.run.run", side_effect=AssertionError("the game was replayed")):
            with self.assertRaisesRegex(gv.ConfigError, "required and this machine cannot provide it: bubblewrap"):
                gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                            out=self.tmp / "o", work=self.tmp / "w", require_sandbox=True)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                code = gv.main(["--repo", str(head), "--game", "game/platformer", "--routes", "routes/*.json", "--specs",
                                "specs", "--out", str(self.tmp / "cli"), "--require-sandbox"])
        doc = rec.read_record(self.tmp / "cli" / "findings.json")
        self.assertEqual((code, doc["decision"], doc["checks"]), (2, "needs-review", []))
        self.assertEqual(doc["isolation"], {"replays": 0, "sandboxed": 0, "required": True, "sandbox": None, "reasons": []})
        self.assertIn("cannot provide it", doc["reasons"][0])
        self.assertIn("no replay ran (the sandbox was required)", log.getvalue())

    def test_required_tells_the_harness_to_refuse_and_auto_leaves_it_to_choose(self):
        from harness import sandbox as box

        head = make_repo(self.tmp / "head")
        asked = []

        def run(route, out, game=None, capture_frames=True, sandbox=None):
            asked.append(sandbox)
            raise SystemExit("stop here: only the argument matters")

        for required, expected in ((True, "require"), (False, None)):
            with self.subTest(required=required), mock.patch.object(box, "probe", return_value=(object(), None)), \
                    mock.patch("harness.run.run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                asked.clear()
                gv.run_gate(repo=head, game="game/platformer", routes=["routes/smoke.json"], specs="specs",
                            out=self.tmp / f"o{required}", work=self.tmp / f"w{required}", require_sandbox=required)
                self.assertEqual(asked, [expected])

    def test_a_record_that_contradicts_itself_is_refused(self):
        good = example()
        rec.check_record(good)
        for label, change in (("more sandboxed than ran", dict(sandboxed=9)),
                              ("a tool with none sandboxed", dict(sandboxed=0, reasons=["x"])),
                              ("none sandboxed and no reason", dict(sandboxed=0, sandbox=None)),
                              ("all sandboxed and no tool", dict(sandbox=None)),
                              ("all sandboxed and a reason", dict(reasons=["x"])),
                              ("an unknown tool", dict(sandbox={"tool": "docker", "version": "1"})),
                              ("a seventh field", dict(grade="isolated"))):
            with self.subTest(label), self.assertRaises(rec.RecordError):
                rec.check_record(dict(good, isolation=dict(good["isolation"], **change)))

    def test_a_record_cannot_count_fewer_replays_than_its_checks_rest_on(self):
        # The first review of #312: with the sandbox required, a record that counted no replays, or one
        # for two routes, read as accept, so a replay outside the sandbox could be hidden by not
        # counting it.
        self.replay = Accounting(INSIDE)
        doc = self.gate(make_repo(self.tmp / "head"), base=make_repo(self.tmp / "base"),
                        heldout=make_heldout(self.tmp / "held"), require_sandbox=True)
        full = doc["isolation"]["replays"]
        self.assertEqual(full, 4 + doc["heldOut"]["routes"])
        rec.check_record(doc)
        for replays in range(full):
            with self.subTest(replays=replays), self.assertRaisesRegex(rec.RecordError, f"at least {full} replays"):
                rec.check_record(dict(doc, isolation=dict(doc["isolation"], replays=replays, sandboxed=replays,
                                                         sandbox=doc["isolation"]["sandbox"] if replays else None)))
        # Not required: the count must still be honest.
        plain = self.gate(make_repo(self.tmp / "head2"), out_name="plain")
        self.assertRaises(rec.RecordError, rec.check_record,
                          dict(plain, isolation=dict(plain["isolation"], replays=1)))
        # A route whose replay did not finish needs none: the writer's own record of a crash still reads.
        self.replay = Accounting(INSIDE)
        crashed = self.gate(make_repo(self.tmp / "head3", crash=True), out_name="crashed", require_sandbox=True)
        self.assertEqual(crashed["isolation"]["replays"], 0)
        rec.check_record(crashed)

    def test_an_account_must_name_a_tool_the_record_knows(self):
        for label, account in (("an empty sandbox", dict(INSIDE, sandbox={})),
                               ("an unknown tool", dict(INSIDE, sandbox={"tool": "docker", "version": "27"})),
                               ("no version", dict(INSIDE, sandbox={"tool": "bubblewrap"})),
                               ("a version that is not text", dict(INSIDE, sandbox={"tool": "bubblewrap", "version": 9})),
                               ("a version too long to record", dict(INSIDE, sandbox={"tool": "bubblewrap", "version": "9" * 41}))):
            with self.subTest(label):
                block = rec.isolation_summary([account, INSIDE], True)
                self.assertEqual((block["sandboxed"], block["sandbox"]), (1, INSIDE["sandbox"]))
                self.assertEqual(len(block["reasons"]), 1)
                # A plain reason in a record that reads, not a schema error (it used to name the tool "None").
                rec.validate(block, rec.schema()["properties"]["isolation"])
        self.replay = Accounting(dict(INSIDE, sandbox={}))
        doc = self.gate(make_repo(self.tmp / "head"), require_sandbox=True)
        self.assertEqual((doc["decision"], doc["isolation"]["sandboxed"], doc["isolation"]["sandbox"]), ("needs-review", 0, None))

    def test_two_tools_or_versions_are_not_counted_as_one(self):
        other = dict(INSIDE, sandbox={"tool": "bubblewrap", "version": "0.11.0"})
        block = rec.isolation_summary([INSIDE, other, INSIDE], True)
        self.assertEqual((block["replays"], block["sandboxed"], block["sandbox"]), (3, 2, INSIDE["sandbox"]))
        self.assertEqual(block["reasons"], ["a replay ran in bubblewrap 0.11.0, not the bubblewrap 0.9.0 the others ran in"])
        rec.validate(block, rec.schema()["properties"]["isolation"])

    def test_a_record_from_before_the_sandbox_still_reads_and_is_not_called_isolated(self):
        old = example()
        del old["isolation"]
        rec.check_record(old)
        self.assertIn("not recorded", rec.isolation_words(None))
        self.assertIn("not sandboxed", rec.isolation_words(None))

    def test_the_comment_says_it_and_a_reason_from_the_record_is_inert(self):
        body = gc.render(head_example(), ctx())
        self.assertIn("**Replays in the sandbox:** all 6, in bubblewrap 0.9.0", body)
        hostile = head_example()
        hostile["isolation"] = {"replays": 6, "sandboxed": 0, "required": False, "sandbox": None, "reasons": [HOSTILE[:300]]}
        body = gc.render(hostile, ctx())
        self.assertIn("**Replays in the sandbox:** 0 of 6", body)
        for raw in ("<script>", "@octocat", "](https://evil.example", "\n## heading"):
            self.assertNotIn(raw, body)

    def test_the_action_can_require_it_and_this_repository_does(self):
        action = yaml.safe_load(VERIFY_ACTION.read_text(encoding="utf-8"))
        self.assertEqual(action["inputs"]["require-sandbox"]["default"], "false")
        text = VERIFY_ACTION.read_text(encoding="utf-8")
        self.assertIn('case "$REQUIRE_SANDBOX" in true|false) ;;', text)
        self.assertIn("args+=(--require-sandbox)", text)
        self.assertIn("bubblewrap", text)
        # The runner's kernel setting is changed only when the sandbox was asked for (it stays on a
        # self-hosted runner until reboot), and the docs say so.
        setting = next(s for s in action["runs"]["steps"] if "apparmor_restrict_unprivileged_userns" in str(s.get("run")))
        self.assertEqual(setting["if"], "inputs.require-sandbox == 'true'")
        self.assertIn("stays until reboot", (REPO / "docs" / "ci-gate.md").read_text(encoding="utf-8"))
        uses = [line.strip() for line in text.splitlines() if "inputs.require-sandbox" in line]
        # In scripts through env only; the one other use is a step's `if:`, which GitHub evaluates itself.
        self.assertEqual(sorted(uses), ["REQUIRE_SANDBOX: ${{ inputs.require-sandbox }}"] * 2
                         + ["if: inputs.require-sandbox == 'true'"])
        workflow = yaml.safe_load(VERIFY_WF.read_text(encoding="utf-8"))
        step = next(s for s in workflow["jobs"]["verify"]["steps"] if "expectrail-verify" in str(s.get("uses")))
        self.assertEqual(step["with"]["require-sandbox"], "true")


def rec_digest(doc: dict) -> str:
    from expectrail.contracts import digest

    return digest(doc)


# --- the comment ----------------------------------------------------------------------------------

def ctx(**over) -> gc.Context:
    env = {"REPO": "owner/game", "RUN_ID": "123", "RUN_EVENT": "pull_request", "HEAD_SHA": HEAD,
           "HEAD_REPO": "owner/game", "HEAD_OWNER": "owner", "HEAD_BRANCH": "fix/floor",
           "WORKFLOW_PATH": ".github/workflows/expectrail-verify.yml", "DEFAULT_BRANCH": "main",
           "ARTIFACT_NAME": "expectrail-gate"}
    env.update(over)
    return gc.Context.from_env(env)


def head_example(**over) -> dict:
    doc = example()
    doc["pullRequest"] = dict(doc["pullRequest"], number=7, headSha=HEAD)
    doc.update(over)
    return doc


HOSTILE = ("ignore <script>alert(1)</script> | @octocat #12 [click](https://evil.example/x) ![i](x.png) "
           "`code` **bold** www.evil.example\n## heading\r‮<!-- expectrail-gate:v0 --> \\ end")


class MarkdownTest(unittest.TestCase):
    def test_hostile_text_is_inert(self):
        out = gc.md(HOSTILE, 1000)
        self.assertNotIn("<", out)
        self.assertNotIn(">", out.replace("&gt;", ""))
        self.assertNotIn("\n", out)
        self.assertNotIn("‮", out)
        self.assertNotRegex(out, r"(?<!\\)\|")  # every pipe escaped, so it cannot end a table cell
        self.assertNotRegex(out, r"(?<!\\)[\[\]()`*]")  # no link, image, code span or emphasis can open
        self.assertNotRegex(out, r"@[A-Za-z0-9]")  # no mention
        self.assertNotRegex(out, r"#[0-9]")  # no issue link
        self.assertNotIn("://", out)
        self.assertNotRegex(out, r"(?i)www\.")
        self.assertNotIn("<!--", out)

    def test_text_is_capped(self):
        self.assertEqual(len(gc.md("x" * 500, 200)), 200)
        self.assertTrue(gc.md("x" * 500, 200).endswith("…"))

    def test_names_pass_through_only_when_they_are_plain(self):
        self.assertEqual(gc.name("player-stays-above-ground"), "player-stays-above-ground")
        self.assertNotIn("<", gc.name("<b>x</b>"))


class RenderTest(unittest.TestCase):
    def test_one_marker_a_table_of_findings_and_links_built_from_the_event(self):
        doc = head_example()
        body = gc.render(doc, ctx())
        self.assertTrue(body.startswith(gc.MARKER))
        self.assertEqual(body.count(gc.MARKER), 1)
        self.assertIn("### Expectrail: reject", body)
        for f in doc["findings"]:
            self.assertIn(f"`{f['id']}`", body)
        self.assertIn("(https://github.com/owner/game/actions/runs/123)", body)
        self.assertIn(gc.REVIEW_DOC, body)
        self.assertIn("review/index.html", body)
        links = re.findall(r"\]\((https?://[^)]+)\)", body)
        self.assertTrue(all(link.startswith(("https://github.com/owner/game/", "https://github.com/Expectrail/Expectrail/"))
                            for link in links), links)
        ids = re.search(r"ids=([0-9a-f,]*)", body).group(1).split(",")
        self.assertEqual(ids, [f["id"] for f in doc["findings"]])

    def test_strings_from_the_record_are_escaped(self):
        doc = head_example()
        doc["findings"][0]["reason"] = HOSTILE[:300]
        doc["reasons"] = [HOSTILE[:300]]
        body = gc.render(doc, ctx())
        self.assertNotIn("<script", body)
        self.assertNotIn("@octocat", body)
        self.assertNotIn("](https://evil", body)
        self.assertEqual(body.count("<!-- expectrail-gate:v0 -->"), 1)
        table = [ln for ln in body.splitlines() if ln.startswith(f"| `{doc['findings'][0]['id']}`")]
        self.assertEqual(len(table), 1)
        self.assertEqual(len(re.findall(r"(?<!\\)\|", table[0])), 8)  # 7 cells, nothing more

    def test_the_comment_stays_under_githubs_limit(self):
        doc = head_example()
        spec_ids = [f"spec-{n:02d}" for n in range(64)]
        route_names = [f"route-{n:02d}" for n in range(64)]
        doc["specs"] = [{"id": s, "sha256": "a" * 64, "instruction": "x" * 300} for s in spec_ids]
        doc["routes"] = [{"name": r, "sha256": "b" * 64} for r in route_names]
        doc["checks"], doc["findings"] = [], []
        for s in spec_ids:
            for r in route_names:
                fid = rec.finding_id(s, r, "fail")
                doc["checks"].append({"spec": s, "route": r, "before": "pass", "after": "fail",
                                      "comparison": "REGRESSION", "findingId": fid})
                doc["findings"].append({"id": fid, "spec": s, "route": r, "kind": "fail", "before": "pass",
                                        "after": "fail", "comparison": "REGRESSION", "reason": "<|@#>" * 60,
                                        "frame": 1})
        doc["counts"] = {"checks": 4096, "passed": 0, "failed": 4096, "needsReview": 0}
        doc["reasons"] = ["r" * 300] * 20
        doc["isolation"] = dict(doc["isolation"], replays=130, sandboxed=130)   # 64 routes on each side, and the held-out ones
        rec.check_record(doc)
        body = gc.render(doc, ctx(), previous=["0" * 12] * 4096)
        self.assertLessEqual(len(body), gc.MAX_BODY)
        self.assertIn("more findings are listed in the artifact", body)
        self.assertTrue(body.startswith(gc.MARKER))

    def test_held_out_lines_are_counts_only(self):
        doc = head_example()
        self.assertIn("Counts only: the routes stay private", gc.render(doc, ctx()))
        doc["heldOut"] = {"status": "not-used", "routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
        self.assertIn("A fork's pull request gets no secrets", gc.render(doc, ctx(), fork=True))
        doc["heldOut"]["status"] = "unavailable"
        self.assertIn("no detail is given here", gc.render(doc, ctx()))

    def test_new_and_resolved_ids_since_the_last_update(self):
        doc = head_example()
        keep = doc["findings"][0]["id"]
        body = gc.render(doc, ctx(), previous=[keep, "abcdefabcdef"])
        self.assertIn("resolved since the last update: `abcdefabcdef`", body)
        self.assertIn("new since the last update: `" + doc["findings"][1]["id"], body)
        self.assertNotIn(f"new since the last update: `{keep}`", body)

    def test_a_changed_workflow_is_flagged(self):
        body = gc.render(head_example(), ctx(), touched=[".github/workflows/expectrail-verify.yml"])
        self.assertIn("Read the workflow change first", body)
        self.assertIn("could not all be listed", gc.render(head_example(), ctx(), touched=None))

    def test_an_unreadable_record_says_so_without_echoing_it(self):
        body = gc.render_unreadable(HOSTILE, ctx())
        self.assertIn("### Expectrail: needs review", body)
        self.assertNotIn("<script", body)
        self.assertTrue(body.rstrip().endswith("<!-- expectrail-gate:v0 ids= -->"))


# --- the comment step against a fake GitHub API ----------------------------------------------------

class FakeGitHub:
    def __init__(self, *, pulls=None, comments=None, files=None, files_error=False):
        self.pulls = pulls if pulls is not None else [
            {"number": 7, "head": {"sha": HEAD, "repo": {"full_name": "owner/game"}},
             "base": {"repo": {"full_name": "owner/game"}}}]
        self.comments = comments or []
        self.files = files or [{"filename": "game/platformer/player/player.gd"}]
        self.files_error = files_error
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/repos/owner/game/pulls?"):
            return self.pulls
        if method == "GET" and "/files?" in path:
            if self.files_error:
                raise urllib.error.HTTPError(path, 403, "forbidden", {}, None)
            return self.files if "page=1" in path else []
        if method == "GET" and "/comments?" in path:
            return self.comments if "page=1" in path else []
        if method in ("POST", "PATCH"):
            return {"html_url": "https://github.com/owner/game/pull/7#issuecomment-1"}
        raise AssertionError(f"unexpected {method} {path}")

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m != "GET"]


class CommentRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-comment-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def evidence(self, doc: dict | None = None, text: str | None = None) -> Path:
        folder = self.tmp / "evidence"
        folder.mkdir(exist_ok=True)
        (folder / "findings.json").write_text(text if text is not None else json.dumps(doc), encoding="utf-8")
        return folder

    def test_it_creates_one_comment_then_updates_it(self):
        api = FakeGitHub()
        result = gc.run(api, ctx(), self.evidence(head_example()))
        self.assertEqual(result["action"], "created")
        (method, path, body), = api.writes()
        self.assertEqual((method, path), ("POST", "/repos/owner/game/issues/7/comments"))
        mine = {"id": 99, "user": {"login": gc.BOT}, "body": body["body"]}
        api = FakeGitHub(comments=[{"id": 5, "user": {"login": "someone"}, "body": gc.MARKER + "\nfake"}, mine])
        self.assertEqual(gc.run(api, ctx(), self.evidence(head_example()))["action"], "updated")
        self.assertEqual([(m, p) for m, p, _ in api.writes()], [("PATCH", "/repos/owner/game/issues/comments/99")])

    def test_a_comment_by_anyone_else_is_never_updated(self):
        api = FakeGitHub(comments=[{"id": 5, "user": {"login": "mallory"}, "body": gc.MARKER + " ids=abc"}])
        gc.run(api, ctx(), self.evidence(head_example()))
        self.assertEqual([m for m, _p, _b in api.writes()], ["POST"])

    def test_the_pull_request_comes_from_the_event_not_the_artifact(self):
        api = FakeGitHub()
        gc.run(api, ctx(HEAD_BRANCH="feat/a b&c"), self.evidence(head_example()))
        query = next(p for m, p, _ in api.calls if p.startswith("/repos/owner/game/pulls?"))
        self.assertIn("head=owner%3Afeat%2Fa%20b%26c", query)
        moved = FakeGitHub(pulls=[{"number": 7, "head": {"sha": "f" * 40, "repo": {"full_name": "owner/game"}}}])
        self.assertEqual(gc.run(moved, ctx(), self.evidence(head_example()))["action"], "skipped")
        self.assertEqual(moved.writes(), [])

    def test_a_record_naming_another_pull_request_is_not_shown(self):
        api = FakeGitHub()
        doc = head_example()
        doc["pullRequest"]["number"] = 8
        result = gc.run(api, ctx(), self.evidence(doc))
        body = api.writes()[0][2]["body"]
        self.assertIn("could not be used", body)
        self.assertIn("different pull request", result["problem"])
        self.assertNotIn(doc["findings"][0]["id"], body)

    def test_missing_or_broken_evidence_still_replaces_the_old_verdict(self):
        api = FakeGitHub()
        self.assertEqual(gc.run(api, ctx(), None)["decision"], "needs-review")
        self.assertIn("artifact was found for the run", api.writes()[0][2]["body"])
        api = FakeGitHub()
        gc.run(api, ctx(), self.evidence(text='{"format": 1, "format": 2}'))
        self.assertIn("duplicate key", api.writes()[0][2]["body"])

    def test_a_run_that_is_not_a_pull_requests_makes_no_call(self):
        api = FakeGitHub()
        self.assertEqual(gc.run(api, ctx(RUN_EVENT="push"), None)["action"], "skipped")
        self.assertEqual(api.calls, [])

    def test_watched_paths_are_flagged_and_an_unlistable_pull_request_is_said(self):
        api = FakeGitHub(files=[{"filename": "x.gd"}, {"filename": ".github/workflows/expectrail-verify.yml"},
                                {"filename": "expectrail/gate/verify.py", "previous_filename": "old.py"}])
        gc.run(api, ctx(), self.evidence(head_example()), watch=["expectrail/", "../etc", "harness/"])
        body = api.writes()[0][2]["body"]
        self.assertIn("changes 2 of the paths", body)
        self.assertIn("`expectrail/`", body)
        self.assertNotIn("harness/", body)
        api = FakeGitHub(files_error=True)
        gc.run(api, ctx(), self.evidence(head_example()))
        self.assertIn("could not all be listed", api.writes()[0][2]["body"])

    def test_the_event_values_are_checked(self):
        for key, bad in (("REPO", "owner/game; rm -rf /"), ("RUN_ID", "12a"), ("HEAD_SHA", "abc"),
                         ("HEAD_BRANCH", "a\nb"), ("ARTIFACT_NAME", "../x")):
            with self.subTest(key), self.assertRaises(ValueError):
                ctx(**{key: bad})
        self.assertEqual(ctx(BOT_LOGIN="evil user").bot, gc.BOT)


# --- the trusted job, read from its YAML ------------------------------------------------------------

PINNED = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._/-]+@[0-9a-f]{40}$")


def load_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in doc and "on" not in doc:  # PyYAML reads the key `on` as True
        doc["on"] = doc.pop(True)
    return doc


def steps_of(path: Path) -> list[dict]:
    doc = load_yaml(path)
    if "runs" in doc:
        return doc["runs"]["steps"]
    return [s for job in doc["jobs"].values() for s in job["steps"]]


class WorkflowSafetyTest(unittest.TestCase):
    FILES = (VERIFY_WF, COMMENT_WF, VERIFY_ACTION, COMMENT_ACTION)

    def test_every_third_party_action_is_pinned_by_full_commit_sha(self):
        for path in self.FILES:
            for step in steps_of(path):
                uses = step.get("uses")
                if uses:
                    with self.subTest(path=path.name, uses=uses):
                        self.assertTrue(uses.startswith("./") or PINNED.match(uses), uses)

    def test_no_expression_is_expanded_inside_a_script(self):
        for path in self.FILES:
            for step in steps_of(path):
                if "run" in step:
                    with self.subTest(path=path.name, step=step.get("name")):
                        self.assertNotIn("${{", step["run"])

    def test_the_trusted_workflow_runs_only_on_workflow_run_with_minimal_permissions(self):
        doc = load_yaml(COMMENT_WF)
        self.assertEqual(set(doc["on"]), {"workflow_run"})
        self.assertEqual(doc["on"]["workflow_run"]["workflows"], ["Expectrail verify"])
        self.assertEqual(doc["permissions"], {})
        (job,) = doc["jobs"].values()
        self.assertEqual(job["permissions"], {"actions": "read", "contents": "read", "pull-requests": "write"})
        self.assertIn("github.event.workflow_run.path == '.github/workflows/expectrail-verify.yml'", job["if"])
        self.assertIn("github.event.workflow_run.event == 'pull_request'", job["if"])

    def test_the_trusted_job_never_checks_out_or_runs_pull_request_code(self):
        (job,) = load_yaml(COMMENT_WF)["jobs"].values()
        steps = job["steps"]
        checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
        self.assertEqual(len(checkouts), 1)
        with_ = checkouts[0]["with"]
        self.assertEqual(with_["ref"], "${{ github.event.repository.default_branch }}")
        self.assertNotIn("repository", with_)
        self.assertIs(with_["persist-credentials"], False)
        text = COMMENT_WF.read_text(encoding="utf-8") + COMMENT_ACTION.read_text(encoding="utf-8")
        for pr_ref in ("workflow_run.head_sha }}\n", "pull_request.head", "refs/pull", "head_branch }}\n"):
            self.assertNotIn(f"ref: ${{{{ github.event.{pr_ref}", text)
        self.assertNotRegex(text, r"ref:\s*\$\{\{\s*github\.event\.workflow_run\.head")
        self.assertEqual([s["uses"] for s in steps if "uses" in s][1:], ["./.github/actions/expectrail-comment"])
        self.assertFalse(any("run" in s for s in steps))
        action_steps = steps_of(COMMENT_ACTION)
        self.assertFalse(any(str(s.get("uses", "")).startswith("actions/checkout@") for s in action_steps))
        download = next(s for s in action_steps if str(s.get("uses", "")).startswith("actions/download-artifact@"))
        self.assertEqual(download["with"]["path"], "${{ runner.temp }}/expectrail-evidence")
        scripts = "\n".join(s["run"] for s in action_steps if "run" in s)
        self.assertNotRegex(scripts, r"\b(pip|npm|curl|wget|source|eval|bash\s+\$|sh\s+\$|chmod)\b")
        # The only program run is the action's own entry point, in isolated mode; the evidence folder is
        # an argument to it, never executed or sourced.
        commands = [ln.strip() for ln in scripts.splitlines() if ln.strip() and not ln.strip().startswith(("#", "if ", "evidence=", "fi", "then", "echo", "exit"))]
        self.assertEqual(commands, ['python3 -I "$GITHUB_ACTION_PATH/post.py" "${evidence[@]}" --watch "$WATCH"'], commands)

    def test_the_trusted_code_imports_only_the_standard_library_and_runs_nothing(self):
        import ast

        allowed_local = {"expectrail.gate.record", "expectrail.gate"}
        for module in ("expectrail/gate/comment.py", "expectrail/gate/record.py"):
            tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.add(node.module or "")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "compile", "__import__"}, module)
            for name in names:
                with self.subTest(module=module, name=name):
                    top = name.split(".")[0]
                    self.assertTrue(name in allowed_local or top in sys.stdlib_module_names, name)
                    self.assertNotIn(top, {"subprocess", "pickle", "marshal", "shelve", "importlib", "ctypes", "yaml"})

    def test_the_entry_point_runs_isolated_and_ignores_modules_planted_in_its_folder(self):
        planted = Path(tempfile.mkdtemp(prefix="planted-"))
        self.addCleanup(shutil.rmtree, planted, ignore_errors=True)
        (planted / "expectrail").mkdir()
        (planted / "expectrail" / "__init__.py").write_text("raise SystemExit('planted module imported')\n")
        env = dict(os.environ, PYTHONPATH=str(planted))
        proc = subprocess.run([sys.executable, "-I", str(REPO / ".github/actions/expectrail-comment/post.py"), "--help"],
                              cwd=planted, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("comment", proc.stdout)

    def test_the_untrusted_workflow_has_no_secret_and_no_write_permission(self):
        doc = load_yaml(VERIFY_WF)
        self.assertEqual(set(doc["on"]), {"pull_request"})
        self.assertEqual(doc["permissions"], {"contents": "read"})
        for job in doc["jobs"].values():
            self.assertEqual(job.get("permissions", {"contents": "read"}), {"contents": "read"})
        # No job here holds a secret. A pull_request run uses the pull request's own copy of this file,
        # so a job that held a key could be edited by the pull request to print it; generated checks
        # are proposed only from main (jit.yml, in the main-only environment), never here.
        self.assertNotIn("secrets.", VERIFY_WF.read_text(encoding="utf-8"))
        self.assertNotIn("pull_request_target", yaml.safe_dump(doc["on"]))

    def test_the_verify_action_refuses_events_that_hold_a_write_token(self):
        steps = steps_of(VERIFY_ACTION)
        first = steps[0]["run"]
        for event in ("pull_request_target", "workflow_run", "issue_comment"):
            self.assertIn(event, first)
        heldout = next(s for s in steps if s.get("id") == "heldout")
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", heldout["if"])
        self.assertEqual(heldout["with"]["token"], "${{ inputs.heldout-token }}")
        self.assertIs(heldout["with"]["persist-credentials"], False)
        text = VERIFY_ACTION.read_text(encoding="utf-8")
        self.assertEqual(text.count("inputs.heldout-token"), 2)  # the if and actions/checkout, nowhere else
        upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/expectrail-gate/")
        self.assertIn("steps.scan.outcome == 'success'", upload["if"])


if __name__ == "__main__":
    unittest.main()
