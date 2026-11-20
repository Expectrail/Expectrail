# Public frozen proposals under the do-nothing validity rule (#285)

The [control audit](675-do-nothing-control.md) used saved clean outcomes and predicted that five
public defects would lose every historical strong catch. This experiment runs those five frozen
proposals through the current replay path and includes gun-cooldown as a comparison expected to
retain a catch. Case selection targets the prior finding. The full public reproduction rate remains
an open measurement.

## Inputs

- Source records from [the public baseline](https://github.com/Expectrail/Expectrail/actions/runs/43465090517),
  committed under [repro](../../bench/jit/recordings/public-43465090517/repro).
- Defects and reports from [the public manifest](../../bench/jit/public/defects.json), with the same
  [comment-only candidate](../../bench/jit/public/no-fix.patch) as the baseline.
- Current code at [da633d5](https://github.com/Expectrail/Expectrail/commit/da633d58b41fecad074cbec672213a15d9075e60).
  Godot 4.7.2 stable, pinned release ZIP checked by the harness installer.
- The old predicate and applicability values come from each record's proposed entries. All applied
  probes in these six records came from the library. Before replay, the report, patch and compiled
  route digests were compared with the saved inputs.

The baseline showed the candidate to the model. This experiment replays those checks and routes
with the current keep rule, three repetitions and the original limit of eight generated near
misses. Its scope is the replay of existing checks. The live report-only generation run is tracked
separately in [#285](https://github.com/Expectrail/Expectrail/issues/285).

## Results

All six runs completed, using 282 headless trace replays. All 35 checks passed the clean reference
three times. The do-nothing control passed three times for 31 checks, which the validity rule
dropped before near-miss and candidate evaluation.

| Public defect | Saved strong catches | Current strong catches | Dropped by the control | Fresh replays |
| --- | ---: | ---: | ---: | ---: |
| air-jump | 6 | 0 | 6 | 60 |
| enemy-fast-left | 6 | 0 | 6 | 42 |
| enemy-ledge | 6 | 0 | 6 | 48 |
| slides-after-stop | 6 | 0 | 6 | 42 |
| slow-left | 5 | 0 | 5 | 42 |
| gun-cooldown | 6 | 4 | 2 | 48 |
| **Total** | **35** | **4** | **31** | **282** |

All five predicted losses were observed. Gun-cooldown retained its two minimum shot-interval and
two shot-gap checks. Their do-nothing readings were indeterminate because there were no shots to
measure. Each kept check failed three times on the bug build and three times on the comment-only
candidate. The two shot-count equalities passed the control and were dropped.

The mechanics profile digest changed since the baseline. The report, both patches, check definitions,
applicability and all 43 applied route digests matched the saved records. Each removed check has
the explicit validity reason `passed the do-nothing control`.

These are advisory results. The replay records report zero model tokens and zero SAM images.
The host refused Bubblewrap's UID map, so the harness ran these public inputs in its automatic
fallback. These diagnostic results cover the six selected cases. The full public bench and its
new proposal rate require the live reproduction run tracked above.

## Reproduce the replay

Use the repository's SHA-512 checked Godot binary, with its path in `EXPECTRAIL_GODOT`. From
the pinned checkout, run the saved proposals against the current public replay entry point.

```bash
work=$(mktemp -d)
public=bench/jit/public
baseline=bench/jit/recordings/public-43465090517/repro

for case in air-jump enemy-fast-left enemy-ledge slides-after-stop slow-left gun-cooldown; do
  record="$baseline/repro-$case/jit-run.json"
  report=$(jq -er --arg id "$case" '.defects[] | select(.id == $id) | .report' "$public/defects.json")
  defect=$(jq -er --arg id "$case" '.defects[] | select(.id == $id) | .patch' "$public/defects.json")
  jq '{
    format: "expectrail.jit-proposal/v0",
    patchSha256: .inputs.patchSha256,
    model: "frozen-public-record",
    offer: "baseline",
    error: null,
    probes: [],
    candidates: .proposed,
    diagnostics: [],
    usage: {promptTokens: 0, completionTokens: 0},
    promptSha256: null
  }' "$record" > "$work/$case-proposal.json"

  EXPECTRAIL_SANDBOX=auto python3 -m expectrail.jit.cli run --model off --offer baseline \
    --report-file "$report" --base "$defect" --candidate "$public/no-fix.patch" \
    --proposal "$work/$case-proposal.json" --out "$work/$case"

  current="$work/$case/jit-run.json"
  jq -e '.status == "complete" and .advisory' "$current"
  for selector in \
    '.inputs | {patchSha256, reportSha256, basePatchSha256}' \
    '.probes | sort_by(.id)' \
    '.proposed | map({spec, applies, probeIds})'; do
    diff -u <(jq -S "$selector" "$record") <(jq -S "$selector" "$current")
  done
  jq '{counts, doNothing: [.validity[] | {specId, control: .doNothing.outcome, reasons}]}' "$current"
done
```
