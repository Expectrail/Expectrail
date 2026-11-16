// The site menu. On narrow screens the section links fold behind a labelled Menu button; on wider screens they stay
// visible and this does nothing but mark the current page. Without this script the links are always shown.
(function () {
  'use strict';
  var narrow = window.matchMedia('(max-width: 860px)');
  var here = location.pathname.split('/').pop() || 'index.html';

  Array.prototype.forEach.call(document.querySelectorAll('header.top'), function (top, n) {
    var btn = top.querySelector('.menu-toggle');
    var nav = top.querySelector('nav');
    if (!nav) { return; }
    Array.prototype.forEach.call(nav.querySelectorAll('a'), function (a) {
      if (a.getAttribute('href') === here) { a.setAttribute('aria-current', 'page'); }
    });
    if (!btn) { return; }
    var label = btn.querySelector('.menu-label');
    nav.id = nav.id || 'site-nav' + (n ? '-' + n : '');
    btn.setAttribute('aria-controls', nav.id);
    btn.hidden = false;
    top.classList.add('has-toggle');

    function set(open, returnFocus) {
      top.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      label.textContent = open ? 'Close' : 'Menu';
      if (!open && returnFocus) { btn.focus(); }
    }
    function isOpen() { return btn.getAttribute('aria-expanded') === 'true'; }

    btn.addEventListener('click', function () { set(!isOpen()); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) { set(false); } });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen()) { set(false, true); } });
    document.addEventListener('click', function (e) { if (isOpen() && !top.contains(e.target)) { set(false); } });
    function onWidth() { if (!narrow.matches) { set(false); } }
    if (narrow.addEventListener) { narrow.addEventListener('change', onWidth); } else { narrow.addListener(onWidth); }
  });
})();
