# Restoring the public routes for the #675 control audit

## What changed

The November 20 audit lacked the routes for 11 checks across four public defects. This follow-up uses the same 24 frozen records from run 43465090517 and the four published route archives. All four ZIP hashes matched the published SHA-256 values. All 24 records matched their committed bytes, and all 11 generated routes matched the canonical digests in their source records. [November 20 audit](../measurements/675-public-counting-rerun.md) · [Public archives and checksums](../measurements/675-harmless-control.md#reproduce-the-measured-route-set)

## What was run

Expectrail 0.1.0 at `bd44b5ad` used headless Godot `4.7.2.stable.official.ed1daf0bf`. All 381 replay manifests reported sandbox mode `auto` and tool `none`. Bubblewrap could not set up its UID map, so the replays used host filesystem, processes and network with an environment allowlist.

- **Do-nothing.** All 165 replays finished across 55 combinations of actor control, route and recording settings. The three trace hashes agreed within every group.
- **Harmless.** All 216 replays finished across 36 routes, three clean and three with the registered comment edit on each. For every route all six trace hashes agreed and matched the previously published hashes. [Earlier full-route harmless measurement](../measurements/675-harmless-control.md#trace-digests-from-the-fresh-control-runs)
- **Row comparison.** Each control produced 137 unique (public defect, check ID) pairs. Every row matched both its frozen run digest and its check digest. For the 126 pairs previously measured on both controls, every repetition and outcome matched. The remaining 11 and their effect on legacy catches are listed in the [November 21 results](../jit.md#november-21-2026-follow-up-with-all-public-routes-675).

To reproduce from revision `bd44b5ad2a2f06220b46b71821556965fcc7c9e2`, use Godot 4.7.2 and the following commands from the checkout. The GitHub CLI download requires access to the artifact host. In this rehearsal the installed GitHub connector supplied the same four ZIPs after the CLI download failed. The checksum comparison precedes extraction in either case. [Run record](https://github.com/Expectrail/Expectrail/issues/675#issuecomment-7056123031)

The two work directories must be new. The audit saves each do-nothing repetition in `dn/rows.json` and each clean and changed repetition in `harmless/control.json`.

```sh
set -e
work=$(mktemp -d)
cp -R bench/jit/recordings/public-43465090517/repro "$work/records"
while read -r defect artifact sha; do
  gh api "repos/Expectrail/Expectrail/actions/artifacts/$artifact/zip" > "$work/$artifact.zip"
  echo "$sha  $work/$artifact.zip" | sha256sum -c -
  unzip -q "$work/$artifact.zip" 'jit-routes/*.json' -d "$work/records/repro-$defect"
done <<'ARTIFACTS'
platforms-not-solid 14061093273 e649d4452e61ff946528f1fa65301494a0c628d50dd47193118b94a179824204
jump-always-full 14060975551 7eded43c524fe316ffd2330138760405ae72efa74e1a11aaeb1c0790cccb0e51
no-shooting-in-air 14060046873 f4fe72e95a6bf6f3a4c0767b92950be75f00d60b0f2f7ac5f195e142da2bc4b6
camera-stops-right 14062370774 02f55cb08083b2c3303471ded450ca0ae4dd1254702011c100d823d9abe4ec61
ARTIFACTS
python3 tools/do_nothing_public.py --records "$work/records" \
  --work "$work/dn" --out "$work/do-nothing.md"
python3 -m expectrail.jit.counting public-bench --records "$work/records" \
  --harmless-work "$work/harmless" --do-nothing-rows "$work/dn/rows.json" \
  --out "$work/public-counting.md"
```

## Not done

The do-nothing comparison uses the recorded clean-reference outcomes. The harmless comparison covers one source comment on one public game. This trace-only audit involved no independent vision observer, unaided maintainer session or model call.

## Files

- [Control results](../jit.md#november-21-2026-follow-up-with-all-public-routes-675)
- `docs/new-work/2026-11-21-public-route-controls.md`
