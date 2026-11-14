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
  focus() {} scrollIntoView() {}
}
function descend(e) { return [e, ...e.children.flatMap(descend)]; }
function boot(views) {
  const root = new Element('section'), evidence = new Element('script'), events = {};
  evidence.textContent = JSON.stringify({views});
  const document = {
    getElementById: id => id === 'evidence' ? evidence : root,
    createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    querySelectorAll: () => [],
    querySelector: () => descend(root).find(e => e.type === 'range'),
    addEventListener: (name, fn) => { events[name] = fn; }
  };
  vm.runInNewContext(script, {document, console, fetch() { throw Error('external request'); }});
  return {
    root,
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
  return {findingId: id, firstFrame: first, spec: id, route: 'smoke', comparison: 'REGRESSION',
    frames: {before: frames, after: frames}, series: {before: s(points), after: s(points)},
    visualSeries: {before: s(visual), after: s(visual)},
    observed: {after: {engine: 'pass', visual: fail ? 'fail' : 'pass'}}, notes: [], visualNotes: []};
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
for (const data of pages) {
  const sample = boot(data.views);
  const first = data.views[0].firstFrame ?? 0;
  assert.ok(sample.frame().startsWith('Frame ' + first));
  sample.key('ArrowRight'); sample.key('ArrowLeft');
  assert.ok(sample.frame().startsWith('Frame ' + first));
  sample.key('End'); sample.key('Home'); sample.key('f'); sample.key('o');
  if (data.decision === 'reject') assert.ok(sample.captions().every(c => c.includes('frame ' + first)));
}
console.log('keyboard navigation: OK (actual viewer script; DOM stand-in, not a browser)');
