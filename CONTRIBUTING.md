# Working in this repository

- **Branches and pull requests.** Work on a branch named after your lane (`vision/...`,
  `harness/...`, `agents/...`, `product/...`) and merge through a pull request that CI passes.
  Keep pull requests small; the end-to-end loop has to work every day from October 28.
- **Contracts first.** If a change needs a field another lane reads, change the schema, the
  example and both sides in one pull request (see [docs/contracts.md](docs/contracts.md)).
- **The game stays clean.** Never edit `game/platformer` to seed a bug: add a patch under `bugs/`.
  Candidate fixes from the fixer are patches too.
- **Held-out cases stay out.** Held-out bug variants and the gameplay checks used to judge fixes
  do not go in this repository during the event; the fixer must not be able to read them.
- **Two kinds of checks.** Checks people write (specs a person approves, the gameplay check, the
  held-out cases) decide a fix. Discovery's contracts ([docs/discovery.md](docs/discovery.md)) only
  advise; never wire one into the verifier's decision without the promotion stage it describes.
- **Discovery is unfrozen; a new blind claim needs a new freeze.** Set 2's blind runs are recorded,
  and freeze 2 was retired on November 9, 2026. `discovery/freeze.json` stays as the record of what
  set 2 ran against, and `tests/test_discovery_freeze.py` checks it against commit c169a5e, the
  baseline commit `c169a5e`, not against main. Before any new blind run, write a new freeze and a new fresh set, as
  [docs/discovery.md](docs/discovery.md) describes. Fresh sets stay in the private repository; only
  their digests are here.
- **The mutation bench reruns at the baseline commit.** Its pre-registration
  (`bench/mutation/preregistration.json`) describes the code at commit c169a5e. Never edit that file.
  Main may change the files it pins; judged mutation runs check out that commit, and `tests/test_mutation_registration.py` checks the
  record against it.
- **No secrets.** API keys go in your environment or the CI secret store, never in a file.
- **Log new work.** Add a line to the After the event table in [docs/new-work.md](docs/new-work.md)
  when something lands; the table above it is the record of the event and stays as it is.
- **Tests.** `python3 -m pip install -r requirements-dev.txt` once, then
  `python3 -m unittest discover -s tests -t .` before you push.
