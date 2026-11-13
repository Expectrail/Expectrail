# One switch, off by default, offers the generator the held-back signals and reach probes (#285)

## What changed
Issue #285 asks for the reproduction rate on the public bench before anything changes, and after
each step. Steps 3 (reach probes, #336) and 4 (three signals, #323) were built before that baseline
was run, so they were held back from the generator with nothing to turn them on.

- `expectrail/jit/offer.py`: one named setting, `baseline` (the default) or `signals-reach`. Under
  `baseline` the generator gets what it got before: the eleven signals and the jit probe library.
  Under `signals-reach` it also gets the three signals of #323 and the eight reach probes of #336
  (the report only orders them).
- `expectrail/jit/intent.py`: the system prompt is built per setting (`system_for`); `SYSTEM` is the
  baseline prompt, the same bytes as on main before this change. The user prompt, the answer parser,
  the Spark call, `propose_to_file`, `from_proposal`, `revise_to_file` and `load_record` all take the
  setting. A proposal records it (`offer`) and is replayed only under it; a revision only under the
  setting of its first round. A proposal or record from before states none and is read as `baseline`.
- `expectrail/jit/run.py`: `generate(offer=...)` uses the setting's probes, writes `settings.offer`,
  records a reach probe's source as `reach`, and generates nothing (`OFFER_MISMATCH`) when the model
  was told about another setting.
- `expectrail/jit/cli.py`: `--offer` on `measure`, `propose`, `revise` and `run`; `measure` also takes
  `--report-file` to order the reach probes.
- `expectrail/repro/score.py` and `python3 -m expectrail.repro score --offer`: a score counts only the
  records of its setting (another setting's record is a row with no result, with that reason), and
  the score record and its page name the setting.
- Contracts: `jit-run.v1` gains optional `settings.offer` and the probe source `reach`;
  `repro-score.v1` gains a required `offer`, and its example has it.
- `.github/workflows/jit.yml`: a dispatch input `offer` (default `baseline`), checked in the plan job
  and passed to every job of a change and to the reproduction score. The known-bugs bench refuses
  anything but `baseline`. No secret, environment, trigger or permission changed.
- `docs/jit.md`, and the docstrings of `reach.py` and `intent.py`, say what is offered under which setting.

## What was run
- The digests of the system prompt, the revision prompt, and one full user prompt (the no-fix
  candidate, a literal report, the jit library with measurements that include held signals) were
  computed on main at b87ff08 and again on this branch: identical
  (`e4ef7a5e…`, `54481018…`, `f0203e6c…`). `tests/test_jit_offer.py` holds them.
- `python3 -m unittest tests.test_jit_offer`: 34 tests, OK.
- The full suite on this branch, merged with main: see the pull request for the count and result.
- No engine run, no model call, no dispatch.

## Not done
- The baseline dispatch and the `signals-reach` dispatch after it: each spends money from main, and
  only Sean dispatches them.
- The evidence records of step 5 are in no setting: they need frames, which the measure job does
  not capture.
- With a real candidate that touches a claimed file, the diff map keeps only that claim's probe
  families, and `reach` is none of them; the reach probes then reach the prompt only for changes
  like the bench's no-fix candidate.

## Files
- `expectrail/jit/offer.py` (new), `expectrail/jit/intent.py`, `expectrail/jit/run.py`, `expectrail/jit/cli.py`
- `expectrail/repro/score.py`, `expectrail/repro/__main__.py`, `expectrail/repro/reach.py`
- `contracts/jit-run.v1.schema.json`, `contracts/repro-score.v1.schema.json`, `contracts/examples/repro-score.json`
- `.github/workflows/jit.yml`, `docs/jit.md`
- `tests/test_jit_offer.py` (new), `tests/test_repro_reach.py`, `tests/test_jit_measure.py`, `tests/test_jit_pipeline.py`
