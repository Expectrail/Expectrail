// Execute the viewer's actual script, with a small DOM stand-in. No browser or network.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {script, pages = []} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = [];
    this.events = {}; this.style = {}; this._text = ''; this.complete = true;
    this.naturalWidth = 1600; this.naturalHeight = 900;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'type') this.type = v; }
  getAttribute(k) { return this.attributes[k]; }
  appendChild(child) { this.children.push(child); return child; }
  set textContent(s) { this._text = String(s); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(' '); }
  addEventListener(name, fn) { this.events[name] = fn; }
  getBoundingClientRect() { return {left: 0, width: 1000}; }
  contains(node) { return descend(this).includes(node); }
  focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  scrollIntoView() {}
}
function descend(e) { return [e, ...e.children.flatMap(descend)]; }
function boot(views, starts = []) {
  const root = new Element('section'), evidence = new Element('script'), events = {};
  root.setAttribute("data-starts", JSON.stringify(starts));
  evidence.textContent = JSON.stringify({views});
  const document = {
    getElementById: id => id === 'evidence' ? evidence : root,
    activeElement: null,
    createElement: tag => Object.assign(new Element(tag), {ownerDocument: document}),
    createElementNS: (_, tag) => new Element(tag),
    querySelectorAll: () => [],
    querySelector: () => descend(root).find(e => e.type === 'range'),
    addEventListener: (name, fn) => { events[name] = fn; }
  };
  vm.runInNewContext(script, {document, console, fetch() { throw Error('external request'); }});
  return {
    root, document,
    key(key, opts = {}) {
      let prevented = false;
      events.keydown({key, target: {tagName: 'BODY'}, ...opts, preventDefault() { prevented = true; }});
      return prevented;
    },
    frame: () => descend(root).find(e => e.attributes['aria-live'] === 'polite')?.textContent,
    captions: () => descend(root).filter(e => e.tagName === 'FIGCAPTION').map(e => e.textContent),
    overlays: () => descend(root).filter(e => e.tagName === 'SVG' && e.attributes['aria-hidden'] === 'true').length,
    click(label) {
      const button = descend(root).find(e => e.attributes['aria-label'] === label);
      assert.ok(button, label); button.events.click();
    }
  };
}
function view(id, first, fail) {
  const points = Array.from({length: 21}, (_, frame) => ({frame, value: frame, state: 'ok',
    boxes: {player: [1, 2, 3, 4]}, line: {axis: 'y', at: 4}}));
  const visual = points.map(p => ({...p, value: p.frame === 3 ? null : p.value,
    state: p.frame === 3 ? 'absent' : p.frame === first && fail ? 'over' : 'ok'}));
  const s = points => ({label: 'distance', source: 'record', limit: 4, unit: 'px', points});
  const frames = points.map(p => ({frame: p.frame, path: 'data:image/png;base64,AA==', sha256: '0'.repeat(64)}));
  return {findingId: id, firstFrame: first, after: fail ? 'fail' : 'pass', spec: id, route: 'smoke', comparison: 'REGRESSION',
    frames: {before: frames, after: frames}, series: {before: s(points), after: s(points)},
    visualSeries: {before: s(visual), after: s(visual)},
    observed: {after: {engine: 'pass', visual: fail ? 'fail' : 'pass'}}, notes: [], visualNotes: []};
}
// A frame locates a finding even when the replay could not decide the check.
for (const outcome of ['needs-review', 'replay-error', undefined, 'fail']) {
  const finding = {...view('finding', 4, false), after: outcome};
  const panel = boot([finding]);
  const failed = outcome === 'fail';
  const button = failed ? 'go to the first failing frame' : 'go to the finding frame';
  const announcement = failed ? 'Frame 4 (first failing frame)' : 'Frame 4 (finding frame)';
  assert.equal(panel.frame(), announcement);
  panel.key('End');
  panel.click(button);
  assert.equal(panel.frame(), announcement);
  panel.key('Home');
  panel.key('f');
  assert.equal(panel.frame(), announcement);
  assert.ok(!descend(panel.root).some(e => e.getAttribute('aria-label') ===
    (failed ? 'go to the finding frame' : 'go to the first failing frame')));
}
const ui = boot([view('later', 15, false), view('earlier', 4, true)]);
assert.match(ui.frame(), /^Frame 4 /); // earliest relevant divergence, even if input order differs
assert.equal(ui.overlays(), 2);
assert.ok(ui.captions().every(c => c.includes('frame 4')));
assert.equal(ui.key('ArrowRight'), true); assert.match(ui.frame(), /^Frame 5/);
assert.ok(ui.captions().every(c => c.includes('frame 5')));
ui.key('ArrowLeft'); assert.match(ui.frame(), /^Frame 4/);
ui.key('ArrowLeft', {shiftKey: true}); assert.match(ui.frame(), /^Frame 0/);
ui.key('ArrowLeft'); assert.match(ui.frame(), /^Frame 0/);
ui.key('End'); assert.match(ui.frame(), /^Frame 20/);
ui.key('ArrowRight'); assert.match(ui.frame(), /^Frame 20/);
ui.key('Home'); assert.match(ui.frame(), /^Frame 0/);
ui.key('f'); assert.match(ui.frame(), /^Frame 4 /);
ui.key('n'); assert.match(ui.frame(), /^Frame 15 /);
ui.key('p'); assert.match(ui.frame(), /^Frame 4 /);
assert.equal(ui.key('ArrowRight', {ctrlKey: true}), false); assert.match(ui.frame(), /^Frame 4 /);
ui.key('ArrowRight', {target: {tagName: 'TEXTAREA'}}); assert.match(ui.frame(), /^Frame 4 /);
ui.key('o'); assert.equal(ui.overlays(), 0);
ui.key('o'); assert.equal(ui.overlays(), 2);
ui.click('toggle measurement source'); assert.match(ui.root.textContent, /Overlays: engine/);
ui.click('toggle measurement source'); assert.match(ui.root.textContent, /Overlays: vision/);
ui.key('ArrowLeft'); assert.match(ui.frame(), /^Frame 3/);
assert.match(ui.root.textContent, /absent/);
assert.match(ui.root.textContent, /not observed/);
const charts = descend(ui.root).filter(e => e.attributes.class === 'timeline');
assert.equal(charts.length, 4);
assert.ok(descend(charts[2]).some(e => e.tagName === 'PATH' && (e.attributes.d.match(/M/g) || []).length === 2),
  'the visual line must break at the absent frame');
for (const views of [[], [{...view(null, null, false), frames: {}, series: {}, visualSeries: {}}]]) {
  const empty = boot(views);
  for (const key of ['ArrowRight', 'ArrowLeft', 'Home', 'End', 'f', 'n', 'p', 'o']) empty.key(key);
}
// Inspect a frame without an image. Each observer and each side has its own series.
const measured = view('readings', 3, false);
measured.frames = {};
measured.series.before = {...measured.series.before, points: measured.series.before.points.filter(p => p.frame !== 3)};
measured.series.after = {...measured.series.after, points: measured.series.after.points.map(p =>
  p.frame === 3 ? {...p, value: 101.87599999999998} : p)};
measured.visualSeries.before = {...measured.visualSeries.before, points: measured.visualSeries.before.points.map(p =>
  p.frame === 3 ? {...p, state: 'not-applicable'} : p.frame === 4 ? {...p, state: 'missing', value: null} : p)};
const readings = boot([measured]);
const selectedReadings = () => descend(readings.root).filter(e => e.getAttribute('class') === 'timeline')
  .map(chart => chart.children.find(e => e.tagName === 'P' && /^Frame \d+: /.test(e.textContent))?.textContent);
assert.equal(selectedReadings().join(' | '),
  'Frame 3: ≈101.876 px | Frame 3: No measurement | Frame 3: Not observed | Frame 3: Not exercised');
readings.key('ArrowRight');
assert.equal(selectedReadings()[3], 'Frame 4: Object missing');
readings.key('Home');
assert.ok(selectedReadings().every(s => s === 'Frame 0: 0 px'), 'zero is a reading');
for (const data of pages) {
  const sample = boot(data.views);
  const first = data.views[0].firstFrame ?? 0;
  assert.ok(sample.frame().startsWith('Frame ' + first));
  sample.key('ArrowRight'); sample.key('ArrowLeft');
  assert.ok(sample.frame().startsWith('Frame ' + first));
  sample.key('End'); sample.key('Home'); sample.key('f'); sample.key('o');
  if (data.decision === 'reject') assert.ok(sample.captions().every(c => c.includes('frame ' + first)));
}
// Redrawing the inspector replaces the controls. The next activation must go
// to the new, attached control, including when a keyboard shortcut redraws it.
const focusUI = boot([view('focus', 0, false)]);
const control = label => descend(focusUI.root).find(e => e.getAttribute('aria-label') === label);
const focusDoc = focusUI.document;
control('next frame').focus();
for (const frame of [1, 2]) {
  focusDoc.activeElement.events.click();
  assert.equal(focusUI.frame(), 'Frame ' + frame);
  assert.equal(focusDoc.activeElement, control('next frame'), 'next frame must keep focus');
}
control('frame').focus();
focusUI.key('ArrowRight', {target: focusDoc.activeElement});
assert.equal(focusUI.frame(), 'Frame 3');
assert.equal(focusDoc.activeElement, control('frame'), 'slider must keep focus');
control('toggle overlays').focus();
for (const count of [0, 2]) {
  focusDoc.activeElement.events.click();
  assert.equal(focusUI.overlays(), count);
  assert.equal(focusDoc.activeElement, control('toggle overlays'));
}
const outside = focusDoc.createElement('button');
outside.setAttribute('aria-label', 'next frame');
outside.focus();
focusUI.key('ArrowLeft', {target: outside});
assert.equal(focusDoc.activeElement, outside, 'redraw must leave external focus alone');

// The earliest difference can belong to a check whose failure is later. Zero is a real tick.
const diff = boot([view('later-difference', 4, false), view('earliest-difference', 15, true)], [2, 0]);
assert.equal(diff.frame(), 'Frame 0 (first measured difference)');
assert.match(diff.root.textContent, /Overlays: engine/);
diff.key('ArrowRight'); assert.equal(diff.frame(), 'Frame 1');
diff.key('f'); assert.equal(diff.frame(), 'Frame 15 (first failing frame)');
assert.match(diff.root.textContent, /Overlays: vision/);
diff.key('d'); assert.equal(diff.frame(), 'Frame 0 (first measured difference)');
assert.match(diff.root.textContent, /Overlays: engine/);
diff.key('n'); assert.equal(diff.frame(), 'Frame 2 (first measured difference)');
diff.key('f'); diff.click('go to the first measured difference');
assert.equal(diff.frame(), 'Frame 2 (first measured difference)');
// A visual failure may precede the first engine difference. Both remain reachable.
const earlyFailure = boot([view('earlier difference', 12, true), view('earlier failure', 0, true)], [5, 20]);
assert.equal(earlyFailure.frame(), 'Frame 0 (first failing frame)');
assert.match(earlyFailure.root.textContent, /earlier failure on smoke/);
assert.match(earlyFailure.root.textContent, /Overlays: vision/);
earlyFailure.key('d');
assert.equal(earlyFailure.frame(), 'Frame 20 (first measured difference)');
assert.match(earlyFailure.root.textContent, /Overlays: engine/);
earlyFailure.key('f');
assert.equal(earlyFailure.frame(), 'Frame 0 (first failing frame)');
assert.match(earlyFailure.root.textContent, /Overlays: vision/);
const repaired = boot([{...view('repair', null, false), findingId: null}], [20]);
assert.equal(repaired.frame(), 'Frame 20 (first measured difference)');
console.log('keyboard navigation: OK (actual viewer script; DOM stand-in, not a browser)');
