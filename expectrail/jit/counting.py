"""Opt-in trusted assessment for generated checks (#271).

The candidate's job and legacy gate-summary cannot enable counting. A trusted
caller supplies expected identities/inputs and an existing receipt trust store.
Only a known issuer's fresh, bound signature carrying both producer capabilities
can establish rule 5. The source certificate need not clear the candidate: that
would be circular. The gate's decide alone decides the candidate.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from expectrail.contracts import digest_v1, validate, validate_v1
from expectrail.gate import record
from expectrail.jit import assess

FORMAT = 'expectrail.generated-counting/v1'


@dataclass(frozen=True)
class Trust:
    store: dict
    repository: str
    base: str
    head: str
    build: str
    policy: str
    inputs: dict

    def document(self):
        result = {key: copy.deepcopy(getattr(self,key)) for key in
                  ('repository','base','head','build','policy','inputs')}
        result['format'] = 'expectrail.generated-counting-context/v1'
        validate(result,'generated-counting-context.v1')
        return result

    @classmethod
    def load(cls, path, store):
        from expectrail.receipt import load_trust_store
        doc=record.read_json(Path(path),cap=65536,label='trusted counting context')
        validate(doc,'generated-counting-context.v1')
        return cls(load_trust_store(Path(store)),**{k:v for k,v in doc.items() if k!='format'})


def authenticated(run, certificate, trust):
    if not isinstance(trust, Trust) or not isinstance(certificate, dict):
        return False
    from expectrail.receipt import _validate_receipt, check_receipt
    try:
        _validate_receipt(certificate)
        checked = check_receipt(certificate,trust.store,expect_repo=trust.repository,
                                expect_head=trust.head,expect_build=trust.build,expect_policy=trust.policy)
        return (all(checked[k] for k in ('valid_signature','known_issuer','identity_ok','policy_ok','fresh'))
                and certificate['baseSha256'] == trust.base and run['inputs'] == trust.inputs
                and {'jit-trusted-proposal','jit-trusted-replay'} <= set(certificate['evidence']['capabilities'])
                and certificate['evidence']['artifacts'].get('jit-run-canonical') == digest_v1(run))
    except (ValueError, TypeError, KeyError):
        return False


def make(run, report, certificate=None, *, trust=None):
    validate_v1(run,'jit-run')
    for entry in run['proposed']:
        validate_v1(entry['spec'],'trace-spec')
    for key, field in [('proposed','spec'), ('validity','specId'), ('probes','id'), ('variants','id')]:
        identifiers=[item[field]['id'] if field=='spec' else item[field] for item in run[key]]
        if len(identifiers)!=len(set(identifiers)):
            raise ValueError('counting-evidence-mismatch: duplicate source identifiers')
    if certificate is not None:
        from expectrail.receipt import _validate_receipt
        _validate_receipt(certificate)
    if not isinstance(report,str) or hashlib.sha256(report.encode()).hexdigest()!=run['inputs']['reportSha256']:
        raise ValueError('counting-evidence-mismatch: bug report digest differs')
    # Trace rows, then one row per pixel check (#286), each recomputed from the source run. The two
    # share one name space: the receipt's coverage and the gate's words name a row by its specId.
    is_trusted=authenticated(run,certificate,trust)
    rows=assess.counting(run,report,trusted=is_trusted)+assess.pixel_counting(run,report,trusted=is_trusted)
    names=[row['specId'] for row in rows]
    if len(names)!=len(set(names)):
        raise ValueError('counting-evidence-mismatch: duplicate check identifiers across trace and pixel checks')
    result={'format':FORMAT,'sourceRun':copy.deepcopy(run),'bugReport':report,
            'sourceReceipt':copy.deepcopy(certificate),'assessment':{
                'runSha256':digest_v1(run),'receiptSha256':digest_v1(certificate) if certificate is not None else None,
                'rows':rows}}
    validate(result,'generated-counting.v1')
    return result


def read(source, *, trust=None):
    doc=record.read_json(Path(source),cap=8*1024*1024,label='generated counting evidence') if not isinstance(source,dict) else source
    validate(doc,'generated-counting.v1')
    rebuilt=make(doc['sourceRun'],doc['bugReport'],doc['sourceReceipt'],trust=trust)
    if doc!=rebuilt:
        raise ValueError('counting-evidence-mismatch: assessment or source changed, or trust is unavailable/stale')
    return record.VerifiedGenerated(rebuilt['assessment'],base=trust.base if trust else None,
                                    head=trust.build if trust else None)


def write(path, run, report, certificate=None, *, trust=None):
    doc=make(run,report,certificate,trust=trust)
    Path(path).write_text(json.dumps(doc,indent=2)+'\n')
    return read(doc,trust=trust)


def judge(gate, source, *, trust=None):
    """Extend an existing gate result, never a second gate/replay/decision rule.

    No workflow calls this by default. Deployment must load it in trusted code
    with independently pinned expectations and the existing issuer trust store.
    """
    record.check_record(gate)
    if trust is not None and (trust.build != gate['game']['headTree'] or trust.base != gate['game']['baseTree']):
        raise ValueError('counting-evidence-mismatch: expected game builds differ from gate evidence')
    proof=read(source,trust=trust)
    doc=copy.deepcopy(gate);doc['countingChecks']=proof.block
    doc['decision'],doc['reasons']=record.decide(doc['counts'],doc['heldOut'],doc.get('isolation'),doc.get('checkProblems',0),
        intent=record.intent_of(doc),repair=doc.get('repair'),anchor=doc.get('anchor'),
        required_routes_missing=record.missing_required_routes(doc['specs'],doc['routes']),
        observers=doc.get('observers'),generated=proof,
        undecided_after_failure=record.undecided_after_failure(doc['checks']))
    record.check_record(doc,generated=proof)
    return doc,proof


def receipt_artifacts(envelope):
    """Provenance digests for the existing signed receipt writer; no new signature rule."""
    validate(envelope,'generated-counting.v1')
    return {'jit-run-canonical':digest_v1(envelope['sourceRun']),
            'generated-counting-canonical':digest_v1(envelope)}


def receipt_document(template, gate, envelope, proof):
    """Feed the existing receipt signer with the final gate result and provenance.

    The issuer/identity/timestamps are the trusted caller's template. Signing and
    checking issuer trust remain the existing receipt module's work.
    """
    record.check_record(gate,generated=proof)
    if proof.block != envelope['assessment']:
        raise ValueError('counting-evidence-mismatch: receipt assessment differs')
    doc=copy.deepcopy(template);doc.pop('signature',None)
    doc['decision']=gate['decision']
    doc['evidence']['artifacts'].update(receipt_artifacts(envelope))
    doc['evidence']['artifacts']['findings-canonical']=digest_v1(gate)
    for row in proof.block['rows']:
        if not record.counting_row(row):continue
        name='generated:'+row['specId']
        if name not in doc['coverage']['required']:doc['coverage']['required'].append(name)
        if name not in doc['coverage']['exercised']:doc['coverage']['exercised'].append(name)
        doc['coverage']['results'][name]=row['outcome']
    return doc


def public_custom_route(folder, pid, sha):
    """A published custom probe's route, supplied in ``jit-routes`` beside its source record, or None.

    It is used only when its canonical digest is the one the record names for that probe."""
    from expectrail.jit import bench
    if sha is None or Path(pid).name != pid or bench.private_name(pid):
        return None
    path = Path(folder) / 'jit-routes' / ('jit-' + pid.removeprefix('jit-') + '.json')
    if path.resolve() != path.absolute() or not path.is_file():
        return None
    try:
        route = record.read_json(path, cap=1024*1024, label='public probe route')
        validate(route, 'route')
    except (OSError, ValueError):
        return None
    return route if digest_v1(route) == sha else None


DO_NOTHING_OUTCOMES = ('passes', 'fails', 'indeterminate', 'not-run')


def do_nothing_rows(path):
    """The per-check rows of ``tools/do_nothing_public.py`` (its ``rows.json``), keyed by (defect, check)."""
    doc = record.read_json(Path(path), cap=8*1024*1024, label='do-nothing control rows')
    rows = doc.get('rows') if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError('do-nothing rows: no rows list')
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('defect'), str) or not isinstance(row.get('check'), str):
            raise ValueError('do-nothing rows: a row has no defect or check')
        if row.get('outcome') not in DO_NOTHING_OUTCOMES:
            raise ValueError(f"do-nothing rows: {row['defect']} {row['check']}: unknown outcome {row.get('outcome')!r}")
        key = (row['defect'], row['check'])
        if key in out:
            raise ValueError(f'do-nothing rows: {key[0]} {key[1]} appears twice')
        out[key] = row
    return out


def do_nothing_tally(defect, run, rows):
    """How the do-nothing control changes one record's legacy keep and catches. Advisory.

    A row is used only when it names this record (``sourceRun``) and this exact check (``specSha256``);
    otherwise the check is "cannot tell" and is neither kept nor dropped. A check is dropped when it passed
    the control (the generator's rule, ``assess.validity``); fails, indeterminate and not-run are kept."""
    source = digest_v1(run)
    valid = {v['specId'] for v in run['validity'] if v.get('valid')}
    caught = {c['specId'] for c in run.get('catches', [])}
    tally = {'legacyKept': 0, 'dropped': 0, 'cannotTell': 0, 'kept': 0,
             'legacyCatches': 0, 'catchesDropped': 0, 'catchesCannotTell': 0, 'catchesKept': 0,
             'outcomes': dict.fromkeys(DO_NOTHING_OUTCOMES, 0),
             'keptBy': dict.fromkeys(DO_NOTHING_OUTCOMES[1:], 0), 'unbound': []}
    for entry in run['proposed']:
        spec = entry['spec']
        row = rows.get((defect, spec['id']))
        bound = (row is not None and row.get('sourceRun') == source and row.get('specSha256') == digest_v1(spec))
        if bound:
            tally['outcomes'][row['outcome']] += 1
        else:
            tally['unbound'].append(spec['id'])
        state = 'cannotTell' if not bound else 'dropped' if row['outcome'] == 'passes' else 'kept'
        if spec['id'] in valid:
            tally['legacyKept'] += 1
            tally[state] += 1
            if state == 'kept':
                tally['keptBy'][row['outcome']] += 1
        if spec['id'] in caught:
            tally['legacyCatches'] += 1
            tally['catches' + state[0].upper() + state[1:]] += 1
    return tally


class HarmlessControl:
    """Advisory paired replays of the public mutation bench's comment-only operator."""

    def __init__(self, work, root):
        from expectrail.discovery.route_compiler import compile_route
        from expectrail.jit.probes import jit_library
        from harness.run import tree_digest

        self.work = Path(work)
        self.game = root / 'game/platformer'
        if self.work.resolve().is_relative_to(self.game.resolve()):
            raise ValueError('harmless work must be outside the clean game')
        self.work.mkdir(parents=True, exist_ok=False)
        self.tree = tree_digest(self.game)
        self.patch = root / 'agents/fixtures/operators/comment-only.patch'
        self.patch_sha = hashlib.sha256(self.patch.read_bytes()).hexdigest()
        # Exactly the single comment that the mutation registration labels good on clean.
        if self.patch_sha != '48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65':
            raise ValueError('the registered comment-only operator has changed')
        actions = json.loads((root / 'discovery/platformer.profile.json').read_text())['actions']
        self.routes = {}
        for probe in jit_library(actions):
            route = compile_route(probe['program'], name=probe['id'],
                                  description=probe['description'], actions=actions)
            self.routes[digest_v1(route)] = route
        self.episodes = {}
        self.evidence = {}
        self.rows = []

    def probe(self, sha, route, ui_integers):
        from tempfile import TemporaryDirectory
        from harness.run import run
        from expectrail.trace.normalize import from_run_dir

        key = sha + ('-ui' if ui_integers else '')
        if key in self.episodes:
            return self.episodes[key]
        folder = self.work / key
        folder.mkdir()
        path = folder / 'route.json'
        path.write_text(json.dumps(route, indent=1) + '\n')
        arms, evidence = {}, {}
        engines = set()
        for arm, patches in [('clean', []), ('changed', [self.patch])]:
            episodes, runs = [], []
            for rep in range(assess.REPS):
                try:
                    with TemporaryDirectory(dir=folder) as tmp:
                        out = Path(tmp) / 'replay'
                        rec = run(path, out, game=self.game, patches=patches, capture_frames=False,
                                  ui_integers=ui_integers)
                        if (rec['route']['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest()
                                or rec['game']['tree'] != self.tree
                                or rec['game']['patchSha256'] != (self.patch_sha if patches else None)):
                            raise ValueError('replay route, tree or patch differs from control')
                        episode = from_run_dir(out, route, episode_id=f'{arm}-{key}-{rep}')
                        saved = folder / f'{arm}-{rep + 1}'
                        saved.mkdir()
                        for filename in ('replay.json', 'trace.json'):
                            shutil.copyfile(out / filename, saved / filename)
                        runs.append({'trace': rec['trace']['sha256'], 'replay': digest_v1(rec),
                                     'engine': rec['engine'], 'isolation': rec['isolation']})
                        engines.add(digest_v1(rec['engine']))
                        episodes.append(episode)
                except (OSError, ValueError, RuntimeError, SystemExit, subprocess.SubprocessError) as exc:
                    runs.append({'error': str(exc)[:300]})
                    break
            # Changing traces within an arm or an interrupted run cannot establish stability.
            stable = len(episodes) == assess.REPS and len({r['trace'] for r in runs}) == 1
            arms[arm] = episodes if stable else []
            evidence[arm] = runs
        if len(engines) != 1:
            arms = {'clean': [], 'changed': []}
        (folder / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        self.evidence[key] = evidence
        self.episodes[key] = arms
        return arms

    def measure(self, defect, run, selected, folder):
        from harness.run import needs_ui_integers
        from expectrail.jit import bench
        from expectrail.trace.evaluator import evaluate

        probes = {p['id']: p['routeSha256'] for p in run['probes']}
        start = len(self.rows)
        for entry in run['proposed']:
            spec = entry['spec']
            ids = entry['probeIds']
            ui = needs_ui_integers([spec])
            shas = [probes.get(pid) for pid in ids]
            row = {'defect': defect, 'check': spec['id'], 'specSha256': digest_v1(spec),
                   'sourceRun': digest_v1(run), 'probes': ids, 'routeSha256': shas, 'uiIntegers': ui,
                   'clean': [], 'changed': [], 'outcome': 'not-run', 'reason': ''}
            self.rows.append(row)
            if not selected:
                row['reason'] = 'outside selected defects'
                continue
            applies = entry['applies']
            if applies.get('kind') not in ('all', 'tag', 'probes', 'pair'):
                row['reason'] = 'unknown probe selection'
                continue
            if applies['kind'] == 'pair' and ids != [applies.get('left'), applies.get('right')]:
                row['reason'] = 'pair identities differ from recorded probe IDs'
                continue
            routes = []
            for pid, sha in zip(ids, shas):
                route = self.routes.get(sha) or public_custom_route(folder, pid, sha)
                if route is None:
                    row['reason'] = 'missing exact route ' + pid
                    break
                routes.append(route)
            if row['reason']:
                continue
            pairs = [self.probe(sha, route, ui) for sha, route in zip(shas, routes)]
            if not pairs or any(not pair[arm] for pair in pairs for arm in ('clean', 'changed')):
                row.update(outcome='indeterminate', reason='incomplete or unstable replay evidence')
                continue
            for arm in ('clean', 'changed'):
                for rep in range(assess.REPS):
                    episodes = [pair[arm][rep] for pair in pairs]
                    verdicts = ([evaluate(spec, *episodes)] if entry['applies']['kind'] == 'pair'
                                else [evaluate(spec, ep) for ep in episodes])
                    row[arm].append(assess.harmless_repetition(spec, verdicts))
            row['outcome'] = assess.harmless_outcome(row['clean'], row['changed'])
        for pixel in run.get('pixelChecks', []):
            row = {'defect': defect, 'check': pixel['check']['id'], 'specSha256': digest_v1(pixel['check']),
                   'sourceRun': digest_v1(run), 'clean': [], 'changed': [], 'outcome': 'not-run',
                   'reason': 'pixel observation unavailable in trace-only control'}
            self.rows.append(row)

        (self.work / f'checks-{defect}.json').write_text(json.dumps(self.rows[start:], indent=2) + '\n')

    def report(self, lines):
        totals = {name: sum(row['outcome'] == name for row in self.rows)
                  for name in ('pass', 'false-rejection', 'indeterminate', 'not-run')}
        report = {'tree': self.tree, 'patchSha256': self.patch_sha, 'probes': self.evidence,
                  'rows': self.rows, 'totals': totals}
        (self.work / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
        environments = sorted({(r['engine']['version'], r['isolation']['mode'],
                                (r['isolation'].get('sandbox') or {}).get('tool') or 'none')
                               for pair in self.evidence.values() for arm in pair.values()
                               for r in arm if 'engine' in r})
        environment = ', '.join(f'{version}, sandbox mode {mode}, tool {tool}'
                                for version, mode, tool in environments) or 'no completed replays'
        lines += ['## Harmless control on the clean platformer', '',
                  'The registered comment-only operator adds one comment in `player/player.gd`. '
                  'Each available trace check uses three fresh clean replays and three with the patch. '
                  'The results measure this source edit only. All rows are advisory.', '',
                  f'Recorded headless engine and isolation: {environment}.', '',
                  f'Clean source tree `{self.tree}`. Patch SHA-256 `{self.patch_sha}`.', '',
                  '| Public defect | Check | Clean repetitions | Changed repetitions | Outcome |',
                  '| --- | --- | --- | --- | --- |']
        for row in self.rows:
            arms = [', '.join(row[a]) or '—' for a in ('clean', 'changed')]
            reason = (' (' + row['reason'] + ')') if row['reason'] else ''
            lines.append(f"| {row['defect']} | `{row['check']}` | {arms[0]} | {arms[1]} | {row['outcome']}{reason} |")
        lines += ['', ', '.join(f'{n} {name}' for name, n in totals.items()) + '.', '']
        return totals


def public_bench(records, out, *, harmless_work=None, harmless_defects=(), do_nothing=None):
    """Offline classification of committed public records; no replay or model.

    ``do_nothing`` is the ``rows.json`` of ``tools/do_nothing_public.py`` (#675): with it, the page also
    says, per defect, how many legacy-kept checks and catches the do-nothing control would drop. Advisory:
    it never changes the counting classification."""
    from expectrail.jit import bench
    if bench.private_name(records) or bench.private_name(Path(records).resolve()):
        raise ValueError('public-only: held-out/fresh record roots refused')
    manifest=bench.public_cases()
    rows=[]
    legacy_valid = 0
    root=Path(__file__).resolve().parents[2]
    selected = set(harmless_defects)
    if selected - {d['id'] for d in manifest['defects']} or (selected and not harmless_work):
        raise ValueError('harmless defect selection requires public defect IDs and --harmless-work')
    control = HarmlessControl(harmless_work, root) if harmless_work else None
    controls = do_nothing_rows(do_nothing) if do_nothing else None
    tallies = []
    metamorphic = 0
    for defect in manifest['defects']:
        path=Path(records)/('repro-'+defect['id'])/'jit-run.json'
        if path.resolve() != path.absolute():
            raise ValueError('public record path cannot be a link')
        run=record.read_json(path,cap=8*1024*1024,label='public JIT record')
        report=(root/defect['report']).read_text()
        result=make(run,report)
        if control:
            control.measure(defect['id'], run, not selected or defect['id'] in selected, path.parent)
        legacy_valid += sum(bool(row['valid']) for row in run['validity'])
        metamorphic += len(run.get('metamorphic') or [])
        counted=sum(r['counting'] for r in result['assessment']['rows'])
        if controls is not None:
            tallies.append((defect['id'], do_nothing_tally(defect['id'], run, controls)))
        rows.append((defect['id'],len(result['assessment']['rows']),counted,digest_v1(run)))
    history_note = ('The counting assessment uses existing records. The separate harmless control replays '
                    'the clean game and its comment-only edit. No trusted source certificate/context is supplied.'
                    if control else 'Existing recorded model outputs only; no model call or replay. No trusted source certificate/context is supplied.')
    lines=['# Offline counting audit of the public reproduction bench (#271)','', history_note,
           'Every legacy record is advisory: candidate shown, no authenticated trusted producer/replayer, and no per-arm coverage provenance.',
           'This is not the rate of a new candidate-withheld, trusted generation run.','',
           '| Public defect | Checks assessed | Counting | Advisory | Canonical run SHA-256 |',
           '| --- | ---: | ---: | ---: | --- |']
    lines += [f'| {name} | {total} | {counted} | {total-counted} | `{sha}` |' for name,total,counted,sha in rows]
    total=sum(r[1] for r in rows);counted=sum(r[2] for r in rows)
    lines += ['',f'Total: {len(rows)} public defects; {total} checks assessed; {counted} counting; {total-counted} advisory.','']
    lines += [f'Of these, {legacy_valid} are recorded as valid by the legacy keep rule; '
              f'{total-legacy_valid} are dropped proposals retained only as advisory diagnostics. '
              + ('The counting classification used the frozen outcomes.' if control else 'No outcomes were replayed.'),'']
    control_totals = {}
    if controls is not None:
        known = {(d, entry['spec']['id']) for d, entry in _proposed(records, manifest)}
        extra = sorted(set(controls) - known)
        if extra:
            raise ValueError('do-nothing rows name checks the records do not have: '
                             + ', '.join(f'{d} {c}' for d, c in extra[:5]))
        control_totals['doNothing'] = do_nothing_report(tallies, lines)
    lines += ['## Metamorphic checks', '',
              f'Metamorphic rows in these records: {metamorphic}. They are advisory: a record keeps them apart from '
              '`proposed`, `validity` and `catches`, and this audit never assesses them for counting.', '']
    control_totals['metamorphicRows'] = metamorphic
    if control:
        control_totals['harmlessControl'] = control.report(lines)
    Path(out).write_text('\n'.join(lines))
    return {**control_totals, 'defects':len(rows),'checks':total,'counting':counted,'advisory':total-counted,
            'legacyKeptAdvisory':legacy_valid,'droppedProposals':total-legacy_valid}


def _proposed(records, manifest):
    for defect in manifest['defects']:
        run = record.read_json(Path(records) / ('repro-' + defect['id']) / 'jit-run.json',
                               cap=8*1024*1024, label='public JIT record')
        for entry in run['proposed']:
            yield defect['id'], entry


def do_nothing_report(tallies, lines):
    keys = ('legacyKept', 'dropped', 'cannotTell', 'kept', 'legacyCatches', 'catchesDropped',
            'catchesCannotTell', 'catchesKept')
    totals = {k: sum(t[k] for _, t in tallies) for k in keys}
    totals['outcomes'] = {o: sum(t['outcomes'][o] for _, t in tallies) for o in DO_NOTHING_OUTCOMES}
    totals['keptBy'] = {o: sum(t['keptBy'][o] for _, t in tallies) for o in DO_NOTHING_OUTCOMES[1:]}
    totals['defectsWithNoCatchKept'] = [d for d, t in tallies if t['legacyCatches'] and not t['catchesKept']
                                        and not t['catchesCannotTell']]
    lines += ['## Do-nothing control (#675)', '',
              'A check that still passes when the actor it is about does nothing states no obligation, and the '
              'generator now drops it. These columns apply that rule to the frozen records, from the control\'s '
              'own replays (`tools/do_nothing_public.py`). A row is used only when it names this record and this '
              'exact check by digest; otherwise the check is "cannot tell", neither kept nor dropped. '
              'Advisory: the counting classification above is unchanged.', '',
              '| Public defect | Legacy kept | Dropped by the control | Cannot tell | Kept | '
              'Legacy catches | Catches kept |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, t in tallies:
        lines.append(f"| {name} | {t['legacyKept']} | {t['dropped']} | {t['cannotTell']} | {t['kept']} | "
                     f"{t['legacyCatches']} | {t['catchesKept']} |")
    o = totals['outcomes']
    lines += ['', f"Total: {totals['legacyKept']} legacy kept; {totals['dropped']} dropped by the control; "
              f"{totals['cannotTell']} cannot tell; {totals['kept']} kept. Catches: {totals['legacyCatches']} "
              f"recorded, {totals['catchesDropped']} dropped, {totals['catchesCannotTell']} cannot tell, "
              f"{totals['catchesKept']} kept.", '',
              f"Control outcomes over all bound checks: {o['passes']} passes, {o['fails']} fails, "
              f"{o['indeterminate']} indeterminate, {o['not-run']} not run.", '',
              f"Of the {totals['kept']} kept, {totals['keptBy']['fails']} fail the control (the check is shown to "
              f"state an obligation), {totals['keptBy']['indeterminate']} are indeterminate and "
              f"{totals['keptBy']['not-run']} were not run on it: the control cannot drop those, and it does not "
              "show they state one.", '',
              'Public defects whose every recorded catch is dropped: '
              + (', '.join(f'`{d}`' for d in totals['defectsWithNoCatchKept']) or 'none') + '.', '']
    return totals


def pixel_bench(records, out):
    """The six rules on the pixel rows of committed public records (#271, #286); no replay or model.

    ``records`` holds one folder per record, named after its public defect (``<defect>-<what>``), each with
    a ``jit-run.json``. Folders whose record has no pixel checks are skipped. Untrusted: rule 5 never
    holds here, so nothing counts; the page says which rules each check meets and why it is advisory."""
    from expectrail.jit import bench
    if bench.private_name(records):
        raise ValueError('public-only: held-out/fresh record roots refused')
    root = Path(__file__).resolve().parents[2]
    defects = sorted(bench.public_cases()['defects'], key=lambda d: -len(d['id']))
    table, total, counted, seen = [], 0, 0, 0
    for folder in sorted(p for p in Path(records).iterdir() if p.is_dir()):
        run = record.read_json(folder / 'jit-run.json', cap=8 * 1024 * 1024, label='public JIT record')
        if not run.get('pixelChecks'):
            continue
        defect = next((d for d in defects if folder.name == d['id'] or folder.name.startswith(d['id'] + '-')), None)
        if defect is None:
            raise ValueError(f'{folder.name}: not named after a public defect')
        report = (root / defect['report']).read_text()
        if hashlib.sha256(report.encode()).hexdigest() != run['inputs']['reportSha256']:
            raise ValueError(f'counting-evidence-mismatch: {folder.name}: bug report digest differs')
        seen += 1
        for row in assess.pixel_counting(run, report):
            total += 1
            counted += row['counting']
            met = ', '.join(str(i + 1) for i, ok in enumerate(row['rules']) if ok) or 'none'
            why = '; '.join(r.split(': ', 1)[1] for r in row['reasons']) or '-'
            table.append(f"| {folder.name} | `{row['specId']}` | {row['predicate']['type']} on {row['predicate']['object']} "
                         f"| {met} | {'yes' if row['counting'] else 'no'} | {why} |")
    lines = ['# The six rules on the public pixel checks (#271, #286)', '',
             'Offline, from the committed records under `bench/jit/stand-in/`; no replay, observer or model.',
             'These checks were written by hand, not by a model, and no trusted certificate is supplied, so rule 5',
             'never holds and nothing counts. The page shows which rules each check meets from its own runs.',
             'Pixel rows reach the gate decision only as authenticated evidence (rule 5); this is not a rate.', '',
             'Made by `python3 -m expectrail.jit.counting pixel-bench --records bench/jit/stand-in --out <page>`.', '',
             '| Record | Check | Predicate | Rules met | Counting | Why advisory |',
             '| --- | --- | --- | --- | --- | --- |'] + table
    lines += ['', f'Total: {seen} records with pixel checks; {total} pixel checks; {counted} counting; '
              f'{total - counted} advisory.', '']
    Path(out).write_text('\n'.join(lines))
    return {'records': seen, 'checks': total, 'counting': counted, 'advisory': total - counted}


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    audit=sub.add_parser('public-bench');audit.add_argument('--records',type=Path,required=True);audit.add_argument('--out',type=Path,required=True)
    audit.add_argument('--harmless-work', type=Path, help='new folder for paired, advisory clean/comment-only replays')
    audit.add_argument('--harmless-defect', action='append', default=[], help='measure only this public defect (repeatable)')
    audit.add_argument('--do-nothing-rows', type=Path, help='rows.json from tools/do_nothing_public.py (#675)')
    pixel=sub.add_parser('pixel-bench');pixel.add_argument('--records',type=Path,required=True);pixel.add_argument('--out',type=Path,required=True)
    judge_cmd=sub.add_parser('judge');judge_cmd.add_argument('--gate',type=Path,required=True)
    judge_cmd.add_argument('--evidence',type=Path,required=True);judge_cmd.add_argument('--context',type=Path,required=True)
    judge_cmd.add_argument('--trust-store',type=Path,required=True);judge_cmd.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='public-bench':print(json.dumps(public_bench(args.records,args.out, harmless_work=args.harmless_work, harmless_defects=args.harmless_defect, do_nothing=args.do_nothing_rows)));return 0
    if args.command=='pixel-bench':print(json.dumps(pixel_bench(args.records,args.out)));return 0
    trust=Trust.load(args.context,args.trust_store)
    doc,proof=judge(record.read_record(args.gate),args.evidence,trust=trust)
    args.out.write_text(json.dumps(doc,indent=2)+'\n')
    record.read_record(args.out,generated=proof)
    print(doc['decision']);return 0 if doc['decision']=='accept' else 1 if doc['decision']=='reject' else 2


if __name__=='__main__':raise SystemExit(main())
