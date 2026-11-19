"""Real engine/CLI fixture driver with a pixel sensor specific to the bundled blue robot.

Only tests import this. No production environment setting selects this observer.
It uses the existing gate and fixer fixture, never a second decision rule.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import zlib

from agents.sam_observations import png_size, sha256_bytes
from harness.unity import png_pixels


class RobotPixels:
    """Locate the robot's opaque blue paint in the captured frame, in frame pixels."""

    model = 'bundled-robot-palette-v1'
    provider = 'offline-repair-fixture'
    base = 'local-fixture'
    blue = bytes((59, 93, 201))

    def __init__(self, engine=None):
        self.engine = engine
        self.by_digest = {}
        self.lock = threading.Lock()

    def _locate(self, width, channels, pixels):
        # A lookahead finds overlapping matches, so a misaligned run of the same bytes cannot hide an aligned
        # pixel; only matches on a pixel boundary count.
        found = re.finditer(b'(?=' + re.escape(self.blue) + b')', pixels)
        return [divmod(match.start() // channels, width) for match in found if match.start() % channels == 0]

    def _capture(self, folder):
        # Decode a replay once. The project supplied to the decoder is an empty
        # temporary directory. Only the trusted fixture script and PNGs are inputs.
        script = Path(__file__).with_name('repair_decode_frames.gd').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([self.engine, '--headless', '--path', tmp, '--script', str(script),
                            '--', str(folder), tmp], check=True, capture_output=True, timeout=120)
            points = {}
            for png in folder.glob('*.png'):
                width, height = png_size(png)
                rgb = zlib.decompress((Path(tmp) / (png.name + '.rgb')).read_bytes())
                if len(rgb) != width * height * 3:
                    raise ValueError(f'incomplete decoded frame: {png.name}')
                points[sha256_bytes(png)] = self._locate(width, 3, rgb)
            return points

    def _points(self, png):
        if self.engine is None:  # Small unit fixtures can be read without Godot.
            width, _, channels, pixels = png_pixels.read(png)
            return self._locate(width, channels, pixels)
        digest = sha256_bytes(png)
        with self.lock:
            if digest not in self.by_digest:
                self.by_digest.update(self._capture(png.parent))
            return self.by_digest[digest]

    @staticmethod
    def _detection(points):
        if not points:
            return None
        ys, xs = zip(*points)
        return {'box': [min(xs), min(ys), max(xs) + 1, max(ys) + 1], 'score': 1.0}

    def segment(self, png, prompt):
        target = self._detection(self._points(png)) if prompt == 'blue robot' else None
        return [target] if target else []

    def segment_in(self, png, boxes):
        points = self._points(png)
        target = self._detection(points)
        return [target if any(x1 <= x < x2 and y1 <= y < y2 for y, x in points) else None
                for x1, y1, x2, y2 in boxes]


def bootstrap():
    from agents.sam_observations import Cache
    from expectrail.observers import FramesObserver
    from expectrail.orchestrator import engines
    visual = FramesObserver(client=RobotPixels(os.environ['EXPECTRAIL_GODOT']), cache=Cache(None), name='repair-pixels', every=1)
    engines.ENGINES = {'godot': engines.GodotGate(visual=visual)}
    def forbidden(*args, **kwargs): raise AssertionError('fixture attempted a model or network transport')
    from expectrail import providers
    from agents import sam_observations
    providers.chat_completion = forbidden
    sam_observations.MetaSamClient = forbidden
    import urllib.request
    urllib.request.urlopen = forbidden
    urllib.request.build_opener = forbidden


def exercise(folder, case, *, isolated):
    from expectrail import contracts
    from expectrail.orchestrator import sample
    from expectrail.gate import record
    root = Path(folder).resolve(); root.mkdir(parents=True)
    before = sample.checkout(root / 'before', bug=False)
    after = sample.checkout(root / 'after', bug=True)
    # Reuse #551's public hand-written fall-through route. The approved check
    # bytes and game source are unchanged; both versions have identical policy.
    route = json.loads((Path(__file__).resolve().parents[1] / 'contracts/examples/playtest-report-fall-through.json').read_text())['route']
    route['name'] = 'smoke'
    for checkout in (before, after):
        (checkout / sample.ROUTE).write_text(json.dumps(route))
    source = after / sample.GAME / 'player/player.tscn'; original = source.read_bytes()
    repo = Path(__file__).resolve().parents[1]
    patch = repo / 'agents/fixtures/fix-collision-mask.patch'
    if case == 'exhausted':
        patch = root / 'bad.patch'
        patch.write_text((repo / 'agents/fixtures/fix-collision-mask.patch').read_text().replace(
            '+collision_mask = 30', '+collision_mask = 12'))
    boot = root / 'bootstrap'; boot.mkdir()
    (boot / 'sitecustomize.py').write_text('from tests.repair_cli_fixture import bootstrap\nbootstrap()\n')
    env = {k:v for k,v in os.environ.items() if not k.startswith('EXPECTRAIL_') and k != 'MODEL_API_KEY'}
    env.update({k:v for k,v in os.environ.items() if k in ('EXPECTRAIL_GODOT','EXPECTRAIL_TOOLS')})
    env['EXPECTRAIL_SANDBOX'] = 'require' if isolated else 'off'
    env['PYTHONPATH'] = str(boot) + os.pathsep + str(repo)
    jobs = root / 'jobs'
    def run(args, name):
        with (root / (name+'.stdout')).open('w') as stdout, (root / (name+'.stderr')).open('w') as stderr:
            proc = subprocess.run([sys.executable, '-m', 'expectrail.cli', *args], env=env,
                                  stdout=stdout, stderr=stderr, timeout=600)
        return proc.returncode, (root / (name+'.stdout')).read_text()
    argv = ['verify', '--head', str(after), '--base', str(before), '--game', sample.GAME,
            '--routes', sample.ROUTE, '--specs', sample.SPECS, '--jobs-root', str(jobs),
            '--execution-class', 'isolated' if isolated else 'diagnostic', '--json']
    if case == 'auto': argv += ['--auto-fix', '--auto-fix-fixture', str(patch), '--auto-fix-attempts', '1']
    code, text = run(argv, 'verify')
    assert code == 1, (code, text, (root/'verify.stderr').read_text())
    parent = json.loads(text); assert parent['decision'] == 'reject'
    if case != 'auto':
        code, text = run(['repair', parent['id'], '--jobs-root', str(jobs), '--fixture', str(patch),
                          '--attempts', '2' if case == 'exhausted' else '1'], 'repair')
        assert code == (2 if case == 'exhausted' else 0), (code, text)
    paths = list((jobs/'jobs'/parent['id']).glob('repair-*/repair-run.json'))
    assert len(paths) == 1
    doc = contracts.load_strict(paths[0], 'repair-run')
    assert doc['fixer']['source'] == 'fixture' and not doc['fixer']['sandboxed']
    findings = []
    for attempt in doc['attempts']:
        child = record.read_record(jobs/'jobs'/attempt['job']/'output/findings.json')
        assert child['observers']['rule'] == 'both'
        assert child['observers']['visual']['provider'] == RobotPixels.provider
        assert child['isolation']['required'] == isolated
        if isolated: assert child['isolation']['sandboxed'] == child['isolation']['replays'] > 0
        findings.append(child)
    if case == 'exhausted':
        assert doc['result']['decision'] == 'needs-review' and doc['stop']['reason'] == 'attempts-exhausted'
        assert [a['decision'] for a in doc['attempts']] == ['reject','reject']
    else:
        assert doc['result']['decision'] == 'accept' and findings[-1]['repair']['demonstrated'] > 0
        assert doc['result']['job'] != parent['id']
    assert source.read_bytes() == original
    proof = {'case':case, 'realEngine':True, 'isolated':isolated,
        'observer':'bundled blue robot pixels', 'modelCalls':0,
        'parentDecision':parent['decision'], 'result':doc['result']['decision'],
        'stop':doc['stop']['reason'], 'attempts':[a['decision'] for a in doc['attempts']],
        'demonstrated':[f['repair']['demonstrated'] for f in findings],
        'sourceUnchanged':True, 'patchSha256':doc['attempts'][-1]['patchSha256']}
    (root/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    return proof
