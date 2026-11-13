"""The package (#249): what the wheel holds, and that a copy installed from it works outside the
checkout with the standard library alone.

The wheel is built once for the module, from a copy of the working tree, with the setuptools that is
installed (no download). Where setuptools is missing the tests skip; CI's `package` job sets
EXPECTRAIL_PACKAGE_TESTS=required, so a skip there is a failure. The real engine is not started
here: the `package` job runs the real sample from the installed copy.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import unittest
import unittest.mock
import zipfile
from pathlib import Path

from harness import tree

REPO = Path(__file__).resolve().parent.parent
BUNDLE = "expectrail/_bundle/"
# What the build reads. Anything else in the tree cannot reach the wheel.
SOURCES = ("pyproject.toml", "setup.py", "README.md", "LICENSE", "NOTICE", "expectrail", "harness", "agents",
           "contracts", "game", "bugs/physics-fall-through")
BUILT: dict = {}


def setUpModule():
    spec = importlib.util.find_spec("setuptools")
    if spec is None:
        return
    tmp = Path(tempfile.mkdtemp(prefix="expectrail-package-"))
    BUILT["tmp"] = tmp
    src = tmp / "src"
    for name in SOURCES:
        if (REPO / name).is_dir():
            shutil.copytree(REPO / name, src / name, ignore=shutil.ignore_patterns("__pycache__", ".godot", "fixtures"))
        else:
            (src / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / name, src / name)
    done = subprocess.run([sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation",
                           "--no-index", "-w", str(tmp / "dist"), "-q"], capture_output=True, text=True)
    BUILT["log"] = done.stdout + done.stderr
    wheels = sorted((tmp / "dist").glob("expectrail-*.whl")) if done.returncode == 0 else []
    if wheels:
        BUILT["wheel"] = wheels[0]


def tearDownModule():
    if "tmp" in BUILT:
        shutil.rmtree(BUILT["tmp"], ignore_errors=True)


def module_lists() -> dict[str, set[str]]:
    """setup.py's lists of which modules of a package go in the wheel, read without running it."""
    module = ast.parse((REPO / "setup.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "BUNDLED_MODULES":
            return {package.rsplit(".", 1)[-1]: set(names) for package, names in ast.literal_eval(node.value).items()}
    raise AssertionError("setup.py has no BUNDLED_MODULES")


# Parts of the `expectrail` package that are not in the wheel, each with why. A new subpackage or
# module must be put in the wheel or added here: the test below fails until one is chosen.
NOT_PACKAGED = {
    "expectrail.discovery": "advisory discovery and the fresh-bug bench: reads the repository's bugs and bench files",
    "expectrail.jit": "the check generator and its benches: needs agents.mutate_game and the repository's bugs",
    "expectrail.repro": "the reproduction bench and scorer: reads the repository's bench files",
    "expectrail.trace": "trace signals for discovery and the check generator; no verification imports it",
    "expectrail.capabilities": "the capability ledger's tool: reads docs/",
    "expectrail.capability_runs": "the capability ledger's tool: reads CI runs",
    "expectrail.change_evidence": "evidence of a fix loop's change; the wheel does not repair",
    "expectrail.observers": "the visual observer: it asks a vision model, and the wheel holds nothing that holds a model key",
    "expectrail.providers": "model provider records; no verification uses a model",
    "expectrail.spec_writer": "drafts specs with a model; no verification uses a model",
}
# Imports a packaged module makes only on a path a verification never takes.
NOT_ON_A_VERIFICATION = {
    "agents.sam_observations": "only when the SAM observer is asked for; the gate reads the engine's position log "
                               "and never asks (expectrail.gate.verify.observations)",
    # expectrail.gate.anchor asks the vision model about the player's place on both sides (#327); it is
    # imported only inside run_gate when a visual observer was given, as agents.sam_observations is.
    "agents.anchor_rule": "only when a visual observer is given to the gate (expectrail.gate.anchor, #327)",
    "agents.sam_anchor": "only when a visual observer is given to the gate (expectrail.gate.anchor, #327)",
    # harness.adapters is in the wheel: the verify path takes its engine from the registry. The
    # registry also lists the web and Unity adapters, whose runners are imported only inside their
    # own `run`. Neither adapter has a verify path, so no verification can reach those imports.
    "harness.web": "only inside the web adapter's run; the adapter has no verify path (harness.adapters.verifying)",
    "harness.web.run": "the same import: the web adapter's runner",
    "harness.unity": "only inside the Unity adapter's run; the adapter has no verify path",
    "harness.unity.run": "the same import: the Unity adapter's runner",
}


class Case(unittest.TestCase):
    def setUp(self):
        if "wheel" not in BUILT:
            why = "the wheel did not build: " + BUILT["log"][-600:] if "log" in BUILT else "setuptools is not installed"
            if os.environ.get("EXPECTRAIL_PACKAGE_TESTS") == "required" or "log" in BUILT:
                self.fail(why)   # a build that fails is a failure everywhere; only a missing tool skips
            self.skipTest(why)
        self.wheel = zipfile.ZipFile(BUILT["wheel"])
        self.addCleanup(self.wheel.close)
        self.names = self.wheel.namelist()


class ContentsTest(Case):
    def test_one_top_level_name_is_installed(self):
        tops = {name.split("/")[0] for name in self.names}
        self.assertEqual({t for t in tops if not t.endswith(".dist-info")}, {"expectrail"})
        entry = [n for n in self.names if n.endswith(".dist-info/entry_points.txt")]
        self.assertEqual(len(entry), 1)
        self.assertIn("expectrail = expectrail.cli:main", self.wheel.read(entry[0]).decode())

    def test_every_part_of_expectrail_is_in_the_wheel_or_left_out_for_a_stated_reason(self):
        lists = module_lists()
        shipped = {n[:-3].replace("/", ".").removesuffix(".__init__") for n in self.names
                   if n.startswith("expectrail/") and not n.startswith(BUNDLE) and n.endswith(".py")}
        on_disk = set()
        for path in (REPO / "expectrail").rglob("*.py"):
            name = ".".join(path.relative_to(REPO).with_suffix("").parts).removesuffix(".__init__")
            on_disk.add(name)
        left_out = {name for name in on_disk - shipped
                    if not any(name == out or name.startswith(out + ".") for out in NOT_PACKAGED)}
        self.assertEqual(left_out, set(), "put these in the wheel (pyproject.toml, setup.py) or in NOT_PACKAGED with why")
        self.assertEqual({out for out in NOT_PACKAGED if out in shipped}, set(), "listed as left out, and in the wheel")
        self.assertEqual({n.split(".")[1] for n in shipped if n.count(".") == 1 and n not in
                          ("expectrail.gate", "expectrail.orchestrator")} | {"__init__"}, lists["expectrail"])

    def test_only_the_listed_harness_and_agents_modules_are_in_it(self):
        lists = module_lists()
        for folder in ("harness", "agents"):
            packed = {Path(n).stem for n in self.names if n.startswith(f"{BUNDLE}{folder}/") and n.endswith(".py")}
            self.assertEqual(packed, lists[folder], folder)
        for folder in ("contracts", "game", "bugs"):
            self.assertEqual([n for n in self.names if n.startswith(f"{BUNDLE}{folder}/") and n.endswith(".py")], [])
        # Nothing of the fix loop, and nothing that reads a model key.
        text = "\n".join(self.names)
        for word in ("fixer", "loop", "keys", "muse", "triage", "gateway"):
            self.assertNotIn(f"agents/{word}", text)

    def test_every_module_in_the_wheel_can_import_what_it_asks_for(self):
        # Read from the wheel itself: each `import` of expectrail, harness or agents in a packaged
        # module, including the ones inside functions, names a module the wheel holds.
        def where(module: str) -> list[str]:
            parts = module.split(".")
            base = "/".join(parts) if parts[0] == "expectrail" else BUNDLE + "/".join(parts)
            return [f"{base}.py", f"{base}/__init__.py"]

        def in_repo(module: str) -> bool:
            path = REPO.joinpath(*module.split("."))
            return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()

        asked: dict[str, str] = {}
        for name in (n for n in self.names if n.endswith(".py")):
            for node in ast.walk(ast.parse(self.wheel.read(name).decode())):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    modules = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names
                                                if in_repo(f"{node.module}.{alias.name}")]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                for module in modules:
                    if module.split(".")[0] in ("expectrail", "harness", "agents"):
                        asked.setdefault(module, name)
        self.assertGreater(len(asked), 10)
        missing = {module: by for module, by in asked.items()
                   if not any(place in self.names for place in where(module)) and module not in NOT_ON_A_VERIFICATION}
        self.assertEqual(missing, {}, "imported by a packaged module and not in the wheel")
        self.assertEqual([m for m in NOT_ON_A_VERIFICATION if m not in asked], [], "no longer imported: drop the exception")

    def test_the_data_a_verification_reads_is_in_it(self):
        for schema in (REPO / "contracts").glob("*.json"):
            self.assertIn(f"{BUNDLE}contracts/{schema.name}", self.names)
        for name in ("harness/get_godot.sh", "harness/godot/expectrail_harness.gd", "harness/godot/expectrail_recorder.gd",
                     "harness/routes/smoke.json", "agents/specs/player-stays-above-ground.json",
                     "bugs/physics-fall-through/v1.patch"):
            self.assertIn(BUNDLE + name, self.names)
            self.assertEqual(self.wheel.read(BUNDLE + name), (REPO / name).read_bytes(), name)
        # No held-out or fresh material, no other bug, no fixture, no import cache.
        for name in self.names:
            self.assertFalse(any(word in name for word in ("fresh", "heldout", "fixtures", "/.godot/", "__pycache__")), name)
            self.assertFalse(name.startswith(("expectrail/discovery", "expectrail/jit", "expectrail/repro")), name)
        self.assertEqual([n for n in self.names if n.startswith(BUNDLE + "bugs/")], [BUNDLE + "bugs/physics-fall-through/v1.patch"])

    def test_the_bundled_game_is_the_repositorys_game_file_for_file(self):
        out = BUILT["tmp"] / "game-check"
        shutil.rmtree(out, ignore_errors=True)
        self.wheel.extractall(out, [n for n in self.names if n.startswith(BUNDLE + "game/")])
        packed = out / BUNDLE / "game" / "platformer"
        self.assertEqual(tree.digest(packed, skip=tree.GODOT_SKIP),
                         tree.digest(REPO / "game" / "platformer", skip=tree.GODOT_SKIP))


class InstalledTest(Case):
    """The wheel unpacked into a new virtual environment that has no other package, used from a
    folder outside the checkout with the environment cleared. (Unpacking is what an install does
    with a pure wheel, less the `expectrail` script; the `package` job installs with pip.)"""

    @classmethod
    def setUpClass(cls):
        cls.venv = None
        if "wheel" not in BUILT:
            return
        cls.venv = BUILT["tmp"] / "venv"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(cls.venv)], check=True, capture_output=True)
        cls.python = cls.venv / "bin" / "python"
        site = subprocess.run([str(cls.python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                              check=True, capture_output=True, text=True).stdout.strip()
        with zipfile.ZipFile(BUILT["wheel"]) as wheel:
            wheel.extractall(site)
        cls.site = Path(site)
        cls.elsewhere = BUILT["tmp"] / "elsewhere"
        cls.elsewhere.mkdir()

    def run_installed(self, *args: str, code: str | None = None) -> subprocess.CompletedProcess:
        command = [str(self.python), "-c", code] if code else [str(self.python), "-m", "expectrail.cli", *args]
        return subprocess.run(command, cwd=self.elsewhere, capture_output=True, text=True, timeout=120,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(self.elsewhere / "home")})

    def test_it_knows_it_is_installed_and_finds_its_files_inside_itself(self):
        done = self.run_installed("--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("installed package", done.stdout)
        self.assertIn(str(self.site / "expectrail" / "_bundle"), done.stdout)
        self.assertNotIn(str(REPO), done.stdout)

    def test_the_harness_it_runs_is_its_own_and_it_writes_outside_the_package(self):
        done = self.run_installed(code=(
            "import json, sys, importlib.util as u\n"
            "import expectrail, harness.run as hr\n"
            "from expectrail import resources\n"
            "from agents.observations import from_trace_synthetic\n"
            "import expectrail.orchestrator.cli, expectrail.gate.verify\n"
            "print(json.dumps({'harness': hr.__file__, 'tools': str(hr.tools_dir()), 'cache': str(hr.get_cache_dir()),\n"
            "                  'game': (hr.REPO / 'game' / 'platformer' / 'project.godot').is_file(),\n"
            "                  'schema': (resources.ROOT / 'contracts' / 'findings.schema.json').is_file(),\n"
            "                  'jsonschema': u.find_spec('jsonschema') is not None,\n"
            "                  'outside': sorted(m for m in sys.modules if m.split('.')[0] in ('harness', 'agents')\n"
            "                                    and '_bundle' not in (getattr(sys.modules[m], '__file__', '') or ''))}))\n"))
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertTrue(found["harness"].startswith(str(self.site / "expectrail" / "_bundle" / "harness")), found)
        self.assertEqual(found["outside"], [])
        self.assertTrue(found["game"] and found["schema"], found)
        self.assertFalse(found["jsonschema"])   # the standard library was enough to import all of that
        home = str(self.elsewhere / "home")
        self.assertEqual(found["tools"], f"{home}/.cache/expectrail")
        self.assertTrue(found["cache"].startswith(f"{home}/.cache/expectrail/"), found)

    def test_a_verification_runs_as_a_job_from_the_installed_copy(self):
        # A real job with a real worker process, on a checkout that has no game: the answer is
        # needs-review with the reason, exit 2. No engine is needed to get that far, and every
        # module and schema on the way came from the installed copy.
        checkout = self.elsewhere / "checkout"
        (checkout / "specs").mkdir(parents=True, exist_ok=True)
        (checkout / "routes").mkdir(exist_ok=True)
        done = self.run_installed("--jobs-root", str(self.elsewhere / "jobs"), "verify", "--head", str(checkout),
                                  "--game", "game", "--routes", "routes/*.json", "--specs", "specs", "--json")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        status = json.loads(done.stdout)
        self.assertEqual((status["phase"], status["decision"], [d["code"] for d in status["diagnostics"]]),
                         ("completed", "needs-review", ["INPUT_INVALID"]))
        self.assertIn("no Godot project", status["diagnostics"][0]["detail"])

    def test_a_command_that_is_not_built_says_so_and_gives_no_verdict(self):
        # `doctor` was the example here until it was built (#333).
        done = self.run_installed("trust-check")
        self.assertEqual(done.returncode, 5, done.stdout + done.stderr)
        self.assertIn("not built yet (#255)", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_doctor_runs_from_the_installed_copy_and_fetches_nothing_when_told_not_to(self):
        # The installed copy carries doctor, its schema and the harness modules it asks. With
        # --no-fetch and an empty home there is no engine, so it is missing, with the fix: exit 3.
        done = self.run_installed("doctor", "--no-fetch", "--json")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        doc = json.loads(done.stdout)
        found = {c["id"]: c for c in doc["checks"]}
        self.assertEqual(list(found), ["python", "godot", "display", "opengl", "disk", "sandbox", "patch", "curl", "unzip",
                                       "vision-key"])
        self.assertEqual((doc["ok"], found["python"]["status"], found["godot"]["status"], found["opengl"]["status"]),
                         (False, "ok", "missing", "skipped"))
        self.assertIn("--no-fetch was given", found["godot"]["found"])
        self.assertFalse((self.elsewhere / "home" / ".cache" / "expectrail" / "godot").exists())
        # The installed copy reads its own record with its own schema.
        check = self.run_installed(code=(
            "import json, sys\nfrom expectrail import doctor\n"
            f"print(json.dumps([doctor.problems(json.loads({done.stdout!r})), str(doctor.SCHEMA)]))\n"))
        self.assertEqual(check.returncode, 0, check.stderr)
        problems, schema = json.loads(check.stdout)
        self.assertEqual(problems, [])
        self.assertIn("_bundle", schema)

    def test_a_usage_error_from_the_installed_command_exits_5(self):
        done = self.run_installed("verify", "--head", ".")
        self.assertEqual((done.returncode, done.stdout), (5, ""), done.stderr)
        self.assertIn("the following arguments are required", done.stderr)


class CommandTest(unittest.TestCase):
    """The `expectrail` command in a clone: a front for the orchestrator's command line."""

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "expectrail.cli", *args], cwd=REPO, capture_output=True, text=True, timeout=60)

    def test_version_says_which_copy_this_is(self):
        done = self.run_cli("--version")
        self.assertEqual(done.returncode, 0)
        self.assertIn(f"(clone; files at {REPO})", done.stdout)

    def test_the_orchestrators_commands_keep_their_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_cli("--jobs-root", tmp, "status", "0" * 32)
            self.assertEqual(done.returncode, 5, done.stdout + done.stderr)   # no such job: could not be carried out
            done = self.run_cli("verify", "--help")
            self.assertEqual(done.returncode, 0)
            self.assertIn("usage: expectrail verify", done.stdout)

    def test_no_command_and_an_unknown_one_exit_5_and_never_0_or_1(self):
        for args in ((), ("frobnicate",), ("_work", "x"), ("--jobs-root",)):
            done = self.run_cli(*args)
            self.assertEqual(done.returncode, 5, f"{args}: {done.stdout}{done.stderr}")
        self.assertEqual(self.run_cli("--help").returncode, 0)

    def test_a_clone_has_no_bundle_and_one_rule_says_where_the_files_are(self):
        from expectrail import resources
        from expectrail.gate import record

        # `_bundle` exists only inside a wheel. In the repository it would go on the module path of
        # everything that imports expectrail, the trusted comment job included.
        self.assertFalse((REPO / "expectrail" / "_bundle").exists())
        self.assertEqual((resources.INSTALLED, resources.ROOT), (False, REPO))
        # The trusted record module works the place out itself (it may import nothing of ours): the same answer.
        self.assertEqual(record.SCHEMA_PATH, resources.ROOT / "contracts" / "findings.schema.json")
        self.assertTrue(record.SCHEMA_PATH.is_file())

    def test_where_tools_are_kept(self):
        from harness import run as hr

        with unittest.mock.patch.dict(os.environ, {"EXPECTRAIL_TOOLS": "/srv/tools"}):
            self.assertEqual(hr.tools_dir(), Path("/srv/tools"))
            self.assertEqual(hr.get_cache_dir(), Path("/srv/tools/godot_cache/.godot"))
        env = {k: v for k, v in os.environ.items() if k not in ("EXPECTRAIL_TOOLS", "EXPECTRAIL_GODOT_CACHE")}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(hr.tools_dir(), REPO / "tools")   # a clone keeps them beside itself, as before


if __name__ == "__main__":
    unittest.main()
