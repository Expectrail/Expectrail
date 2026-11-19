"""The deterministic assessor: which generated checks are valid, which catch, and how strongly.

Validity/catch are pure functions of replay outcomes. Counting additionally uses
a conservative binding between predicate signals and words in the untrusted
report, plus separately authenticated provenance. Model verdicts never count.

- **Valid**: the check passed on every run of the clean reference (``REPS`` of ``REPS``: no failure,
  no gap, no error, and actually exercised), and it killed at least one near-miss variant, meaning it
  failed on every run of that variant. A check that never fails on anything near the candidate tells
  us nothing about the candidate.
- **Catch**: a valid check that failed on every run of the candidate. Mixed results are ``flaky``,
  never a catch.
- **Strong** catch: the check also fails on every run of the base build (the build the bug report
  describes), so it fails where the report says the game is wrong and still fails after the change;
  or its claim is one a person approved. **Weak**: every other catch.

Legacy outcomes are advisory. The opt-in six-rule assessment can supply the shared
gate decision with authenticated counting evidence (issue #271).
"""
from __future__ import annotations

from expectrail.coverage import all_of

REPS = 3
OUTCOMES = ("pass", "fail", "not_exercised", "insufficient_observation", "execution_error")


def combine(results: list[str]) -> str:
    """One run's outcome for a check over every probe or pair it applies to."""
    if not results:
        return "not_exercised"
    for res in ("execution_error", "fail", "insufficient_observation", "pass"):
        if res in results:
            return res
    return "not_exercised"


def validity(reference: list[str], variants: dict[str, list[str]], reps: int = REPS) -> dict:
    """{valid, killed, reasons} for one check."""
    reasons = []
    bad = sorted({r for r in reference if r != "pass"})
    if bad:
        reasons.append("did not pass on the reference: " + ", ".join(bad))
    elif len(reference) < reps:
        reasons.append(f"ran {len(reference)} of {reps} times on the reference")
    killed = sorted(v for v, runs in variants.items() if all_of(runs, "fail", reps))
    if not reasons and not killed:
        reasons.append("killed no near-miss variant")
    return {"valid": not reasons, "killed": killed, "reasons": reasons}


def catch(valid: bool, candidate: list[str], reps: int = REPS) -> str:
    """catch | no-catch | flaky | not-evaluated."""
    if not valid:
        return "not-evaluated"
    if len(candidate) < reps:
        return "not-evaluated"
    if all_of(candidate, "fail", reps):
        return "catch"
    if "fail" in candidate[:reps]:
        return "flaky"
    return "no-catch"


def strength(base: list[str] | None, claim_id: str, approved_claims: frozenset[str] = frozenset(),
             reps: int = REPS) -> str:
    if claim_id in approved_claims:
        return "strong"
    if base is not None and all_of(base, "fail", reps):
        return "strong"
    return "weak"

# Conservative predicate-to-behaviour bindings. Model claim/statement text alone
# cannot make an unrelated predicate relevant. Unknown predicates stay advisory.
BEHAVIOURS = {
    'air_jumps': ('jump', 'jumps', 'jumping', 'air'),
    'max_rise_px': ('jump', 'jumps', 'jumping', 'height'),
    'facing_flips': ('facing', 'flip', 'flips', 'direction'),
    'facing_mismatch_fraction': ('facing', 'backwards', 'direction'),
    'projectile_count': ('shoot', 'shooting', 'fire', 'cooldown', 'bullets'),
    'min_projectile_interval_ticks': ('shoot', 'shooting', 'fire', 'cooldown', 'bullets'),
    'max_enemy_drop_px': ('enemy', 'patrol', 'ledge'),
    'min_enemy_extent_px': ('enemy', 'patrol', 'ledge'),
    'coins_collected': ('coin', 'coins', 'counter'),
}


DIFF_BEHAVIOURS = {
    'air_jumps': 'player.jump', 'max_rise_px': 'player.jump',
    'projectile_count': 'weapon.cooldown', 'min_projectile_interval_ticks': 'weapon.cooldown',
    'facing_flips': 'player.facing', 'facing_mismatch_fraction': 'player.facing',
    'max_enemy_drop_px': 'enemy.patrol', 'min_enemy_extent_px': 'enemy.patrol',
}


def relevant(operation, report, diff_claims=()):
    """Lexical, audited signal binding; no inference from a generated statement.

    False negatives: synonyms outside this small vocabulary, unbound operations,
    cross-domain predicates and screen-only checks remain advisory. Matching is
    evidence of a named behaviour, not proof that the predicate expresses intent.
    """
    import re
    signal = operation.get('signal') if operation.get('type') == 'relation' else {
        'max_episode_rise': 'max_rise_px'}.get(operation.get('type'))
    words = set(re.findall(r'[a-z]+', report.lower()))
    return bool(words.intersection(BEHAVIOURS.get(signal, ()))
                or DIFF_BEHAVIOURS.get(signal) in set(diff_claims))


# Pixel checks (#286): a closed object role and a closed predicate type, both from the check's schema,
# never its statement. Relevance needs the report to name the object AND the drawn behaviour.
PIXEL_OBJECTS = {
    'player': ('robot', 'player', 'character'),
    'enemy': ('enemy', 'enemies'),
    'bullet': ('bullet', 'bullets'),
    'coin': ('coin', 'coins'),
    'coins-counter': ('counter', 'count'),
}
PIXEL_PREDICATES = {
    'visible': ('see', 'visible', 'invisible', 'disappear', 'disappears', 'behind', 'hidden', 'missing'),
    'faces-motion': ('face', 'faces', 'facing', 'backwards'),
    'inside-region': ('screen',),
    'never-crosses': ('through', 'cross', 'crosses'),
}


def pixel_relevant(check, report):
    """Lexical binding for a pixel check: the report names its object and its predicate's behaviour.

    False negatives: synonyms outside these small vocabularies, ``reaches`` and the ground (unbound),
    and every diff-map claim (a pixel row is not bound to the diff map yet) stay advisory.
    """
    import re
    words = set(re.findall(r'[a-z]+', report.lower()))
    obj = PIXEL_OBJECTS.get(check.get('object'), ())
    pred = PIXEL_PREDICATES.get((check.get('predicate') or {}).get('type'), ())
    return bool(words.intersection(obj)) and bool(words.intersection(pred))


def pixel_counting(run, report, *, trusted=False):
    """The six rules of #271 recomputed for each row of ``pixelChecks``, from the rows' runs.

    Reported only: ``counting.make`` does not call this, so no pixel row reaches ``decide``.
    Rule 2: no near miss is replayed for a pixel check, so the base build is the only discriminator, and
    it counts only when the candidate passes 3 of 3 (as for trace checks). Rule 4: a pixel run is
    ``pass`` or ``fail`` only when every planned frame in its window was judged with no gap
    (expectrail/jit/pixel.py), so every run on all three builds must be one of those, under one observer
    setting, with a stable candidate. ``trusted`` is the caller's, as in ``counting``.
    """
    from expectrail.contracts import validate_v1
    from expectrail.gate.record import counting_row
    rows_in = run.get('pixelChecks') or []
    ids = []
    for row in rows_in:
        validate_v1(row['check'], 'pixel-check')
        ids.append(row['check']['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('counting-evidence-mismatch: duplicate pixel check identifiers')
    probes = {p['id']: p['routeSha256'] for p in run.get('probes', [])}
    provenance = run.get('provenance') or {}
    inputs = run.get('inputs') or {}
    reps = run.get('settings', {}).get('reps')
    triple = lambda rs, value: len(rs) == REPS and all(r == value for r in rs)
    judged = lambda rs: len(rs) == REPS and all(r in ('pass', 'fail') for r in rs)
    out = []
    for row in rows_in:
        check = row['check']
        clean, bug, candidate = list(row['clean']), list(row['bug']), list(row['candidate'])
        rule1 = (run.get('status') == 'complete' and run.get('settings', {}).get('candidate') == 'withheld'
                 and reps == REPS and triple(bug, 'fail') and triple(clean, 'pass'))
        kills = ['base'] if triple(bug, 'fail') and triple(candidate, 'pass') else []
        stable = triple(candidate, 'pass') or triple(candidate, 'fail')
        rule4 = (row.get('setting') is not None and judged(clean) and judged(bug) and stable)
        rule6 = (bool(provenance.get('generatorVersion')) and bool(provenance.get('modelVersion'))
                 and bool(inputs.get('model')) and bool(inputs.get('promptSha256'))
                 and check['probe'] in probes and row.get('setting') is not None)
        rules = [bool(rule1), bool(kills), pixel_relevant(check, report), bool(rule4), trusted is True, bool(rule6)]
        descriptions = ['base-only reproduction/clean 3-of-3 missing',
                        'no independent near miss killed (the candidate does not pass 3 of 3)',
                        'drawn object and predicate not both named in the report',
                        'a run not judged, no single observer setting, or an unstable candidate',
                        'trusted producer/replayer and input binding not authenticated',
                        'provenance incomplete']
        result = {'kind': 'pixel', 'specId': check['id'], 'requirementSource': 'bug-report',
                  'predicate': {'object': check['object'], **check['predicate']},
                  'observer': check['observer'], 'setting': row.get('setting'),
                  'probeIds': [check['probe']], 'routeSha256': [probes[check['probe']]] if check['probe'] in probes else [],
                  'reference': clean, 'base': bug, 'candidate': candidate, 'killed': kills, 'rules': rules,
                  'counting': False,
                  'outcome': 'pass' if triple(candidate, 'pass') else 'fail' if triple(candidate, 'fail') else 'unknown',
                  'reasons': [f'rule-{i+1}: {why}' for i, (met, why) in enumerate(zip(rules, descriptions)) if not met],
                  'model': inputs.get('model'), 'modelVersion': provenance.get('modelVersion'),
                  'generatorVersion': provenance.get('generatorVersion')}
        result['counting'] = bool(counting_row(result))
        out.append(result)
    return out


def counting(run, report, *, trusted=False):
    """Recompute all six rules, then use the gate's single counting guard.

    trusted is supplied only by counting.py after signature, identity, policy,
    freshness and artifact binding; it is never read from a record/model field.
    """
    from expectrail.gate.record import counting_row
    proposed = {p['spec']['id']: p for p in run['proposed']}
    probes = {p['id']: p['routeSha256'] for p in run['probes']}
    variants = {v['id']: v for v in run['variants']}
    provenance = run.get('provenance', {})
    rows = []
    for validity in run['validity']:
        sid = validity['specId']; entry = proposed.get(sid)
        if entry is None:
            continue
        base = validity.get('base', [])
        clean = validity['reference']; candidate = validity['candidate']
        exercise = validity.get('exercised', {})
        triple = lambda rs, value: len(rs) == REPS and all(r == value for r in rs)
        kills = []
        for vid in validity['killed']:
            meta = variants.get(vid)
            if not meta or sid in meta.get('sameAsCandidateFor', []):
                continue
            # Base-only reproduction is also a discriminator when the candidate
            # passes: differing check outcomes prove these builds differ. When
            # both fail it proves no independent near miss, so do not count it.
            if meta['kind'] == 'base' and not triple(candidate, 'pass'):
                continue
            if triple(validity.get('variantResults', {}).get(vid, []), 'fail'):
                kills.append(vid)
        rule1 = (run['status'] == 'complete' and run['settings'].get('candidate') == 'withheld'
                 and triple(base, 'fail') and triple(clean, 'pass') and run['settings']['reps'] == REPS)
        coverage = all(triple(exercise.get(arm, []), True) for arm in ('reference', 'base', 'candidate'))
        coverage = coverage and any(triple(exercise.get(vid, []), True) for vid in kills)
        stable = triple(candidate, 'pass') or triple(candidate, 'fail')
        inputs = run['inputs']
        provenance_ok = (bool(provenance.get('generatorVersion')) and bool(provenance.get('modelVersion'))
                         and bool(inputs.get('model')) and bool(inputs.get('promptSha256'))
                         and all(pid in probes for pid in entry['probeIds']) and bool(entry['probeIds']))
        rules = [bool(rule1), bool(kills), relevant(entry['spec']['operation'], report,
                                                  provenance.get('assessmentDiffClaims', [])),
                 bool(coverage and stable), bool(trusted), bool(provenance_ok)]
        descriptions = ['base-only reproduction/clean 3-of-3 missing', 'no independent near miss killed',
                        'predicate not bound to a behaviour named in the report', 'coverage or stability missing',
                        'trusted producer/replayer and input binding not authenticated', 'provenance incomplete']
        row = {'specId': sid, 'requirementSource': 'bug-report', 'predicate': entry['spec']['operation'],
               'probeIds': entry['probeIds'], 'routeSha256': [probes[p] for p in entry['probeIds'] if p in probes],
               'reference': clean, 'base': base, 'candidate': candidate, 'killed': kills, 'rules': rules,
               'counting': False, 'outcome': 'pass' if triple(candidate,'pass') else 'fail' if triple(candidate,'fail') else 'unknown',
               'reasons': [f'rule-{i+1}: {reason}' for i, (met,reason) in enumerate(zip(rules,descriptions)) if not met],
               'model': inputs.get('model'), 'modelVersion': provenance.get('modelVersion'),
               'generatorVersion': provenance.get('generatorVersion')}
        row['counting'] = bool(counting_row(row))
        rows.append(row)
    return rows
