# Engine readings at the first visual failure

## What changed

For #819, the frame captions identify each observer and show its recorded value on each side. When the visual verdict failed and the export contains no visual timeline, the inspector explains the gap and draws the available engine overlays. Opening the finding by button or keyboard preserves the frame and verdict.

## What was run

All 57 focused viewer tests passed. The keyboard harness covers zero, a missing reading on one side, and a visual gap alongside an engine measurement.

Playwright Chromium opened standalone exports regenerated from the original public stuck-fade and restored records. Both stuck-fade captions showed about −27.565 px at frame 0, and the visual finding still reported the player missing in 83 of 120 frames. The restored captions showed about 2.352 px Before and 0.754 px After at frame 20. Both frame images in each export decoded. No fresh captures were generated.

The historical baseline was fetched. Full Linux discovery passed with 6,120 tests and 57 skips after correcting the work-log headings. The export scan checked 1,402 files with zero errors or warnings.

## Standalone browser reproduction

GPT builder two reran the standalone browser check on `b423ca676218b37202ea469b3bc643042ba6bf49`. The direct Actions download returned HTTP 403 here too. The GitHub connector’s artifact-download action successfully returned the public [outside-trial ZIP, artifact 14639209497](https://github.com/Expectrail/Expectrail/actions/runs/44759316826/artifacts/14639209497). Save that ZIP as `/tmp/outside-trial.zip`.

From the checkout at the tested commit, with the Python Playwright package installed:

```sh
mkdir -p /tmp/two819-art
unzip -oq /tmp/outside-trial.zip 'repair-pair/restored-evidence.html' 'repair-pair/stuck-fade-evidence.html' -d /tmp/two819-art
PLAYWRIGHT_BROWSERS_PATH=/tmp/two244-pw python3 -m playwright install chromium --only-shell
PYTHONPATH="$PWD" PLAYWRIGHT_BROWSERS_PATH=/tmp/two244-pw python3 /tmp/two819-browser.py
```

Contents of `/tmp/two819-browser.py`:

```python
from pathlib import Path
from playwright.sync_api import sync_playwright
from tests.test_viewer_timeline import embedded
from expectrail import viewer

root = Path('/tmp/two819-art/repair-pair')
for sample in ('stuck-fade', 'restored'):
    data = embedded((root / f'{sample}-evidence.html').read_text())
    (root / f'{sample}-candidate.html').write_text(viewer.render(data))
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox'])
    for sample in ('stuck-fade', 'restored'):
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((root / f'{sample}-candidate.html').as_uri())
        if sample == 'stuck-fade':
            page.get_by_role('button', name='first failing frame').click()
        readings = page.locator('figcaption').all_text_contents()
        print(sample, readings)
        images = page.locator('.stage img')
        assert images.count() == 2
        decoded = [images.nth(i).evaluate("(image) => image.complete ? [image.naturalWidth, image.naturalHeight] : [0, 0]") for i in range(2)]
        assert all(width > 0 and height > 0 for width, height in decoded)
        print("Decoded image sizes:", decoded)
        if sample == 'stuck-fade':
            assert len([caption for caption in readings if 'frame 0' in caption and 'Engine measured ≈-27.565' in caption]) == 2
            assert page.get_by_text('This export contains no visual timeline for this check.').is_visible()
            assert '83 of 120' in page.locator('body').inner_text()
        else:
            assert any('frame 20' in caption and '2.352' in caption for caption in readings)
            assert any('frame 20' in caption and '0.754' in caption for caption in readings)
        assert not errors, errors
        page.close()
    browser.close()
```

Observed output, exit 0:

```text
stuck-fade ['Before the change, frame 0', 'After the change, frame 0', 'Before the change, frame 0, sha256 1119c586bdcf8496. Engine measured ≈-27.565 px (ok)', 'After the change, frame 0, sha256 e66aa8bc3e364645. Engine measured ≈-27.565 px (ok)']
Decoded image sizes: [[530, 495], [530, 495]]
restored ['Before the change, frame 20', 'After the change, frame 20', 'Before the change, frame 20, sha256 5913b34c463f8067. Engine measured ≈2.352 px (ok)', 'After the change, frame 20, sha256 e1b03824a769f2e6. Engine measured ≈0.754 px (ok). Vision measured ≈0.518 px (ok)']
Decoded image sizes: [[530, 495], [530, 495]]
```

I also built the queued #264 viewer PR #833, and based this change on its merged renderer after the hub builder [adapted and released the caption patch](https://github.com/Expectrail/Expectrail/issues/819#issuecomment-7189924487). That handover records the coordination.

## Files

- `expectrail/viewer.py`
- `tests/viewer_keyboard.cjs`
- `docs/new-work/2026-11-26-visual-failure-engine-readings.md`
