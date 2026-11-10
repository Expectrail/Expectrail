# Demo path (offline, filmable)

One-command Gate-2 hand-over without Meta keys:

```sh
python3 -m agents.loop --out runs/demo-path --mode offline --runs 10
```

Open:

- `runs/demo-path/morning-report.md` — overnight rollup (accepts, wall-clock, cost stub, trust)
- `runs/demo-path/summary.json` — schema-valid `expectrail.overnight-summary/v0`
- `runs/demo-path/frames/` — latest accept before/after
- `runs/demo-path/run-00/morning/release-candidate.json` — signed RC pointer
- `runs/demo-path/run-00/trust/trust-evidence.md` — deny-by-absence evidence

Freeze reject film (optional):

```sh
python3 -m agents.loop --out runs/demo-freeze --mode offline --runs 1 \
  --candidate-patch agents/fixtures/freeze-player.patch \
  --observations agents/fixtures/obs-freeze.json
```

Regenerate the agents offline bench stub:

```sh
python3 -m agents.bench --summary runs/demo-path/summary.json
```

Harness morning film (Linux CI `agents-harness-verify`): after Godot verify, `agents.report`
writes `runs/harness-accept/morning/` and `runs/harness-negatives/freeze-morning/` with
schema-valid RCs and suite/gameplay sections.

`--no-trust` is for local debugging only — the demo path keeps trust on so the rollup films
`## Trust` PASS evidence.

Gate 1 one-shot (also writes `morning/` + schema-valid RC):

```sh
python3 -m agents.gate1 --out runs/gate1 --skip-harness \
  --observations agents/fixtures/obs-fixed.json
```

Bound trust recheck against an overnight run:

```sh
python3 -m agents.trust --out runs/trust-recheck \
  --fixer-work runs/demo-path/run-00/fix/fixer-work \
  --verifier-host runs/demo-path/run-00/verifier-host
```

Trust canary denial film (scripted attempts, no Muse spend):

```sh
python3 -m agents.prove_live --out runs/prove --trust-only
# → runs/prove/prove.md + trust/canary-attempts.json
```

Live Muse accept film (needs `META_API_KEY` + `muse`; or CI `workflow_dispatch` job
`agents-live-muse`, run from main with META_API_KEY in the main-only environment):

```sh
export META_API_KEY=LLM_…
python3 -m agents.prove_live --out runs/prove
```
