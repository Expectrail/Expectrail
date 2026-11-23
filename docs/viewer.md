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
- **Evidence grade.** Beside the verdict, the viewer shows the grade saved by the job. A viewer built
  from findings alone says “Not recorded”, including when the findings accompany a verified receipt.
  The observer rule and replay sandbox details come from the findings.
- **The job's decision wins.** When the job and its evidence disagree, the page says needs review and
  why; it never picks the kinder of the two. An empty result (no check, no evidence) is never shown
  as success, and a record that says accept over a check that did not pass is not shown as accepted.
- **First difference and first failure.** In a finding, the inspector opens at the first tick where the
  engine recorded different before and after values for the same check and bound. Missing readings
  cannot establish a difference. The first failing frame is labeled separately. If paired measurements
  do not show a difference, the inspector opens on the finding's frame, when available. A measured
  difference alone does not change the verdict. The before and after pictures always use the selected
  tick. An unavailable picture is labeled, even if a nearby frame exists.
- **Without JavaScript.** Expand a measurement table to see the before and after values for each
  recorded window tick, their bounds and gaps. Engine and vision readings have separate tables.
  The selected pair of pictures opens without scripts. The reproduction command appears above
  the measurements. With scripts, **Step through frame** opens the interactive inspector.
- **A timeline per side.** The value the check measures in each frame against its tolerance, with
  frames where an object was not found and frames with nothing to compare marked. It is measured
  from the same engine's record the evaluator judged, by the evaluator's rules, and it is shown only
  when it agrees with the evaluator's verdict (its first failing frame is the verdict's; a pass has
  none). Otherwise it is left out and the page says so. It decides nothing.
- **The visual observer has its own timelines.** A public check's saved visual observations and
  verdict must match the observation digest in its findings row and the spec digest. Missing,
  changed or linked evidence is left out with a note. Engine measurements never stand in for
  visual measurements. If vision alone found the failure, its overlays are selected first;
  the measurement-source button switches between engine and vision boxes.
- **Gaps and coverage.** A frame absent from the observations is a grey band and a break in the
  line. An observed frame with no object is marked separately. Frames with no overlapping
  reference are marked as not exercised. The recorded coverage status is shown without changing
  the verdict. Points are capped; a truncated timeline says so.
- **When vision did not run.** The page says so, including `PROVIDER_FAILED` when the job records
  it. A recorded engine failure remains a reject. A provider which was called but returned no
  usable answer is described that way, rather than as never called.
- **Run facts and what was not tested:** head and base, the policy (which checks, from which
  commit), which observers judged, the sandbox, held-out routes as counts only.
- **The reproduction command**, from the job's request. Run it supplies its public sample id, so
  those viewers show `python3 -m expectrail.runit run --sample NAME --out NAME-run`, not temporary
  checkout paths. That command reuses recorded vision answers and makes no model call.

## Offline export and real examples

Every folder also has `evidence.html`: the same viewer with its checked PNG frames embedded.
It opens offline without a server or neighbouring files. The CSP is unchanged.

- [The supplied clean run: accept](viewer-samples/clean.html).
- [The supplied fall-through run: reject](viewer-samples/fall-through-bug.html).
- [Source records and provenance](viewer-samples/provenance.json).

Sean supplied these real Run it outputs from the architect's Linux run with Godot 4.7.2 and
xvfb-run, described in the supplied README as made on #416's branch. Their status records name
commit `c5d1e53344b0f484c0d1c082aa60f41507932fc8`; that value is preserved. This slice changes their
presentation and reproduction command, not the recorded verdicts, job facts or frame bytes.
The clean export has no kept images; the rejecting export embeds 24 frames. Both contain engine
measurements and recorded visual results, but neither includes raw visual measurements. Their
visual panels say that those measurements were not supplied; no timeline was reconstructed or
guessed from a pass/fail label. New gate runs include the visual timelines when their saved
observations and verdicts can be verified.

## A written explanation

A job folder may hold `explanation.json` (`expectrail.explanation/v1`,
[schema](../contracts/explanation.v1.schema.json)). `expectrail report` then adds an
**Explanation** section below the findings. Each point names the evidence it is about, and a
finding's id is a button that opens that finding. The page says who wrote it (the model, and
whether its answer was replayed from a recording) and that it decides nothing.

It is shown only when `python3 -m expectrail.explanation check FINDINGS FILE` passes:
- its decision is the verifier's and the record's, and it was written for this record (`recordSha256`);
- every id it cites is in the record (a finding's id, or `check:<spec>@<route>`), and every verdict it states is the record's;
- the text is printable ASCII, and every number in a point appears in the evidence that point cites;
- **every word is one Expectrail can match**: a short fixed list of words that cannot carry a claim
  (articles, prepositions, "is", "before", "after", and nouns such as "frame" and "route"), the names of the evidence the point cites, and the verifier's own
  wording of that evidence (a finding's comparison and reason). A spec's name counts as a name; it
  is never split into words to make a claim. The check allows words rather than refusing them,
  because a list of words to refuse can never be finished;
- a point can say "fails" or "regression" only if every cited id failed after the change. It can say
  "passes" or "fixed" only if every cited id passed. The point must state at least one matching
  after verdict. “Accepted” requires an accepted run and a pass on every cited check.
  “Rejected” requires a rejected run and a failure on every cited check. A route or spec whose
  name is a verdict word can still be identified by its full `check:<spec>@<route>` ID. Negations and words of certainty
  ("not", "no longer", "proves", "all", "always") are never allowed;
- "same" or "unchanged" needs every cited verdict to be equal before and after the change, and
  "difference" or "changed" needs one that differs. Words that limit or widen what the evidence
  covers ("only", "also", "other", "than") are never allowed.

This is a word-level check. It withholds every case found so far that contradicts the record, but a
sentence made only of allowed words could still mislead in a way the check does not see; that is why
the record's own verdicts are printed under every point.

Under each point the page prints the recorded verdicts for every cited id ("From the
record: … pass before the change, fail after the change"). The model's words are shown beside the
record's, never in place of them.

Anything else is **withheld**. The page then shows why, and none of the explanation's text. The
banner, the decision, the reasons and the exit code never change because of an explanation.

`python3 -m expectrail.explanation prompt FINDINGS` prints the question for a model.
`from-answer FINDINGS ANSWER --model NAME [--recorded] --out FILE` turns the answer into the file.
Expectrail fills in the decision and the record's digest, never the model. No model is called by
any of these commands. Asking one live, with a budget, is not built yet.

## Keys

`←` `→` step a captured frame (`Shift` for five), `Home` `End`, `d` the first measured difference, `f` the finding’s frame, `o`
overlays on or off, `n` `p` the next or previous finding. Clicking a timeline jumps to that frame.

## Not yet

The two-minute trial still needs a person who has not seen the run. Ask them to find the failed
relation and its reproduction command in the failing sample, then record the elapsed time on
[#264](https://github.com/Expectrail/Expectrail/issues/264).
No model is asked for an explanation yet: the commands above format and check one, and the tests use a stand-in answer.
