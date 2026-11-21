# Replay frozen public proposals against the current validity rule (#285)

## What changed

Recorded a fresh, trace-only replay of six public cases on main at da633d5. The sample was chosen
to check five predicted losses from the do-nothing audit and one previously retained case. It
informs Q1 and Q7 in #282.

## What was run

- Fetched the required historical commit and installed the SHA-512 checked Godot 4.7.2 binary.
- Ran the normal JIT replay entry point on six archived sets of predicates, with no model or SAM
  requests. Verified the reports, patches, predicates, applicability and 43 route digests against the
  committed baseline records.
- Ran 282 fresh trace replays. All 29 historical catches in the five predicted cases passed the
  do-nothing control and were dropped. Gun-cooldown retained four of six strong catches.
- Compared all six table rows with the source and replay records. Checked relative links and the
  reproduction code block's Bash syntax.
- `python3 -m unittest discover -s tests -t .` passed. Ran 5,725 tests with 82 skipped.
- The public export scan reported zero errors and warnings across 1,301 files.

## Not done

Bubblewrap's UID setup was refused by the local host. The advisory measurement used the harness's
automatic fallback. The live public reproduction measurement remains recorded as open in #285.

## Files

- [Frozen proposal replay measurement](../measurements/285-frozen-proposal-replays.md)
- [Verification risks](../verification-risks.md)
- This work-log entry.
