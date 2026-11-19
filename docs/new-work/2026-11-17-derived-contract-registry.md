# Derive the v1 contract registry and explain missing ledger entries

## What changed

The v1 registry reads each schema's top-level format constant or derives the
record ID from its schema ID. New v1 schemas need no registration edit. Duplicate
and unreadable declarations name the schema files. All 17 old registry entries
retain their exact kind and filename. Main at 2e014e1 had 46 v1 schema files,
so the complete registry adds 29 entries. The handover contains both dictionaries
and their comparison.

A failing capability check prints copyable JSON for an unlisted command or page.
It names candidate mode rows when the source, module or evidence connects them.
The check's coverage and exit status stay the same.

## What was run

The handover contains the historical fetch reference, the red regression run,
the passing focused run, baseline and final full-suite logs, and the export
scan. The comparison asserts that every v1 file appears once and that the
projection onto all old keys is identical to the old dict.

## Not done

Schema data, the capability ledger and AGENTS.md were outside the change.
The CLI suggests candidate rows and leaves the choice to the builder.

## Files

`expectrail/contracts.py`, `expectrail/capabilities.py`,
`tests/test_contracts.py`, `tests/test_capabilities.py`,
`docs/capabilities-howto.md`, and this entry.
