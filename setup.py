"""The one thing pyproject.toml cannot say: which modules of a package go in the wheel.

The verification command and app need selected top-level modules of `expectrail` (beside its `gate` and `orchestrator`
packages, which go in whole), five harness modules (the adapter registry among them: the verify path
takes its engine from it), and one from the agents lane (the reader of the engine's position log).
The fixer, the loop and everything that holds a model key stay out of the package: it verifies, it
does not repair. tests/test_package.py reads the built wheel and checks
that every module in it can import everything it asks for.
"""
from setuptools import setup
from setuptools.command.build_py import build_py

BUNDLED_MODULES = {
    # The top-level modules a verification imports. Left out: the capability ledger's tools (they read
    # docs/), the spec writer and the provider records (model-side), change evidence (the fix loop's).
    "expectrail": {"__init__", "app", "app_page", "cli", "contracts", "diagnostics", "doctor", "evaluator", "legacy", "resources", "route", "timing", "viewer"},
    "expectrail._bundle.harness": {"__init__", "adapters", "run", "sandbox", "tree"},
    "expectrail._bundle.agents": {"__init__", "observations"},
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
