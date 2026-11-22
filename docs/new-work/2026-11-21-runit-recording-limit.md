# Explain how a missing recorded answer affects a visitor's run (#244)

## What changed

The Run it introduction used to say that a missing answer yielded needs-review. It now explains that a missing required visual answer blocks acceptance, while a failing check can still reject the change. The page links to the recorded-vision ledger row and describes the cost claim specifically as no live model call.

## What was run

- The [published status](https://github.com/Expectrail/Expectrail/blob/8adada4aeaf3f3c7cb777a4ea461265b82aa683f/6128e640-9cad-40ef-9fda-dda350190c2d/status.json) for November 21 shows 134 of 135 answers and a reject. The [findings](https://github.com/Expectrail/Expectrail/blob/8adada4aeaf3f3c7cb777a4ea461265b82aa683f/6128e640-9cad-40ef-9fda-dda350190c2d/findings.json) record that the smoke check failed on engine evidence and vision was not asked about that after-change check.
- Chromium opened the local page at 375 and 1280 px with JavaScript disabled. At both widths the paragraph was visible, the link identified the recorded-vision ledger row, and the page fit the viewport.
- The offline site check opened 19 pages in Chromium with zero findings. The public export scan checked 1,330 files with zero errors and warnings.
- The first full run found one failure in 5,949 tests. Restoring the established wording for a sample without recordings made all five `tests.test_runit_links` tests pass.
- `python3 -m unittest discover -s tests -t .` passed all 5,949 tests with 78 skips in 624.278 s.
- After rebasing onto main at `07b66e7e`, the full suite ran 5,956 tests in 650.719 seconds and passed with 78 skips. The public export scan checked 1,338 files with zero errors or warnings. The system Chromium rerun again opened 19 pages with zero findings, and the corrected paragraph fit at both widths with scripts off.

## Not done

This change uses an existing published run. The stored status does not establish why the recording lacked one answer.

## Files

- `docs/run-it/index.html`
- `docs/new-work/2026-11-21-runit-recording-limit.md`
