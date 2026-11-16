# Spec drafting and the model month (#267)

Every real spec-drafting sender requires `EXPECTRAIL_SPEC_USD_CAP` and holds $0.05
before each request. This includes Meta, the open endpoint, feedback's OpenAI
transport when drafting a spec, and the provider transport. Provider HTTP retries,
schema fallbacks and corrected drafts each hold again. Missing, invalid or exhausted
caps raise `BudgetStop` before a send. These holds are reservations, not vendor bills.

Fixture transports need no cap. When a spec cap is set they count against it too.
The built-in senders account at the request boundary. They carry `_spec_budgeted`
so `draft()` only adds accounting for stand-ins; wrappers should use `functools.wraps`
(as `agents.spark_open.counting` does) to preserve that marker and avoid double holds.
The real sender always checks its cap even when called directly or wrapped.
Feedback classification and transcription are outside the spec-drafting cap.

## Opt-in month total

Set `EXPECTRAIL_MODEL_MONTH_LEDGER` to a durable file **outside the checkout**, shared
by all workers that should share a month total. With it unset, only the per-process
caps apply. The new `expectrail.model-month/v1` ledger has a combined $200 limit for
Glimmer, Muse, triage and spec drafting; vision retains its separate $200 ledger and
`EXPECTRAIL_VISION_MONTH_LEDGER` variable.

On the first held request for a role in a process, the ledger reserves that role's
whole process cap. Later requests for that role do not reserve it again. Raising a
cap reserves the difference. A new process reserves again, even for the same
`EXPECTRAIL_JOB_ID`, because it starts a new request counter. Entries name the role,
job id, reserved dollars and UTC timestamp. Months follow UTC; a valid older month
starts a new total. A future month is a stop.

The file's parent must be writable, including for `<ledger>.lock` and temporary files.
A stable `flock` sidecar serializes Linux processes, and a flushed, synced temporary
file replaces the ledger atomically before a request can proceed. Keep the ledger
and its lock on a local filesystem with working file locks and atomic rename; do not
remove the lock while workers run. An unreadable file, empty or invalid existing file,
invalid old-month file, or failed write raises a named `BudgetStop`. A ledger that
vanishes after this process reserved against it also stops. These failures never
silently become an empty month.

The ledger conservatively keeps reservations after a failed model call or process
exit. It does not reconcile vendor bills or refund unused caps. A person chooses the
durable ledger location and supplies workflow caps; this change edits no workflow.

`job-budget.v1` now includes `capsUsd.spec` and the `spec` role in the `drafting`
phase. Its existing writer and reader use the shared role table; `build_job_budget`
was not edited. The schema's original formatting is preserved.
