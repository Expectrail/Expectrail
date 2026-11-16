// The home page's interactive and moving parts. Everything they show is also in the page's HTML for the default
// state, so the page reads the same without this script. Each figure is a recorded result; the links beside each
// figure on the page name its source.
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var LEDGER = 'https://github.com/Expectrail/Expectrail/blob/main/docs/capabilities.md';

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function field(root, name) { return root.querySelector('[data-field="' + name + '"]'); }
  function onView(el, ratio, fn, once) {
    if (!('IntersectionObserver' in window)) { fn(true); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var seen = e.isIntersecting && e.intersectionRatio >= ratio;
        if (seen || !once) { fn(seen); }
        if (seen && once) { io.disconnect(); }
      });
    }, { threshold: [0, ratio] });
    io.observe(el);
  }

  // Scroll-in text and counting numbers.
  each(document.querySelectorAll('.reveal'), function (el) {
    if (reduce) { el.classList.add('in'); return; }
    onView(el, 0.15, function () { el.classList.add('in'); }, true);
  });
  each(document.querySelectorAll('[data-count]'), function (el) {
    var end = parseFloat(el.getAttribute('data-count'));
    var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
    if (reduce || !(end > 0)) { return; }
    onView(el, 0.5, function () {
      var start = null;
      function tick(t) {
        if (start === null) { start = t; }
        var k = Math.min(1, (t - start) / 900);
        el.textContent = (end * (1 - Math.pow(1 - k, 3))).toFixed(decimals);
        if (k < 1) { requestAnimationFrame(tick); } else { el.textContent = end.toFixed(decimals); }
      }
      el.textContent = (0).toFixed(decimals);
      requestAnimationFrame(tick);
    }, true);
  });

  // One recorded deceptive fix (judge bench: bad/fall-through-sink-player), judged three ways.
  var MODES = {
    engine: { verdict: 'ACCEPT', right: false, engine: true, vision: false,
      why: 'The position log looks normal, so a check of the engine alone passes it.',
      caught: '4 of 8', fooled: '3 of 7', blocked: '0 of 8' },
    judge: { verdict: 'ACCEPT', right: false, engine: false, vision: true,
      why: 'Muse Code judging screenshots accepted it in both runs, and it also turns down good fixes.',
      caught: 'not a gate', fooled: '2 of 7', blocked: '1 to 2 of 8' },
    both: { verdict: 'REJECT', right: true, engine: true, vision: true,
      why: 'The engine passes, vision sees the robot below the ground, and plain code refuses to accept.',
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

  // How it works: each step explains itself; a scenario lights the path a change takes.
  var NODES = {
    change: { title: 'Agent’s change', link: ['concepts.html#checks', 'Checks and routes'],
      text: 'A pull request or patch. Expectrail doesn’t take its tests or description on trust; it replays the change.' },
    replay: { title: 'Replay on fixed routes', link: [LEDGER + '#godot-harness', 'Godot harness · ledger row'],
      text: 'The game replays fixed input routes and captures every frame and the engine’s record. Checks and routes come from the base, not the change.' },
    record: { title: 'Channel 1: the runtime record', link: [LEDGER + '#godot-harness', 'Godot harness · ledger row'],
      text: 'The engine’s account of each frame: where the player is and what it touches. It can’t see what was drawn.' },
    vision: { title: 'Channel 2: vision on judged frames', link: [LEDGER + '#sam-observer', 'SAM observer · ledger row'],
      text: 'Current verify uses live SAM or exact recorded answers for the judged frames. Historical agent benchmarks also used Muse Glimmer 30B. Observers do not decide verdicts.' },
    evaluator: { title: 'Plain-code evaluator', link: [LEDGER + '#godot-verify', 'Godot verify path · ledger row'],
      text: 'Ordinary code judges each approved check from the engine’s record and what vision saw. No model decides. Acceptance needs both observations for every required check; missing vision needs review unless a check already fails.' },
    accept: { title: 'accept', link: ['concepts.html#decisions', 'What a verdict means'],
      text: 'Every configured check passed with the required evidence. It covers those checks and routes, and it isn’t release clearance.' },
    review: { title: 'needs-review', link: ['concepts.html#decisions', 'What a verdict means'],
      text: 'Not enough usable evidence to accept, for example no vision. It isn’t a weaker pass.' },
    reject: { title: 'reject → opt-in repair', link: ['#repair', 'Verify, then repair'],
      text: 'A check failed, which counts even without vision. With auto-fix on, a sandboxed fixer can try a patch on a copy, and a person reviews it.' }
  };
  var SCENARIOS = {
    accept: ['change', 'replay', 'record', 'vision', 'evaluator', 'accept'],
    reject: ['change', 'replay', 'record', 'vision', 'evaluator', 'reject'],
    review: ['change', 'replay', 'record', 'evaluator', 'review']
  };

  each(document.querySelectorAll('[data-flow]'), function (root) {
    var timers = [];
    var touched = false;
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
      b.addEventListener('click', function () { touched = true; stop(); select(b.getAttribute('data-node')); });
    });
    each(root.querySelectorAll('[data-scenario]'), function (b) {
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', function () { touched = true; play(b.getAttribute('data-scenario')); });
    });
    // Play the deceptive fix once when the flow first comes into view, unless the reader got there first.
    onView(root, 0.5, function () { if (!touched) { play('reject'); } }, true);
  });

  // How it works, the equation: sensor × telemetry → evaluator → repair, one beat at a time while on screen.
  each(document.querySelectorAll('[data-equation]'), function (fig) {
    var terms = fig.querySelectorAll('[data-eq-term]');
    var ops = fig.querySelectorAll('[data-eq-op]');
    var hit = fig.querySelector('.eq-hit');
    var btn = fig.querySelector('[data-eq-play]');
    var BEATS = 7, step = 0, timer = null, visible = false, paused = reduce;
    function draw() {
      fig.setAttribute('data-step', String(step));
      each(terms, function (t, i) {
        t.classList.toggle('is-lit', step >= i * 2);
        t.classList.toggle('is-on', step === i * 2 || (i === 3 && step === 6));
      });
      each(ops, function (o, i) {
        o.classList.toggle('is-lit', step > i * 2 + 1);
        o.classList.toggle('is-on', step === i * 2 + 1);
      });
      if (hit) { hit.classList.toggle('is-lit', step >= 4); }
    }
    function run() {
      clearInterval(timer); timer = null;
      if (visible && !paused) { timer = setInterval(function () { step = (step + 1) % BEATS; draw(); }, 1300); }
      btn.textContent = paused ? 'Play' : 'Pause';
      btn.setAttribute('aria-pressed', paused ? 'true' : 'false');
    }
    btn.addEventListener('click', function () { paused = !paused; run(); });
    if (reduce) { btn.hidden = true; return; }   // with reduced motion every term stays lit and nothing moves
    draw();
    onView(fig, 0.4, function (seen) { visible = seen; run(); }, false);
    run();
  });

  // The repair loop: plays through its five stages while it is on screen; pause, previous and next take over.
  each(document.querySelectorAll('.repair-story'), function (story) {
    var root = story.parentNode;
    var status = root.querySelector('[data-loop-status]');
    if (!status) { return; }
    var cards = root.querySelectorAll('.loop-card rect');
    var labels = root.querySelectorAll('.loop-label text');
    var notes = root.querySelectorAll('.repair-notes li');
    var bar = root.querySelector('.loop-progress i');
    var playBtn = root.querySelector('[data-loop-play]');
    var names = ['Verify the change', 'Reject with auto-fix on', 'Fix a separate copy', 'Judge the candidate', 'Review the patch'];
    // Which of the five notes explain each of the five steps (the first two steps share the "Reject" note).
    var noteFor = [[0], [0], [1], [2, 3], [4]];
    var at = -1, timer = null, visible = false, paused = reduce;
    function go(i) {
      at = (i + names.length) % names.length;
      each(cards, function (c, k) { c.classList.toggle('is-on', k === at); });
      each(labels, function (t, k) { t.classList.toggle('is-on', k === at); });
      each(notes, function (li, k) { li.classList.toggle('is-on', noteFor[at].indexOf(k) !== -1); });
      if (bar) { bar.style.width = ((at + 1) / names.length * 100) + '%'; }
      status.textContent = 'Step ' + (at + 1) + ' of ' + names.length + ': ' + names[at];
    }
    function run() {
      clearInterval(timer); timer = null;
      if (visible && !paused) { timer = setInterval(function () { go(at + 1); }, 2400); }
      playBtn.textContent = paused ? 'Play' : 'Pause';
      playBtn.setAttribute('aria-pressed', paused ? 'true' : 'false');
    }
    playBtn.addEventListener('click', function () { paused = !paused; if (!paused && at < 0) { go(0); } run(); });
    root.querySelector('[data-loop-prev]').addEventListener('click', function () { paused = true; go(at < 0 ? 0 : at - 1); run(); });
    root.querySelector('[data-loop-next]').addEventListener('click', function () { paused = true; go(at + 1); run(); });
    each(cards, function (c, k) { c.addEventListener('click', function () { paused = true; go(k); run(); }); });
    onView(story, 0.4, function (seen) {
      visible = seen;
      if (seen && at < 0) { go(0); }
      run();
    }, false);
    run();
  });
})();
