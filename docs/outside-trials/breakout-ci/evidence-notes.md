# Evidence handling

The handover retains original before/after logs and local replay records. Repository
copies of pending pointer/menu evidence have machine-specific path prefixes replaced
with `$REPO`, `$WORK`, `$HOME`, `$SCRATCH`, `$TMPDIR` and `$PYTHON`. This changes only
path spellings, not test counts, decisions, geometry, timings or trace bytes. The
historical support scripts are provenance with placeholders; adapt paths before
running them. Original replay/observation digests refer to the original captured
records in the handover, not redacted replay metadata. Trace hashes remain directly
verifiable against the published trace files.

This follow-up's outside-trial JSON/Markdown and geometric derivation need no host
paths. They are linked from report.md. No source game, private material, credentials
or approval is published. CI proof is pending Sean's push and the PR job; local
results are labelled diagnostic.
