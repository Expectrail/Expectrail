# Record Breakout’s draft-only setup refusal in the outside trial (#695)

## What changed

The pinned, harmless and broken Breakout cases now expect the configured CLI to refuse
verification because the two selected checks are unapproved drafts. The trial inspects
the trusted Before project for a usable route, zero approved checks, the expected number
of drafts and no inspection problems. It matches the CLI’s complete readiness explanation,
exit 5 and empty standard output, and checks the job store for partial or completed jobs.
The JSON and Markdown report the refusal separately from a verdict. Each independent
engine diagnostic must still produce its specified finding.

## What was run

- `python3 -m unittest discover -s tests -t .` ran 5,672 tests in 1,157.304 seconds.
  The suite passed with 56 skips.
- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,256 files
  with zero errors and zero warnings.
- `python3 -m unittest tests.test_outside_root tests.test_outside_trial tests.test_outside_vision`
  passed 53 tests. The real CLI through the trial entry point exited 5, produced no verdict
  and created zero jobs. This test supplied the separate replay diagnostics.
- `python3 -m tools.outside_trial --fetch --only breakout --execution-class isolated --out <output>`
  fetched public pin `0ac7aed444ea593a023d9b666c211d7ab8acd51e`. With the final code,
  repeating the isolated run using that source found the same specific refusal and zero
  verification jobs in all three cases. The trial exited 3 because none of the three
  separate diagnostic replays could launch. Running the harness preflight on the same
  route reported that the required virtual display launcher was missing.
- In the earlier hosted run the broken paddle first failed at frame 20. The ball checkpoint
  was never reached. Both drafts passed on pinned and harmless. That job failed because
  its registry still expected a verification verdict. [Hosted outside trial](https://github.com/Expectrail/Expectrail/actions/runs/44723616398/job/136245376778)

## Not done

A hosted run of this change is needed to record the refusal and the isolated engine findings
together. This trial supplies no visual judgement or unaided developer timing.

## Files

- `tools/outside_trial.py`, `tests/outside/projects.json` and `tests/test_outside_root.py`
- The `outside-projects` and `outside-trial` schemas and their examples under `contracts/`
- `docs/outside-projects.md` and this entry
