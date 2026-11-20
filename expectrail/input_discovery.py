"""Conservative menu/pointer route planning from saved hints and engine evidence.

Saved scripts are hints, not proof of control. Only an opt-in disposable harness
probe supplies live button geometry/connections. Nothing here approves a check.
"""
from __future__ import annotations
import json
import re
import shutil
import tempfile
from pathlib import Path
from expectrail import route

START = {'start', 'play', 'begin', 'newgame'}
CONTROL_ONLY = {'pause', 'menu', 'ui_cancel', 'ui_focus_next', 'ui_focus_prev'}


def words(value):
    return set(re.findall(r'[a-z]+', re.sub(r'([a-z])([A-Z])', r'\1_\2', value).lower()))


def pointer_reads(source):
    # Remove comments and all quoted strings (including multiline strings) before
    # looking for a call. A comment/instruction is never steering evidence.
    code = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[^\n]*', '', source)
    return bool(re.search(r'\bget_(?:global_)?mouse_position\s*\(', code))


def hints(root, nodes, players, actions, fallback):
    from expectrail.onboarding import resource
    pointers, starts, menus = [], [], []
    for path, node in nodes.items():
        if path in players and node.get('script'):
            source = resource(root, node['script']).read_text(encoding='utf-8-sig')
            if pointer_reads(source):
                pointers.append({'node': path or '.', 'script': node['script']})
        if node.get('type') not in ('Button', 'TextureButton', 'LinkButton', 'CheckButton', 'CheckBox'):
            continue
        label = words(node.get('text', '') + ' ' + node.get('name', ''))
        if label & START:
            starts.append(path)
        parts = words(path)
        if 'menu' in parts and not (parts & {'pause', 'resume'}):
            menus.append(path)
    # Built-in fallback arrows are not authored movement bindings.
    return {'pointer': pointers if fallback or not any(route.is_movement(a) for a in actions) else [],
            'startControls': starts, 'menus': menus}


def needed(info):
    h = info.get('inputHints', {})
    return bool(h.get('pointer') or h.get('startControls') or h.get('menus') or
                (set(info['actions']) and set(info['actions']) <= CONTROL_ONLY))


def probe(root, info, *, replay=None):
    """Read real root-viewport buttons at tick 9; retain failure diagnostics."""
    from expectrail.contracts import validate
    if replay is None:
        from harness.run import run
        replay = run
    work = Path(tempfile.mkdtemp(prefix='expectrail-input-probe-'))
    candidate = work / 'probe.json'
    candidate.write_text(json.dumps({'format':'expectrail.route/v0','name':'input-probe',
                                     'seed':1,'ticks':10,'events':[]}) + '\n')
    try:
        replay(candidate, work/'replay', game=Path(root), capture_frames=False, input_probe=True)
        trace = json.loads((work/'replay/trace.json').read_text())
        validate(trace, 'trace')
        result = trace.get('inputProbe')
        if result is None:
            raise ValueError('engine did not report input controls')
    except (SystemExit, OSError, ValueError) as exc:
        # Keep the named log, not an ephemeral path. Never preserve a game copy.
        for folder in ('work', 'frames', 'sandbox'):
            shutil.rmtree(work/'replay'/folder, ignore_errors=True)
        (work/'failure.txt').write_text(str(exc) + '\n')
        raise ValueError(f'cannot inspect live start controls: {exc}; diagnostics kept at {work / "failure.txt"}') from exc
    shutil.rmtree(work)
    return result


def choose_start(report, *, menu_expected):
    """One visible enabled start-labelled button with a matching pressed handler.

    A label alone is insufficient. Ambiguous, truncated or unsupported evidence
    refuses; no hard-coded project name, tree path or screen position is used.
    """
    shown = [b for b in report['buttons'] if b['visible']]
    candidates = []
    width, height = report['viewport']
    for b in shown:
        left, top, right, bottom = b['box']
        if (b['enabled'] and words(b['path'].rsplit('/',1)[-1]+' '+b['text']) & START
                and len(b['connections']) == 1
                and words(b['connections'][0]['method']) & START
                and 0 <= left < right <= width and 0 <= top < bottom <= height):
            candidates.append(b)
    found = '; '.join(f"{b['path']} ({b['text']!r}, {'visible' if b['visible'] else 'hidden'}, "
                      f"{'enabled' if b['enabled'] else 'disabled'}, "
                      f"pressed → {', '.join(c['target']+':'+c['method'] for c in b['connections']) or 'no connection'})"
                      for b in report['buttons']) or 'no controls'
    if report['truncated'] or len(candidates) > 1:
        raise ValueError(f'cannot tell which control starts play; found {found}; probe may be truncated')
    if candidates:
        return candidates[0]
    if report['paused'] or (menu_expected and shown):
        raise ValueError(f'cannot tell which control starts play; found {found}. Supply a reviewed start route.')
    return None


def plan(root, info, *, probe_fn=None):
    actions, rate = info['actions'], info['physicsTicksPerSecond']
    if not needed(info):
        return route.make_route(actions, rate)
    measured = (probe_fn or probe)(root, info)
    h = info.get('inputHints', {})
    start = choose_start(measured, menu_expected=bool(h.get('startControls') or h.get('menus')))
    events, lead = [], measured['tick'] + 3
    width, height = measured['viewport']
    point = [width/2, height/2]
    if start:
        l,t,r,b = start['box'];point = [(l+r)/2,(t+b)/2]
        events = [{'tick':lead,'pointer':{'position':point}},
                  {'tick':lead+1,'pointer':{'position':point,'button':'left','pressed':True}},
                  {'tick':lead+2,'pointer':{'position':point,'button':'left','pressed':False}}]
        lead += 5
    if h.get('pointer'):
        # Smooth per-tick movement avoids a large acceleration jump in controllers
        # that steer toward the pointer. Coordinates come only from the viewport.
        tick = lead
        for x in (0.1, 0.9, 0.1, 0.9, 0.5):
            target = [round(width*x,3), round(height*0.8,3)]
            previous = point
            for n in range(1,rate+1):
                point = [round(a+(b-a)*n/rate,3) for a,b in zip(previous,target)]
                events.append({'tick':tick,'pointer':{'position':point}});tick += 1
            tick += max(1,rate//4)
        ticks = tick + max(1,rate//4)
        description = 'Draft pointer sweep from script hints and engine viewport; replay must demonstrate movement.'
    else:
        useful = [a for a in actions if a not in CONTROL_ONLY]
        if not useful:
            found = ', '.join(b['path'] for b in measured['buttons']) or 'no controls'
            raise ValueError(f'inputs {", ".join(actions)} do not exercise play; found {found}. '
                             'No movement/pointer control was found; supply a route. No pause-only route was written.')
        doc = route.make_route(useful,rate)
        events += [dict(e,tick=e['tick']+lead) for e in doc['events']]
        ticks = doc['ticks']+lead
        description = 'Draft input route after an engine-measured start control; replay before use.'
    if start:
        c = start['connections'][0]
        description += f" Start: {start['path']}, pressed → {c['target']}:{c['method']}, viewport {events[0]['pointer']['position']}."
    return {'format':'expectrail.route/v0','name':'auto-input-map','seed':1,
            'description':description,'ticks':ticks,'events':events}


def project_plan(root, actions, rate, fallback):
    """Legacy input-only stand-ins without an entry scene retain their old plan."""
    from expectrail import onboarding, project_config
    text = (Path(root)/'project.godot').read_text(encoding='utf-8-sig')
    if not (Path(root)/project_config.FILENAME).exists() and not re.search(r'^\s*run/main_scene\s*=',text,re.M):
        return route.make_route(actions,rate)
    info = onboarding.inspect(root)
    # Config actions are authoritative for replay; saved authored actions remain
    # the hints used to tell built-in fallback from real movement bindings.
    info.update(actions=actions,physicsTicksPerSecond=rate,builtInActions=fallback)
    return plan(root,info)
