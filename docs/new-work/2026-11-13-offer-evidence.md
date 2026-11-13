# A third offer setting gives the proposer what the bug build changes, in the record and on the screen (#285)

## What changed
Issue #285, step 5: the proposer should write a check about a difference it can see. The evidence
record (`expectrail/repro/evidence.py`, #363) already says, for one bug build along every probe,
which record fields differ and from which tick, which signals moved, and on how many frames the
picture differs, from which frame and where. Nothing offered it to the generator.

- `--offer signals-reach-evidence` (`expectrail/jit/offer.py`): everything `signals-reach` offers, and
  that evidence. Off by default.
- The measure step, under this setting and with a bug build, also replays every probe with frames
  (clean game twice, bug build once; `--evidence-jobs`) and writes `repro-evidence.json`. If it
  cannot, the step fails rather than letting a run look like it had the evidence.
- The propose and revise steps take `--evidence`. `offer.attach_evidence` re-checks the file as
  untrusted data (schema, its own sums, made for these base patches) and puts
  `evidence.for_proposer`'s summary on at most six probes as `differs`. The prompt shows it under
  this setting only, and only numbers and names from closed lists (probe ids, trace fields, signals).
- The system prompt under this setting is `signals-reach`'s with one paragraph more. That paragraph
  says checks still read only signals, because the closed language has no pixel predicate yet (#286).
- `jit.yml`: `offer` input and plan check take the new value. Under it, the measure job installs
  `xvfb libgl1-mesa-dri libglx-mesa0` through `apt-install`, may run 75 minutes instead of 30, and
  uploads `repro-evidence.json` beside the measurements. Propose and revise pass `--evidence` when
  the file is there. No secret, permission or environment changed.
- `contracts/jit-run.v1.schema.json` and `contracts/repro-score.v1.schema.json`: the `offer` enum gains
  the value. The writer (`run.generate`) and readers (`intent.load_record`, `repro.score`) take any
  setting `offer.OFFERS` names, unchanged.
- `offer.py` is the one file under `expectrail/jit` that reads the evidence module, as it is for reach.

Decisions:
- **Per-probe, not a separate block.** The evidence rides on the probes like the measurements. That
  way it goes through propose, revise and the budget estimate without new arguments, and a probe the
  diff map drops takes its evidence with it.
- **No observer column in the prompt.** The measure job reads no recorded answers. Reading them in
  CI would need a recording first (Sean's call, comment on #285).
- **Fail the measure job, not the proposal.** A missing measurement lets the proposal go ahead with a
  note, and that stays. A missing evidence file under the evidence setting stops at measure, because
  a rate counted under this setting would otherwise mix runs that had it with runs that did not.

## What was run
- Digests of the `baseline` and `signals-reach` system prompts, revision prompt and a full user prompt,
  computed on main at f9c364b before the change, are identical on the branch
  (`tests/test_jit_offer.py`, `tests/test_jit_offer_evidence.py`).
- `python3 -m unittest tests.test_jit_offer_evidence`: 24 tests, OK. They include the four evidence
  records recorded on the real engine for the public bench (`bench/jit/public/evidence-*.json`), each
  attached to its defect's library. For `coin-stays`, every probe where both differ shows the picture
  change before the record's `coins`.
- Full suite on the branch merged with main ada0dd3: `python3 -m unittest discover -s tests -t .`,
  2,926 tests, OK, 27 skipped.

Not run: the engine (the frames in the measure job, here or in CI), any model, any dispatch.

## Not done
- The baseline dispatch (Sean), then a run under `signals-reach`, then one under
  `signals-reach-evidence`. Nothing was dispatched.
- The measure job's frame capture under this setting has not run in CI. The capture smoke job renders
  with the same packages.
- An observer's recorded answers in the evidence a proposer sees (needs a first recording, Sean's call).
- Pixel predicates themselves (#286).

## Files
- `expectrail/jit/offer.py`, `expectrail/jit/intent.py`, `expectrail/jit/cli.py`, `expectrail/repro/evidence.py` (docstrings)
- `.github/workflows/jit.yml`
- `contracts/jit-run.v1.schema.json`, `contracts/repro-score.v1.schema.json`
- `docs/jit.md`
- `tests/test_jit_offer_evidence.py` (new), `tests/test_jit_offer.py`, `tests/test_repro_evidence.py`
- `docs/new-work/2026-11-13-offer-evidence.md`
