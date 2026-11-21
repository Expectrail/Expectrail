# What text from judged material reaches a model, written down and tested (#745)

## What changed
- `docs/sam.md` has a new section, "What text reaches a model". It states the invariant as it
  actually holds on main, cites the functions, and classifies every vision backend. It corrects one
  point of the trace on #745. The default text path (`FramesObserver`, the visibility checks, Run it)
  does send one spec field to the model: the approved object's noun phrase (`prompt`, for example
  "blue robot"). It never sends `instruction`.
- `docs/verification-risks.md` section 10 has a short paragraph on the same trust boundary, for text.
- `agents/calibration_observers.py`: `name_proposals()` used to pass a texture file name or node
  name through with a newline, punctuation or any other character. Now it proposes a name only when
  the name is lowercase ASCII words one space apart, at most 64 characters, after splitting camel
  case and `_`/`-`. Any other name is left out whole, never rewritten. These names are asked of a
  recording only today, so no live request changed.
- `tests/test_untrusted_text.py`, 14 tests. Each part of the invariant has one that fails if it
  stops holding:
  - anchored wire text is coordinates only, even for a spec whose `instruction` and `prompt` carry
    an injection;
  - the anchored modules call only `segment_at`/`segment_in`;
  - the text path sends only object prompts, in a one-message request;
  - every backend is classified, and a vision-language model alone is refused for a verdict;
  - `both` can only remove;
  - verdict modules import no text-model module;
  - calibration names are words.

## What was run
- `python3 -m unittest tests.test_untrusted_text`: before the `name_proposals` change, 3 of 14
  failed (the hostile-name cases). After it, 14 OK.
- Six mutations, each caught by the new tests:
  - an anchored `look` asking `segment(frame, spec["instruction"])`;
  - `observers.py` importing `expectrail.providers`;
  - `_prompts` appending the instruction;
  - a seventh backend added unclassified;
  - `BothClient` returning SAM's boxes when Glimmer sees nothing;
  - Glimmer alone allowed for a verdict.
  These mutations were made locally and reverted. `agents/sam_observations.py` is pinned by the
  mutation registration and is not changed by this pull request.
- `python3 -m unittest tests.test_observer_calibration`: OK.
- Full suite: see the pull request.

## Not done
- No sanitiser, blocklist or escaping, as the issue scopes it.
- `contracts/test-spec.schema.json` still allows any string as an object `prompt`. A limit there
  (one line, short) would be a contract change across every spec; not done here.

## Files
- `agents/calibration_observers.py`
- `docs/sam.md`
- `docs/verification-risks.md`
- `tests/test_untrusted_text.py`
- `docs/new-work/2026-11-21-untrusted-text-invariant.md`
