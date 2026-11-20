# A hand-written stand-in for `slow-left`, with mirror-inputs metamorphic checks offered (#675)

**No model wrote the proposal.** Its one check is a stand-in (`model: hand-written-stand-in`), so the
reproduction score gives this record no result (`expectrail/repro/score.py`, `STAND_INS`). The record is
here for its `metamorphic` rows, which the generator made itself and which nothing counts.

- `jit-proposal.json`: one check, "walking right 40 ticks before jumping moves the player further right
  than not walking", with the candidate withheld, so it is bound to the bench's report and to no patch.
- `candidate.patch`: the candidate, applied on top of the bug build (the two lines the defect added, removed).
- `jit-run.json`: `jit run --proposal ... --metamorphic` on the real engine (Godot 4.7.2), November 20, 2026.

```
python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/slow-left/report.txt --base bench/jit/public/slow-left/defect.patch \
  --candidate bench/jit/stand-in/slow-left-metamorphic-revert/candidate.patch --proposal bench/jit/stand-in/slow-left-metamorphic-revert/jit-proposal.json \
  --withhold-candidate --metamorphic --out OUT --run-id mm-slow-left-revert
```

The results are in [docs/measurements/675-metamorphic-generate.md](../../../../docs/measurements/675-metamorphic-generate.md).
