"""The app's only asset, included in the wheel. No external scripts, styles or fonts."""
PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Expectrail — verify a change</title>
<style nonce="__NONCE__">
:root{font-family:system-ui,sans-serif;color:#182c29;background:#f4f6f1;line-height:1.55}
*{box-sizing:border-box}body{margin:0}main{max-width:900px;margin:auto;padding:32px 24px 64px}
h1{font-size:2rem;line-height:1.2}h2{font-size:1.25rem}section{background:white;padding:24px;margin:20px 0;border:1px solid #ccd5cb;border-radius:12px}
label{display:block;font-weight:600;margin:16px 0 6px}input,select{width:100%;font:inherit;border:1px solid #687d74;border-radius:5px;padding:10px;min-width:0}
input[type=checkbox]{width:auto}
button{font:inherit;font-weight:600;background:#175c47;color:white;border:2px solid #175c47;border-radius:6px;padding:10px 18px;margin:16px 12px 0 0;cursor:pointer}
button.secondary{background:white;color:#175c47}button:disabled{opacity:.55;cursor:default}a{color:#175c47}a:focus,button:focus,input:focus{outline:3px solid #b35c12;outline-offset:3px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.note{color:#475a53}#result-text{font-size:1.2rem;font-weight:600}#details,#inspection,#rendering{white-space:pre-wrap;overflow-wrap:anywhere}
[hidden]{display:none!important}summary{cursor:pointer}#error{color:#8e251c;font-weight:600}li{margin:5px 0;overflow-wrap:anywhere}
@media(max-width:600px){main{padding:16px 12px 36px}section{padding:16px}.grid{grid-template-columns:1fr;gap:0}h1{font-size:1.65rem}button{width:100%;margin-right:0}}
</style></head><body><main>
<p class="note">Expectrail · Local verification</p><h1>Verify a change to your game</h1>
<p>Compare two folders on this computer. This first version supports Godot projects with existing routes and approved checks.</p>
<section aria-labelledby="project-heading"><h2 id="project-heading">1. Your project and versions</h2>
<p>Choose a copy from before the change and a copy from after it. Both must have the same folder layout.
For your own checks, the routes and approvals come from <strong>Before</strong>. Expectrail does not change these folders.</p>
<div class="grid"><div><label for="before">Before: full folder path</label><input id="before" placeholder="/Users/you/MyGame-before" autocomplete="off" spellcheck="false"></div>
<div><label for="after">After: full folder path</label><input id="after" placeholder="/Users/you/MyGame-after" autocomplete="off" spellcheck="false"></div></div>
<p>Each folder contains <code>project.godot</code> and <code>expectrail.project.json</code>.
The config names the routes and checks. A draft config cannot give an accept.
The kinematic-character example uses the same config path as your project.</p>
<details id="paths"><summary>Older projects without a config</summary>
<label><input type="checkbox" id="manual"> Enter paths manually</label>
<p>For an existing checkout with routes and checks. Paths are relative to each version's folder.</p>
<label for="game">Game folder</label><input id="game" value="." spellcheck="false">
<label for="routes">Route files (patterns separated by spaces or commas)</label><input id="routes" value="routes/*.json" spellcheck="false">
<label for="specs">Checks folder</label><input id="specs" value="specs" spellcheck="false"></details>
<button id="inspect" class="secondary" type="button">Check folders</button><p id="inspection" role="status"></p></section>
<section aria-labelledby="run-heading"><h2 id="run-heading">2. Verify</h2>
<p>Uses the same verifier as the Expectrail command. Only run games you trust.</p>
<label><input id="auto-fix" type="checkbox"> Try to fix the game if verification rejects it</label>
<div id="repair-settings" class="grid" hidden>
<div><label for="fix-agent">Fixer</label><select id="fix-agent"><option value="llm-patch">llm-patch (bounded provider requests)</option><option value="muse-code">Muse (live bound unavailable; stops for review)</option></select></div>
<div><label for="attempts">Maximum fix attempts (1 to 10)</label><input id="attempts" type="number" min="1" max="10" value="3"></div>
<div><label for="usd-cap">Maximum fixer spend in US dollars</label><input id="usd-cap" type="number" min="0" step="any"></div>
</div>
<p id="rendering" role="status"></p>
<button id="verify" type="button">Verify</button><button id="cancel" type="button" class="secondary" disabled>Cancel</button>
<p id="progress" role="status">No verification has started.</p><ol id="phases" aria-label="Recorded phases"></ol>
<p id="error" role="alert" hidden></p></section>
<section aria-labelledby="result-heading"><h2 id="result-heading">3. Result</h2>
<p id="result-text" role="status">No result yet.</p><p id="next-step"></p><p id="judged-by"></p><p id="details"></p>
<a id="repair-record" target="_blank" rel="noopener noreferrer" hidden>Open repair record</a>
<a id="report" target="_blank" rel="noopener noreferrer" hidden>Open this job's existing report</a>
<div id="evidence-viewer"><h3>Evidence viewer</h3><a id="viewer" target="_blank" rel="noopener noreferrer" hidden>Open this job's evidence viewer</a><p id="viewer-note" class="note">Available when a job from this app session finishes.</p></div>
</section>
<section aria-labelledby="past-heading"><h2 id="past-heading">Past runs</h2>
<p>Newest first. Runs from earlier app sessions show their recorded result, but their reports and viewer files cannot be opened in this session.</p>
<button id="refresh" class="secondary" type="button">Refresh past runs</button><p id="past-note" role="status"></p><ol id="past-runs"></ol>
</section></main>
<script nonce="__NONCE__">
'use strict';
const token = '__TOKEN__';
try { sessionStorage.setItem('expectrail-token', token); } catch (_) {}
history.replaceState(null, '', '/');
const el = id => document.getElementById(id);
const values = () => ({projectConfig:!el('manual').checked,...Object.fromEntries((el('manual').checked?['before','after','game','routes','specs']:['before','after']).map(id => [id,el(id).value]))});
el('auto-fix').onchange=()=>{el('repair-settings').hidden=!el('auto-fix').checked;};
let job = null, busy = false, rendererAcknowledged = null;
for(const input of document.querySelectorAll('input,select')) input.addEventListener('input',()=>{
  rendererAcknowledged=null; el('rendering').textContent=''; if(!job)el('verify').textContent='Verify';
});
function rendering(data) {
  return data.rendering ? [data.rendering.message,data.rendering.fix].filter(Boolean).join('\n') : '';
}
const phaseNames = {queued:'Waiting to start',preparing:'Checking inputs and tools',executing:'Running the game',
  observing:'Reading observations',evaluating:'Evaluating checks',completed:'Finished',failed:'Failed',cancelled:'Cancelled'};
function controls(active) {
  busy=active;
  el('verify').disabled=active; el('inspect').disabled=active; el('cancel').disabled=!active || !job;
  for (const id of ['manual','before','after','game','routes','specs','auto-fix','attempts','usd-cap','fix-agent']) el(id).disabled=active;
}

async function api(path, body) {
  const options = {method:body===undefined?'GET':'POST', headers:{'X-Expectrail-Token':token}};
  if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
  const response=await fetch(path,options), data=await response.json();
  if(!response.ok) throw new Error(data.detail || 'The request could not be carried out.');
  return data;
}
function problem(error) {
  el('error').textContent=error.message; el('error').hidden=false;
  el('result-text').textContent='Could not be carried out — no result is available here.';
  el('next-step').textContent = job ? 'Use Retry status to reconnect, or Cancel to stop the job.'
    : 'Read the message above, check the folders, and try again. Check Past runs if a job may have started.';
  el('details').textContent='';
  el('viewer-note').hidden=true;
  el('repair-record').hidden=true; el('report').hidden=true; el('viewer').hidden=true; el('judged-by').textContent='';
  // Losing the connection does not cancel a worker. Keep its controls so it can be recovered.
  controls(Boolean(job)); el('verify').textContent=job?'Retry status':'Verify'; el('verify').disabled=false;
}
const screens = {
  queued: ['Waiting to start', 'Keep this page open. Use Cancel if you no longer want to verify this change.'],
  running: ['Verification is running', 'Follow the progress above, or use Cancel to stop this run.'],
  cancelled: ['Verification cancelled', 'Choose Verify whenever you are ready to try again.'],
  failed: ['Verification stopped unexpectedly', 'Read the details below, then try Verify again. If it stops again, share the details with your project maintainer.'],
  'could-not-be-carried-out': ['Verification could not be carried out', 'Follow the instructions below, then choose Verify again.'],
  accept: ['Accept', 'Open the evidence to see which routes and checks passed.'],
  reject: ['Reject', 'Open the evidence to see what failed. Try Verify again after fixing the change.'],
  'needs-review': ['Needs review', 'Open the evidence and read what was left unchecked before deciding what to do with the change.']
};
function show(data) {
  el('error').hidden=true;
  el('progress').textContent=phaseNames[data.phase] || 'Status unavailable';
  el('phases').replaceChildren(...data.history.map(entry=>{const li=document.createElement('li');li.textContent=phaseNames[entry.phase] || entry.phase;return li;}));
  const [title, next] = screens[data.screen];
  el('result-text').textContent = ['accept','reject','needs-review'].includes(data.screen) ? data.summary : title;
  if (['cancelled','failed','could-not-be-carried-out'].includes(data.screen)) {
    el('result-text').textContent += ' — no verdict was reached.';
  }
  const active = data.state === 'running';
  el('next-step').textContent = active && !data.sessionOwned
    ? 'Refresh past runs to check for an update. This run belongs to another app session.'
    : active || !['accept','reject','needs-review'].includes(data.screen) || data.viewer || data.report
      ? next : 'Read the saved result and details below. Start a new verification to get evidence you can open here.';
  el('judged-by').textContent=data.judgedBy;
  el('details').textContent=[...data.reasons,...data.diagnostics.flatMap(d=>[d.detail,d.fix])].filter((s,i,a)=>s&&a.indexOf(s)===i).join('\n');
  el('repair-record').hidden=!data.repairUrl;
  if(data.repairUrl) el('repair-record').href=data.repairUrl;
  el('report').hidden=!data.report;
  if(data.report) el('report').href=data.report;
  el('viewer').hidden=!data.viewer;
  if(data.viewer) el('viewer').href=data.viewer;
  el('viewer-note').hidden=Boolean(data.viewer);
  el('viewer-note').textContent=data.sessionOwned?'Available when this job finishes.':'This job was created in an earlier app session; its files cannot be opened here.';
  if(data.repairRunning) el('cancel').disabled=true;
  if(data.state!=='running' && !data.repairRunning){job=null;controls(false);el('verify').textContent='Verify';}
}
async function poll() {
  const current=job;if(!current)return;
  try {const data=await api('/api/jobs/'+current);if(job!==current)return;show(data);if(job)setTimeout(poll,500);else await pastRuns();}
  catch(error){if(job===current)problem(error);}
}
el('inspect').onclick=async()=>{
  el('error').hidden=true; controls(true);
  try {const body=values(), lines=[];
    for(const side of ['before','after']){const data=await api('/api/inspect',{...body,side,folder:body[side]});
      lines.push(side==='before'?'Before (checks used for this run)':'After',
        data.godot?'Godot project found.':'No Godot project found.',
        `${data.routes} usable routes; ${data.checks} approved checks; ${data.drafts} draft checks.`,
        ...(data.routeNames||[]).map(name=>'Route: '+name), ...(data.checkNames||[]).map(name=>'Check: '+name),data.help,rendering(data),...data.problems,'');}
    el('inspection').textContent=lines.join('\n');
  }catch(error){problem(error);} finally{controls(false);}
};
el('verify').onclick=async()=>{
  if(job){controls(true);el('verify').textContent='Verify';await poll();return;}
  el('error').hidden=true;el('repair-record').hidden=true;el('report').hidden=true;el('viewer').hidden=true;el('judged-by').textContent='';el('details').textContent='';el('next-step').textContent='';el('phases').replaceChildren();
  el('result-text').textContent='No verdict yet.';el('progress').textContent='Checking the rendering environment before starting…';controls(true);
  try{const body=values();
    if(el('auto-fix').checked){
      body.autoFix=true;body.repairAgent=el('fix-agent').value;body.attempts=el('attempts').valueAsNumber;body.usdCap=el('usd-cap').valueAsNumber;
      if(!Number.isInteger(body.attempts)||body.attempts<1||body.attempts>10) throw new Error('Enter 1 to 10 fix attempts.');
      if(!Number.isFinite(body.usdCap)||body.usdCap<0) throw new Error('Enter a fixer spend cap of zero or more US dollars.');
    }
    if(body.projectConfig){
      const inspection=await api('/api/inspect',{...body,side:'before',folder:body.before});
      el('rendering').textContent=rendering(inspection);
      const signature=JSON.stringify([body,inspection.rendering]);
      if(inspection.rendering?.warning && rendererAcknowledged!==signature){
        rendererAcknowledged=signature;controls(false);el('verify').textContent='Verify with this warning';
        el('progress').textContent='Nothing has started. Read the rendering warning above before continuing.';return;
      }
    }
    rendererAcknowledged=null;el('verify').textContent='Verify';
    el('progress').textContent='Creating the job and recording its inputs…';
    const data=await api('/api/jobs',body);job=data.id;controls(true);show(data);if(job)await poll();else await pastRuns();}
  catch(error){problem(error);}
};
el('cancel').onclick=async()=>{
  const current=job;if(!current)return;el('cancel').disabled=true;
  try{const data=await api('/api/jobs/'+current+'/cancel',{});if(job===current){show(data);await pastRuns();}}
  catch(error){if(job===current)problem(error);}
};
async function pastRuns() {
  try {
    const data=await api('/api/history');
    el('past-note').textContent=data.jobs.length?'':'No runs in this job store yet.';
    el('past-runs').replaceChildren(...data.jobs.map(row=>{
      const li=document.createElement('li'), detail=document.createElement('p'), open=document.createElement('a');
      detail.textContent=`${row.createdAt} — ${row.summary} Before: ${row.before || 'None'}. After: ${row.after}.`;
      open.textContent='Open run';open.href='#result-heading';
      open.onclick=event=>{
        if(busy || job){event.preventDefault();el('past-note').textContent='Finish or cancel the current run before opening another.';return;}
        job=row.sessionOwned && (row.state==='running' || row.repairRunning)?row.id:null;
        show(row);controls(Boolean(job));if(job)poll();
      };
      li.append(detail,open);return li;
    }));
  }catch(error){el('past-note').textContent='Past runs could not be read: '+error.message;}
}
el('refresh').onclick=pastRuns;
pastRuns();
</script></body></html>'''
