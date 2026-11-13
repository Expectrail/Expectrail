"""`expectrail doctor` (#333): one list of what a run needs, checked as a run uses it, shared with
the engine's preflight; and a command line that cannot be read exits 5, never 2.

The engine here is a stand-in script that answers `--version` and names a device when asked to draw,
and the programs on the PATH are a stand-in for `shutil.which`. One test at the end uses the real
engine when EXPECTRAIL_ENGINE_TESTS=required, as the other real-engine tests do.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from expectrail import cli, doctor
from expectrail.orchestrator import cli as orchestrator_cli
from expectrail.orchestrator import engines

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "contracts" / "examples" / "doctor.json"
ENGINE_TESTS = os.environ.get("EXPECTRAIL_ENGINE_TESTS", "")
LLVMPIPE = "OpenGL API 4.5 (Core Profile) Mesa 25.2.8 - Compatibility - Using Device: Mesa - llvmpipe (LLVM 20.1.2, 256 bits)"
EVERYTHING = ("xvfb-run", "bwrap", "patch", "curl", "unzip")
SECRET = "sk-THIS-VALUE-MUST-NEVER-BE-PRINTED"
Usage = namedtuple("Usage", "total used free")
STUB = """#!/bin/bash
here="$(dirname "$0")"
if [ "$1" = "--version" ]; then cat "$here/version"; exit 0; fi
cat "$here/draws"
exit "$(cat "$here/exit")"
"""


class Machine(unittest.TestCase):
    """A stand-in machine: an engine, a set of programs, free disk, an environment."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.engine = self.tmp / "engine" / "godot"
        self.engine.parent.mkdir()
        self.engine.write_text(STUB, encoding="utf-8")
        self.engine.chmod(self.engine.stat().st_mode | stat.S_IXUSR)
        self.set_engine()
        self.programs = set(EVERYTHING)
        self.free = 50 * 1024 ** 3
        self.sandbox = True
        env = {k: v for k, v in os.environ.items() if k not in doctor.VISION_KEYS}
        env.update(EXPECTRAIL_GODOT=str(self.engine), EXPECTRAIL_TOOLS=str(self.tmp / "tools"))
        for patch in (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(doctor.shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}" if name in self.programs else None),
                mock.patch.object(doctor.shutil, "disk_usage", lambda path: Usage(self.free * 2, self.free, self.free)),
                mock.patch.object(doctor.sys, "platform", "linux"),
                # The engine is started as a replay starts it, less the virtual display this stand-in has no use for.
                mock.patch("harness.run.godot_cmd", lambda godot, display: [str(godot)]),
                mock.patch("harness.sandbox.probe", lambda display=True: (
                    (namedtuple("Tool", "path version")("/usr/bin/bwrap", "0.9.0"), None) if self.sandbox and "bwrap" in self.programs
                    else (None, "bubblewrap (bwrap) is not installed")))):
            patch.start()
            self.addCleanup(patch.stop)

    def set_engine(self, version: str = "4.7.2.stable.official.ed1daf0bf", draws: str = LLVMPIPE, code: int = 0):
        (self.engine.parent / "version").write_text(version + "\n", encoding="utf-8")
        (self.engine.parent / "draws").write_text(draws + "\n", encoding="utf-8")
        (self.engine.parent / "exit").write_text(str(code), encoding="utf-8")

    def by_id(self, **kw) -> dict[str, doctor.Check]:
        return {c.id: c for c in doctor.checks(**kw)}

    def run_doctor(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["doctor", *argv])
        return code, out.getvalue(), err.getvalue()


class DoctorTest(Machine):
    def test_a_machine_with_everything_passes_and_names_each_thing_it_checked(self):
        code, out, err = self.run_doctor()
        self.assertEqual((code, err), (0, ""))
        for words in ("Python 3.12 or later", "Godot 4.7.2-stable", "a virtual display (xvfb-run)", "OpenGL the engine can draw with",
                      "MB free for the engine", "the replay sandbox (bubblewrap)", "`patch`", "`curl`", "`unzip`",
                      "a key for a visual observer", "Everything a verification needs is here.",
                      "It is not a verdict on any change."):
            self.assertIn(words, out)
        self.assertIn("the engine drew a frame with Mesa - llvmpipe", out)
        self.assertNotIn("MISSING", out)
        self.assertEqual([c.id for c in doctor.checks()],
                         ["python", "godot", "display", "opengl", "disk", "sandbox", "patch", "curl", "unzip", "vision-key"])

    def test_each_required_tool_removed_fails_and_names_the_fix(self):
        for gone, check, fix in (("xvfb-run", "display", "sudo apt-get install xvfb"),
                                 ("patch", "patch", "sudo apt-get install patch")):
            with self.subTest(gone=gone):
                self.programs = set(EVERYTHING) - {gone}
                code, out, _ = self.run_doctor()
                self.assertEqual(code, 3)
                self.assertIn(f"fix: {fix}", out)
                self.assertIn(f"{gone} is not installed", out)
                self.assertIn("fix that before running `expectrail sample` or a verification here", out)
                found = self.by_id()
                self.assertEqual((found[check].status, found[check].required), ("missing", True))

    def test_without_a_display_the_drawing_check_is_not_tried_and_says_so(self):
        self.programs -= {"xvfb-run"}
        found = self.by_id()
        self.assertEqual((found["opengl"].status, found["opengl"].required), ("skipped", True))
        self.assertIn("one is missing above", found["opengl"].found)
        self.assertEqual({c.id for c in doctor.missing(list(found.values()))}, {"display", "opengl"})

    def test_what_is_not_required_is_reported_and_does_not_fail(self):
        self.programs -= {"curl", "unzip", "bwrap"}
        code, out, _ = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("Not required and missing: sandbox, curl, unzip.", out)
        self.assertIn("fix: sudo apt-get install bubblewrap", out)
        self.assertIn("to fetch the engine; it is already here", out)
        self.assertNotIn("MISSING", out)   # the capitals are for what stops a run

    def test_the_isolated_class_requires_the_sandbox(self):
        self.programs -= {"bwrap"}
        self.assertEqual(self.run_doctor()[0], 0)
        code, out, _ = self.run_doctor("--isolated")
        self.assertEqual(code, 3)
        self.assertIn("MISSING   the replay sandbox (bubblewrap)", out)
        self.assertIn("the isolated class and `require-sandbox` refuse to run", out)
        self.programs.add("bwrap")
        self.assertEqual(self.run_doctor("--isolated")[0], 0)

    def test_an_engine_of_another_version_is_not_the_pinned_one(self):
        for version in ("4.6.1.stable.official.abc", "4.7.20.stable.official.abc", "4.7.2.beta1.official.abc", ""):
            with self.subTest(version=version):
                self.set_engine(version=version)
                found = self.by_id()
                self.assertEqual(found["godot"].status, "missing")
                self.assertIn("not 4.7.2-stable", found["godot"].found)
                self.assertIn("recorded results are for that version", found["godot"].fix)
                self.assertEqual(found["opengl"].status, "skipped")
        self.set_engine(version="4.7.2.stable")
        self.assertEqual(self.by_id()["godot"].status, "ok")

    def test_an_engine_that_is_not_there(self):
        os.environ["EXPECTRAIL_GODOT"] = str(self.tmp / "nowhere" / "godot")
        found = self.by_id()
        self.assertEqual(found["godot"].status, "missing")
        self.assertIn("Godot could not be found or downloaded (FileNotFoundError)", found["godot"].found)
        self.assertIn("allow a download from github.com", found["godot"].fix)
        self.programs -= {"curl", "unzip"}
        self.assertIn("sudo apt-get install curl unzip, then run `expectrail doctor` again", self.by_id()["godot"].fix)
        self.programs = set(EVERYTHING)
        # Not named, not fetched, and told not to fetch: missing, with the way to get it.
        del os.environ["EXPECTRAIL_GODOT"]
        found = self.by_id(fetch=False)
        self.assertEqual(found["godot"].status, "missing")
        self.assertIn("--no-fetch was given", found["godot"].found)
        self.assertIn("to fetch the engine", found["curl"].what)
        self.assertNotIn("already here", found["curl"].what)
        # A fetch that fails is the same finding, by the kind of error only.
        # The fetch script's own last line is shown; nothing else it or a program under it printed is.
        said = f"curl: (56) {SECRET}\nget_godot: download attempt 1 of 2 failed; trying again in 5s\n" \
               "get_godot: could not download https://example.invalid/Godot.zip with a matching SHA-512 in 2 attempts\n"
        with mock.patch("harness.run.find_godot", side_effect=subprocess.CalledProcessError(1, "get_godot.sh", stderr=said)):
            found = self.by_id()
        self.assertIn("could not be found or downloaded (CalledProcessError): could not download https://example.invalid/Godot.zip "
                      "with a matching SHA-512 in 2 attempts", found["godot"].found)
        self.assertNotIn(SECRET, json.dumps(doctor.document(list(found.values()))))
        with mock.patch("harness.run.find_godot", side_effect=subprocess.CalledProcessError(1, "get_godot.sh", stderr=SECRET)):
            found = self.by_id()
        self.assertTrue(found["godot"].found.endswith("could not be found or downloaded (CalledProcessError)"))

    def test_the_engine_must_draw_a_frame(self):
        self.set_engine(draws="ERROR: Your video card drivers seem not to support the required OpenGL 3.3 version.", code=1)
        found = self.by_id()
        self.assertEqual(found["opengl"].status, "missing")
        self.assertIn("the engine drew no frame (exit 1, no device named)", found["opengl"].found)
        self.assertEqual(found["opengl"].fix, "sudo apt-get install libgl1-mesa-dri libglx-mesa0")
        self.assertEqual(self.run_doctor()[0], 3)
        self.set_engine(draws="no device line at all")
        self.assertEqual(self.by_id()["opengl"].status, "missing")
        # Another device draws, and the answer says it is not what the recorded runs used.
        self.set_engine(draws="OpenGL API 4.6 - Compatibility - Using Device: NVIDIA Corporation - GeForce RTX 3080")
        seen = self.by_id()["opengl"]
        self.assertEqual(seen.status, "ok")
        self.assertIn("this is not Mesa's software renderer", seen.found)

    def test_too_little_free_disk_is_missing(self):
        self.free = 200 * 1024 ** 2
        found = self.by_id()
        self.assertEqual(found["disk"].status, "missing")
        self.assertIn("200 MB free in the engine's folder", found["disk"].found)
        self.assertIn("EXPECTRAIL_TOOLS", found["disk"].fix)
        self.assertEqual(self.run_doctor()[0], 3)

    def test_an_older_python_is_missing(self):
        info = namedtuple("V", "major minor micro releaselevel serial")(3, 11, 9, "final", 0)
        with mock.patch.object(doctor.sys, "version_info", info):
            found = doctor.python()
        self.assertEqual((found.status, found.found), ("missing", "Python 3.11.9"))
        self.assertIn("3.12 or later", found.fix)

    def test_the_vision_key_is_present_or_absent_and_never_printed(self):
        code, out, _ = self.run_doctor()
        self.assertEqual(code, 0)   # no key is not a missing piece
        self.assertIn("absent    a key for a visual observer", out)
        self.assertIn("a run without a key still rejects a failing change and accepts nothing", out)
        self.assertIn("judge on the engine's record only and use no key", out)
        for name in doctor.VISION_KEYS:
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: SECRET}):
                for argv in ((), ("--json",)):
                    code, out, err = self.run_doctor(*argv)
                    self.assertEqual(code, 0)
                    self.assertNotIn(SECRET, out + err)
                    self.assertIn(name, out)
                self.assertEqual(self.by_id()["vision-key"].status, "present")
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "   "}):
            self.assertEqual(self.by_id()["vision-key"].status, "absent")

    def test_the_key_names_are_the_ones_the_observers_read(self):
        from agents import glimmer_client, sam_observations

        self.assertIn(sam_observations.KEY_ENV, doctor.VISION_KEYS)
        for name in glimmer_client.KEY_ENVS:
            self.assertIn(name, doctor.VISION_KEYS)


class RecordTest(Machine):
    def test_json_is_one_valid_record_and_ok_follows_from_the_checks(self):
        code, out, _ = self.run_doctor("--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["format"], doc["ok"]), (0, "expectrail.doctor/v1", True))
        self.assertEqual(doctor.problems(doc), [])
        self.programs -= {"patch"}
        code, out, _ = self.run_doctor("--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["ok"]), (3, False))
        self.assertEqual(doctor.problems(doc), [])
        self.assertEqual([c["fix"] for c in doc["checks"] if c["id"] == "patch"], ["sudo apt-get install patch"])

    def test_the_example_is_a_valid_record(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(doctor.problems(doc), [])
        self.assertFalse(doc["ok"])
        self.assertEqual({c["status"] for c in doc["checks"]}, {"ok", "missing", "skipped", "absent"})

    def test_a_reader_does_not_take_the_summarys_word(self):
        self.programs -= {"patch"}
        doc = doctor.document(doctor.checks())
        doc["ok"] = True
        self.assertEqual(doctor.problems(doc), ["doctor: `ok` does not follow from the checks"])
        doc = doctor.document(doctor.checks())
        doc["checks"][0]["note"] = "x"
        self.assertTrue(doctor.problems(doc))
        doc = doctor.document(doctor.checks())
        doc["checks"].append(dict(doc["checks"][0]))
        self.assertIn("doctor: a check is listed twice", doctor.problems(doc))
        doc = doctor.document(doctor.checks())
        doc["checks"][0]["fix"] = "do something"
        self.assertTrue(any("a fix is given exactly when" in p for p in doctor.problems(doc)))
        for bad in ([], {"format": "expectrail.doctor/v0"}, None):
            self.assertTrue(doctor.problems(bad))

    def test_long_text_is_cut_to_what_the_schema_holds(self):
        long = doctor.Check("godot", "w" * 500, "missing", True, "f" * 5000, "x" * 5000, True)
        doc = doctor.document([long])
        self.assertEqual(doctor.problems(doc), [])


class PreflightTest(Machine):
    """The engine's preflight asks the same list, so `doctor` and a run cannot disagree about a tool."""

    def preflight(self) -> list[dict]:
        return engines.GodotGate._tools()

    def test_what_stops_a_run_is_what_doctor_calls_missing(self):
        def broken_display():
            self.programs -= {"xvfb-run"}

        def wrong_engine():
            self.set_engine(version="4.6.1.stable.official.abc")

        def no_opengl():
            self.set_engine(draws="nothing", code=1)

        def full_disk():
            self.free = 1024

        def no_patch():   # not every run needs it: doctor fails, the preflight does not
            self.programs -= {"patch"}

        for change, stops in ((lambda: None, set()), (broken_display, {"display", "opengl"}), (wrong_engine, {"godot", "opengl"}),
                              (no_opengl, {"opengl"}), (full_disk, {"disk"}), (no_patch, set())):
            with self.subTest(change=change.__name__):
                self.programs, self.free = set(EVERYTHING), 50 * 1024 ** 3
                self.set_engine()
                change()
                found = doctor.checks()
                for_run = [c for c in doctor.missing(found) if c.run]
                self.assertEqual({c.id for c in for_run}, stops)
                diagnostics = self.preflight()
                self.assertEqual([d["code"] for d in diagnostics], ["TOOL_MISSING"] * len(stops))
                self.assertEqual([d["detail"] for d in diagnostics], [f"{c.found}. Fix: {c.fix}" for c in for_run])
                # When doctor passes, the preflight's tool check passes.
                if not doctor.missing(found):
                    self.assertEqual(diagnostics, [])

    def test_the_preflights_list_is_the_part_of_doctors_list_every_run_needs(self):
        self.assertEqual([c.id for c in doctor.for_run()], [c.id for c in doctor.checks() if c.run])
        self.assertEqual([c.id for c in doctor.for_run()], ["godot", "display", "opengl", "disk"])
        self.assertTrue(all(c.required for c in doctor.for_run()))

    def test_a_missing_engine_keeps_the_words_the_preflight_always_used(self):
        os.environ["EXPECTRAIL_GODOT"] = str(self.tmp / "nowhere")
        details = [d["detail"] for d in self.preflight()]
        self.assertTrue(details[0].startswith("Godot could not be found or downloaded (FileNotFoundError). Fix: "), details)
        self.programs -= {"xvfb-run"}
        self.assertTrue(any(d["detail"].startswith("xvfb-run is not installed. Fix: sudo apt-get install xvfb") for d in self.preflight()))


class UsageTest(unittest.TestCase):
    """A command line that cannot be read exits 5 (could not be carried out), never 2 (needs review)."""

    def run_main(self, main, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_verify_with_missing_options_exits_5_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for main in (cli.main, orchestrator_cli.main):
                for argv in (("verify",), ("verify", "--head", "."), ("verify", "--head", ".", "--game", "g", "--routes", "r"),
                             ("verify", "--head", ".", "--game", "g", "--routes", "r", "--specs", "s", "--frobnicate"),
                             ("verify", "--head", ".", "--game", "g", "--routes", "r", "--specs", "s", "--timeout", "soon"),
                             ("verify", "--head", ".", "--game", "g", "--routes", "r", "--specs", "s",
                              "--execution-class", "trusted"),
                             ("status",), ("cancel",), ("report",), ("sample", "--frobnicate")):
                    with self.subTest(main=main.__module__, argv=argv):
                        code, out, err = self.run_main(main, "--jobs-root", tmp, *argv)
                        self.assertEqual(code, 5, err)
                        self.assertEqual(out, "")
                        self.assertIn("usage:", err)
                        self.assertIn("Nothing was run.", err)
            self.assertEqual(list(Path(tmp).iterdir()), [])   # no job was made

    def test_the_orchestrator_with_no_command_exits_5_too(self):
        self.assertEqual(self.run_main(orchestrator_cli.main)[0], 5)
        self.assertEqual(self.run_main(orchestrator_cli.main, "frobnicate")[0], 5)

    def test_help_is_still_exit_0(self):
        for argv in (("verify", "--help"), ("--help",)):
            with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(io.StringIO()):
                orchestrator_cli.main(list(argv))
            self.assertEqual(stop.exception.code, 0)

    def test_as_a_process_the_exit_code_is_5(self):
        done = subprocess.run([sys.executable, "-m", "expectrail.cli", "verify", "--head", "."], cwd=REPO,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout), (5, ""))
        self.assertIn("the following arguments are required: --game, --routes, --specs", done.stderr)

    def test_doctor_with_an_option_it_does_not_have_exits_5_and_checks_nothing(self):
        with mock.patch.object(doctor, "checks", side_effect=AssertionError("nothing may be checked")):
            for argv in (("doctor", "--frobnicate"), ("doctor", "extra"), ("--jobs-root", "x", "doctor")):
                code, out, err = self.run_main(cli.main, *argv)
                self.assertEqual((code, out), (5, ""), err)
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["doctor", "--help"])
        self.assertEqual(stop.exception.code, 0)

    def test_doctor_is_listed_as_a_command_that_is_built(self):
        text = cli.usage()
        self.assertIn("doctor       check that this machine has what a verification needs", text)
        self.assertNotIn("doctor", cli.PLANNED)
        self.assertEqual(sorted(cli.PLANNED), ["repair", "trust-check"])


@unittest.skipUnless(ENGINE_TESTS == "required", "set EXPECTRAIL_ENGINE_TESTS=required to check with real Godot")
class RealEngineTest(unittest.TestCase):
    def test_the_real_engine_at_the_pinned_version_draws_a_frame(self):
        found = {c.id: c for c in doctor.for_run()}
        self.assertEqual({c.status for c in found.values()}, {"ok"}, [(c.id, c.found) for c in found.values()])
        self.assertIn("4.7.2.stable", found["godot"].found)
        self.assertIn("llvmpipe", found["opengl"].found)
        self.assertEqual(engines.GodotGate._tools(), [])


class DisplayApplicabilityTest(Machine):
    """An inapplicable display check is not a successful or a failed probe (#377)."""

    def test_non_linux_documents_are_readable_with_or_without_an_engine(self):
        self.programs.discard("xvfb-run")
        for platform in ("darwin", "win32"):
            for engine_here in (True, False):
                with self.subTest(platform=platform, engine_here=engine_here), \
                        mock.patch.object(doctor.sys, "platform", platform), \
                        mock.patch.dict(os.environ, EXPECTRAIL_GODOT=str(self.engine if engine_here else self.tmp / "missing")):
                    checks = doctor.checks(fetch=False, env={})
                    doc = doctor.document(checks)
                    self.assertEqual(doctor.problems(doc), [])
                    shown = next(c for c in doc["checks"] if c["id"] == "display")
                    self.assertEqual((shown["status"], shown["required"], shown["fix"]), ("skipped", False, None))
                    self.assertIn("does not apply", shown["found"])
                    self.assertNotIn(f"  {'ok':<9} {shown['what']}", doctor.text(checks))
                    if not engine_here:
                        self.assertFalse(doc["ok"])

    def test_linux_display_still_requires_xvfb_run(self):
        for installed in (True, False):
            with self.subTest(installed=installed):
                self.programs = set(EVERYTHING) if installed else set(EVERYTHING) - {"xvfb-run"}
                shown = doctor.display()
                self.assertTrue(shown.required)
                self.assertEqual(shown.status, "ok" if installed else "missing")
                self.assertEqual(shown.fix, None if installed else "sudo apt-get install xvfb")
                doc = doctor.document([shown])
                self.assertEqual(doc["ok"], installed)
                self.assertEqual(doctor.problems(doc), [])

    def test_a_required_skipped_check_still_blocks_readiness(self):
        with mock.patch.object(doctor.sys, "platform", "darwin"):
            shown = doctor.display()
        waiting = doctor.Check("opengl", "OpenGL", "skipped", True, "not tried", "install the engine")
        checks = [shown, waiting]
        doc = doctor.document(checks)
        self.assertFalse(doc["ok"])
        self.assertEqual(doctor.missing(checks), [waiting])
        self.assertEqual(doctor.problems(doc), [])
        with mock.patch.object(doctor, "checks", return_value=checks):
            code, out, _ = self.run_doctor()
        self.assertEqual(code, 3)
        self.assertNotIn("Everything a verification needs is here.", out)
        doc["ok"] = True
        self.assertIn("doctor: `ok` does not follow from the checks", doctor.problems(doc))
        doc["ok"] = False
        doc["checks"][1]["fix"] = None
        self.assertTrue(doctor.problems(doc))

    def test_missing_checks_still_need_a_fix_even_when_optional(self):
        for required in (False, True):
            for fix in (None, ""):
                with self.subTest(required=required, fix=fix):
                    check = doctor.Check("display", "a display", "missing", required, "not installed", fix)
                    self.assertTrue(doctor.problems(doctor.document([check])))

    def test_a_failed_probe_with_no_fix_is_still_refused(self):
        self.set_engine(draws="the drawing probe failed", code=1)
        failed = self.by_id(fetch=False)["opengl"]
        self.assertEqual(failed.status, "missing")
        self.assertTrue(failed.fix)
        self.assertEqual(doctor.problems(doctor.document([failed])), [])
        failed.fix = None
        self.assertTrue(doctor.problems(doctor.document([failed])))

    def test_an_optional_skipped_check_can_still_name_a_fix(self):
        check = doctor.Check("probe", "an optional probe", "skipped", False, "not tried", "install its tool")
        self.assertEqual(doctor.problems(doctor.document([check])), [])

    def test_the_schema_requires_fixes_for_missing_and_required_skipped_checks(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(doctor.SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for status, required in (("missing", False), ("missing", True), ("skipped", True)):
            for fix in (None, ""):
                with self.subTest(status=status, required=required, fix=fix):
                    check = doctor.Check("probe", "a probe", status, required, "not available", fix)
                    doc = doctor.document([check])
                    self.assertTrue(list(validator.iter_errors(doc)))
                    self.assertTrue(doctor.problems(doc))
                    doc["checks"][0]["fix"] = "install its tool"
                    validator.validate(doc)
                    self.assertEqual(doctor.problems(doc), [])

    def test_the_example_has_an_inapplicable_display_and_validates(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(doctor.SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(doc)
        self.assertEqual(doctor.problems(doc), [])
        shown = next(c for c in doc["checks"] if c["id"] == "display")
        self.assertEqual((shown["status"], shown["required"], shown["fix"]), ("skipped", False, None))
        self.assertFalse(doc["ok"])


if __name__ == "__main__":
    unittest.main()
