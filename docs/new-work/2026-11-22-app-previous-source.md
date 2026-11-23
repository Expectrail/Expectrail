# Identify the previous Git selection in app history (#370)

## What changed

The app now saves the original project folder and full parent commit when the
developer verifies a temporary Before copy opened by the picker. The current
result and Past runs can identify that selection after the copy has been
deleted. The worker still verifies folder snapshots. The additional field
lives in the existing local display file. Ordinary folder selections and older
records use the same reader as before.

## What was run

On November 22, an installed-wheel rehearsal on Linux combined the queued app
with the previous-commit picker. The public kinematic-character project failed
its ground check at frame 44 with an uncommitted collision change. Closing the
app removed its temporary Before. The reopened result only named that deleted
folder. The request, status and findings digests stayed unchanged.
[Run record](https://github.com/Expectrail/Expectrail/issues/370#issuecomment-7079373816)

The new HTTP regression failed on the queued app head because the Before label
was a temporary path. With the fix, 11 HTTP, browser and picker tests passed.
The regression uses a different After folder to check which project the label
names. It checks the selection on reopen, and checks that the local source
information stays out of the verifier request and the downloadable evidence.
A malformed commit in the local display file falls back to the recorded
checkouts. The unaided participant trial remains open.

With the fix in the locally combined wheel, Chromium reopened job
`28a11e935f664069bbe1f5c7158577ca` in a second app process. Past runs showed
the original project and its full parent commit after the temporary copy was
removed. No job or copy was created on reopen. The working game, saved request,
status and findings kept their digests.

## Files

- `expectrail/app.py`
- `tests/test_app_selected_folders.py`
- `docs/new-work/2026-11-22-app-previous-source.md`
