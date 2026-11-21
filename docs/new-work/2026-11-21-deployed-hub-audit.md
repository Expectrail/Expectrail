# Checking the deployed hub (#709)

## What changed

Compared the recorded verify screen and the local app at main `1f6ad434`. The hub uses the shared site stylesheet and hub stylesheet. The local app defines its own CSS in the page template. Both show project selection, verification and result sections with separate markup. The recorded verify screen omits Past runs. The project hub lists recent verifications instead. The local folder chooser, inspection, verification controls and job history work on the developer’s machine. The site shows dated, read-only examples of those tasks. The local app also exposes optional repair settings, progress, sandbox details and per-job evidence links. The hub instead presents a project overview and links to published review and evidence pages.

## Files

Only this work log changed. Files compared: `docs/hub/index.html`, `docs/hub/verify.html`, `expectrail/app_page.py`. The public root returned HTTP 200. Browser verification uses the existing `agents.check_pages.check_root` and `check_hub` functions against the deployed HTTPS origin at widths 375 and 1280 with page JavaScript disabled.

## Not done

The independent nightly confirmation and Sean’s decision on the root page remain open. This entry records an audit only.

## What was run

21 November 2026

Python’s HTTPS client verified the connection and returned HTTP 200 for the root, hub, recorded verify, Breakout setup, accepted result and repair evidence pages. Chromium initially stopped at the root with `ERR_CERT_AUTHORITY_INVALID`. With browser certificate errors ignored for this navigation check, both existing checks returned empty findings lists. The links were visible at both widths and reached the expected screen headings with page scripts off. This run used a desktop browser with a phone-sized viewport. A physical phone and the scheduled nightly job were outside this run.

At both widths, the visible root links labelled Verify “Recorded 17 Nov 2026”, setup “Recorded 16 Nov 2026”, the accepted result “Recorded 13 Nov 2026”, and repair “Fixture, published 14 Nov 2026”. The repair link describes its stand-in fixer. An initial probe that expected the word “Recorded” on every link failed on that more specific fixture label.

Full suite on d5b1e8f4: 5946 tests in 652.012 seconds, OK (skipped=79).
