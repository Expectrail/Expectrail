# Generated checks: records

Records of per-change check generation ([docs/jit.md](../../docs/jit.md)) go here, one folder per
measured run, each named after its CI run and holding the `jit-run.json` records that run wrote.

**No measured run yet.** The only thing here is [`rehearsal/`](rehearsal): the public air-jump bug
fixed exactly and "fixed" with a comment only, each with a proposal written by a fixture standing in
for the model. The **Generated checks** workflow replays them to prove the plumbing. A rehearsal is
never a result.

[`public/`](public/README.md) is the public reproduction bench (issue #285): 24 defects with bug
reports, and what each one changes in the engine's record on the probes generated checks may use.
It holds no reproduction rate yet: the workflow mode and the scorer for a live run on it are built
and have not been run.
