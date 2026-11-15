"""Generate the release dossier from an explicit allowlist of public evidence, offline.

python -m tools.dossier [--check] [--commit FULL_SHA] [--out docs/release/index.html]

No discovery crawl, GitHub request, engine, model, private manifest or blind-set file.
The API cache is a verbatim selection of public issue comments, not a score record.
Markdown readers deliberately fail on changed/ambiguous formats instead of guessing.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GH = 'https://github.com/Expectrail/Expectrail'
LEDGER = 'docs/capabilities.json'
PUBLIC = 'bench/jit/public/README.md'
DEFECTS = 'bench/jit/public/defects.json'
GATE = 'docs/release-gate.md'
OUTSIDE = 'docs/outside-projects.md'
SAMPLES = 'docs/run-it/samples.json'
SAM = 'docs/sam.md'
COMMENTS = 'docs/release/sources/outside-comments.json'
INPUTS = (LEDGER, PUBLIC, DEFECTS, GATE, OUTSIDE, SAMPLES, SAM, COMMENTS)
DECISIONS = {'accept', 'reject', 'needs-review'}


class EvidenceError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise EvidenceError(message)


def one(pattern, text, label, flags=0):
    found = list(re.finditer(pattern, text, flags))
    require(len(found) == 1, f'{label}: expected one matching published record, found {len(found)}')
    return found[0]


def esc(value):
    return html.escape(str(value), quote=True)


def cite(value, url):
    require(url.startswith(('https://github.com/', 'https://docs.python.org/', 'sources/')), 'unsupported citation URL')
    return f'<a href="{esc(url)}">{esc(value)}</a>'


def issue(number, label=None):
    return cite(label or f'#{number}', f'{GH}/issues/{number}')


@dataclass
class Source:
    path: str
    text: str
    commit: str

    def ref(self, needle=None):
        if self.path == COMMENTS:
            return 'sources/outside-comments.json'
        line = 1
        if needle is not None:
            require(needle in self.text, f'{self.path}: source excerpt missing: {needle!r}')
            line += self.text[:self.text.index(needle)].count('\n')
        return f'{GH}/blob/{self.commit}/{self.path}#L{line}'

    def json(self):
        return json.loads(self.text, parse_float=Decimal)


def sources(root, commit):
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'source commit must be a full lowercase Git SHA')
    result = {}
    for name in INPUTS:
        path = root
        for part in Path(name).parts:
            path = path / part
            require(not path.is_symlink(), f'{name}: evidence links are refused')
        require(path.is_file(), f'{name}: recorded evidence is missing')
        require(path.stat().st_size <= 2_000_000, f'{name}: evidence file is too large')
        result[name] = Source(name, path.read_text(encoding='utf-8'), commit)
    return result


def tables(text):
    """Published Markdown tables, with their nearest heading; never follow their links."""
    heading, rows = '', []
    for line in text.splitlines() + ['']:
        if line.startswith('#'):
            heading = line.lstrip('# ').strip()
        if line.startswith('|'):
            cells = [c.strip().replace('**', '').strip('`') for c in line.strip('|').split('|')]
            if not all(re.fullmatch(r'[: -]+', c) for c in cells):
                rows.append(cells)
        elif rows:
            yield heading, rows
            rows = []


def table(headers, rows, label):
    return ('<div class="scroll" tabindex="0" aria-label="' + esc(label) + '"><table><thead><tr>' +
            ''.join('<th scope="col">' + h + '</th>' for h in headers) + '</tr></thead><tbody>' +
            ''.join('<tr>' + ''.join('<td>' + str(c) + '</td>' for c in row) + '</tr>' for row in rows) +
            '</tbody></table></div>')


def ratio(n, d, ref):
    require(0 <= n <= d and d > 0, 'invalid result denominator')
    return cite(f'{n} / {d}', ref)


def verdict_stats(rows):
    require(rows and all(r['actual'] in DECISIONS for r in rows), 'no complete verdict sample')
    require(all(r['truth'] in {'good', 'bad'} for r in rows), 'unknown truth label')
    bad = [r for r in rows if r['truth'] == 'bad']
    good = [r for r in rows if r['truth'] == 'good']
    return {'false_accept': sum(r['actual'] == 'accept' for r in bad), 'bad': len(bad),
            'false_reject': sum(r['actual'] == 'reject' for r in good), 'good': len(good),
            'review': sum(r['actual'] == 'needs-review' for r in rows), 'total': len(rows)}


def verdict_summary(rows, ref):
    s = verdict_stats(rows)
    def count(n, d):
        return ratio(n, d, ref) if d else 'not measured (no eligible cases)'
    text = table(['False accepts / bad candidates', 'False rejects / benign candidates', 'Needs-review / all candidates'], [[
        count(s['false_accept'], s['bad']), count(s['false_reject'], s['good']), count(s['review'], s['total'])]], 'Separate verdict outcomes')
    if s['bad'] and not s['false_accept']:
        text += ('<p>Zero false accepts in this small sample: ' + count(0, s['bad']) +
                 ' bad candidates, among ' + cite(s['total'], ref) +
                 ' candidates overall. This is not a general false-accept rate.</p>')
    return text


def ledger_row(ledger, rid):
    rows = [r for r in ledger['rows'] if r['id'] == rid]
    require(len(rows) == 1, 'missing or duplicate ledger mode: ' + rid)
    return rows[0]


def blind_section(src, ledger):
    gate = ledger_row(ledger, 'ci-gate')
    generated = ledger_row(ledger, 'generated-checks')
    a = one(r'blind set 3,.*?accepted all (\d+) candidates, so it caught (\d+) of (\d+) wrong fixes; it also rejected none of the (\d+) correct fixes or (\d+) intentional changes',
            '\n'.join(e['shows'] for e in gate['evidence']), 'published blind gate counts')
    total, caught, wrong, good, intentional = map(int, a.groups())
    require(caught == 0 and wrong + good + intentional <= total, 'blind gate aggregate contradicts accepted-all report')
    ref = next(e['ref'] for e in gate['evidence'] if a.group(0) in e['shows'])
    b = one(r'blind set 3,.*?(\d+) of (\d+) wrong fixes caught against (\d+) of (\d+) with the approved checks alone; no false catch on (\d+) correct fixes and (\d+) intentional changes; \$(\d+\.\d+) for (\d+) candidates',
            '\n'.join(e['shows'] for e in generated['evidence']), 'published advisory counts')
    hit, eligible, baseline, baseline_n, correct, changes = map(int, b.groups()[:6])
    require((eligible, baseline, baseline_n, correct, changes, int(b[8])) == (wrong, caught, wrong, good, intentional, total), 'blind published aggregates disagree')
    require(0 <= hit <= eligible, 'invalid blind advisory count')
    text = '<h2 id="blind">' + issue(248, 'Blind set 3: published counts only') + '</h2>'
    text += '<p>No blind-set file, per-defect row or private manifest is read. The following is a historical result from ' + cite('the published run', ref) + ', not an evaluation of current main.</p>'
    text += table(['Arm / cohort', 'False accepts', 'False rejects', 'Needs-review'], [[
        'Approved gate; primary labelled cases for error rates', ratio(wrong-caught, wrong, ref), ratio(0, good+intentional, ref), ratio(0, total, ref)]], 'Blind aggregate verdicts')
    text += '<p>The gate accepted all ' + cite(total, ref) + ' candidates. Error denominators above use only the published primary wrong-fix and benign cohorts; they are not a reconstructed label breakdown for every candidate.</p>'
    text += '<p>Generated checks detected ' + ratio(hit, eligible, ref) + ' primary wrong fixes and missed ' + ratio(eligible-hit, eligible, ref) + '; false catches on benign candidates: ' + ratio(0, correct+changes, ref) + '. These checks were advisory. Their detections are not additional gate rejects or fewer actual false accepts. Needs-review for the advisory arm: not measured in these aggregates.</p>'
    text += '<p>Assertion-family and defect-type breakdowns: not measured in the public aggregate used here; no private breakdown is reconstructed. ' + cite('Published ledger statements', src.ref('"id": "generated-checks"')) + '.</p>'
    return text, (Decimal(b[7]), ref)


def reproduction(src, meta):
    marker = '## The baseline:'
    require(src.text.count(marker) == 1, 'public reproduction baseline heading changed')
    section = src.text.split(marker, 1)[1].split('\n## ', 1)[0]
    run = one(r'https://github.com/Expectrail/Expectrail/actions/runs/\d+', section, 'public reproduction run')[0]
    quoted = one(r'^\{"defects":.*\}$', section, 'quoted scorer totals', re.M)[0]
    totals = json.loads(quoted, parse_float=Decimal)
    data = [rows for _, rows in tables(section) if rows[0] == ['Defect', 'Library probes see', 'Proposed', 'Kept', 'Catches', 'Outcome', 'Spend']]
    require(len(data) == 1, 'public reproduction result table missing or ambiguous')
    defs = meta.json()['defects']; families = {d['id']: d['family'] for d in defs}
    rows = data[0][1:]
    require(len(rows) == totals['defects'] and {r[0] for r in rows} == set(families), 'public defect denominator/table/manifest disagree')
    require(len({r[0] for r in rows}) == len(rows), 'duplicate public defect')
    for row in rows:
        proposed, kept, catches = map(int, row[2:5])
        require(0 <= catches <= kept <= proposed, 'invalid public per-defect check counts')
        require((row[5] == 'reproduced') == (catches > 0), 'reproduction outcome contradicts its catches')
    counts = Counter(r[5] for r in rows)
    require(set(counts) <= {'reproduced', 'not reproduced'}, 'unknown reproduction outcome')
    require(counts['reproduced'] == totals['reproduced'] and counts['not reproduced'] == totals['notReproduced'] and totals['noResult'] == 0, 'public result counts disagree')
    spends = [Decimal(r[6].removeprefix('$')) for r in rows]
    require(sum(spends) == totals['spendUsd'] and max(spends) == totals['maxSpendUsd'] and sum(int(r[3]) for r in rows) == totals['keptChecks'], 'public spend/check totals disagree')
    group = defaultdict(list)
    for r in rows:
        group[families[r[0]]].append(r)
    ref = src.ref(quoted)
    out = '<h2 id="reproduction">Public reproduction bench</h2><p>Reproduced: ' + ratio(totals['reproduced'], totals['defects'], ref) + '; no result: ' + ratio(totals['noResult'], totals['defects'], ref) + '. Trace-visible subset: ' + ratio(totals['reproducedTraceVisible'], totals['traceVisible'], ref) + '. ' + cite('Recorded run', run) + ' · ' + issue(285) + ' · ' + cite('Publication', GH+'/pull/396') + '.</p>'
    out += '<p>This measures reproduction, not fix verification. Not-reproduced is not needs-review. False accepts, false rejects and verification needs-review: not measured by this scorer. Kept checks passed the clean-build repetitions by definition; this selection rule is not an independent false-reject measurement. The score artifact is not committed; these are the published log totals and per-defect table, cross-checked against each other.</p>'
    out += table(['Defect family', 'Reproduced / attempted', 'Not reproduced / attempted'], [[cite(family, meta.ref('"family": "'+family+'"')), ratio(sum(r[5]=='reproduced' for r in rs),len(rs),ref), ratio(sum(r[5]!='reproduced' for r in rs),len(rs),ref)] for family,rs in sorted(group.items())], 'Public defect families')
    out += table(['Public defect', 'Family', 'Reproduction', 'Recorded model spend'], [[cite(r[0],src.ref('| `'+r[0]+'` | '+' | '.join(r[1:])+' |')), cite(families[r[0]],meta.ref('"id": "'+r[0]+'"')), esc(r[5]), cite(r[6],run)] for r in rows], 'Public reproduction cases')
    out += '<p>Assertion-family breakdown: not measured in the published reproduction totals. Family labels above come from ' + cite('the public defect manifest',meta.ref()) + ', not inferred private categories.</p>'
    return out, (totals['spendUsd'], totals['maxSpendUsd'], totals['defects'], ref, run)


def release_gate(src):
    groups = [(heading, rows[1:]) for heading,rows in tables(src.text) if rows[0] == ['Control','Status','Why']]
    require(groups, 'release control tables missing')
    rows = [r for _,group in groups for r in group]
    require(all(len(r)==3 for r in rows), 'malformed release control row')
    count = Counter(r[1] for r in rows)
    require(set(count) <= {'held','open','FAILED','not run'}, 'unknown release control status')
    summary=one(r'- Rows: (\d+)\. Held (\d+), open (\d+), failed (\d+), not run (\d+)\.',src.text,'release summary')
    require(tuple(map(int,summary.groups())) == (len(rows),count['held'],count['open'],count['FAILED'],count['not run']), 'release summary disagrees with rows')
    commit=one(r'- Commit: `([0-9a-f]{40})`',src.text,'release source commit')[1]
    where=one(r'^- Run: (.+)$',src.text,'release source run',re.M)[1]
    out='<h2 id="gate">Release gate suite</h2><p>'+issue(258)+' · '+cite(where,src.ref('- Run:'))+' · recorded commit '+cite(commit,GH+'/commit/'+commit)+'. This is the committed result, not a rerun against the dossier’s current source tree. Later fixes do not silently turn its open rows into held rows.</p>'
    out+=table(['Held / all controls','Open / all controls','Failed / all controls','Not run / all controls'], [[ratio(count[s],len(rows),src.ref('- Rows:')) for s in ('held','open','FAILED','not run')]],'Release control coverage')
    out+=table(['Control group','Held / group','Open / group','Failed / group','Not run / group'], [[esc(name)]+[ratio(sum(r[1]==s for r in rs),len(rs),src.ref('## '+name)) for s in ('held','open','FAILED','not run')] for name,rs in groups], 'Release groups')
    out+='<p>False accepts, false rejects and needs-review per candidate: not measured as a verdict matrix in this summary. Held means the named tests passed, with positive controls; an open or expected-failure probe is not a defended control. No false-accept rate is inferred from a green test count.</p>'
    out+=table(['Control','Recorded status','Recorded reason'], [[cite(r[0],src.ref('| '+r[0]+' |')),esc(r[1]),cite(r[2],src.ref('| '+r[0]+' |'))] for r in rows], 'Every release control')
    return out


def outside(src, doc):
    comments=src.json()
    require(isinstance(comments,list) and len(comments)==2, 'expected the two captured outside-trial comments')
    out='<h2 id="outside">Outside-project trial</h2>'
    for c in comments:
        require(re.fullmatch(GH+r'/issues/263#issuecomment-\d+',c['url']), 'outside comment source is not the public issue')
        run=one(r'https://github.com/Expectrail/Expectrail/actions/runs/\d+',c['body'],'outside run URL')[0]
        ts=[r for _,r in tables(c['body']) if r[0][:2]==['kinematic-character','Verdict']]
        require(len(ts)==1,'outside verdict table missing')
        cases=[]
        for cells in ts[0][1:]:
            variant=cells[0].split(' (')[0]
            actual=one(r'^(accept|reject|needs-review)\b',cells[1], 'outside decision')[1]
            require(variant in {'as pinned','broken','harmless'},'unknown outside variant')
            cases.append({'name':variant,'truth':'bad' if variant=='broken' else 'good','actual':actual})
        require({r['name'] for r in cases}=={'as pinned','broken','harmless'} and len(cases)==len({r['name'] for r in cases}), 'outside cohort incomplete')
        vision='First vision run on an outside project' in c['body']
        require(vision or 'no model spend' in c['body'], 'outside observation mode not recorded')
        out+='<h3>'+('Attempted vision run: still unverified' if vision else 'Without vision')+'</h3><p>'+cite('Run',run)+' · '+cite('Published result',c['url'])+' · '+cite('Captured API text',src.ref())+'.</p>'
        out+=table(['kinematic-character variant','Observed verdict'], [[esc(r['name']),cite(r['actual'],run)] for r in cases], 'Outside verdicts')
        out+=verdict_summary(cases,c['url'])
        if vision:
            found=one(r'found the player in (\d+) of (\d+) frames',c['body'],'outside visual coverage')
            out+='<p>Player found on the clean run: '+ratio(int(found[1]),int(found[2]),c['url'])+'. The provider answered but usable visual coverage was missing. This attempted run is not a successfully verified outside project; '+issue(330)+' tracks adapting the observer.</p>'
        else:
            out+='<p>The engine rejected the broken collision case. Clean and harmless needed review without vision; neither is counted as a false reject. These are seeded cases on a public demo, not a studio-wide accuracy estimate.</p>'
    out+='<p>Assertion family: the public above-ground check; defect type: seeded collision failure. Other assertion families and defect types: not measured in this cohort. Setup and historical outcomes: '+cite('outside-project notes',doc.ref())+'.</p>'
    # Keep this run separate from the older no-vision and unsuccessful vision cohorts above.
    heading = '## First outside game verified with vision'
    require(doc.text.count(heading) == 1, 'outside vision report missing or ambiguous')
    report = doc.text.split(heading, 1)[1].split('\n## ', 1)[0]
    run = one(GH + r'/actions/runs/\d+', report, 'verified outside run')[0]
    cost = one(r'(\$\d+\.\d{2}) at list price', report, 'verified outside cost')[1]
    results = [rows for _, rows in tables(report) if rows[0] == ['Change', 'Verdict', 'Engine', 'Visual observer']]
    require(len(results) == 1, 'verified outside verdict table missing or ambiguous')
    rows = results[0][1:]
    require(all(len(r) == 4 and r[1] in DECISIONS for r in rows), 'invalid outside vision verdict row')
    variants = [r[0].split(' (', 1)[0] for r in rows]
    require(sorted(variants) == ['broken', 'harmless', 'invisible', 'none'], 'verified outside cohort incomplete')
    out += '<section id="outside-vision"><h3>First outside game verified with vision</h3>'
    out += table(['kinematic-character variant', 'Observed verdict', 'Engine', 'Visual observer'],
                 [[esc(change), cite(verdict, run), cite(engine, run), cite(vision, run)]
                  for change, verdict, engine, vision in rows], 'Outside vision verdicts')
    out += ('<p>The full run cost ' + cite(cost, run) + ' at list price. For the hidden sprite, vision '
            'measured the background. ' + cite('Read the outside-project report', doc.ref(heading)) + '.</p></section>')
    return out


def runit(ledger, manifest, src):
    ev=ledger_row(ledger, 'run-it')['evidence']
    cases=[]; rendered=[]
    for sample in manifest.json()['samples']:
        if sample.get('repairRecorded') is False:
            # A sample the page does not publish yet (#433's recorded fix): shown, never counted.
            rendered.append([cite(sample['id'],manifest.ref('"id": "'+sample['id']+'"')),cite(sample['expected'],manifest.ref('"id": "'+sample['id']+'"')),'not recorded yet','not measured'])
            continue
        matches=[]
        for e in ev:
            if e['kind']!='run' or 'vision questions answered from the recording' not in e['shows']:
                continue
            m=re.search(r'for the sample ([\w-]+):.*?decided (accept|reject|needs-review),',e['shows'])
            if m and m[1]==sample['id']:
                matches.append((m[2],e))
        require(len(matches)==1, 'Run it: missing or ambiguous recorded result for '+sample['id'])
        actual,e=matches[0]
        require(e.get('conclusion')=='success','Run it source run did not succeed')
        require(sample['expected'] in {'accept','reject'},'Run it sample lacks a binary expected result')
        cases.append({'actual':actual,'truth':'good' if sample['expected']=='accept' else 'bad'})
        answers=one(r'(\d+) of (\d+) vision questions answered',e['shows'],'Run it answers')
        rendered.append([cite(sample['id'],manifest.ref('"id": "'+sample['id']+'"')),cite(sample['expected'],manifest.ref('"id": "'+sample['id']+'"')),cite(actual,e['ref']),ratio(int(answers[1]),int(answers[2]),e['ref'])])
    out='<h2 id="samples">Run it recorded samples</h2><p>Hand-dispatched samples using recorded vision answers. These are seeded demonstrations, not independent coverage or evidence that the visitor service is deployed.</p>'
    out+=table(['Sample','Published expectation','Observed verdict','Vision answers / questions'],rendered,'Run it samples')
    out+=verdict_summary(cases,src.ref('"id": "run-it"'))
    out+='<p>Assertion family: the approved above-ground check. Defect type: seeded fall-through, with unchanged and repaired controls. Other families: not measured here.</p>'
    return out


def percentiles(values):
    """Nearest-rank empirical percentiles; singleton records do not measure spread."""
    require(all(math.isfinite(float(v)) and v>=0 for v in values),'invalid runtime')
    if len(values)<2:
        return None
    v=sorted(values)
    return v[math.ceil(len(v)*.50)-1],v[math.ceil(len(v)*.95)-1]


def runtimes(ledger,src,sam,blind_cost,repro_cost,comments):
    out='<h2 id="runtime">Runtime and cost</h2><p>Only comparable records are grouped: identical operation, runner and step, then phase. Different operations and providers are not pooled. Empirical nearest-rank percentiles require repeated records; a single duration is not a measured spread.</p>'
    groups=defaultdict(list)
    for t in ledger.get('timings',[]):
        groups[(t['what'],t['runner'],t['step'])].append(t)
    rows=[]
    for (what,runner,_),ts in groups.items():
        phases=sorted({p for t in ts for p in t.get('phases',{})}|{'whole'})
        # Stable run links are the measurement identity; repeated entries must not inflate n.
        require(len({t['run'] for t in ts})==len(ts),'duplicate timing run within a profile')
        for phase in phases:
            pairs=[(t['seconds'] if phase=='whole' else t['phases'][phase],t['run']) for t in ts if phase=='whole' or phase in t.get('phases',{})]
            values=[v for v,_ in pairs]; qs=percentiles(values)
            ref=src.ref('"timings"')
            rows.append([cite(what+'; '+runner,ref),esc(phase),cite(len(values),ref),', '.join(cite(str(v)+' s',r) for v,r in pairs),cite(str(qs[0])+' s',ref) if qs else 'not measured',cite(str(qs[1])+' s',ref) if qs else 'not measured','not measured'])
    out+=table(['Recorded profile','Phase','Samples','Recorded durations',cite('p50',src.ref('"timings"')),cite('p95',src.ref('"timings"')),'Cost per run'],rows,'Runtime records')
    for t in ledger.get('timings',[]):
        out+='<p>'+cite(t['notMeasured'],t['run'])+'</p>'
    out+='<p>Import, replay and evaluation phase percentiles for all other ledger profiles, and end-to-end deployment latency: not measured. Release-control test durations are not pooled into verification-phase timings.</p>'
    total,maximum,defects,ref,run=repro_cost
    costs=[['Public reproduction baseline, complete bench run',cite('$'+str(total),run),'Reported model spend; '+cite(defects,ref)+' defects, maximum '+cite('$'+str(maximum),ref)+' per defect.'],['Blind generated-check experiment, complete run',cite('$'+str(blind_cost[0]),blind_cost[1]),'Historical advisory experiment; not current installed-verifier pricing.']]
    # This is the published estimate, not an invoice or a newly measured price.
    estimate=one(r'about \$(\d+\.\d+) for both prompts over a (\d+)-frame run, against up to \$(\d+\.\d+)',sam.text,'SAM image/video estimate')
    costs.append(['SAM historical image-prompt example',cite('up to $'+estimate[3],sam.ref(estimate[0])),'List-price estimate for both prompts over '+cite(estimate[2]+' frames',sam.ref(estimate[0]))+'; not measured billing for a current verification.'])
    vision_comments = [c for c in comments.json() if 'First vision run on an outside project' in c['body']]
    require(len(vision_comments) == 1, 'outside cost source missing or ambiguous')
    c = vision_comments[0]
    amount = one(r'\$(\d+\.\d+) at list price, (\d+) images answered', c['body'], 'outside recorded cost')
    costs.append(['Outside vision trial, complete run', cite('$' + amount[1], c['url']),
                  'List-price amount, not an invoice; ' + cite(amount[2], c['url']) +
                  ' images answered. Cost per variant is not measured.'])
    out+=table(['Scope','Recorded cost or labelled estimate','Boundary'],costs,'Cost evidence')
    out+='<p>Measured billed cost per installed verification, outside-project verification, release-control run and Run it replay: not measured in these cost sources. A no-paid-call replay does not measure runner or deployment cost. Other provider profiles: not measured.</p>'
    return out


def build(root,commit):
    ss=sources(root,commit);ledger=ss[LEDGER].json()
    require(ledger.get('format')=='expectrail.capabilities/v1','unsupported capability ledger')
    require(len({r['id'] for r in ledger['rows']})==len(ledger['rows']),'duplicate ledger mode')
    out=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Release dossier — Expectrail</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#181536;background:#f6f7fc;margin:0}main{max-width:76rem;margin:auto;padding:2rem 1rem}a{color:#362b81}h1{font-size:2.4rem}h2{margin-top:3rem}table{border-collapse:collapse;width:100%;min-width:44rem;font-size:.92rem}th,td{padding:.7rem;text-align:left;vertical-align:top;border-bottom:1px solid #d2d3e0;overflow-wrap:anywhere}th{background:#e9e8f3}.scroll{overflow:auto;margin:1rem 0}nav{display:flex;gap:1rem;flex-wrap:wrap}.note{border-left:4px solid #e5b218;padding:1rem;background:white}code{overflow-wrap:anywhere}</style></head><body><main data-source-commit="'+commit+'"><a href="../">Expectrail</a><h1>Release evaluation dossier</h1><p class="note">Generated from recorded public evidence, offline. This is an evidence inventory, not release clearance. Historical experiments, demonstrations and incomplete controls stay separate.</p><nav aria-label="Dossier sections"><a href="#ledger">Capability snapshot</a><a href="#blind">Blind aggregates</a><a href="#reproduction">Reproduction</a><a href="#gate">Release controls</a><a href="#outside">Outside trial</a><a href="#samples">Run it</a><a href="#runtime">Runtime and cost</a><a href="#limits">Limitations</a><a href="#pending">Not run yet</a></nav>']
    out+=['<p>Repository evidence snapshot: '+cite(commit,GH+'/tree/'+commit)+'. Public API comments are separately captured with their original URLs. Source tag and container image digests: not measured in the inputs; no release tag or image identity is invented.</p><h2 id="ledger">Capability ledger snapshot</h2><p>Each row is copied as recorded, including its supported profile, status and evidence grade. A stale row is not silently updated from newer code. No mode is promoted by this dossier.</p>']
    out+=[table(['Mode','Status','Grade','Supported profile / environment','Observer','Recorded limits'], [[cite(r['mode'],ss[LEDGER].ref('"id": "'+r['id']+'"')),esc(r['status']),esc(r['grade']),cite(r['profile'],ss[LEDGER].ref('"id": "'+r['id']+'"')),cite(r['observer'],ss[LEDGER].ref('"id": "'+r['id']+'"')),cite(r['limits'],ss[LEDGER].ref('"id": "'+r['id']+'"'))] for r in ledger['rows']], 'Capability snapshot')]
    blind,blind_cost=blind_section(ss[LEDGER],ledger);out.append(blind)
    repro,repro_cost=reproduction(ss[PUBLIC],ss[DEFECTS]);out.append(repro)
    out.extend([release_gate(ss[GATE]),outside(ss[COMMENTS],ss[OUTSIDE]),runit(ledger,ss[SAMPLES],ss[LEDGER]),runtimes(ledger,ss[LEDGER],ss[SAM],blind_cost,repro_cost,ss[COMMENTS])])
    out+=['<h2 id="limits">Known limitations and owners</h2><ul>']
    limits=[(246,'The game originates its frames and trace; capture the game cannot forge is not established.'),(253,'The replay sandbox shares the host kernel and does not bound total job disk usage.'),(258,'Open release controls remain open; the dossier does not substitute unit-test counts for integration coverage.'),(257,'Observation-timeline controls still need their recorded release-suite evidence.'),(255,'Signed release receipts remain separate work.'),(285,'Reproduction misses and the unavailable baseline score artifact limit the public bench analysis.'),(263,'The outside trial is a small seeded demo cohort, not a successfully verified customer project.'),(330,'The hidden-player reject in the outside vision trial measured the background at the player’s position.'),(265,'Hand-dispatched Run it samples do not establish a deployed visitor service.'),(268,'Comparable repeated runtime samples, billed per-profile costs and environment image digests are incomplete.')]
    out.extend('<li>'+esc(text)+' '+issue(n)+'</li>' for n,text in limits)
    out+=['</ul><h2 id="pending">Not run yet</h2><ul><li>'+issue(282,'Blind test 4')+': <strong>not run yet</strong>. No private material is read and no result is guessed.</li><li>First-user quickstart test: <strong>not run yet</strong>; <strong>needs-sean</strong>. Sean or Timothy must arrange a person unfamiliar with Expectrail. Time to first verdict, obstacles and report comprehension remain unmeasured. '+issue(268)+'</li><li>Dodge the Creeps vision verification: <strong>not run yet</strong>. Its draft check awaits approval. '+issue(263)+' · '+issue(330)+'</li></ul><h2 id="sources">Source inventory and regeneration</h2><p>Regenerate with <code>python -m tools.dossier</code>; use <code>--check</code> to compare without writing. The checker retains the page’s recorded source commit unless an explicit <code>--commit</code> is supplied. Each visible numerical value links to its run or source file. Ratios and counts are computed from those records; error rates are never inferred from missing results.</p>']
    out+=[table(['Input','Content digest'],[[cite(s.path,s.ref()),cite(hashlib.sha256(s.text.encode()).hexdigest(),s.ref())] for s in ss.values()],'Source fingerprints')]
    out+=['<p>No crawler follows evidence links. No private manifest, blind-set directory, model or engine is invoked. The captured outside comments are read as text, never instructions. '+issue(268)+'</p></main></body></html>\n']
    return '\n'.join(out)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--out',type=Path)
    p.add_argument('--commit')
    p.add_argument('--check',action='store_true')
    args=p.parse_args(argv)
    out=args.out or args.root/'docs/release/index.html'
    try:
        commit=args.commit
        if not commit and args.check and out.is_file():
            commit=one(r'data-source-commit="([0-9a-f]{40})"',out.read_text(),'dossier source commit')[1]
        if not commit:
            commit=subprocess.check_output(['git','-C',str(args.root),'rev-parse','HEAD'],text=True).strip()
        rendered=build(args.root,commit)
        if args.check:
            require(out.is_file() and out.read_text(encoding='utf-8')==rendered,'generated dossier differs; run python -m tools.dossier')
            print('Dossier matches its recorded sources; offline check passed.')
        else:
            out.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=out.parent,delete=False) as f:
                f.write(rendered);name=f.name
            Path(name).replace(out)
            print('Wrote '+str(out)+' from public recorded sources; no network requests.')
        return 0
    except (EvidenceError,OSError,ValueError,KeyError,subprocess.CalledProcessError) as e:
        print('dossier: '+str(e),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
