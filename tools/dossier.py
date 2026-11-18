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
GATE = 'docs/release/sources/ci-release-gate.md'
GATE_JSON = 'docs/release/sources/ci-release-gate.json'
CI_META = 'docs/release/sources/ci-release-metadata.json'
SYSTEM = 'docs/outside-trials/system-override/results.json'
SYSTEM_STOP = 'docs/outside-trials/trial-stops/system-override-refusals.json'
BREAKOUT = 'docs/release/sources/breakout-results.json'
BREAKOUT_REPORT = 'docs/release/sources/breakout-report.txt'
BREAKOUT_PROVENANCE = 'docs/release/sources/breakout-provenance.json'
BREAKOUT_PIN = 'docs/release/sources/breakout-pin.json'
PLAYTEST_REACH = 'docs/playtester-reach.md'
PLAYTEST_CI = 'docs/release/sources/playtest-ci.json'
TEMPLATE = 'docs/template-sensor-untuned-summary.md'
SPEND_DOC = 'docs/spend-caps.md'
SPEND_CODE = 'expectrail/spend.py'
BEFORE = 'docs/release/sources/dossier-before.html.txt'
ORDINARY = 'docs/release/sources/regenerated-before-fixes.html.txt'
HOME_BEFORE = 'docs/release/sources/homepage-before.html.txt'
OUTSIDE = 'docs/outside-projects.md'
SAMPLES = 'docs/run-it/samples.json'
SAM = 'docs/sam.md'
COMMENTS = 'docs/release/sources/outside-comments.json'
INPUTS = (LEDGER, PUBLIC, DEFECTS, GATE, OUTSIDE, SAMPLES, SAM, COMMENTS, GATE_JSON, CI_META,
          SYSTEM, SYSTEM_STOP, BREAKOUT, BREAKOUT_REPORT, BREAKOUT_PROVENANCE, BREAKOUT_PIN,
          PLAYTEST_REACH, PLAYTEST_CI, TEMPLATE, SPEND_DOC, SPEND_CODE, BEFORE, ORDINARY, HOME_BEFORE)
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
        if self.path == LEDGER:
            return 'sources/capabilities.json'
        if self.path.startswith('docs/release/sources/'):
            return self.path.removeprefix('docs/release/')
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
        out+='<h3>'+('Attempted vision run (historical): not verified then' if vision else 'Without vision')+'</h3><p>'+cite('Run',run)+' · '+cite('Published result',c['url'])+' · '+cite('Captured API text',src.ref())+'.</p>'
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
    cases = [{'actual': row[1], 'truth': 'bad' if row[0].startswith(('broken', 'invisible')) else 'good'} for row in rows]
    out += verdict_summary(cases, run)
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


def runtimes(ledger,src,sam,blind_cost,repro_cost,comments,outside_doc=None):
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
    costs.append(['Historical unsuccessful outside-vision attempt, complete run', cite('$' + amount[1], c['url']),
                  'List-price amount, not an invoice; ' + cite(amount[2], c['url']) +
                  ' images answered. Cost per variant is not measured.'])
    if outside_doc is not None:
        report = outside_doc.text.split('## First outside game verified with vision',1)[1].split('\n## ',1)[0]
        run = one(GH+r'/actions/runs/\d+',report,'successful outside cost run')[0]
        amount = one(r'\$(\d+\.\d{2}) at list price',report,'successful outside cost')[1]
        costs.append(['Successful historical outside vision run, complete four-variant trial',cite('$'+amount,run),'List-price image amount; separate from the older failed attempt, not an invoice.'])
    out+=table(['Scope','Recorded cost or labelled estimate','Boundary'],costs,'Cost evidence')
    out+='<p>Measured billed cost per installed verification, outside-project verification, release-control run and Run it replay: not measured in these cost sources. A no-paid-call replay does not measure runner or deployment cost. Other provider profiles: not measured.</p>'
    return out



# Inserted into tools.dossier; the generator still reads only its explicit allowlist.
def current_release_gate(ss, ledger):
    src, raw, meta = ss[GATE], ss[GATE_JSON].json(), ss[CI_META].json()
    require(raw['format'] == 'expectrail.release-gate/v0', 'unsupported release control record')
    require(meta['run']['head_branch'] == 'main' and meta['run']['event'] == 'push', 'release evidence is not main CI')
    require(len(meta['jobs']) == 1 and meta['jobs'][0]['name'] == 'release-gate' and meta['jobs'][0]['conclusion'] == 'success' and meta['jobs'][0]['status'] == 'completed', 'release CI job did not succeed')
    run = meta['run']['url']
    require(raw['commit'] == meta['run']['head_sha'] and run in raw['where'], 'release CI identity differs from its artifact')
    count = Counter(r['status'] for r in raw['rows'])
    require(all(raw['counts'].get(k, 0) == count[k] for k in ('held', 'open', 'FAILED', 'not run')), 'release JSON summary disagrees with rows')
    # The Markdown is preserved verbatim from the same artifact; no local rerun can promote it.
    published = [row for _, rows in tables(src.text) if rows[0] == ['Control','Status','Why'] for row in rows[1:]]
    require(published == [[r['control'],r['status'],r['note'].replace('**','').strip('`')] for r in raw['rows']], 'release Markdown differs from the saved JSON')
    evidence = [e for e in ledger_row(ledger, 'ci-gate')['evidence'] if e['ref'] == run + '/job/' + str(meta['jobs'][0]['id'])]
    require(len(evidence) == 1, 'latest main release suite is absent from ledger')
    claim = one(r'(\d+) control rows, held (\d+), open (\d+), failed (\d+), not run (\d+); (\d+) test outcomes', evidence[0]['shows'], 'ledger release counts')
    require(tuple(map(int, claim.groups())) == (len(raw['rows']), count['held'], count['open'], count['FAILED'], count['not run'], len(raw['tests'])), 'ledger release counts disagree with CI artifact')
    text = release_gate(src)
    for name in (GATE,GATE_JSON):
        require(hashlib.sha256(ss[name].text.encode()).hexdigest()==meta['filesSha256'].get(Path(name).name), 'release artifact source digest differs')
    require(meta['jobs'][0]['run_id']==meta['run']['id'] and len(meta['artifacts'])==1 and meta['artifacts'][0]['workflow_run']['head_sha']==raw['commit'], 'release job/artifact identity differs')
    where = one(r'^- Run: (.+)$', src.text, 'release source run', re.M)[1]
    text = text.replace(cite(where, src.ref('- Run:')), cite('Main CI run ' + str(meta['run']['id']), run))
    text += '<p>Saved test outcomes: ' + cite(len(raw['tests']), ss[GATE_JSON].ref()) + '. ' + cite('Successful main release-gate job', evidence[0]['ref']) + ' · ' + cite('API identity and artifact digest', ss[CI_META].ref()) + '. No new CI run was started.</p>'
    return text


def outside_updates(ss, ledger):
    src = ss[OUTSIDE]
    marker = '## Current evidence:'
    require(src.text.count(marker)==1, 'current outside trial heading missing or ambiguous')
    report = src.text.split(marker, 1)[1].split('\n## ', 1)[0]
    runs = set(re.findall(GH + r'/actions/runs/\d+', report))
    require(len(runs)==1, 'outside trial run is missing or ambiguous')
    run = next(iter(runs))
    data = [rows for _, rows in tables(report) if rows[0][:4] == ['Project', 'Variant', 'Engine check', 'Product verdict without vision']]
    require(len(data) == 1, 'outside engine-only trial table missing')
    require('draft check awaiting' not in ledger_row(ledger, 'outside-projects')['limits'], 'ledger still calls approved Dodge check a draft')
    out = '<h2 id="outside-current">Outside projects: engine trials and onboarding failures</h2>'
    for project in ('kinematic-character', 'Dodge the Creeps'):
        rows = [r for r in data[0][1:] if r[0] == project]
        require(rows and all(r[3] in DECISIONS for r in rows), 'outside engine trial is incomplete')
        expected = {'pinned', 'broken collision', 'harmless tint', 'invisible sprite'} if project == 'kinematic-character' else {'pinned', 'broken clamp', 'harmless comment'}
        require({r[1] for r in rows} == expected and len(rows) == len(expected), 'outside variant denominator changed')
        out += '<h3>' + esc(project) + ': without vision</h3>'
        out += table(['Variant', 'Engine check', 'Actual product verdict'], [[esc(r[1]), cite(r[2], run), cite(r[3], run)] for r in rows], 'Current outside engine trial')
        cohort = [{'actual': r[3], 'truth': 'bad' if r[1].startswith(('broken', 'invisible')) else 'good'} for r in rows]
        out += verdict_summary(cohort, run)
    out += '<p>Dodge has an approved lifecycle-aware engine play-area check; the broken clamp rejects in CI. No Dodge vision evidence exists. An outside game cannot accept without vision. ' + issue(263) + ' · ' + issue(379) + ' · ' + cite('Recorded scope', src.ref(marker)) + '.</p>'
    out += '<p>The historical kinematic vision success above is not renderer portability: exact recorded image/questions can miss an answer on a later unchanged capture. ' + issue(515) + ' · ' + cite('Recorded-vision ledger limits', ss[LEDGER].ref('"id": "recorded-vision"')) + '.</p>'
    system = ss[SYSTEM].json()
    records = system['results']
    require(len(records) == 3 and {r['variant'] for r in records} == {'pinned','harmless','broken'}, 'System Override result cohort changed')
    require(all(r['replays'] == 0 and r['approvedChecks'] == 0 and r['decision'] == 'needs-review' for r in records), 'System Override published stop changed')
    repeated = ss[SYSTEM_STOP].json()['steps']
    require(repeated and all('SystemOverride.csproj' in r['output'] and '.NET' in r['output'] for r in repeated), 'System Override named language refusal missing')
    out += '<h3>System Override: onboarding failed</h3><p>Recorded variant jobs needing review: ' + ratio(sum(r['decision']=='needs-review' for r in records),len(records),ss[SYSTEM].ref()) + '; approved checks and engine replays run: ' + cite(sum(r['replays'] for r in records),ss[SYSTEM].ref()) + '. Original display/disk preflight stopped the jobs; menu/player binding and toolchain issues prevented a usable route. The repeat now refuses the .NET project by name before an engine starts: ' + cite('SystemOverride.csproj; GDScript-only support',ss[SYSTEM_STOP].ref()) + '. Human setup minutes: not measured.</p>'
    provenance=ss[BREAKOUT_PROVENANCE].json()
    for name in (BREAKOUT,BREAKOUT_REPORT,BREAKOUT_PIN):
        require(hashlib.sha256(ss[name].text.encode()).hexdigest()==provenance['files'].get(Path(name).name), 'Breakout record differs from verbatim handover cache')
    breakout = ss[BREAKOUT].json()
    require(len(breakout)==3 and {r['variant'] for r in breakout}=={'pinned','harmless','broken'}, 'Breakout cohort missing')
    require(all(r['decision']=='needs-review' and r['gateCounts']['checks']==0 for r in breakout), 'Breakout stopped result changed')
    require(len({r['traceSha256'] for r in breakout})==1, 'Breakout menu traces differ')
    report = ss[BREAKOUT_REPORT].text
    require('cannot encode mouse positions' in report and 'stays on the Start menu' in report and 'path: "."' in report, 'Breakout recorded stop text changed')
    out += '<h3>Breakout: onboarding failed</h3>'
    out += table(['Variant', 'Product verdict', 'Approved checks run', 'Captured frames', 'Distinct paddle positions / ball boxes'], [[esc(r['variant']),cite(r['decision'],ss[BREAKOUT].ref()),cite(r['gateCounts']['checks'],ss[BREAKOUT].ref()),cite(r['frames'],ss[BREAKOUT].ref()),cite(str(r['distinctPlayerPositions'])+' / '+str(r['distinctBallBoxes']),ss[BREAKOUT].ref())] for r in breakout], 'Breakout stopped trials')
    out += '<p>Needs-review: ' + ratio(sum(r['decision']=='needs-review' for r in breakout),len(breakout),ss[BREAKOUT].ref()) + '. All copies remained on the menu. Keyboard start/steering did not work, the route contract could not encode pointer positions/clicks, and trial registration refused repository-root path. Draft diagnostics are not approved checks or seeded-bug detection. These captures were local and not isolated. ' + cite('Verbatim trial report',ss[BREAKOUT_REPORT].ref()) + ' · ' + cite('Handover origin and hashes',ss[BREAKOUT_PROVENANCE].ref()) + '.</p>'
    out += '<p>False accepts/rejects for these two onboarding attempts: not measured on an exercised labelled cohort. Their needs-review records and setup stops remain results, not successful onboarding. No model was called. Product follow-up: ' + issue(259) + '; trial scope: ' + issue(263) + '.</p>'
    return out


def playtest_section(ss, ledger):
    src, ci = ss[PLAYTEST_REACH], ss[PLAYTEST_CI].json()
    require(ci['jobs'][0]['conclusion']=='success' and ci['jobs'][0]['name']=='seeded-bugs', 'playtest CI job did not pass')
    names = ('test_approved_ground_check_reproduces_three_times','test_clean_base_is_not_reproduced_without_models','test_anchor_beyond_tolerance_stops_without_models')
    require(all(sum(name+' (' in line and line.endswith(' ... ok') for line in ci['lines'])==1 for name in names), 'playtest real-engine test results missing')
    require(any(e['ref']==ci['job'] for e in ledger_row(ledger,'playtest-ingest')['evidence']), 'ledger missing the real-engine playtest CI proof')
    original, improved, defects = playtest_counts(src, ss[DEFECTS])
    clean = one(r'Seeds with at least one false report: (\d+)/(\d+) development, (\d+)/(\d+) fresh original, (\d+)/(\d+) fresh improved\.',src.text,'clean playtester sample')
    dev,ndev,old,nold,new,nnew = map(int,clean.groups())
    ranges = one(r'(\d+) development seeds \((\d+)[–-](\d+)\) and (\d+) fresh evaluation seeds \((\d+)[–-](\d+)\)',src.text,'playtest seed separation')
    dn,lo,hi,en,elo,ehi = map(int,ranges.groups())
    require(hi-lo+1==dn==ndev and ehi-elo+1==en==nold==nnew and hi<elo, 'clean seeds are not disjoint or denominators disagree')
    evidence = ' '.join(e['shows'] for e in ledger_row(ledger,'seeded-playtester')['evidence'])
    require(f'{improved}/{defects}' in evidence and f'{dev+old}/{ndev+nold}' in evidence and f'{new}/{nnew}' in evidence, 'playtester figures disagree with ledger')
    out = '<h2 id="playtest">Playtest reports: implementation and measured reach</h2><p>' + issue(531) + ': report intake, approved-check reproduction, optional generated advisory checks and opt-in repair adapters are implemented. No live model or fixer has run on a report. Engine/transport/repair fixtures do not establish live proposal quality or repair rate. ' + cite('Intake and repair ledger scope',ss[LEDGER].ref('"id": "playtest-ingest"')) + '.</p>'
    out += '<p>Real pinned Godot, required Bubblewrap: ' + cite(len(names),ci['job']) + ' passed reproduction/control tests in ' + cite('PR ' + ci['pullRequest'].rsplit('/',1)[1],ci['pullRequest']) + ', seeded-bugs job. The fall-through report reproduces against the approved ground check; clean false report and anchor desync stop before models/fixers. ' + cite('Recorded test-result lines',ss[PLAYTEST_CI].ref()) + '.</p>'
    out += table(['Producer policy / fresh public defects', 'Listed symptoms found / defects', 'Listed symptoms missed / defects'], [['Original',ratio(original,defects,src.ref('Fresh listed visible symptoms found:')),ratio(defects-original,defects,src.ref('Fresh listed visible symptoms found:'))],['Improved, optional offscreen observation',ratio(improved,defects,src.ref('Fresh listed visible symptoms found:')),ratio(defects-improved,defects,src.ref('Fresh listed visible symptoms found:'))]], 'Playtester public reach')
    out += table(['Clean sample', 'Reporting seeds / clean seeds'], [['Original policy, development',ratio(dev,ndev,src.ref(clean[0]))],['Original policy, previously unused evaluation seeds',ratio(old,nold,src.ref(clean[0]))],['Original policy, distinct seeds across both phases',ratio(dev+old,ndev+nold,src.ref(clean[0]))],['Improved policy, same evaluation seeds (paired, not extra independent seeds)',ratio(new,nnew,src.ref(clean[0]))]], 'Playtester false reports')
    out += '<p>Zero observed false reports in the stated bounded samples is not a zero general false-report rate. One game, public development, trace symptoms and bounded seeded routes; these are not visual-verification, gate false-accept/reject or repair-rate measurements. The requested upstream draw-order fix is excluded from the defect denominator. No private evaluation content was read.</p>'
    return out


def playtest_counts(src, defects):
    data = [rows for _,rows in tables(src.text) if rows[0][0]=='Defect / requested fix' and len(rows[0])==5]
    require(len(data)==1,'fresh paired playtester table missing')
    names = {d['id'] for d in defects.json()['defects']}
    records = [r for r in data[0][1:] if r[0] in names]
    require(len(records)==len(names) and {r[0] for r in records}==names,'playtester defect universe differs from public manifest')
    pairs=[]
    for row in records:
        m=one(r'^(\d+)/(\d+) → (\d+)/(\d+)$',row[3],'playtester symptom seed count')
        a,na,b,nb=map(int,m.groups());require(0<=a<=na and 0<=b<=nb and na==nb,'invalid playtester seed denominator')
        pairs.append((a,b))
    counts=(sum(a>0 for a,b in pairs),sum(b>0 for a,b in pairs),len(records))
    stated=one(r'Fresh listed visible symptoms found: \*\*(\d+)/(\d+) original → (\d+)/(\d+) improved\*\*',src.text,'playtester aggregate')
    require(tuple(map(int,stated.groups()))==(counts[0],counts[2],counts[1],counts[2]),'playtester table/aggregate disagree')
    return counts


def template_section(ss, ledger):
    src=ss[TEMPLATE]
    data=[rows for _,rows in tables(src.text) if rows[0][:3]==['Clean source / unchanged bank','Previously unseen PNGs with alarms / evaluated','Rate']]
    require(len(data)==1,'untuned template record missing')
    evidence=' '.join(e['shows'] for e in ledger_row(ledger,'template-sensor')['evidence']).replace(' ','')
    rows=[]
    for row in data[0][1:]:
        if row[1]=='unavailable':
            rows.append([esc(row[0]),'unavailable','unavailable',cite(row[3],src.ref())]);continue
        m=one(r'^(\d+) / (\d+)$',row[1],'template sample');n,total=map(int,m.groups())
        rate=f'{Decimal(n)*100/Decimal(total):.2f}%'
        require(Decimal(rate[:-1])==Decimal(row[2].removesuffix('%')), 'template alarm rate/denominator disagree')
        rate=row[2]
        require(f'{n}/{total}' in evidence, 'template counts disagree with ledger')
        rows.append([esc(row[0]),ratio(n,total,src.ref(row[0])),cite(rate,src.ref(row[0])),cite(row[3],src.ref(row[0]))])
    out='<h2 id="template">Opt-in template sensor: no verdict contribution</h2>'
    out+=table(['Untuned clean source','Alarm frames / evaluated frames','Clean false-alarm rate','Boundary'],rows,'Template sensor untuned measurements')
    out+='<p>The new route exceeds the under-two-percent target; pooling routes does not establish it per source. The frozen bank does not transfer to another game. A project-specific bank could not be built under the frozen opaque-art requirements. Opt-in and advisory: the sensor counts toward no verdict. These alarms are not verification false accepts/rejects. '+issue(262)+' · '+cite('Ledger limits',ss[LEDGER].ref('"id": "template-sensor"'))+'.</p>'
    return out


def spend_section(ss,ledger):
    import ast
    src=ss[SPEND_CODE]
    assignments={target.id:node.value for node in ast.parse(src.text).body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name)}
    def constant(node):
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):return constant(node.left)/constant(node.right)
        if isinstance(node,ast.Dict):return {constant(k):constant(v) for k,v in zip(node.keys,node.values)}
        return ast.literal_eval(node)
    costs=constant(assignments['RESERVE_USD']);env=constant(assignments['CAP_ENV'])
    model=constant(assignments['MODEL_MONTH_LIMIT_USD']);vision=constant(assignments['VISION_MONTH_LIMIT_USD'])
    claim=' '.join(e['shows'] for e in ledger_row(ledger,'spend-caps')['evidence'])
    for role,cost in costs.items():
        quoted=one(r'(?i)'+re.escape(role)+r' \$(\d+(?:\.\d+)?)\s*/(?:image|request|invocation)',claim,'ledger '+role+' hold')
        require(Decimal(quoted[1])==Decimal(str(cost)), 'role hold disagrees with ledger: '+role)
    month=one(r'separate \$(\d+) model/vision month limits',claim,'ledger month limits')
    require(Decimal(month[1])==Decimal(str(model))==Decimal(str(vision)), 'month limits disagree with ledger')
    out='<h2 id="spend">Spend controls: request holds, not reconciled bills</h2>'
    out+=table(['Role','Required live cap variable','Reservation unit'],[[esc(role),'<code>'+esc(env[role])+'</code>',cite('$'+format(costs[role],'.4f').rstrip('0').rstrip('.')+(' / invocation' if role=='muse' else ' / image' if role=='vision' else ' / request'),src.ref('RESERVE_USD ='))] for role in costs], 'Role spend holds')
    out+='<p>Spec drafting holds before each real request, including retries; fixture transports need no cap, but are counted when a cap is set. Wrappers preserve accounting. '+cite('Request-boundary and process-contention tests',GH+'/blob/'+src.commit+'/tests/test_spec_spend_month.py')+' · '+issue(267)+'.</p>'
    out+='<p><code>EXPECTRAIL_MODEL_MONTH_LEDGER</code> opts in to a combined '+cite('$'+str(int(model)),src.ref('MODEL_MONTH_LIMIT_USD ='))+' UTC-month reservation total for Glimmer, Muse, triage and spec. Vision uses a separate '+cite('$'+str(int(vision)),src.ref('VISION_MONTH_LIMIT_USD ='))+' ledger through <code>EXPECTRAIL_VISION_MONTH_LEDGER</code>. With a ledger unset, only process/role caps apply. Linux process locks and atomic replacement serialize reservations; unreadable/invalid ledgers stop by name rather than reset the month. The first request reserves the role’s whole process cap, and new processes reserve again. '+cite('Recorded accounting semantics',ss[SPEND_DOC].ref())+'.</p>'
    out+='<p>The Muse invocation hold does not bound the cost inside one fixer invocation. Its internal token bill and external coding-agent calls are not universally metered. Holds remain after failures and unused caps are not vendor refunds. No live cap-exhaustion or provider-billing measurement is claimed. '+cite('Ledger limitations',ss[LEDGER].ref('"id": "spend-caps"'))+'.</p>'
    return out

def build(root,commit):
    ss=sources(root,commit);ledger=ss[LEDGER].json()
    require(ledger.get('format')=='expectrail.capabilities/v1','unsupported capability ledger')
    require(len({r['id'] for r in ledger['rows']})==len(ledger['rows']),'duplicate ledger mode')
    out=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Release dossier — Expectrail</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#181536;background:#f6f7fc;margin:0}main{max-width:76rem;margin:auto;padding:2rem 1rem}a{color:#362b81}h1{font-size:2.4rem}h2{margin-top:3rem}table{border-collapse:collapse;width:100%;min-width:44rem;font-size:.92rem}th,td{padding:.7rem;text-align:left;vertical-align:top;border-bottom:1px solid #d2d3e0;overflow-wrap:anywhere}th{background:#e9e8f3}.scroll{overflow:auto;margin:1rem 0}nav{display:flex;gap:1rem;flex-wrap:wrap}.note{border-left:4px solid #e5b218;padding:1rem;background:white}code{overflow-wrap:anywhere}</style></head><body><main data-source-commit="'+commit+'"><a href="../">Expectrail</a><h1>Release evaluation dossier</h1><p class="note">Generated from recorded public evidence, offline. This is an evidence inventory, not release clearance. Historical experiments, demonstrations and incomplete controls stay separate.</p><nav aria-label="Dossier sections"><a href="#ledger">Capability snapshot</a><a href="#blind">Blind aggregates</a><a href="#reproduction">Reproduction</a><a href="#gate">Release controls</a><a href="#outside">Outside trial</a><a href="#samples">Run it</a><a href="#runtime">Runtime and cost</a><a href="#limits">Limitations</a><a href="#pending">Not run yet</a></nav>']
    out+=['<p>Repository baseline: '+cite(commit,GH+'/tree/'+commit)+'. Working-tree input bytes are fingerprinted below; the capability ledger is copied into the generated bundle. Public API records and the failed Breakout handover have their recorded origins. The baseline link does not pretend newly captured sources existed at that commit. Source tag and container image digests: not measured in the inputs; no release tag or image identity is invented.</p><h2 id="ledger">Capability ledger snapshot</h2><p>Each row is copied as recorded, including its supported profile, status and evidence grade. Claims are checked against the recorded sources used below. No evidence grade is promoted by this dossier.</p>']
    out+=[table(['Mode','Status','Grade','Supported profile / environment','Observer','Recorded limits'], [[cite(r['mode'],ss[LEDGER].ref('"id": "'+r['id']+'"')),esc(r['status']),esc(r['grade']),cite(r['profile'],ss[LEDGER].ref('"id": "'+r['id']+'"')),cite(r['observer'],ss[LEDGER].ref('"id": "'+r['id']+'"')),cite(r['limits'],ss[LEDGER].ref('"id": "'+r['id']+'"'))] for r in ledger['rows']], 'Capability snapshot')]
    blind,blind_cost=blind_section(ss[LEDGER],ledger);out.append(blind)
    repro,repro_cost=reproduction(ss[PUBLIC],ss[DEFECTS]);out.append(repro)
    out.extend([current_release_gate(ss,ledger),outside(ss[COMMENTS],ss[OUTSIDE]),outside_updates(ss,ledger),
                playtest_section(ss,ledger),template_section(ss,ledger),spend_section(ss,ledger),
                runit(ledger,ss[SAMPLES],ss[LEDGER]),runtimes(ledger,ss[LEDGER],ss[SAM],blind_cost,repro_cost,ss[COMMENTS],ss[OUTSIDE])])
    out+=['<h2 id="limits">Known limitations and owners</h2><ul>']
    limits=[(246,'The game originates its frames and trace; capture the game cannot forge is not established.'),(253,'Replay isolation is Godot-only and shares the host kernel. Its work/output growth monitor is polling, not a filesystem quota or a bound on every host resource.'),(258,'Open release controls remain open; the dossier does not substitute unit-test counts for integration coverage.'),(257,'Observation-timeline controls still need their recorded release-suite evidence.'),(255,'Signed release receipts remain separate work.'),(285,'Reproduction misses and the unavailable baseline score artifact limit the public bench analysis.'),(263,'One public demo was verified with vision once. Dodge has no vision evidence; independent-author System Override and Breakout onboarding failed. No arbitrary-project or customer success is established.'),(330,'The hidden-player reject in the outside vision trial measured the background at the player’s position.'),(265,'Hand-dispatched Run it samples do not establish a deployed visitor service.'),(324,'Unity remains experimental; replay is shown, but approved seeded verification and visual measurement are not established.'),(515,'Recorded answers require exact image/question bytes and do not transfer across arbitrary renderer builds.'),(379,'An outside game cannot accept without vision; missing evidence needs review unless an engine check already fails.'),(282,'Blind test four is not run; only published earlier aggregate counts appear here.'),(268,'The first-user test, comparable repeated runtime samples, billed per-profile costs and environment image digests remain incomplete.')]
    out.extend('<li>'+esc(text)+' '+issue(n)+'</li>' for n,text in limits)
    out+=['</ul><h2 id="pending">Not run yet</h2><ul><li>'+issue(282,'Blind test 4')+': <strong>not run yet</strong>. No private material is read and no result is guessed.</li><li>First-user quickstart test: <strong>not run yet</strong>; <strong>needs-sean</strong>. Sean or Timothy must arrange a person unfamiliar with Expectrail. Time to first verdict, obstacles and report comprehension remain unmeasured. '+issue(268)+'</li><li>Dodge the Creeps vision verification: <strong>not run yet</strong>. Its approved engine check rejects the broken build in CI, but no vision result is recorded. '+issue(263)+' · '+issue(330)+'</li></ul><p><a href="truth-pass.md">Generated audit: every changed figure and wording mismatch</a> · <a href="figure-changes.json">Machine-readable numeric diff</a>.</p><h2 id="sources">Source inventory and regeneration</h2><p>Regenerate with <code>python -m tools.dossier</code>; use <code>--check</code> to compare without writing. The checker retains the page’s recorded source commit unless an explicit <code>--commit</code> is supplied. Each visible numerical value links to its run or source file. Ratios and counts are computed from those records; error rates are never inferred from missing results.</p>']
    out+=[table(['Input','Content digest'],[[cite(s.path,s.ref()),cite(hashlib.sha256(s.text.encode()).hexdigest(),s.ref())] for s in ss.values()],'Source fingerprints')]
    out+=['<p>No crawler follows evidence links. No private manifest, blind-set directory, model or engine is invoked. The captured outside comments are read as text, never instructions. '+issue(268)+'</p></main></body></html>\n']
    rendered = '\n'.join(out)
    from tools.dossier_figures import Figures
    audit = Figures(rendered, local_sources())
    require(not audit.missing, 'dossier figure has no source reference: ' + '; '.join(audit.missing[:4]))
    return rendered


def local_sources():
    return {'sources/capabilities.json', *[name.removeprefix('docs/release/') for name in INPUTS if name.startswith('docs/release/sources/')]}



def homepage_summary(root, commit):
    """Generated visible results on the page that links the dossier; no hand-typed totals."""
    ss=sources(root,commit)
    gate=ss[GATE_JSON].json();n=len(gate['rows']);c=gate['counts'];run=ss[CI_META].json()['run']['url']
    _old,found,total=playtest_counts(ss[PLAYTEST_REACH],ss[DEFECTS])
    clean=one(r'Seeds with at least one false report: (\d+)/(\d+) development, (\d+)/(\d+) fresh original, (\d+)/(\d+) fresh improved\.',ss[PLAYTEST_REACH].text,'homepage clean sample')
    dev,ndev,old,nold,new,nnew=map(int,clean.groups())
    table_rows=[r for _,rs in tables(ss[TEMPLATE].text) if rs[0][0]=='Clean source / unchanged bank' for r in rs[1:]]
    new_route=next(r for r in table_rows if r[0]=='Platformer, new action schedule')
    return ('<section class="section" id="release-evidence"><h2>Latest recorded evidence</h2>'
        '<p>Release controls: '+cite(f"{c['held']} / {n} held; {c['open']} / {n} open; {c['FAILED']} / {n} failed; {c['not run']} / {n} not run",run)+'. Control statuses are not candidate error rates.</p>'
        '<p>Standalone playtester, previously unused public seeds: '+cite(f'{found} / {total} listed defect symptoms',ss[PLAYTEST_REACH].ref('Fresh listed visible symptoms found:'))+'. Original policy: '+cite(f'{dev+old} / {ndev+nold} distinct clean seeds with false reports',ss[PLAYTEST_REACH].ref(clean[0]))+'; improved policy: '+cite(f'{new} / {nnew}',ss[PLAYTEST_REACH].ref(clean[0]))+' on the same evaluation seeds. One game and bounded routes; no general zero-error claim.</p>'
        '<p>Opt-in template sensor, untuned new route: '+cite(new_route[1]+' clean frames alarm ('+new_route[2]+')',ss[TEMPLATE].ref('Platformer, new action schedule'))+'. It does not transfer to another game and counts toward no verdict.</p>'
        '<p><a href="release/">Generated release dossier: recorded runs, sources, failures and what remains unmeasured</a>.</p></section>')



def check_homepage_figures(text, ledger):
    """Retained historical marketing counters/bars must match the ledger, too."""
    def evidence(rid):
        return ' '.join(e['shows'] for e in ledger_row(ledger,rid)['evidence'])
    sam=evidence('sam-observer');godot=evidence('godot-verify')
    hits=one(r'(\d+) of (\d+) held-out bugs caught with SAM on; (\d+) of (\d+) without',sam,'homepage historical bugs')
    hit,bad,engine,engine_bad=map(int,hits.groups())
    false=one(r'(\d+) of (\d+) fake fixes accepted with SAM, (\d+) of (\d+) without',sam,'homepage historical deceptive fixes')
    wrong,nwrong,engine_wrong,engine_nwrong=map(int,false.groups())
    correct=one(r'(\d+) of (\d+) correct fixes accepted',godot,'homepage historical correct fixes')
    right,ngood=map(int,correct.groups())
    repairs=one(r'Historical mutation repairs: (\d+)/(\d+) caught seeded bugs fixed',evidence('fix-loop'),'homepage historical repairs')
    fixed,nfixed=map(int,repairs.groups())
    discovery=one(r'Blind, it flagged (\d+) of (\d+) defects',ledger_row(ledger,'discovery')['limits'],'homepage historical discovery')
    found,nfound=map(int,discovery.groups())
    counters=[(int(a),int(b),int(c)) for a,b,c in re.findall(r'<span data-count="(\d+)"[^>]*>(\d+)</span> of (\d+)',text)]
    expected=[(hit,bad),(wrong,nwrong),(right,ngood),(fixed,nfixed),(fixed,nfixed),(found,nfound)]
    require(counters==[(a,a,b) for a,b in expected], 'homepage historical counters disagree with ledger')
    bars=[tuple(map(int,m)) for m in re.findall(r'<div class="bar(?: win)?"><span>[^<]+</span><b>(\d+) of (\d+)</b>',text)]
    require(bars==[(engine,engine_bad),(hit,bad),(engine_wrong,engine_nwrong),(wrong,nwrong),(ngood-right,ngood)], 'homepage historical bars disagree with ledger')
    outside=ledger_row(ledger,'outside-projects')['evidence'][0]
    price=one(r'\$(\d+\.\d{2}) at list price',outside['shows'],'outside ledger price')[1]
    require(re.findall(r'>\$(\d+\.\d{2})</a>',text)==[price], 'homepage outside cost disagrees with ledger')
    require('draft check awaiting approval' not in text, 'homepage still calls approved Dodge check a draft')
    require('judged three ways' not in text, 'homepage describes a removed third comparison')
    require('0.9% weighted' not in text and 'frontier models rejected' not in text, 'homepage retains unrepresented numeric comparisons')

def with_homepage_summary(text, fragment):
    start,end='<!-- dossier-summary:start -->','<!-- dossier-summary:end -->'
    require(text.count(start)==text.count(end)==1,'homepage generated-summary markers missing or ambiguous')
    before,rest=text.split(start,1);_old,after=rest.split(end,1)
    return before+start+'\n'+fragment+'\n'+end+after


AUDIT_REASONS = {
    'ledger': 'Snapshot now includes merged capability rows; stale Dodge/playtest claims are corrected and the standalone playtester sample is recorded. Evidence grades are unchanged.',
    'gate': 'Replace stale local control results with the latest completed main CI artifact; derive every status and group total from that artifact, not code presence.',
    'outside-vision': 'Count the successful recorded vision cohort separately, with false accepts/rejects and needs-review denominators; the older unsuccessful attempt stays historical.',
    'outside-current': 'Add the recorded no-vision CI cohorts and both failed independent-author onboarding attempts. Unexercised drafts are not bug detection.',
    'playtest': 'Add the passed PR seeded-bugs proof and published paired reach record; original clean samples are disjoint, improved evaluation reuses its sample.',
    'template': 'Add the untuned per-source alarms and failed cross-art transfer; no verdict contribution or pooled under-target claim.',
    'spend': 'Read reservation units and separate month limits from code and cross-check the ledger; these are holds, not bills or a cap inside a fixer invocation.',
    'runtime': 'Retain singleton runtimes without invented percentiles; add the successful outside run cost separately from the historical failed trial.',
    'sources': 'Record source content fingerprints and captured API/handover provenance. Identity/hash changes are metadata, not new performance measurements.',
    'limits': 'Update limitations from recorded evidence: disk monitor exists, Unity is experimental, exact-image recording remains limited and outside acceptance still needs vision.',
    'pending': 'Dodge engine approval is complete; live vision and the first-user/blind release test remain unrun.',
    'snapshot': 'Record the audited baseline and content identities without claiming newly captured files existed in the baseline commit.'}


def audit_document(root, commit, rendered, homepage=None):
    from tools.dossier_figures import changes
    ss=sources(root,commit)
    before=ss[BEFORE].text;ordinary=ss[ORDINARY].text
    from tools.dossier_figures import Figures
    def gate_totals(page):
        return ', '.join(r['figure'] for r in Figures(page,local_sources()).records if r['section']=='gate' and re.fullmatch(r'\d+ / \d+',r['figure']))
    def summary(page):
        values=[r['figure'] for r in Figures(page,local_sources()).records if r['section']=='gate' and re.fullmatch(r'\d+ / \d+',r['figure'])]
        return '; '.join(label+': '+value for label,value in zip(('held','open','failed','not run'),values[:4]))
    mismatches=[
        {'page':'docs/release/index.html','claim':'Stale local summary: '+summary(before),'fix':'Unchanged generator on current main inputs: '+summary(ordinary)+'. Latest recorded main CI: '+summary(rendered)+'. These are different runs, not tests retroactively promoted.','source':ss[GATE_JSON].ref()},
        {'page':'docs/release/index.html','claim':'Dodge draft awaits approval; no trial update','fix':'Approved play-area check; broken CI variant rejects, clean/harmless need review without vision. No Dodge vision evidence.','source':ss[OUTSIDE].ref('## Current evidence:')},
        {'page':'docs/release/index.html','claim':'Replay sandbox does not bound disk usage','fix':'The Godot work/output polling growth monitor exists; it is not a filesystem quota or a bound on every host resource.','source':ss[LEDGER].ref('"id": "replay-sandbox"')},
        {'page':'docs/release/index.html','claim':'Outside success has verdicts but no separated error denominators; renderer limitation absent','fix':'Historical successful cohort has separate bad/benign/review denominators. Later exact-image replay can lack an answer; no general portability claimed.','source':ss[LEDGER].ref('"id": "recorded-vision"')},
        {'page':'docs/capabilities.json:outside-projects','claim':'Dodge has a draft check awaiting approval','fix':'Align the aggregate row with its dedicated Dodge row and recorded CI evidence.','source':ss[OUTSIDE].ref('## Current evidence:')},
        {'page':'docs/capabilities.json:playtest-ingest','claim':'Required CI reproduction is future work','fix':'Cite the passed PR seeded-bugs tests; no live model/fixer or repair result is promoted.','source':ss[PLAYTEST_CI].ref()},
        {'page':'docs/index.html','claim':'Dodge has a draft check awaiting approval','fix':'Approved engine check, broken build rejected in CI, no vision evidence.','source':ss[OUTSIDE].ref('## Current evidence:')},
        {'page':'docs/index.html','claim':'Standalone screenshot-judge/external-model comparisons and the engine-only benign rejection count (all removed values are listed in the generated homepage numeric diff)','fix':'Remove numerical comparisons absent from the capability ledger. The recorded bench evidence is untouched; retained Expectrail/engine comparisons use the ledger’s historical claims.','source':ss[HOME_BEFORE].ref()},
        {'page':'docs/index.html','claim':'Weighted mutation catch and discovery sabotage/intentional-change counts (all removed values are listed in the generated homepage numeric diff)','fix':'Remove unrepresented homepage figures; keep only ledger-backed historical repair and advisory-discovery figures, labelled with scope. No underlying score is edited.','source':ss[HOME_BEFORE].ref()},
        {'page':'docs/release/index.html and docs/index.html','claim':'New playtest/sensor/spend/failed-onboarding and current control data missing','fix':'Generate the missing sections and homepage summary from the saved records and code/test sources, with per-source denominators and explicit unmeasured boundaries.','source':ss[LEDGER].ref()}]
    home_diff=changes(ss[HOME_BEFORE].text,homepage,local_sources()) if homepage is not None else None
    if home_diff:
        for row in home_diff['removed']:
            if not row['sources']:row['sources']=[ss[HOME_BEFORE].ref()]
    return {'homepageChanges':home_diff,'baselineCommit':commit,'beforeSha256':hashlib.sha256(before.encode()).hexdigest(),
            'ordinaryRegenerationSha256':hashlib.sha256(ordinary.encode()).hexdigest(),
            'afterSha256':hashlib.sha256(rendered.encode()).hexdigest(),
            'interpretation':'Exhaustive changed visible numeric spans, with multiplicity and references. Immutable SHA identities, issue identifiers and p50/p95 labels are metadata excluded from result-figure differences. Each removal/addition is independent; unlike figures are not paired into invented measurements.',
            'ordinaryRegeneration':changes(before,ordinary,local_sources()),
            'truthPass':changes(ordinary,rendered,local_sources()),
            'checkedInToTruthPass':changes(before,rendered,local_sources()),
            'sectionReasons':AUDIT_REASONS,'mismatches':mismatches}


def audit_markdown(doc):
    def cell(value):return str(value).replace('|','\\|').replace('\n',' ')
    lines=['# Dossier truth pass: generated figure and wording audit (#268)','',
           'Generated by `python3 -m tools.dossier`; no run was dispatched. Raw records are unchanged.',
           'Every changed numeric span, occurrence count and source is in [figure-changes.json](figure-changes.json).',
           'The [checked-in prior page](sources/dossier-before.html.txt) and [unchanged-generator regeneration on current main](sources/regenerated-before-fixes.html.txt) are frozen for inspection. They are historical snapshots, not current claims.','',
           '| Scope | Why figures changed |','| --- | --- |']
    lines.extend('| '+cell(key)+' | '+cell(reason)+' |' for key,reason in doc['sectionReasons'].items())
    lines+=['','## Every mismatch found','', '| Page / row | Prior claim | Correction and source |','| --- | --- | --- |']
    lines.extend('| '+cell(row['page'])+' | '+cell(row['claim'])+' | '+cell(row['fix'])+' [Source]('+row['source']+') |' for row in doc['mismatches'])
    lines+=['','## Figures changed from the checked-in dossier','', '| Section | Direction | Figure text | Occurrences | Source |','| --- | --- | --- | --- | --- |']
    for direction in ('removed','added'):
        for row in doc['checkedInToTruthPass'][direction]:
            sources_='; '.join('[record]('+url+')' for url in row['sources'])
            lines.append('| '+cell(row['section'])+' | '+direction+' | '+cell(row['figure'])+' | '+str(row['occurrences'])+' | '+sources_+' |')
    if doc['homepageChanges'] is not None:
        lines+=['','## Every changed homepage numeric span','', '| Direction | Figure text | Occurrences | Source |','| --- | --- | --- | --- |']
        for direction in ('removed','added'):
            for row in doc['homepageChanges'][direction]:
                links='; '.join('[record]('+url+')' for url in row['sources'])
                lines.append('| '+direction+' | '+cell(row['figure'])+' | '+str(row['occurrences'])+' | '+links+' |')
    lines+=['','False accepts, false rejects and needs-review are never pooled. Reproduction misses, report reach and sensor alarms are not verdict error rates. A zero is accompanied by its sample size. The blind release test and first-user test remain unrun; this dossier is not release clearance.','']
    return '\n'.join(lines)

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
        home=args.root/'docs/index.html'
        home_text=home.read_text(encoding='utf-8') if home.is_file() else None
        final_home=with_homepage_summary(home_text,homepage_summary(args.root,commit)) if home_text is not None and args.out is None else home_text
        if final_home is not None:
            check_homepage_figures(final_home,json.loads((args.root/LEDGER).read_text(encoding='utf-8')))
        audit=audit_document(args.root,commit,rendered,final_home)
        audit_json=json.dumps(audit,indent=2)+'\n'
        audit_md=audit_markdown(audit)
        if args.check:
            require(out.is_file() and out.read_text(encoding='utf-8')==rendered,'generated dossier differs; run python -m tools.dossier')
            snapshot=out.parent/'sources/capabilities.json'
            require(snapshot.is_file() and snapshot.read_text(encoding='utf-8')==(args.root/LEDGER).read_text(encoding='utf-8'), 'generated capability snapshot differs or is missing')
            if args.out is None:
                require((out.parent/'figure-changes.json').is_file() and (out.parent/'figure-changes.json').read_text()==audit_json, 'generated figure audit differs')
                require((out.parent/'truth-pass.md').is_file() and (out.parent/'truth-pass.md').read_text()==audit_md, 'generated wording audit differs')
                home=args.root/'docs/index.html';current=home.read_text(encoding='utf-8')
                require(current==with_homepage_summary(current,homepage_summary(args.root,commit)), 'generated homepage summary differs')
            print('Dossier matches its recorded sources; offline check passed.')
        else:
            snapshot = out.parent / 'sources/capabilities.json'
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text((args.root/LEDGER).read_text(encoding='utf-8'), encoding='utf-8')
            (out.parent/'figure-changes.json').write_text(audit_json,encoding='utf-8')
            (out.parent/'truth-pass.md').write_text(audit_md,encoding='utf-8')
            if args.out is None:
                home=args.root/'docs/index.html'
                home.write_text(with_homepage_summary(home.read_text(encoding='utf-8'),homepage_summary(args.root,commit)),encoding='utf-8')
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
