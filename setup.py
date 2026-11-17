"""The one thing pyproject.toml cannot say: which modules of a package go in the wheel.

A verification ships the local app, the gate, orchestrator, replay harness, visual observer and its model clients.
Repair includes its fixer and sandbox. The demo loop stays out. A verification reads its vision key only from the
environment. tests/test_package.py checks the wheel's complete import chain.
"""
from setuptools import setup
from setuptools.command.build_py import build_py

BUNDLED_MODULES = {
    # The top-level modules a verification imports. Left out: the capability ledger's tools (they read
    # docs/), the spec writer (model-side) and change evidence (the fix loop's).
    "expectrail": {
        "__init__",
        "anchored",
        "calibration",
        "app",
        "app_kinematic",
        "app_page",
        "approval",
        "attestation",
        "auto_fix",
        "cli",
        "contracts",
        "coverage",
        "diagnostics",
        "doctor",
        "evaluator",
        "fixer_budget",
        "godot_project",
        "legacy",
        "observers",
        "onboard",
        "onboarding",
        "project_config",
        "project_job",
        "providers",
        "receipt",
        "recorded",
        "renderer",
        "repair",
        "resources",
        "route",
        "spend",
        "timing",
        "viewer",
    },
    "expectrail._bundle.harness": {"__init__", "adapters", "run", "sandbox", "tree"},
    "expectrail._bundle.agents": {
        "__init__",
        "byo_fixer",
        "fixer",
        "fixer_meter",
        "fixer_guard_hook",
        "gateway",
        "gateway_bridge",
        "guard",
        "keys",
        "muse_gateway_addon",
        "patchutil",
        "sandbox",
        "anchor_rule",
        "observations",
        "sam_anchor",
        "sam_observations",
        "godot_roles",
        "glimmer_client",
        "byo_vision",
        "engine_check",
    },
    # Data only: no module of these folders is packaged.
    "expectrail._bundle.contracts": set(),
    "expectrail._bundle.game": set(),
    "expectrail._bundle.bugs": set(),
    "expectrail._bundle.outside": set(),
}


# Only staged wheel code is qualified. Repository entry points stay compatible.
PRIVATE = 'expectrail._bundle'
SAMPLE_RECORDINGS = ('clean', 'fall-through-bug', 'fall-through-repair')


def qualify_imports(source):
    """Qualify Python import statements, preserving their original local bindings.

    Use AST byte positions, not text replacement: data paths, prompts and documentation
    must remain byte-identical. No sys.path insertion or top-level module aliases.
    """
    import ast
    lines = source.encode('utf-8').splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    edits = []
    for node in ast.walk(ast.parse(source)):
        replacement = None
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.split('.')[0] in ('harness', 'agents'):
            node.module = PRIVATE + '.' + node.module
            replacement = ast.unparse(node)
        elif isinstance(node, ast.Import) and any(a.name.split('.')[0] in ('harness', 'agents') for a in node.names):
            parts = []
            for alias in node.names:
                top = alias.name.split('.')[0]
                if top in ('harness', 'agents'):
                    if alias.asname:
                        parts.append('import ' + PRIVATE + '.' + alias.name + ' as ' + alias.asname)
                    else:
                        parts.append('from ' + PRIVATE + ' import ' + top)
                        if '.' in alias.name:
                            parts.append('import ' + PRIVATE + '.' + alias.name)
                else:
                    parts.append(ast.unparse(ast.Import(names=[alias])))
            # Semicolons preserve indentation and imports inside a one-line suite.
            replacement = '; '.join(parts)
        if replacement is not None:
            edits.append((starts[node.lineno - 1] + node.col_offset,
                          starts[node.end_lineno - 1] + node.end_col_offset, replacement.encode()))
    raw = source.encode('utf-8')
    for start, end, replacement in sorted(edits, reverse=True):
        raw = raw[:start] + replacement + raw[end:]
    ast.parse(raw.decode('utf-8'))
    return raw.decode('utf-8')


def without_path_bootstrap(source):
    """Remove only the installed-copy sys.path bootstrap, refusing unexpected source drift."""
    import ast
    lines = source.splitlines(keepends=True)
    candidates = [node for node in ast.parse(source).body if isinstance(node, ast.If)
                  and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                          and ast.unparse(call.func) == '_sys.path.insert' for call in ast.walk(node))]
    if len(candidates) != 1:
        raise ValueError('expected exactly one legacy installed-copy path bootstrap')
    node = candidates[0]
    return ''.join(lines[:node.lineno - 1] + ['# Private imports are qualified by the wheel builder; sys.path is unchanged.\n']
                   + lines[node.end_lineno:])


class BuildPy(build_py):
    def get_source_files(self):
        # sdist asks build_py for its inputs too. These are required wheel data,
        # even though their public originals live outside the Python packages.
        recordings = [f'docs/run-it/vision/{name}.json' for name in SAMPLE_RECORDINGS]
        return super().get_source_files() + recordings

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        keep = BUNDLED_MODULES.get(package)
        return modules if keep is None else [m for m in modules if m[1] in keep]

    def run(self):
        from pathlib import Path
        import shutil
        super().run()
        package = Path(self.build_lib) / 'expectrail'
        for path in package.rglob('*.py'):
            source = path.read_text(encoding='utf-8')
            if path == package / '__init__.py':
                source = without_path_bootstrap((Path(self.get_package_dir('expectrail')) / '__init__.py').read_text(encoding='utf-8'))
            path.write_text(qualify_imports(source), encoding='utf-8')
        (package / '_bundle' / '__init__.py').write_text('"""Private verification modules and read-only sample assets."""\n', encoding='utf-8')
        destination = package / '_bundle' / 'sample-vision'
        destination.mkdir(exist_ok=True)
        for name in SAMPLE_RECORDINGS:
            shutil.copyfile(Path('docs/run-it/vision') / (name + '.json'), destination / (name + '.json'))


setup(cmdclass={"build_py": BuildPy})
