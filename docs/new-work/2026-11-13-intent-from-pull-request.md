# The gate reads a change's intent from its pull request, and the trusted job checks it (#284)

## What changed
Second slice of #284. The first (#355) gave the gate `--intent fix|change|none`; on a pull request
nothing passed it, so the gate always ran with `none`.

- `expectrail/gate/intent.py` (standard library only) reads what a pull request declares: a label
  `intent:fix`, `intent:change` or `intent:none`, or a description line that starts
  `Expectrail-Intent:`. Nothing declared is `none`; with several, the strictest wins; a value that is
  not one of the three is `fix`. So no label or line can make acceptance easier than leaving it out.
  `python3 -m expectrail.gate.intent --event FILE` prints the intent; an event file that cannot be
  read prints `fix`.
- The verify action takes `intent` (default `from-pull-request`) and passes it to the gate, read from
  the `pull_request` event file.
- The trusted comment job reads the declaration again from the pull request it already fetches, and
  when the pull request declares a fix and the record was judged as anything else, it shows "the
  evidence could not be used" instead of the verdict. A reject is still shown, and so is a record
  judged more strictly than declared. The comment job's permissions are unchanged.
- "Expectrail verify" also runs on `labeled`, `unlabeled` and `edited`, so a declaration added after
  a push is judged by a new run.
- The correction the merge guard asked for on #355: an unverified fix's first reason now starts
  `repair-not-demonstrated:` in every case. When no check ran, "no checks ran" came first; when the
  run stopped, the stop reason came first. The #355 work-log entry and description said otherwise
  for those two cases; the code now matches the sentence, and `docs/ci-gate.md` says when it changed.

## What was run
- `python3 -m unittest tests.test_gate_intent_from_pr tests.test_gate_intent`: 58 tests, OK.
- The full suite on the branch merged with main: see the pull request description for the count.
- Not run: the verify or comment workflow on GitHub with a declared intent. The first pull request
  labelled `intent:fix` that touches the gate's paths will be its first run.

## Not done
- A pull request that links a bug issue is not treated as a fix: the trusted job would need
  `issues: read` to see the linked issue's labels, which only a person may add (question on #284).
- `agents/review_change.py` onto the shared rule, the `expectrail verify` flag, and the counts on
  `bench/jit/known/` before and after.

## Files
- `expectrail/gate/intent.py` (new)
- `expectrail/gate/comment.py`, `expectrail/gate/record.py`, `expectrail/gate/verify.py`
- `.github/actions/expectrail-verify/action.yml`, `.github/workflows/expectrail-verify.yml`
- `docs/ci-gate.md`
- `tests/test_gate_intent_from_pr.py` (new), `tests/test_gate_intent.py`
- `docs/new-work/2026-11-13-intent-from-pull-request.md`
