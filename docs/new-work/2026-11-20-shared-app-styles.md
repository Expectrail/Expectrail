# Share the local app’s visual styles with the hub (#709)

## What changed

Extracted the app’s styles into a static stylesheet. It preserves its native controls, panels, result formatting and mobile layout. Named classes let the hub use those components without copying the app’s element IDs.

## What was run

The full suite ran 5,660 tests in 639.545 seconds with 78 skips and no failures or errors. At 375 px and 1280 px, Chromium compared 48 computed properties on the local app page with each stylesheet. They matched at both widths. Keyboard focus was visible, the page fit its viewport, and the link-button, native disabled button and reject label had their expected styles.

## Not done

The app still uses its embedded styles. Builder two owns its integration. The signed-out hub and its recorded screens follow separately.

## Files

- `docs/assets/expectrail.css`
- `docs/assets/expectrail-css.md`
- `docs/new-work/2026-11-20-shared-app-styles.md`
