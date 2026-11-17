"""One offline review document. Its only export is a person's unanswered/answered decisions, never approvals."""
import base64
import hashlib
import json
from html import escape

from expectrail import viewer

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f3f4ee;color:#19362e;font:16px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:32px 20px 70px}h1{font-size:clamp(30px,5vw,46px);line-height:1.12}
h2{margin-top:36px}h3{margin:0 0 10px}header>p{max-width:740px}.tag{font-weight:650;color:#4c655b}
article{background:#fff;border:1px solid #cbd4ca;padding:22px;margin:16px 0;border-radius:12px}
.samples{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}figure{margin:8px 0}
img{display:block;max-width:100%;height:auto}.sprite img,.sprite svg{max-height:96px;image-rendering:pixelated}
.stage{position:relative;overflow:hidden}.snapshot{display:block;width:100%;height:auto}.sprite .snapshot{width:auto;max-width:100%}.stage img{width:100%}.stage svg:not(.snapshot){position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
figcaption,.muted{font-size:14px;color:#53685d}.facts{display:grid;grid-template-columns:150px 1fr;gap:7px 14px}
dt{font-weight:650}dd{margin:0}.choice{display:flex;gap:18px;margin-top:18px;padding-top:14px;border-top:1px solid #e2e7df}
label{cursor:pointer}input[type=radio]{accent-color:#16684e}input[type=text]{font:inherit;padding:10px;border:1px solid #849b8f;border-radius:5px}
button{font:inherit;font-weight:650;background:#155b46;color:white;padding:12px 18px;border:0;border-radius:5px;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}.notice{background:#fff5d8;border-left:4px solid #cb922d;padding:14px 18px}
.bad{color:#923329}.result{padding:10px 0;border-top:1px solid #e2e7df}.result figure{max-width:240px}
footer{margin-top:32px;padding:24px;background:#e4ebe0;border-radius:10px}code{overflow-wrap:anywhere}
@media(max-width:600px){.samples{grid-template-columns:1fr}.facts{grid-template-columns:1fr}main{padding:20px 14px}}
"""
JS = r"""
(function(){
'use strict';
const info=JSON.parse(document.getElementById('review-data').textContent);
const openedAt=new Date().toISOString();
const selected={objects:Object.create(null),checks:Object.create(null)};
const status=document.getElementById('save-status');
document.querySelectorAll('input[data-kind]').forEach(function(input){
 input.addEventListener('change',function(){selected[input.dataset.kind][input.dataset.key]=input.value==='yes';});
});
document.getElementById('save-answers').addEventListener('click',function(){
 const person=document.getElementById('person-name').value.trim();
 if(info.example){status.textContent='This example cannot approve project files. Generate a review on your own local project.';return;}
 if(!person){status.textContent="Enter the person's name before saving answers.";return;}
 for(const kind of ['objects','checks']){
  for(const key of info[kind]){if(typeof selected[kind][key]!=='boolean'){status.textContent='Answer yes or no for every object and draft check first.';return;}}
 }
 const answers={format:'expectrail.onboard-answers/v1',reviewFile:info.reviewFile,reviewSha256:info.reviewSha256,
  person:person,openedAt:openedAt,answeredAt:new Date().toISOString(),objects:selected.objects,checks:selected.checks};
 const url=URL.createObjectURL(new Blob([JSON.stringify(answers,null,2)+'\n'],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='expectrail-review-answers.json';link.click();
 setTimeout(function(){URL.revokeObjectURL(url);},0);
 status.textContent='Answers saved. No project file was changed. A person can now run the command below.';
});
})();
"""


def choice(kind, key, *, allowed=True):
    key=escape(key,quote=True)
    return (f'<div class="choice" role="group" aria-label="Review {key}">'
            f'<label><input type="radio" name="{kind}-{key}" data-kind="{kind}" data-key="{key}" value="yes" '
            + ('' if allowed else 'disabled ') + '> Yes</label>'
            f'<label><input type="radio" name="{kind}-{key}" data-kind="{kind}" data-key="{key}" value="no"> No — revise it</label></div>')


def figure(state, frame, label, *, boxes=False, images=None):
    if not frame:return '<p class="muted">No measured frame available.</p>'
    if frame.get('mime') == 'image/webp':
        from expectrail.onboard_review import native_sprite_bytes
        raw = native_sprite_bytes(state,frame)
        if raw is None:return '<p class="muted">The saved sprite is missing or changed.</p>'
        source = 'data:image/webp;base64,' + base64.b64encode(raw).decode()
        return (f'<figure><img src="{source}" alt="{escape(label,quote=True)}">'
                f'<figcaption>{escape(label)}</figcaption></figure>')
    raw=viewer._frame_bytes(state,frame)
    if raw is None:return '<p class="muted">The saved frame is missing or changed.</p>'
    data={**frame,'path':'data:image/png;base64,'+base64.b64encode(raw).decode()}
    overlay={'engine':frame.get('engineBox'),'observer':frame.get('observerBox')} if boxes else None
    return viewer.frame_figure(data,label,single_file=True,boxes=overlay,images=images)


def render(record, details, state, review_file, review_sha, *, example=False):
    images={}
    payload={'reviewFile':str(review_file),'reviewSha256':review_sha,'example':example,
             'objects':[o['role'] for o in record['objects']],
             'checks':[s['id'] for s in record['specs'] if not s['approved']]}
    script_hash=base64.b64encode(hashlib.sha256(JS.encode()).digest()).decode()
    csp=("default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'sha256-"+script_hash+
         "'; connect-src 'none'; base-uri 'none'; form-action 'none'")
    parts=['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f'<meta http-equiv="Content-Security-Policy" content="{escape(csp,quote=True)}">',
           f'<title>Review {escape(details["project"])} · Expectrail</title><style>{CSS}</style></head><body><main>',
           f'<header><p class="tag">Expectrail · onboarding review</p><h1>Does this describe your game?</h1>',
           f'<p>Review the objects and checks for <strong>{escape(details["project"])}</strong>. '
           'Choose yes only when the binding and expectation are right. No approval is applied by this page.</p></header>']
    if example:parts.append('<p class="notice">Read-only example from public trial inputs. No decisions can be applied from this copy. Generate a local review to approve your own files.</p>')
    parts.append('<p class="notice">Orange boxes are the engine\'s measurements, not proof of what was drawn. Cyan boxes, when present, are recorded observer answers. '
                 +escape(details['observer'])+'. No live observer is called.</p><h2>1. Objects</h2>')
    for obj in details['objects']:
        parts.append(f'<article data-object="{escape(obj["role"],quote=True)}"><h3>{escape(obj["role"].replace("_"," "))}</h3>'
                     f'<p>Binding: {escape(obj["selector"])}.</p><p>Prompt: {escape(obj["prompt"] or "No observer prompt supplied")}</p><div class="sprite">'
                     +figure(state,obj['sprite'],'Sprite / clean replay crop',images=images)+'</div><div class="samples">')
        for sample in obj['samples']:
            score='No recorded observer answer' if sample['score'] is None else f'Recorded observer score {sample["score"]:.3f}'
            parts.append(figure(state,sample,f'Frame {sample["frame"]} · {score}',boxes=True,images=images))
        for _ in range(3-len(obj['samples'])):parts.append('<figure><p class="muted">Measured frame unavailable; this object cannot yet be confirmed.</p></figure>')
        parts.append('</div><p>Is this the right object and sprite?</p>'+choice('objects',obj['role'],allowed=obj['reviewable'])+'</article>')
    parts.append('<h2>2. Checks</h2>')
    if not details['checks']:parts.append('<p>No draft checks were supplied. Object review alone does not prove a change is safe.</p>')
    for row in details['checks']:
        parts.append(f'<article data-check="{escape(row["id"],quote=True)}"><h3>{escape(row["sentence"])}</h3><dl class="facts">')
        for label,key in [('Object','object'),('Region or condition','condition'),('Window and coverage','window'),('Pass looks like','pass'),('Fail looks like','fail')]:
            parts.append(f'<dt>{label}</dt><dd>{escape(row[key])}</dd>')
        parts.append('</dl>')
        if not row['results']:parts.append('<p class="notice">No clean or broken-copy replay was supplied. No detection result is claimed.</p>')
        for result in row['results']:
            first=result['firstFrame']; words=f'First failing frame: {first}.' if first is not None else 'No failing frame (not a pass when unexercised or missing data).'
            parts.append(f'<div class="result"><strong>{escape(result["copy"])}: {escape(result["result"])}</strong> '
                         +escape(words)+f'<p>{escape(result["reason"])}</p><p class="muted">{escape(result["source"])}</p>'
                         +figure(state,result['image'],f'{result["copy"]}, first failing frame {first}',images=images)+'</div>')
        parts.append('<p>Already approved; no new decision is requested.</p>' if row['approved'] else '<p>Should this check hold?</p>'+choice('checks',row['id']))
        parts.append('</article>')
    parts.append('<h2>3. What ran</h2><ul>')
    for stage in details['timing']['stages']:
        parts.append(f'<li>{escape(stage["name"])}: {escape(stage["status"])}'
                     +(f' — {escape(stage["reason"])}' if stage['reason'] else '')+'</li>')
    parts.append(f'</ul><p>Machine time to review-ready: {details["timing"]["machineSeconds"]:.2f} seconds. '
                 'Human time is not measured until a person opens the page and submits answers.</p>')
    parts.append('<footer><h2>Save your answers</h2><p>This saves an answers file only. It cannot write project config or approvals.</p>'
                 '<label for="person-name">Your name</label><br><input id="person-name" type="text" maxlength="200" autocomplete="name" placeholder="Person reviewing this page"> '
                 '<button id="save-answers" type="button">Save review answers</button><p id="save-status" role="status"></p>'
                 '<p>Then a person runs:</p><code>expectrail onboard --approve expectrail-review-answers.json</code></footer>')
    parts.append('<script id="review-data" type="application/json">'+viewer._json_for_script(payload)+'</script>')
    parts.append('<script>'+JS+'</script></main></body></html>')
    return '\n'.join(parts)+'\n'
