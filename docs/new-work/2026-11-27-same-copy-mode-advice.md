# Update same-copy baseline advice when manual paths change (#803)

## What changed

When both selected paths resolve to one project, changing **Enter paths
manually** now refreshes the baseline advice beside the fields. For a
project without an Expectrail config, manual paths allow a deliberate
baseline. Switching back to project configuration removes that advice.
Editing either folder discards the saved pair response.

## What was run

On #813 head `3f239bec`, I ran the shipped JavaScript handlers in V8 with
stand-in fields and a controlled paired-folder response. With an
unconfigured project on both sides, switching modes left the advice from
the starting mode visible in both directions.

I repeated the check with the changed handlers. Across eight combinations
of starting mode, matching or distinct folders, and present or missing
setup, toggling the mode twice gave the expected text. Each case made one
folder-check request. A separate sequence checked a mode change during a
pending reply, a replaced selection, a failed request and a cleared field.
The complete candidate page script also parsed in V8.

## Not done

Chromium and full Linux discovery on this change are pending. The browser
rehearsal now checks the visible notice when the user turns manual paths
off and back on for the same unconfigured project.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-27-same-copy-mode-advice.md`
