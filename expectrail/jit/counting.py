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
    result={'format':FORMAT,'sourceRun':copy.deepcopy(run),'bugReport':report,
            'sourceReceipt':copy.deepcopy(certificate),'assessment':{
                'runSha256':digest_v1(run),'receiptSha256':digest_v1(certificate) if certificate is not None else None,
                'rows':assess.counting(run,report,trusted=authenticated(run,certificate,trust))}}
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


def public_bench(records, out):
    """Offline classification of committed public records; no replay or model."""
    from expectrail.jit import bench
    if bench.private_name(records):
        raise ValueError('public-only: held-out/fresh record roots refused')
    manifest=bench.public_cases()
    rows=[]
    legacy_valid = 0
    root=Path(__file__).resolve().parents[2]
    for defect in manifest['defects']:
        path=Path(records)/('repro-'+defect['id'])/'jit-run.json'
        run=record.read_json(path,cap=8*1024*1024,label='public JIT record')
        report=(root/defect['report']).read_text()
        result=make(run,report)
        legacy_valid += sum(bool(row['valid']) for row in run['validity'])
        counted=sum(r['counting'] for r in result['assessment']['rows'])
        rows.append((defect['id'],len(result['assessment']['rows']),counted,digest_v1(run)))
    lines=['# Offline counting audit of the public reproduction bench (#271)','',
           'Existing recorded model outputs only; no model call or replay. No trusted source certificate/context is supplied.',
           'Every legacy record is advisory: candidate shown, no authenticated trusted producer/replayer, and no per-arm coverage provenance.',
           'This is not the rate of a new candidate-withheld, trusted generation run.','',
           '| Public defect | Checks assessed | Counting | Advisory | Canonical run SHA-256 |',
           '| --- | ---: | ---: | ---: | --- |']
    lines += [f'| {name} | {total} | {counted} | {total-counted} | `{sha}` |' for name,total,counted,sha in rows]
    total=sum(r[1] for r in rows);counted=sum(r[2] for r in rows)
    lines += ['',f'Total: {len(rows)} public defects; {total} checks assessed; {counted} counting; {total-counted} advisory.','']
    lines += [f'Of these, {legacy_valid} are recorded as valid by the legacy keep rule; '
              f'{total-legacy_valid} are dropped proposals retained only as advisory diagnostics. No outcomes were replayed.','']
    Path(out).write_text('\n'.join(lines))
    return {'defects':len(rows),'checks':total,'counting':counted,'advisory':total-counted,
            'legacyKeptAdvisory':legacy_valid,'droppedProposals':total-legacy_valid}


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    audit=sub.add_parser('public-bench');audit.add_argument('--records',type=Path,required=True);audit.add_argument('--out',type=Path,required=True)
    judge_cmd=sub.add_parser('judge');judge_cmd.add_argument('--gate',type=Path,required=True)
    judge_cmd.add_argument('--evidence',type=Path,required=True);judge_cmd.add_argument('--context',type=Path,required=True)
    judge_cmd.add_argument('--trust-store',type=Path,required=True);judge_cmd.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='public-bench':print(json.dumps(public_bench(args.records,args.out)));return 0
    trust=Trust.load(args.context,args.trust_store)
    doc,proof=judge(record.read_record(args.gate),args.evidence,trust=trust)
    args.out.write_text(json.dumps(doc,indent=2)+'\n')
    record.read_record(args.out,generated=proof)
    print(doc['decision']);return 0 if doc['decision']=='accept' else 1 if doc['decision']=='reject' else 2


if __name__=='__main__':raise SystemExit(main())
