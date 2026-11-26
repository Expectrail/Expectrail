# Explain incomplete archived Run it results (#244)

## What changed

When a completed gate reports accept but recorded vision answers are incomplete, the sample panel names both the gate’s decision and the reason Run it shows needs-review. Both the previously published evidence and the receipt information remain available. The browser smoke reads the visible evidence iframe selected by its ID and srcdoc attribute. It checks the viewer marker before using the headline.

## What was run

I executed the page’s showResult function in V8 with a DOM stand-in against four published status files. Before the change the November 22 repair said it ended as expected. After the change that repair and the November 25 repair both explained the gate accept and the missing vision answer (134/135). The November 23 clean outcome stayed Accepted (120/120) and the November 24 bug stayed Rejected (134/135). A fixture with a result different from the sample expectation retained that distinction.

I ran the Python smoke comparison in Skulpt against the four resulting panels. All four matched. Substituting the old sample wording produced a disagreement for each incomplete repair. With controlled frame and clock objects the prior headline reader returned Accepted from an unrelated iframe. The candidate returned Rejected from the visible evidence frame and withheld a headline for a hidden frame or a missing viewer marker.

These runs exercised page rendering and smoke logic in memory. On main base `90147026`, the historical baseline fetch completed. The full Linux suite ran 6,120 tests with 57 skips. A separate run with Playwright Chromium installed passed all 28 targeted Run it offline and smoke tests. The public export scan checked 1,401 files with zero errors or warnings. The original queued change’s November 22 browser results are recorded separately on #244. The production service was not dispatched.

## Files

- `docs/run-it/run-it.js`
- `tools/runit_smoke.py`
- `tests/test_runit_offline.py`
- `tests/test_runit_smoke.py`
- `docs/new-work/2026-11-26-run-it-archived-expectation.md`
