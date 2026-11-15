// The home page's interactive parts. Everything they show is also in the page's HTML for the default
// state, so the page reads the same without this script. Each figure is a recorded result; the links
// beside each figure on the page name its source.
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var LEDGER = 'https://github.com/Expectrail/Expectrail/blob/main/docs/capabilities.md';

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function field(root, name) { return root.querySelector('[data-field="' + name + '"]'); }

  // One recorded deceptive fix (judge bench: bad/fall-through-sink-player), judged three ways.
  var MODES = {
    engine: { verdict: 'ACCEPT', right: false, engine: true, vision: false,
      why: 'The position log looks normal, so a check of the engine’s record alone passes the fix that draws the robot into the ground.',
      caught: '4 of 8', fooled: '3 of 7', blocked: '0 of 8' },
    judge: { verdict: 'ACCEPT', right: false, engine: false, vision: true,
      why: 'Muse Code judging the screenshots accepted this fix in both recorded runs. A screenshot judge is not a deterministic gate, and it also rejects working fixes.',
      caught: 'not a gate', fooled: '2 of 7', blocked: '1 to 2 of 8' },
    both: { verdict: 'REJECT', right: true, engine: true, vision: true,
      why: 'The engine passes, vision sees the player below the ground line, and plain code refuses to accept.',
      caught: '8 of 8', fooled: '0 of 7', blocked: '0 of 8' }
  };

  each(document.querySelectorAll('[data-switch]'), function (root) {
    var frame = root.querySelector('.switch-frame');
    var verdict = root.querySelector('.switch-verdict');
    function show(name) {
      var m = MODES[name];
      if (!m) { return; }
      each(root.querySelectorAll('[data-mode]'), function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-mode') === name ? 'true' : 'false');
      });
      field(root, 'verdict').textContent = m.verdict;
      field(root, 'right').textContent = m.right ? '· correct' : '· wrong';
      verdict.setAttribute('data-right', m.right ? 'true' : 'false');
      field(root, 'why').textContent = m.why;
      field(root, 'caught').textContent = m.caught;
      field(root, 'fooled').textContent = m.fooled;
      field(root, 'blocked').textContent = m.blocked;
      frame.setAttribute('data-show-engine', m.engine ? 'true' : 'false');
      frame.setAttribute('data-show-vision', m.vision ? 'true' : 'false');
    }
    each(root.querySelectorAll('[data-mode]'), function (b) {
      b.addEventListener('click', function () { show(b.getAttribute('data-mode')); });
    });
  });

  // The how-it-works flow: each step explains itself; a scenario lights the path a change takes.
  var NODES = {
    change: { title: 'Agent’s change', link: ['concepts.html#checks', 'Checks and routes'],
      text: 'A pull request or patch from a coding agent or a person. Expectrail does not take its tests or its description on trust; it replays the change.' },
    replay: { title: 'Replay on fixed routes', link: [LEDGER + '#godot-harness', 'Godot harness · ledger row'],
      text: 'The game replays fixed input routes with a seed and ticks, capturing every frame and the engine’s record. Approved checks and routes come from the base, not from the change.' },
    record: { title: 'Channel 1: the runtime record', link: [LEDGER + '#godot-harness', 'Godot harness · ledger row'],
      text: 'The engine’s own account of each frame: where the player is, what it touches, what state the game is in. It cannot see what was drawn.' },
    vision: { title: 'Channel 2: vision on every frame', link: [LEDGER + '#sam-observer', 'SAM observer · ledger row'],
      text: 'SAM 3.1 or open-weight Muse Glimmer 30B finds what each check names in each captured frame. It only observes; it never decides.' },
    evaluator: { title: 'Deterministic evaluator', link: [LEDGER + '#godot-verify', 'Godot verify path · ledger row'],
      text: 'Plain code judges each approved check over its window, from the runtime’s record and the visual observations. No model decides. An accept needs both channels; missing or unusable vision means needs-review.' },
    accept: { title: 'accept', link: ['concepts.html#decisions', 'What a verdict means'],
      text: 'The configured checks passed with the required observations. It is bounded by those checks and routes, and it is not release clearance.' },
    review: { title: 'needs-review', link: ['concepts.html#decisions', 'What a verdict means'],
      text: 'Not enough usable evidence to accept, including missing vision or no approved checks. It is not a weaker pass.' },
    reject: { title: 'reject → opt-in repair', link: ['#repair', 'Verify, then repair'],
      text: 'A check failed, which is decisive even when vision did not run. With auto-fix turned on, a sandboxed fixer may try a patch on a separate copy; a person reviews any accepted patch.' }
  };
  var SCENARIOS = {
    accept: ['change', 'replay', 'record', 'vision', 'evaluator', 'accept'],
    reject: ['change', 'replay', 'record', 'vision', 'evaluator', 'reject'],
    review: ['change', 'replay', 'record', 'evaluator', 'review']
  };

  each(document.querySelectorAll('[data-flow]'), function (root) {
    var timers = [];
    function stop() { timers.forEach(clearTimeout); timers = []; }
    function select(name) {
      var n = NODES[name];
      if (!n) { return; }
      each(root.querySelectorAll('[data-node]'), function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-node') === name ? 'true' : 'false');
      });
      field(root, 'title').textContent = n.title;
      field(root, 'text').textContent = n.text;
      var a = field(root, 'link');
      a.setAttribute('href', n.link[0]);
      a.textContent = n.link[1];
    }
    function light(path) {
      each(root.querySelectorAll('[data-node]'), function (b) {
        b.classList.toggle('is-on', path.indexOf(b.getAttribute('data-node')) !== -1);
      });
    }
    function play(name) {
      var path = SCENARIOS[name];
      if (!path) { return; }
      stop();
      each(root.querySelectorAll('[data-scenario]'), function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-scenario') === name ? 'true' : 'false');
      });
      if (reduce) { light(path); select(path[path.length - 1]); return; }
      light([]);
      path.forEach(function (step, i) {
        timers.push(setTimeout(function () { light(path.slice(0, i + 1)); select(step); }, i * 650));
      });
    }
    each(root.querySelectorAll('[data-node]'), function (b) {
      b.addEventListener('click', function () { stop(); select(b.getAttribute('data-node')); });
    });
    each(root.querySelectorAll('[data-scenario]'), function (b) {
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', function () { play(b.getAttribute('data-scenario')); });
    });
  });

  // The repair loop: step through the five stages; the diagram and the notes light together.
  each(document.querySelectorAll('.repair-story'), function (story) {
    var root = story.parentNode;
    if (!root.querySelector('[data-loop-status]')) { return; }
    var cards = root.querySelectorAll('.loop-card rect');
    var labels = root.querySelectorAll('.loop-label text');
    var notes = root.querySelectorAll('.repair-notes li');
    var status = root.querySelector('[data-loop-status]');
    var names = ['Verify the change', 'Reject with auto-fix on', 'Fix a separate copy', 'Judge the candidate', 'Review the patch'];
    // Which of the five notes explain each of the five steps (the first two steps share the "Reject" note).
    var noteFor = [[0], [0], [1], [2, 3], [4]];
    var at = -1;
    function go(i) {
      at = (i + names.length) % names.length;
      each(cards, function (c, k) { c.classList.toggle('is-on', k === at); });
      each(labels, function (t, k) { t.classList.toggle('is-on', k === at); });
      each(notes, function (li, k) { li.classList.toggle('is-on', noteFor[at].indexOf(k) !== -1); });
      status.textContent = 'Step ' + (at + 1) + ' of ' + names.length + ': ' + names[at];
    }
    root.querySelector('[data-loop-prev]').addEventListener('click', function () { go(at < 0 ? 0 : at - 1); });
    root.querySelector('[data-loop-next]').addEventListener('click', function () { go(at + 1); });
    each(cards, function (c, k) {
      c.addEventListener('click', function () { go(k); });
    });
  });
})();
