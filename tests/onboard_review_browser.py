"""Optional browser check, using only invented temporary specs (requires Playwright + Chromium).

python3 -m tests.onboard_review_browser --chromium /usr/bin/chromium
It downloads synthetic answers but never invokes an approval writer.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from expectrail import onboard_page, onboard_review as review
from tests.test_onboard_review import HumanReviewTest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--chromium',required=True)
    args=parser.parse_args();fixture=HumanReviewTest();fixture.setUp()
    try:
        path=fixture.tmp/'page.html'
        path.write_text(onboard_page.render(fixture.record,fixture.details,fixture.state,fixture.manifest,review.sha(fixture.manifest.read_bytes())))
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            context=browser.new_context(accept_downloads=True,offline=True)
            page=context.new_page();errors=[];external=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:external.append(request.url) if request.url.startswith(('http:','https:')) else None)
            # Managed Chromium in the build workspace blocks file navigation by policy.
            # Render the identical standalone bytes in an offline in-memory document.
            page.set_content(path.read_text());page.wait_for_selector('#save-answers')
            assert page.locator('svg.snapshot').count()>=4
            assert page.locator('svg.snapshot image').count()==1  # the same synthetic PNG serves art and frames
            assert page.locator('svg.snapshot use').count()>=2
            page.locator('#save-answers').click();assert "person's name" in page.locator('#save-status').inner_text()
            page.locator('#person-name').fill('Synthetic Browser Test Person')
            page.locator('#save-answers').click();assert 'every object' in page.locator('#save-status').inner_text()
            page.locator('input[data-kind="objects"][value="yes"]').check()
            page.locator('input[data-kind="checks"][value="yes"]').check()
            with page.expect_download() as event:page.locator('#save-answers').click()
            dest=fixture.tmp/'synthetic-browser-answers.json';event.value.save_as(dest)
            answer=json.loads(dest.read_bytes());assert answer['person']=='Synthetic Browser Test Person'
            assert answer['checks']=={'throwaway-review-only':True}
            assert 'approval' not in json.loads(fixture.spec_path.read_bytes())
            assert not errors and not external,(errors,external)
            browser.close()
        print('PASS: offline document (identical HTML bytes), reused raster previews, boxes, mandatory name/decisions, synthetic answers download; no approval, no external requests.')
    finally:fixture.doCleanups()


if __name__=='__main__':main()
