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
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.note{color:#475a53}#result-text{font-size:1.2rem;font-weight:600}#details,#inspection,#rendering,#error{white-space:pre-wrap;overflow-wrap:anywhere}
.folder-entry{display:flex;flex-wrap:wrap;gap:8px}.folder-entry button{margin:0;padding:8px 12px}.folder-entry input{flex:1 1 10rem}
.folder-feedback{overflow-wrap:anywhere;color:#475a53}
#result-folders dt{font-weight:600}#result-folders dd{margin:0 0 .5em;overflow-wrap:anywhere}
[hidden]{display:none!important}summary{cursor:pointer}#error{color:#8e251c;font-weight:600}li{margin:5px 0;overflow-wrap:anywhere}
@media(max-width:600px){main{padding:16px 12px 36px}section{padding:16px}.grid{grid-template-columns:1fr;gap:0}h1{font-size:1.65rem}button{width:100%;margin-right:0}}
</style></head><body><main>
<p class="note">Expectrail · Local verification</p><h1>Verify a change to your game</h1>
<p>Compare two folders on this computer. This first version supports Godot projects with existing routes and approved checks.</p>
<section aria-labelledby="project-heading"><h2 id="project-heading">1. Your project and versions</h2>
<p>Choose a copy from before the change and a copy from after it. Both must have the same folder layout.
For your own checks, the routes and approvals come from <strong>Before</strong>. Checking folders and verifying leave your source files unchanged.</p>
<p id="drop-help" hidden>Drop one project folder on Before or After, then select it in the desktop dialog to confirm its full path.</p>
<div class="grid"><div data-folder-side="before"><label for="before">Before: full folder path or project.godot file path</label>
<div class="folder-entry"><button id="choose-before" type="button">Choose Before folder</button>
<input id="before" autocomplete="off" spellcheck="false" aria-describedby="before-feedback"></div>
<div id="recent-before-group" hidden><label for="recent-before">Recent Before folders</label>
<select id="recent-before"></select></div>
<div id="before-feedback" class="folder-feedback" role="status"></div></div>
<div data-folder-side="after"><label for="after">After: full folder path or project.godot file path</label>
<div class="folder-entry"><button id="choose-after" type="button">Choose After folder</button>
<input id="after" autocomplete="off" spellcheck="false" aria-describedby="after-feedback"></div>
<div id="recent-after-group" hidden><label for="recent-after">Recent After folders</label>
<select id="recent-after"></select></div>
<div id="after-feedback" class="folder-feedback" role="status"></div></div></div>
<div id="folder-pair-feedback" class="folder-feedback" role="status"></div>
<div id="before-suggestion" class="folder-feedback" hidden>
<p><span id="suggestion-source"></span> <strong id="suggested-folder"></strong></p>
<button id="use-before" type="button" class="secondary" aria-describedby="suggested-folder">Use as Before</button></div>
<div id="previous-option" class="folder-feedback" hidden>
<p id="previous-help">Use a temporary copy from one commit before the current Git commit (its first parent).
After stays in your working folder, including edits you haven’t committed.</p>
<button id="use-previous" type="button" class="secondary" aria-describedby="previous-help">Use previous commit as Before</button></div>
<p>Each folder needs <code>project.godot</code>. If <code>expectrail.project.json</code> is missing, check the folder to review and save a draft setup.
The config names the routes and checks. A draft config cannot give an accept.
The kinematic-character example uses the same config path as your project.</p>
<details id="paths"><summary>Older projects without a config</summary>
<label><input type="checkbox" id="manual"> Enter paths manually</label>
<p>For an existing checkout with routes and checks, enter folder paths for Before and After. The paths below are relative to each folder.</p>
<label for="game">Game folder</label><input id="game" value="." spellcheck="false">
<label for="routes">Route files (patterns separated by spaces or commas)</label><input id="routes" value="routes/*.json" spellcheck="false">
<label for="specs">Checks folder</label><input id="specs" value="specs" spellcheck="false"></details>
<button id="inspect" class="secondary" type="button">Check folders</button><div id="inspection" role="status"><div id="inspection-before"></div><div id="inspection-after"></div></div></section>
<section aria-labelledby="run-heading"><h2 id="run-heading">2. Verify</h2>
<p>Uses the same verifier as the Expectrail command. Only run games you trust.</p>
<label><input id="isolated" type="checkbox"> Require the replay sandbox</label>
<p class="note">When selected, verification stops if the sandbox is unavailable.
Otherwise the verifier can run outside the sandbox and explains this in the result.</p>
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
<p id="result-text" role="status">No result yet.</p>
<dl id="result-folders" hidden><dt>Before folder</dt><dd id="result-before"></dd><dt>After folder</dt><dd id="result-after"></dd></dl>
<p id="next-step"></p><p id="judged-by"></p><p id="isolation" hidden></p><p id="details"></p>
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
const values = () => ({executionClass:el('isolated').checked?'isolated':'diagnostic',projectConfig:!el('manual').checked,...Object.fromEntries((el('manual').checked?['before','after','game','routes','specs']:['before','after']).map(id => [id,el(id).value]))});
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
  for (const id of ['manual','choose-before','before','recent-before','use-before','use-previous','choose-after','after','recent-after','game','routes','specs','auto-fix','attempts','usd-cap','fix-agent','isolated']) el(id).disabled=active;
}

async function api(path, body) {
  const options = {method:body===undefined?'GET':'POST', headers:{'X-Expectrail-Token':token}};
  if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
  const response=await fetch(path,options), data=await response.json();
  if(!response.ok) {
    const error=new Error(data.detail || 'The request could not be carried out.');
    error.setupPreview=data.setupPreview;
    error.jobStarted=data.jobStarted;
    throw error;
  }
  return data;
}
function problem(error, submissionAttempted=false) {
  el('result-folders').hidden=true;
  el('error').textContent=error.message; el('error').hidden=false;
  el('result-text').textContent='Could not be carried out — no result is available here.';
  if(job) {
    el('progress').textContent='Current run status is unavailable.';
    el('next-step').textContent='Use Retry status to reconnect, or Cancel to stop the job.';
  } else if(submissionAttempted && error.jobStarted!==false) {
    el('progress').textContent='Could not confirm whether verification started.';
    el('next-step').textContent='Check Past runs for this comparison, then check the folders before trying again.';
  } else {
    el('progress').textContent='Verification did not start.';
    el('next-step').textContent='Read the message above, check the folders, and try again.';
  }
  el('details').textContent='';
  el('viewer-note').hidden=true;
  el('isolation').hidden=true;
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
  el('result-before').textContent=data.before || 'No before folder recorded';
  el('result-after').textContent=data.after;
  el('result-folders').hidden=false;
  el('error').hidden=true;
  el('progress').textContent=phaseNames[data.phase] || 'Status unavailable';
  el('phases').replaceChildren(...data.history.map(entry=>{const li=document.createElement('li');li.textContent=phaseNames[entry.phase] || entry.phase;return li;}));
  const [title, next] = screens[data.screen];
  el('result-text').textContent = ['accept','reject','needs-review'].includes(data.screen) ? data.summary : title;
  if (data.screen === 'could-not-be-carried-out') {
    el('result-text').textContent += ' — needs review.';
  } else if (['cancelled','failed'].includes(data.screen)) {
    el('result-text').textContent += ' — no verdict was reached.';
  }
  const active = data.state === 'running';
  el('next-step').textContent = active && !data.sessionOwned
    ? 'Refresh past runs to check for an update. This run belongs to another app session.'
    : active || !['accept','reject','needs-review'].includes(data.screen) || data.viewer || data.report
      ? next : 'Read the saved result and details below. Start a new verification to get evidence you can open here.';
  el('judged-by').textContent=data.judgedBy;
  el('isolation').hidden=!data.isolation;
  el('isolation').textContent=data.isolation?'Replays in the sandbox: '+data.isolation:'';
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
const sideNames = {before:'Before', after:'After'};
el('drop-help').hidden=false;
document.addEventListener('dragover',event=>{
  if(!event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  const target=event.target.closest?.('[data-folder-side]');
  event.dataTransfer.dropEffect=target && !busy && !job ? 'copy' : 'none';
});
document.addEventListener('drop',event=>{
  if(!event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  const side=event.target.closest?.('[data-folder-side]')?.dataset.folderSide;
  if(!side || busy || job) return;
  const files=Array.from(event.dataTransfer.items).filter(item=>item.kind==='file');
  if(files.length===1 && files[0].webkitGetAsEntry?.()?.isDirectory) {
    el('choose-'+side).click();
  } else {
    el(side+'-feedback').textContent='Drop one project folder here, or use Choose '+sideNames[side]+' folder.';
  }
});
function textElement(tag, text) {
  const node=document.createElement(tag);
  node.textContent=text;
  return node;
}
function setupSave(result, select, side, folder, report) {
  const review=report.saveReview;
  if(!review) return;
  if(review.blocked){result.append(textElement('p',review.blocked));return;}
  const player=report.selectedPlayer;
  const remaining=report.unresolvedBindings.length
    ? 'Resolve the listed bindings and save a reviewed project config. Replay the route and choose checks for human approval.'
    : 'Review the player binding, replay the route and choose checks for human approval.';
  const summary=[
    sideNames[side]+' folder: '+review.folder, 'Selected player: '+player,
    review.runsProject ? 'This starts a disposable copy of the game headless to measure its controls. Continue only if you trust its project scripts.'
                       : 'The input map supplies the route without starting the game.',
    'On success, save '+review.setupFile+' and a content-addressed draft-first route in routes/.', remaining
  ].join('\n');
  const action=textElement('button','Save draft setup…');
  action.type='button';
  const status=textElement('p','');
  result.append(textElement('p',summary),action,status);
  action.onclick=async()=>{
    if(busy || !result.isConnected) return;
    if(!window.confirm(summary+'\n\nSave this draft setup?')){
      status.textContent='Save cancelled. No setup files were written.';return;
    }
    controls(true);select.disabled=true;action.disabled=true;
    status.textContent=review.runsProject?'Measuring controls and preparing the draft…':'Saving the draft…';
    try {
      const saved=await api('/api/setup/save',{side,folder,player,review:review.id});
      status.textContent='Saved '+saved.setupFile+' and '+saved.route+' in '+review.folder+'. '+remaining;
    } catch(error) {
      status.textContent=error.message+' Check folders again before retrying.';
    } finally {controls(false);}
  };
}
function playerPicker(panel, side, folder, preview, detail) {
  const overview=textElement('p',folder+'\n'+detail);
  panel.append(overview);
  const label=textElement('label',sideNames[side]+' player');
  const select=document.createElement('select');
  label.htmlFor=select.id=side+'-player';
  const prompt=textElement('option','Choose a player to review its image details');
  prompt.value=''; prompt.disabled=true; prompt.selected=true;
  select.append(prompt);
  for(const player of preview.players) {
    const option=textElement('option',player);
    option.value=player;
    select.append(option);
  }
  const evidence=document.createElement('div');
  panel.append(label,select,evidence);
  select.onchange=async()=>{
    // A new choice, folder edit or recheck detaches the previous response's destination.
    const result=textElement('div','Reading the selected player…');
    evidence.replaceChildren(result);
    const player=select.value;
    overview.textContent=folder+'\nStarting scene: '+preview.entryScene;
    try {
      await api('/api/inspect',{projectConfig:true,side,folder,player,executionClass:values().executionClass});
      result.textContent='The project setup changed. Check folders again.';
    } catch(error) {
      const report=error.setupPreview;
      if(!report || report.selectedPlayer!==player) {
        result.textContent=error.message;
        return;
      }
      const lines=report.imageSuggestions.map(item=>{
        const size=item.imageSize ? item.imageSize.join(' × ') : 'size unknown';
        const drawing=item.regions ? 'atlas regions '+item.regions.map(([x,y,w,h])=>`${w} × ${h} at (${x}, ${y})`).join(', ') : 'whole image reference';
        return `${item.sprite}.${item.property}: ${item.image} (${size}), ${drawing}.`;
      });
      lines.push(...report.unresolvedBindings);
      result.textContent=lines.join('\n');
      setupSave(result,select,side,folder,report);
    }
  };
}
let latestRecentRequest=0;
async function refreshRecentFolders() {
  const request=++latestRecentRequest;
  try {
    const {folders}=await api('/api/projects/recent');
    if(request!==latestRecentRequest) return;
    for(const side of Object.keys(sideNames)) {
      const select=el('recent-'+side);
      select.replaceChildren(new Option('Choose a recent folder',''),
                             ...folders.map(folder=>new Option(folder,folder)));
      el('recent-'+side+'-group').hidden=folders.length===0;
    }
  } catch {
    // The desktop chooser and path fields remain usable if local history is unavailable.
  }
}
let folderRevision=0;
let pairTimer;
const pairedProblems=new Map();
const checkingFolder='Checking the selected folder…';
function hasFolderPair() {
  return Boolean(el('before').value.trim() && el('after').value.trim());
}
function checkFolderPair(delay) {
  clearTimeout(pairTimer);
  const notice=el('folder-pair-feedback');
  notice.textContent='';
  for(const [field,problem] of pairedProblems) {
    if(field.textContent===problem) field.textContent='';
  }
  pairedProblems.clear();
  const before=el('before').value, after=el('after').value, revision=folderRevision;
  if(!before.trim() || !after.trim()) return;
  // Compare the paths resolved by the server, including project.godot selections.
  pairTimer=setTimeout(async()=>{
    try {
      const pair=await api('/api/projects/check',{before,after});
      if(revision!==folderRevision) return;
      for(const side of Object.keys(sideNames)) {
        const field=el(side+'-feedback'), problem=pair[side].problem;
        if(problem) {
          pairedProblems.set(field,problem);
          field.textContent=problem;
        } else if(!field.textContent || field.textContent===checkingFolder) {
          field.textContent=sideNames[side]+' folder selected.';
        }
      }
      if(pair.before.folder && pair.before.folder===pair.after.folder) {
        notice.textContent='Before and After are the same copy. Select “Choose Before folder” to compare a different version. You can still verify this copy as a baseline.';
      }
    } catch(error) {
      if(revision===folderRevision) notice.textContent=error.message;
    }
  },delay);
}
let previousAfter=null;
function selectBefore(folder, message) {
  const before=el('before');
  before.value=folder;
  before.dispatchEvent(new Event('input',{bubbles:true}));
  el('before-feedback').textContent=message;
}
el('use-before').onclick=()=>{
  const before=el('before');
  if(busy || job || before.value.trim() || el('before-suggestion').hidden) return;
  selectBefore(el('suggested-folder').textContent,'Before folder selected.');
  before.focus();
};
el('use-previous').onclick=async()=>{
  if(busy || job || el('before').value.trim() || el('previous-option').hidden) return;
  const after=el('after').value, revision=folderRevision;
  controls(true);
  el('before-feedback').textContent='Opening the previous commit…';
  try {
    const copy=await api('/api/projects/previous',{after});
    if(revision!==folderRevision) return;
    selectBefore(copy.folder,'Before is a temporary copy of Git commit '+copy.commit+'.');
    previousAfter=after;
  } catch(error) {
    if(revision===folderRevision) el('before-feedback').textContent=error.message+' You can select a folder with Choose Before folder.';
  } finally {
    controls(false);
    if(previousAfter===after) el('before').focus();
    else if(!el('previous-option').hidden) el('use-previous').focus();
  }
};
for(const side of Object.keys(sideNames)) {
  const input=el(side), choose=el('choose-'+side), feedback=el(side+'-feedback');
  const recent=el('recent-'+side);
  let selection=0;
  input.addEventListener('input',event=>{
    selection++;
    folderRevision++;
    el('before-suggestion').hidden=true;
    el('previous-option').hidden=true;
    if(side==='before') previousAfter=null;
    if(side==='after' && previousAfter!==null && input.value!==previousAfter) {
      selectBefore('','Choose a Before version for the changed After folder.');
    }
    if(recent.value!==input.value) recent.value='';
    el('inspection-'+side).replaceChildren();
    feedback.textContent='';
    // Picker selections dispatch a complete path. Debounce only manual text edits.
    checkFolderPair(event instanceof InputEvent ? 200 : 0);
  });
  async function checkFolder(showFeedback) {
    const folder=input.value, revision=folderRevision, current=selection;
    if(hasFolderPair()) return; // The input event scheduled the paired check.
    const offerBefore=side==='after' && !el('before').value.trim();
    if(!showFeedback && (!offerBefore || !folder.trim())) return;
    if(showFeedback) feedback.textContent=checkingFolder;
    try {
      const checked=await api('/api/projects/check',{[side]:folder});
      if(current!==selection || input.value!==folder || hasFolderPair()) return;
      if(showFeedback) feedback.textContent=checked[side].problem || sideNames[side]+' folder selected.';
      const suggestion=checked.beforeSuggestion;
      if(!offerBefore || revision!==folderRevision || el('before').value.trim()) return;
      if(suggestion) {
        el('suggestion-source').textContent=suggestion.source==='worktree'
          ? 'Possible Before in another Git worktree:' : 'Possible Before in a neighboring folder:';
        el('suggested-folder').textContent=suggestion.folder;
        el('before-suggestion').hidden=false;
      } else if(checked.hasGitCheckout) el('previous-option').hidden=false;
    } catch(error) {
      if(showFeedback && current===selection && !hasFolderPair()) feedback.textContent=error.message;
    }
  }
  if(side==='after') {
    input.addEventListener('change',()=>checkFolder(false));
    el('before').addEventListener('change',()=>{
      if(!el('before').value.trim()) checkFolder(false);
    });
  }
  recent.onchange=()=>{
    const folder=recent.value;
    if(!folder || busy || job) return;
    input.value=folder;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    checkFolder(true);
  };
  choose.onclick=async()=>{
    if(busy || job) return;
    selection++;
    controls(true);
    el('before').disabled=el('after').disabled=false;
    feedback.textContent='Choose a project folder in the desktop dialog.';
    let edited=false;
    const markEdited=()=>{edited=true;};
    input.addEventListener('input',markEdited);
    try {
      const {folder}=await api('/api/projects/choose',{});
      if(folder) refreshRecentFolders();
      if(edited) return;
      if(folder===null){feedback.textContent='Folder choice cancelled.';return;}
      if(typeof folder!=='string' || !folder.trim()) throw new Error('The desktop dialog returned no usable folder.');
      input.value=folder;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      feedback.textContent=sideNames[side]+' folder selected.';
      if(side==='after') checkFolder(false);
    } catch(error) {
      if(!edited) feedback.textContent=error.message+' You can also paste the full path here.';
    } finally {
      input.removeEventListener('input',markEdited);
      controls(false);
      if(document.activeElement===document.body) choose.focus();
    }
  };
}
for(const id of ['manual','game','routes','specs','isolated']) {
  el(id).addEventListener('input',()=>{
    for(const side of Object.keys(sideNames)) el('inspection-'+side).replaceChildren();
  });
}
el('inspect').onclick=async()=>{
  el('error').hidden=true; controls(true);
  try {const body=values();
    const blocked=[], panels={};
    for(const side of Object.keys(sideNames)) {
      panels[side]=document.createElement('div');
      el('inspection-'+side).replaceChildren(panels[side]);
      el(side).disabled=false;
    }
    for(const [side,panel] of Object.entries(panels)){
      if(!panel.isConnected) continue;
      const request={...body,side,folder:body[side]};
      const heading=textElement('h3',side==='before'?'Before (checks used for this run)':'After');
      try {
        const data=await api('/api/inspect',request);
        const lines=[data.godot?'Godot project found.':'No Godot project found.',
          `${data.routes} usable routes; ${data.checks} approved checks; ${data.drafts} draft checks.`,
          ...(data.routeNames||[]).map(name=>'Route: '+name), ...(data.checkNames||[]).map(name=>'Check: '+name),
          data.help,rendering(data),...data.problems];
        panel.append(heading,textElement('p',lines.filter(Boolean).join('\n')));
      } catch(error) {
        if(!panel.isConnected) continue;
        blocked.push(panel);
        panel.append(heading);
        if(error.setupPreview) playerPicker(panel,side,request.folder,error.setupPreview,error.message);
        else panel.append(textElement('p',error.message));
      }
    }
    if(blocked.some(panel=>panel.isConnected)) problem(new Error('Review the folder details above before verifying.'));
  } finally{controls(false);}
};
el('verify').onclick=async()=>{
  if(job){controls(true);el('verify').textContent='Verify';await poll();return;}
  el('error').hidden=true;el('repair-record').hidden=true;el('report').hidden=true;el('viewer').hidden=true;el('judged-by').textContent='';el('details').textContent='';el('next-step').textContent='';el('isolation').hidden=true;el('phases').replaceChildren();
  el('result-folders').hidden=true;
  el('result-text').textContent='No verdict yet.';el('progress').textContent='Checking the rendering environment before starting…';controls(true);
  let submissionAttempted=false;
  try{const body=values();
    for(const side of Object.keys(sideNames)) {
      if(!body[side].trim()) {
        problem(new Error('Choose both versions before starting verification.'));
        el(side+'-feedback').textContent='Choose the '+sideNames[side]+' folder or enter its path.';
        el(side).focus();
        return;
      }
    }
    if(el('auto-fix').checked){
      body.autoFix=true;body.repairAgent=el('fix-agent').value;body.attempts=el('attempts').valueAsNumber;body.usdCap=el('usd-cap').valueAsNumber;
      if(!Number.isInteger(body.attempts)||body.attempts<1||body.attempts>10) throw new Error('Enter 1 to 10 fix attempts.');
      if(!Number.isFinite(body.usdCap)||body.usdCap<0) throw new Error('Enter a fixer spend cap of zero or more US dollars.');
    }
    if(body.projectConfig){
      const inspection=await api('/api/inspect',{...body,side:'before',folder:body.before});
      if(inspection.readinessSteps?.length){
        rendererAcknowledged=null;el('rendering').textContent='';
        throw new Error('Before is not ready for verification. '+inspection.readinessSteps.join(' '));
      }
      el('rendering').textContent=rendering(inspection);
      const signature=JSON.stringify([body,inspection.rendering]);
      if(inspection.rendering?.warning && rendererAcknowledged!==signature){
        rendererAcknowledged=signature;controls(false);el('verify').textContent='Verify with this warning';
        el('progress').textContent='Nothing has started. Read the rendering warning above before continuing.';return;
      }
    }
    rendererAcknowledged=null;el('verify').textContent='Verify';
    el('progress').textContent='Creating the job and recording its inputs…';
    submissionAttempted=true;
    const data=await api('/api/jobs',body);if(body.projectConfig)refreshRecentFolders();job=data.id;controls(true);show(data);if(job)await poll();else await pastRuns();}
  catch(error){problem(error,submissionAttempted);}
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
refreshRecentFolders();
pastRuns();
</script></body></html>'''
