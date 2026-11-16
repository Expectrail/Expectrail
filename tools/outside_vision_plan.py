"""Exact, no-model question planning for saved outside captures."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from agents.observations import _frame_tick, _frame_box, _view_at
from agents.sam_observations import SamError, USD_PER_IMAGE, box_prompt, frame_files, png_size, point_prompt, sample, sampling_plan, sha256_bytes, window
from expectrail import anchored
from expectrail.gate import anchor as paired


def visible(run, frame):
    trace = run['trace']
    step = max(trace['physicsTicksPerSecond']//60, 1)
    tick = _frame_tick(frame, step)
    rows = trace['rows']
    row = rows[tick] if tick<len(rows) else {}
    return row.get('playerVisible') if row.get('player') is not None else None


def calibration_selection(run, spec):
    frames = frame_files(Path(run['framesDir']))
    chosen = sample(sorted(frames), anchored.CALIBRATION_EVERY)[:anchored.MAX_FRAMES]
    if not spec.get('coverage', {}).get('whenPlayerVisible'):
        return chosen, []
    places = anchored._places(run['trace'], frames, chosen, anchored.PAD)
    trace = run['trace']
    step = max(trace['physicsTicksPerSecond']//60, 1)
    selected, excluded = [], []
    for n in chosen:
        why = None
        if visible(run, n) is not True:
            why = 'player is not visibly in play'
        elif 'why' in places[n]:
            why = places[n]['why']
        else:
            tick = _frame_tick(n, step)
            row = trace['rows'][tick]
            left, top, right, bottom = _frame_box(_view_at(trace['rows'], tick), row['body'])
            width, height = png_size(frames[n])
            if left<0 or top<0 or right>width or bottom>height:
                why = 'collision body is clipped by the captured image'
        if why:
            excluded.append({'frame':n, 'why':why})
        else:
            selected.append(n)
    return selected, excluded


@contextmanager
def calibration_run(run, spec):
    """Only conditional specs need a scoped calibration; image bytes/tick IDs stay exact."""
    selected, excluded = calibration_selection(run, spec)
    if not spec.get('coverage', {}).get('whenPlayerVisible'):
        yield run, anchored.CALIBRATION_EVERY, selected, excluded
        return
    with tempfile.TemporaryDirectory(prefix='expectrail-outside-calibration-') as tmp:
        root = Path(tmp)
        frames = root/'frames'
        frames.mkdir()
        original = Path(run['framesDir'])
        for n in selected:
            shutil.copyfile(original/f'f{n:08d}.png', frames/f'f{n:08d}.png')
        # Preserve capture provenance and the engine trace for the stand-in client too.
        for name in ('trace.json', 'replay.json'):
            shutil.copyfile(original.parent/name, root/name)
        yield {**run, 'framesDir':frames}, 1, selected, excluded


def question(kind, png, prompts):
    size = png_size(Path(png))
    prompt = (point_prompt if kind=='point' else box_prompt)(prompts, size)
    return kind, sha256_bytes(Path(png)), prompt


def key_digest(key):
    return hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest()


class QuestionClient:
    """Reuse only exact successful questions within one job; never cache errors or invent answers.

    For a conditional check, explicit hidden frames are not model questions. The anchored observer
    already treats a nonfatal no-answer as missing data; the unchanged evaluator excludes precisely
    those hidden frames. Nothing is written to the recording for a question that was not sent.
    """
    def __init__(self, inner, *, conditional=False):
        self.inner, self.conditional = inner, conditional
        self.model = inner.model
        self.provider = getattr(inner, 'provider', 'unknown')
        self.base = getattr(inner, 'base', '')
        self.answers, self.traces = {}, {}
        self.hits = self.skipped = 0

    @property
    def calls(self):
        return getattr(self.inner, 'calls', 0)

    def _ask(self, kind, png, prompts):
        png = Path(png)
        if self.conditional:
            path = png.parent.parent/'trace.json'
            if path not in self.traces:
                self.traces[path] = {'trace':json.loads(path.read_bytes())}
            if visible(self.traces[path], int(png.stem[1:])) is not True:
                self.skipped += 1
                raise SamError('frame is outside the check\'s in-play lifecycle', kind='not-exercised')
        key = question(kind, png, prompts)
        if key in self.answers:
            self.hits += 1
            return copy.deepcopy(self.answers[key])
        result = (self.inner.segment_at if kind=='point' else self.inner.segment_in)(png, prompts)
        self.answers[key] = copy.deepcopy(result)
        return result

    def segment_at(self, png, points):
        return self._ask('point', png, points)

    def segment_in(self, png, boxes):
        return self._ask('box', png, boxes)


def plan(project, spec, runs, *, every=1):
    """Full calibration-pass/no-error execution, from exact frame bytes and the asking algorithms."""
    route_names = sorted({name for case, name in runs})
    conditional = spec.get('coverage', {}).get('whenPlayerVisible', False)
    first = runs['pinned', route_names[0]]
    selected, excluded = calibration_selection(first, spec)
    phases, keys = [], set()
    def add(label, kind, run, indices, *, nudge=False):
        frames = frame_files(Path(run['framesDir']))
        if kind == 'box':
            from agents.sam_anchor import anchors, BODY
            places = anchors(run['trace'], png_size(next(iter(frames.values()))), indices, box=BODY, pad=anchored.PAD)
        else:
            places = anchored._places(run['trace'], frames, indices, anchored.PAD)
        asked, new, reused = [], 0, 0
        for n in indices:
            place = places[n]
            if 'why' in place or (conditional and visible(run,n) is not True):
                continue
            if kind=='point':
                point = tuple(place['point'])
                if nudge:
                    step = max(int(round(anchored.RULES['nudgePx']*(place['scale'][0] or 1.0))),1)
                    width = png_size(frames[n])[0]
                    point = (point[0]+step if point[0]+step<width else point[0]-step, point[1])
                prompts = [point]
            else:
                prompts = [tuple(place['promptBox'])]
            key = question(kind, frames[n], prompts)
            asked.append(n)
            if key not in keys:
                keys.add(key)
                new += 1
            else:
                reused += 1
        phases.append(dict(phase=label, kind=kind, frames=asked, questions=len(asked),
                           newRequests=new, reused=reused, images=new))
    # Calibration actually alternates centre/nudge; counting both sets gives the same exact key set.
    add('calibration/centre','point',first,selected)
    add('calibration/nudge','point',first,selected,nudge=True)
    for case in ['pinned',*[c['name'] for c in project.get('changes',[])]]:
        for route in route_names:
            head = runs[case,route]
            # The gate does not ask vision about an arm whose engine already fails.
            from expectrail.gate import verify
            def visual_frames(run):
                try:
                    result = verify.evaluate(spec, verify.observations(run['trace'],run['replaySha256']),
                        route=Path(route).stem, trace=run['trace'],
                        expected_frames=verify.window_frames(spec,run['trace'].get('ticks'),run['trace']))
                except Exception:
                    result = {'result':'needs-review'}  # the gate still asks vision in this case
                return [] if result['result'] in ('fail','not-applicable') else sample(window(sorted(frame_files(Path(run['framesDir']))),spec), sampling_plan(spec, every))
            add(case+'/'+route+'/head','point',head,visual_frames(head))
            if case!='pinned':
                base = runs['pinned',route]
                add(case+'/'+route+'/base','point',base,visual_frames(base))
        if case!='pinned':
            for route in route_names:
                base,head = runs['pinned',route],runs[case,route]
                indices=sample(sorted(set(frame_files(Path(base['framesDir']))) & set(frame_files(Path(head['framesDir'])))),paired.DEFAULT_EVERY)
                add(case+'/'+route+'/paired-base','box',base,indices)
                add(case+'/'+route+'/paired-head','box',head,indices)
    requests = len(keys)
    # Integer image units avoid a rounded-up/down count from a binary float price.
    cost = round(requests*USD_PER_IMAGE, 6)
    return dict(project=project['name'], commit=project['commit'], assumption=f'calibration and visual checks pass; stride {every}; every question answers on its first attempt',
        calibration=dict(frames=selected, excluded=excluded, pointQuestions=2*len(selected), rules=dict(anchored.RULES)),
        runs=[dict(variant=case,route=name,frames=len(frame_files(Path(run['framesDir']))),
                   visibleFrames=sum(visible(run,n) is True for n in frame_files(Path(run['framesDir']))),
                   engine=run['engine']) for (case,name),run in runs.items()],
        phases=phases, pointQuestions=sum(p['questions'] for p in phases if p['kind']=='point'),
        boxQuestions=sum(p['questions'] for p in phases if p['kind']=='box'),
        requests=requests, images=requests, uniqueFrameHashes=len({k[1] for k in keys}),
        listPriceUsdPerImage=USD_PER_IMAGE, listPriceUsd=cost, recommendedCapUsd=2.0,
        maxAttemptsPerQuestion=4, maxAttemptsWithoutRunCap=4*requests,
        worstRetryListPriceUsd=round(4*cost,6), attemptsAtTwoDollarCap=800,
        requestKeyDigests=sorted(key_digest(k) for k in keys))


def markdown_plan(doc):
    lines = ['\n**No-model request plan; conditional on calibration passing, with no retries.**',
             f"Project `{doc['project']}`; {doc['requests']} requests / {doc['images']} image submissions, "
             f"${doc['listPriceUsd']:.4f} at the repository's list price. Recommended cap $2.00.",
             f"Calibration frame IDs: {doc['calibration']['frames']} (two distinct point questions each).",
             '| Phase | Kind | Logical questions | New requests / images | Exact reuses |',
             '| --- | --- | ---: | ---: | ---: |']
    for phase in doc['phases']:
        lines.append(f"| {phase['phase']} | {phase['kind']} | {phase['questions']} | {phase['newRequests']} | {phase['reused']} |")
    lines += [f"The client permits up to {doc['maxAttemptsPerQuestion']} tries per question. "
              f"Worst retry cost without a run cap is ${doc['worstRetryListPriceUsd']:.4f}; "
              'the $2.00 cap stops before attempt 801. Failed attempts count too. This is a plan, not spend evidence.']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    import argparse
    from tools import outside_trial, outside_vision
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, choices=[p['name'] for p in outside_trial.load_list()])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--digest', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    project = next(p for p in outside_trial.load_list() if p['name']==args.project)
    _path, spec, runs = outside_vision.preflight(project, args.data, args.digest)
    doc = plan(project, spec, runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2)+'\n')
    print(markdown_plan(doc))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
