"""The one thing pyproject.toml cannot say: which modules of a package go in the wheel.

A verification ships the local app, the gate, orchestrator, replay harness, visual observer and its model clients.
The fixer, loop and dotenv key loader stay out. A verification reads its vision key only from the
environment. tests/test_package.py checks the wheel's complete import chain.
"""
from setuptools import setup
from setuptools.command.build_py import build_py

BUNDLED_MODULES = {
    # The top-level modules a verification imports. Left out: the capability ledger's tools (they read
    # docs/), the spec writer (model-side) and change evidence (the fix loop's).
    "expectrail": {"__init__", "app", "app_page", "approval", "cli", "contracts", "coverage", "diagnostics", "doctor", "evaluator", "legacy", "observers", "providers", "resources", "route", "timing", "viewer"},
    "expectrail._bundle.harness": {"__init__", "adapters", "run", "sandbox", "tree"},
    "expectrail._bundle.agents": {"__init__", "anchor_rule", "observations", "sam_anchor", "sam_observations", "glimmer_client", "byo_vision", "engine_check"},
    # Data only: no module of these folders is packaged.
    "expectrail._bundle.contracts": set(),
    "expectrail._bundle.game": set(),
    "expectrail._bundle.bugs": set(),
}


class BuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        keep = BUNDLED_MODULES.get(package)
        return modules if keep is None else [m for m in modules if m[1] in keep]


setup(cmdclass={"build_py": BuildPy})
