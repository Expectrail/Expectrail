"""First-time downloads in CI are retried and cached (#296): the Godot engine and Playwright's Chromium.

harness/get_godot.sh is run here from a copy in a temporary tree, against a stand-in for curl and a
small zip standing in for the engine, with the copy's SHA-512 set to that zip's. Nothing is
downloaded. Not covered here: the actions on a real runner (CI covers that) and actions/cache itself.
"""
import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "harness" / "get_godot.sh"
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
ACTIONS = REPO / ".github" / "actions"

# curl fails while $STATE/failures is above zero; then it writes $STATE/served to the -o path.
CURL = r'''#!/bin/bash
echo "curl" >> "$STATE/calls"
left=$(cat "$STATE/failures" 2>/dev/null || echo 0)
if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$STATE/failures"; echo "curl: (22) The requested URL returned error: 500" >&2; exit 22; fi
out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done
cp "$STATE/served" "$out"
'''


class GetGodot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import executable
        for tool in ("bash", "sha512sum", "unzip"):
            executable(tool)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        text = SCRIPT.read_text(encoding="utf-8")
        self.binary_name = "Godot_v" + re.search(r'^VERSION="([^"]+)"', text, re.M).group(1) + "_linux.x86_64"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(self.binary_name, "#!/bin/sh\necho stand-in engine\n")
        self.zip = buffer.getvalue()
        pinned = re.search(r'^SHA512="([0-9a-f]{128})"', text, re.M)
        self.assertIsNotNone(pinned, "the script pins a SHA-512")
        (self.root / "harness").mkdir()
        copy = self.root / "harness" / "get_godot.sh"
        copy.write_text(text.replace(pinned.group(1), hashlib.sha512(self.zip).hexdigest()), encoding="utf-8")
        self.bin, self.state = self.root / "bin", self.root / "state"
        self.bin.mkdir()
        self.state.mkdir()
        curl = self.bin / "curl"
        curl.write_text(CURL, encoding="utf-8")
        curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
        (self.state / "served").write_bytes(self.zip)
        self.output = self.root / "output"
        self.cache = self.root / "tools" / "godot_cache"

    def script_env(self, keep="1"):
        return dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                    GITHUB_OUTPUT=str(self.output), GODOT_DOWNLOAD_PAUSE_SECONDS="0", GODOT_DOWNLOAD_ATTEMPTS="3",
                    GODOT_KEEP_DOWNLOAD=keep, EXPECTRAIL_TOOLS=str(self.root / "tools"))

    def run_script(self, keep="1"):
        return subprocess.run(["bash", str(self.root / "harness" / "get_godot.sh")], env=self.script_env(keep),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)

    def pause_extraction(self):
        # Hold an executable open for writing until the caller releases stdin. This models the
        # window in which the real unzip has created the executable and is still filling it.
        stub = self.bin / "unzip"
        stub.write_text(f'''#!/bin/bash
set -eu
(
    while [[ "$1" != -d ]]; do shift; done
    exec 3>"$2/{self.binary_name}"
    chmod +x "$2/{self.binary_name}"
    echo extracting >&2
    read -r -t 15 || exit 19
)
exec "{shutil.which('unzip')}" "$@"
''', encoding="utf-8")
        stub.chmod(0o755)

    def curls(self):
        path = self.state / "calls"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def source(self):
        return self.output.read_text(encoding="utf-8").strip().splitlines()[-1]

    def test_a_failed_download_is_tried_again(self):
        (self.state / "failures").write_text("2")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.curls(), 3)
        binary = Path(done.stdout.strip())
        self.assertEqual(binary.name, self.binary_name)
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertEqual(self.source(), "source=download")
        self.assertEqual([p.name for p in self.cache.iterdir()], [self.binary_name + ".zip"])   # kept for the cache

    def test_a_download_that_never_works_fails_and_says_so(self):
        (self.state / "failures").write_text("99")
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("in 3 attempts", done.stderr)
        self.assertEqual(self.curls(), 3)
        self.assertFalse((self.root / "tools" / "godot" / self.binary_name).exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_the_cached_download_is_used_with_no_network(self):
        self.cache.mkdir(parents=True)
        (self.cache / (self.binary_name + ".zip")).write_bytes(self.zip)
        (self.state / "failures").write_text("99")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.curls(), 0)
        self.assertEqual(self.source(), "source=cache")

    def test_a_cached_file_that_does_not_match_is_never_unpacked(self):
        self.cache.mkdir(parents=True)
        poisoned = io.BytesIO()
        with zipfile.ZipFile(poisoned, "w") as archive:
            archive.writestr(self.binary_name, "#!/bin/sh\necho not the engine\n")
        (self.cache / (self.binary_name + ".zip")).write_bytes(poisoned.getvalue())
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("does not match its SHA-512", done.stderr)
        self.assertEqual(self.curls(), 1)
        self.assertIn("stand-in engine", Path(done.stdout.strip()).read_text())
        self.assertEqual(self.source(), "source=download")

    def test_a_download_with_the_wrong_bytes_is_refused(self):
        (self.state / "served").write_bytes(b"not the zip")
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertFalse((self.root / "tools" / "godot" / self.binary_name).exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_outside_ci_the_download_is_not_kept(self):
        done = self.run_script(keep="")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertTrue(os.access(done.stdout.strip(), os.X_OK))

    def test_a_binary_already_there_touches_nothing(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = self.curls()
        done = self.run_script()
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.curls(), before)
        self.assertEqual(self.source(), "source=present")

    def test_concurrent_consumers_can_execute_the_returned_path_immediately(self):
        self.pause_extraction()
        script = self.root / "harness" / "get_godot.sh"
        binary = self.root / "tools" / "godot" / self.binary_name
        consumer = ['bash', '-c', 'echo starting >&2; bin=$(bash "$1") && echo "$bin" && exec "$bin" --version',
                    'consumer', str(script)]
        options = dict(env=self.script_env(keep=""), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
        with subprocess.Popen(consumer, **options) as first:
            self.assertEqual(first.stderr.readline(), "starting\n")
            self.assertEqual(first.stderr.readline(), "extracting\n")
            with subprocess.Popen(consumer, **options) as second:
                self.assertEqual(second.stderr.readline(), "starting\n")
                exposed_while_writing = binary.exists()
                for process in (first, second):
                    stdout, stderr = process.communicate(input="finish\n", timeout=20)
                    self.assertEqual(process.returncode, 0, stderr)
                    self.assertEqual(stdout.splitlines(), [str(binary), "stand-in engine"])
        self.assertFalse(exposed_while_writing, "unzip exposed a writable executable at the install path")
        self.assertEqual(self.curls(), 1)
        self.assertCountEqual(self.output.read_text().splitlines(), ["source=download", "source=present"])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_interrupted_extraction_can_be_retried(self):
        self.pause_extraction()
        done = self.run_script()
        self.assertEqual(done.returncode, 19, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertFalse((self.root / "tools" / "godot" / self.binary_name).exists())
        (self.bin / "unzip").unlink()
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.source(), "source=cache")
        self.assertEqual(subprocess.check_output([done.stdout.strip(), "--version"], text=True), "stand-in engine\n")


class MacGodotLookup(unittest.TestCase):
    def test_doctor_finds_the_engine_on_the_first_install(self):
        from expectrail import doctor
        from harness import run
        from tests.tool_requirements import executable

        for tool in ("bash", "shasum", "unzip"):
            executable(tool)
        with tempfile.TemporaryDirectory(prefix="mac engine ") as tmp:
            root = Path(tmp).resolve()
            executable_name = "Godot.app/Contents/MacOS/Godot"
            expected = root / "tools" / "godot_mac" / executable_name
            served = root / "served"
            version = run.GODOT_VERSION.replace("-", ".")
            with zipfile.ZipFile(served, "w") as archive:
                archive.writestr(executable_name, f'#!/bin/sh\n[ "$1" = --version ] && echo "{version}"\n')

            helper = root / "harness" / "macos" / "get_godot_mac.sh"
            helper.parent.mkdir(parents=True)
            script = (REPO / "harness" / "macos" / helper.name).read_text(encoding="utf-8")
            digest = hashlib.sha512(served.read_bytes()).hexdigest()
            script, pins = re.subn(r'^SHA512="[0-9a-f]{128}"$', f'SHA512="{digest}"', script, flags=re.M)
            self.assertEqual(pins, 1)
            helper.write_text(script, encoding="utf-8")
            helper.chmod(0o755)
            curl = root / "curl"
            curl.write_text(CURL, encoding="utf-8")
            curl.chmod(0o755)
            env = {"EXPECTRAIL_GODOT": "", "STATE": str(root), "PATH": str(root) + os.pathsep + os.environ["PATH"]}
            with (
                mock.patch.object(run, "REPO", root),
                mock.patch("sys.platform", "darwin"),
                mock.patch.dict(os.environ, env),
            ):
                self.assertFalse(expected.exists())
                check, found = doctor.godot()
                self.assertTrue(os.access(expected, os.X_OK))
                self.assertEqual(check.status, "ok", check.found)
                self.assertEqual(found, expected)
                self.assertEqual(run.find_godot(), expected)
            self.assertEqual((root / "calls").read_text().splitlines(), ["curl"])


class EveryWorkflowUsesTheActions(unittest.TestCase):
    def test_no_workflow_downloads_the_engine_or_the_browser_itself(self):
        godot = chromium = 0
        for path in WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
            self.assertNotIn("get_godot.sh", code, f"{path.name}: use ./.github/actions/get-godot")
            self.assertNotIn("playwright install", code, f"{path.name}: use ./.github/actions/get-chromium")
            godot += code.count("uses: ./.github/actions/get-godot")
            chromium += code.count("uses: ./.github/actions/get-chromium")
        self.assertGreaterEqual(godot, 25)
        self.assertGreaterEqual(chromium, 5)

    def test_the_repository_is_checked_out_and_playwright_installed_first(self):
        for path in WORKFLOWS:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for name, job in (doc.get("jobs") or {}).items():
                checked_out = pip_web = False
                for step in job.get("steps") or []:
                    uses, run = str(step.get("uses", "")), str(step.get("run", ""))
                    if uses.startswith("actions/checkout@") and "path" not in (step.get("with") or {}):
                        checked_out = True
                    if "requirements-web.txt" in run:
                        pip_web = True
                    if uses.startswith("./.github/actions/get-"):
                        self.assertTrue(checked_out, f"{path.name}#{name}: check out before {uses}")
                    if uses == "./.github/actions/get-chromium":
                        self.assertTrue(pip_web, f"{path.name}#{name}: install requirements-web.txt before get-chromium")

    def test_the_actions_pin_the_cache_action_and_key_on_the_pinned_version(self):
        for name, keyed_on in (("get-godot", "harness/get_godot.sh"), ("get-chromium", "requirements-web.txt")):
            doc = yaml.safe_load((ACTIONS / name / "action.yml").read_text(encoding="utf-8"))
            steps = doc["runs"]["steps"]
            caches = [s for s in steps if "uses" in s]
            self.assertEqual(len(caches), 2, name)
            for step in caches:
                self.assertRegex(step["uses"], r"^actions/cache/(restore|save)@[0-9a-f]{40}$")
                self.assertIn(f"hashFiles('{keyed_on}')", step["with"]["key"])
            self.assertIn("if", caches[1], f"{name}: save only after a fresh download")
            for step in steps:
                self.assertNotIn("${{", str(step.get("run", "")))
        godot = yaml.safe_load((ACTIONS / "get-godot" / "action.yml").read_text(encoding="utf-8"))
        self.assertEqual(godot["runs"]["steps"][1]["env"], {"GODOT_KEEP_DOWNLOAD": "1"})


if __name__ == "__main__":
    unittest.main()
