# Show the recorded evidence grade beside the verdict (#264)

## What changed

A viewer built directly from findings omitted the evidence grade. Both the folder and the single-file export now show the job's recorded grade beside the verdict, or “Not recorded” if the input supplies none. The observer rule and sandbox description appear with the grade. Their values still come from the findings.

## What was run

- On main `62918117`, the new tests reported four failures across the two test methods. The schema example for findings produced a reject with no grade label in either export. With the change, all 49 viewer tests in the four focused modules passed.
- In system Chromium with JavaScript disabled, at 375 and 1280 px, the November 13 clean and fall-through samples regenerated from their stored payloads both displayed their recorded diagnostic grade. Their banners still showed Accepted and Rejected respectively. A published-findings fixture displayed its recorded reject and “Not recorded”. The grade, observer rule and sandbox details were visible in all six views, with no horizontal overflow. [Sample provenance](../viewer-samples/provenance.json)
- Full unittest discovery ran 5,961 tests in 656.063 seconds and passed with 78 skips. The export scan checked 1,356 files with zero errors or warnings.

## Not done

The two-minute reading trial needs Sean or Timothy to recruit someone unfamiliar with the run. The browser checks used local renders and covered neither a human participant nor a deployment.

## Files

- `expectrail/viewer.py`
- `docs/viewer.md`
- `tests/test_viewer_grade.py`
- `docs/new-work/2026-11-21-viewer-evidence-grade.md`
