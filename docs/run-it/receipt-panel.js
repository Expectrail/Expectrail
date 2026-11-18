// The Run it receipt entry point delegates to the existing #255 reader. No key embedded
// in a receipt is trusted. Nothing is uploaded; file clearance never signs a saved run.
(function (root, factory) {
  'use strict';
  var reader = root.ExpectrailReceipt;
  if (typeof module !== 'undefined' && module.exports) reader = require('../verify/receipt-check.js');
  var api = factory(reader);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RunItReceipt = api;
  if (!root.document) return;
  var $ = function (id) { return root.document.getElementById(id); };
  var form = $('receipt-form');
  if (!form) return;
  var generation = 0;
  function resetResult() {
    generation++;
    $('receipt-outcome').hidden = true;
    $('receipt-outcome').setAttribute('data-tone', 'review');
    $('receipt-check').disabled = !$('receipt-file').files.length;
  }
  api.reset = function () {
    form.reset(); resetResult();
    $('receipt-availability').textContent = 'Receipt not yet available for this run. No signed receipt was checked.';
    $('receipt-availability').setAttribute('data-state', 'unavailable');
  };
  form.addEventListener('input', resetResult);
  form.addEventListener('change', resetResult);
  function value(id) { return $(id).value.trim() || null; }
  async function fileText(id, optional) {
    var file = $(id).files[0];
    if (!file) return optional ? '' : null;
    if (file.size > 2 * 1024 * 1024) throw new Error('Choose a JSON file no larger than 2 MiB.');
    return file.text();
  }
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var at = ++generation;
    var opts = {expectRepo: value('receipt-repo'), expectHead: value('receipt-head'),
                expectBuild: value('receipt-build'), expectPolicy: value('receipt-policy')};
    var result;
    try { result = await api.checkTexts(await fileText('receipt-file', false), await fileText('receipt-store', true), opts); }
    catch (e) { result = {outcome: 'cannot-tell', message: e.message}; }
    if (at !== generation) return; // another file/run/expectation was selected while checking
    var box = $('receipt-outcome');
    box.hidden = false;
    box.setAttribute('data-tone', result.outcome === 'clearance' ? 'pass' : 'review');
    $('receipt-title').textContent = result.outcome === 'clearance' ? 'Clearance for the selected file' :
      result.outcome === 'unavailable' ? 'Receipt not yet available' : 'No clearance for the selected file';
    $('receipt-means').textContent = 'This checks only your selected file against your trust store and expectations. It does not publish or sign a receipt for the run above.';
    var reasons = $('receipt-reasons'); reasons.textContent = '';
    var messages = result.report ? result.report.reasons : [result.message || 'This receipt could not be checked.'];
    messages.forEach(function (text) { var item = root.document.createElement('li'); item.textContent = text; reasons.appendChild(item); });
  });
  resetResult();
})(typeof window !== 'undefined' ? window : globalThis, function (reader) {
  'use strict';
  var emptyStore = '{"format":"expectrail.trust-store/v1","keys":[]}';
  return {checkTexts: async function (receiptText, storeText, expectations) {
    if (!receiptText || !receiptText.trim()) return {outcome: 'unavailable', message: 'Receipt not yet available. Choose a receipt file first.'};
    if (!reader || typeof reader.check !== 'function') return {outcome: 'cannot-tell', message: 'The receipt reader could not be loaded.'};
    return reader.check(receiptText, storeText && storeText.trim() ? storeText : emptyStore, expectations || {});
  }};
});
