# The evidence viewer

One folder that answers, without opening JSON: what failed, where and when, expected against
measured, how sure, and how to reproduce it (#264). The code is `expectrail/viewer.py`.

## Where it is

- The gate writes `viewer/` beside `review/` and `findings.json` in its output, on every run.
- `expectrail report JOB` writes the job's viewer to `<jobs root>/jobs/<id>/viewer/index.html` and
  prints that path. It is written for every finished job, including one that was cancelled, failed
  or could not be carried out, so every state the job model has gets a page. `report --json` still
  prints the job's status and nothing else.

The folder opens from disk (`file://`) and from a web site the same way: the evidence is embedded in
`index.html`, so nothing is fetched, and the page's Content-Security-Policy refuses every request but
its own frame files. "Run it" on expectrail.tech (#265) and the local app (#370) open this folder.

## What it shows

- **The state, first.** One of: accepted; rejected (a check fails); needs review because an observer
  could not decide; needs review because a replay did not run to the end; not verified because
  Expectrail cannot verify the project or request; not verified because the run could not be
  carried out; not verified because no check ran; cancelled; running. Only an accept is green.
- **The job's decision wins.** When the job and its evidence disagree, the page says needs review and
  why; it never picks the kinder of the two. An empty result (no check, no evidence) is never shown
  as success, and a record that says accept over a check that did not pass is not shown as accepted.
- **Findings, earliest first.** The inspector opens at the first failing frame of the earliest
  finding: the frame before the change and after it, side by side, on the same frame number, with
  the captured frames around it (six either side). Overlays draw the boxes the check measured and
  the boundary line; they can be turned off so the raw pixels show.
- **A timeline per side.** The value the check measures in each frame against its tolerance, with
  frames where an object was not found and frames with nothing to compare marked. It is measured
  from the same engine's record the evaluator judged, by the evaluator's rules, and it is shown only
  when it agrees with the evaluator's verdict (its first failing frame is the verdict's; a pass has
  none). Otherwise it is left out and the page says so. It decides nothing.
- **Run facts and what was not tested:** head and base, the policy (which checks, from which
  commit), which observers judged, the sandbox, held-out routes as counts only.
- **The reproduction command**, from the job's request (the job viewer only).

## Keys

`←` `→` step a captured frame (`Shift` for five), `Home` `End`, `f` the first failing frame, `o`
overlays on or off, `n` `p` the next or previous finding. Clicking a timeline jumps to that frame.

## Not yet

A single-file export that opens offline, a model-written explanation linked to evidence ids, the
viewer for a real failing and a real passing run published under `docs/`, and the two-minute trial
with one person who has not seen the run.
