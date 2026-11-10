# The CI gate: Expectrail on a game repository's pull requests

The gate replays a pull request's Godot game on scripted routes, judges the approved test specs on
what the engine recorded, and posts the verdict (accept, reject or needs review) with its evidence
as one pull request comment. The comment is updated on every push, and each finding keeps its id
from push to push. It is the G04 package in [discovery.md](discovery.md#whats-next): evidence in the
pull request, posted from a separate trusted step.

It comes as two composite actions in this repository:

- [`.github/actions/expectrail-verify`](../.github/actions/expectrail-verify/action.yml) runs the
  pull request's game. It is the untrusted half.
- [`.github/actions/expectrail-comment`](../.github/actions/expectrail-comment/action.yml) posts the
  comment from a `workflow_run` job that never runs the pull request's code. It is the trusted half.

They live under `.github/actions/` rather than as one `action.yml` at the repository root because
the two halves need different trust and different permissions, and a root action would be a single
entry point for both. The repository root stays the project. Both actions come from the same commit,
so one pinned SHA covers both.

## Add it to a game repository

You need a Godot project that runs in Godot 4.7.2 (the version the harness pins), at least one route
(`expectrail.route/v0`, see [contracts.md](contracts.md)) and at least one approved test spec
(`expectrail.test-spec/v0` with an `approval`). The harness adds its autoload to a copy of the
project. A route presses the game's own input actions on exact physics ticks, and the position log
follows the node named `Player`. Add two workflow files. Replace `COMMIT_SHA` with the full SHA of an Expectrail commit on
`main` that contains `.github/actions/` (for example from
`git ls-remote https://github.com/Expectrail/Expectrail refs/heads/main`). Pin both files to the same
SHA, as you would pin any third-party action.

`.github/workflows/expectrail-verify.yml`, the untrusted job:

```yaml
name: Expectrail verify
on: pull_request
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: Expectrail/Expectrail/.github/actions/expectrail-verify@COMMIT_SHA
        with:
          game-path: game              # the folder holding project.godot ("." for the root)
          routes: tests/routes/*.json  # one path or glob per line
          specs: tests/specs
```

`.github/workflows/expectrail-comment.yml`, the trusted job:

```yaml
name: Expectrail comment
on:
  workflow_run:
    workflows: [Expectrail verify]
    types: [completed]
permissions: {}
jobs:
  comment:
    if: >-
      github.event.workflow_run.event == 'pull_request' &&
      github.event.workflow_run.path == '.github/workflows/expectrail-verify.yml' &&
      github.event.workflow_run.conclusion != 'cancelled'
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      actions: read
      contents: read
      pull-requests: write
    steps:
      - uses: Expectrail/Expectrail/.github/actions/expectrail-comment@COMMIT_SHA
```

The comment workflow takes effect once it is on your default branch: GitHub runs `workflow_run`
workflows only from the default branch's copy. Until then the verify job runs and uploads its
evidence, and no comment appears.

This repository runs the same pair on its own pull requests:
[`expectrail-verify.yml`](../.github/workflows/expectrail-verify.yml) (the platformer, the smoke and
combat routes, `agents/specs`) and [`expectrail-comment.yml`](../.github/workflows/expectrail-comment.yml).
Both use the actions from the checked-out repository (`./.github/actions/...`) instead of a pinned SHA.

### Inputs

| Action | Input | Default | What it does |
| --- | --- | --- | --- |
| verify | `game-path` | required | The Godot project folder, relative to the repository root |
| verify | `routes` | required | Route files, one path or glob per line |
| verify | `specs` | required | The folder of test specs; only specs with an `approval` judge a change |
| verify | `compare-base` | `true` | Also replay the pull request's base commit, and read the specs and routes from it |
| verify | `heldout-repository` | empty | `owner/name` of a private repository of held-out routes (a `manifest.json` listing `routes[].file`) |
| verify | `heldout-ref` | empty | Its branch, tag or commit |
| verify | `heldout-token` | empty | A token that can read it; see "Held-out routes" below before passing one |
| verify | `fail-on` | `reject` | Fail the job on `reject`, on `needs-review` (or reject), or `never` |
| verify | `artifact-name` | `expectrail-gate` | The evidence artifact's name |
| verify | `generated-checks` | empty | An advisory block of checks generated for this change ([jit.md](jit.md)), shown in the comment and the review page; it never changes the decision, and one that cannot be read shows as "no generated checks" |
| comment | `github-token` | the run's token | Reads the verify run's artifact and writes the comment |
| comment | `artifact-name` | `expectrail-gate` | Must match the verify action's |
| comment | `watch` | empty | More paths the verdict depends on, one per line (end a folder with `/`); the comment warns when the pull request changes one |
| comment | `bot-login` | `github-actions[bot]` | The only author whose comment is ever updated |

The adapter boundary (a separate workstream) will add an `adapter` input to the verify action, with
`godot` as its default. The record already carries `"adapter": "godot"`, and the only place that
replays a route is `harness_replay` in [`expectrail/gate/verify.py`](../expectrail/gate/verify.py), so
another engine plugs in there. Until then, the gate supports Godot only.

## What the gate decides

The verify job checks out the pull request's merge commit. With `compare-base: true` (the default), it
also checks out the base commit. It then does this:

1. Reads the specs and routes **from the base commit**, so a pull request cannot weaken the checks that
   judge it. Spec and route files the pull request edits are counted in the comment. They judge
   changes once the pull request merges. Without a base (a push, or `compare-base: false`), the head's
   own checks are used, and the comment says so.
2. Replays every route on the head and on the base through the Godot harness ([harness.md](harness.md)).
3. Judges every approved spec on every route with the evaluator, on the engine's position log. Each
   check gets the review's comparison words ([review.md](review.md)): `REPAIRED`, `PRESERVED`,
   `REGRESSION`, `UNRESOLVED` or `INCONCLUSIVE`.
4. Replays the held-out routes on the head, if configured, and keeps counts only.
5. Decides. **Accept** only when at least one check ran and every public and held-out check passes.
   **Reject** when any check fails after the change. **Needs review** otherwise: a check that could not
   be decided, a replay that did not finish, held-out routes that could not be read, or no checks at
   all. Accepted means this change passed these checks on these routes, not that the game is correct.

A finding is a check that does not pass after the change. Its id is the first 12 hex digits of
`sha256(spec + "\n" + route + "\n" + kind)`, where kind is `fail`, `needs-review` or `replay-error`.
Nothing that changes between pushes goes into it (no commit, frame, reason or time), so the same
failure keeps its id. To reproduce one:
`printf '%s\n%s\n%s' player-stays-above-ground smoke fail | sha256sum | cut -c1-12`. The comment lists
the ids that are new and resolved since its last update.

The evidence artifact holds `findings.json` (the record, [`contracts/findings.schema.json`](../contracts/findings.schema.json)),
`verdicts/head/<route>/<spec>.json` and `verdicts/base/...` (the evaluator's verdicts), and
`review/index.html`. The review page opens from disk with no scripts. It shows every check, and for
each finding the first failing frame before and after the change, each with its SHA256. The comment
links the run that holds the artifact, [review.md](review.md) for how to read the comparisons, and this
page.

## How it is kept safe

GitHub's guidance is to run untrusted pull request code only where no secret and no write token can
be reached, and to treat anything that code produces as untrusted data
([Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target);
GitHub Security Lab,
[Preventing pwn requests](https://securitylab.github.com/research/github-actions-preventing-pwn-requests)).
The gate follows that split.

**The verify job is untrusted.** It runs on `pull_request`, with `contents: read` and no secret
except, optionally, the held-out token. It runs the pull request's game, so it is treated as
compromised by design:

- The action refuses `pull_request_target`, `workflow_run` and `issue_comment`, where it would run the
  pull request's code next to a write token.
- Every input reaches a script through `env`, never by `${{ }}` expansion inside a script.
- Godot gets only the display and rendering variables from the environment (`harness.run.game_env`).
- Python runs from the action's own folder, so a file in the pull request cannot stand in for an
  Expectrail module.
- Before upload, the evidence goes through the repository's export scan (`agents/export_scan.py`):
  key-like strings and, with the held-out set, its route names and lines. A finding stops the upload.

**The comment job is trusted.** It runs on `workflow_run`, from the default branch's copy of its
workflow file, with `actions: read`, `contents: read` and `pull-requests: write`, and nothing else:

- It never checks out, builds or runs the pull request's code. The action does not check anything
  out. This repository's workflow checks out only its default branch (sparse), to use main's copy of
  the action. `tests/test_ci_gate.py` reads both YAML files and fails if a checkout names another ref
  or repository, if a step runs anything but the action's entry point, or if any script expands
  `${{ }}`.
- It installs nothing. The code is [`expectrail/gate/comment.py`](../expectrail/gate/comment.py) and
  [`expectrail/gate/record.py`](../expectrail/gate/record.py), standard library only (a test parses
  their imports). It runs as `python3 -I`, so `PYTHONPATH`, user site-packages and the current
  directory are ignored, and only the pinned commit's files can be imported.
- The artifact is downloaded into the runner's temp folder and read as data. Only `findings.json` is
  opened. It must be a regular file (not a symlink), at most 4 MiB, UTF-8, and JSON with no duplicate
  keys, NaN or Infinity, nested at most 32 deep. It is checked against the closed schema by a small
  validator that refuses any schema keyword it does not implement. A test holds that validator equal
  to `jsonschema` on the example and on mutated records. Then every derived value is recomputed: each
  finding id from its spec, route and kind, each comparison, the counts and the decision. A record
  that fails any of this is not shown. The comment says the evidence could not be used, so an older
  verdict does not stand.
- The pull request is found from the event (the run's head repository, branch and commit), not from
  the artifact. A fork's run carries no pull request list. A record that names another pull request
  or commit is refused. If the pull request's head has moved on, nothing is posted, because the newer
  run will post.
- Every string from the record is escaped before it goes into Markdown. Newlines and control,
  zero-width and bidirectional characters become spaces. HTML is entity-escaped, and Markdown
  punctuation is backslash-escaped, so a pipe cannot end a table cell. A word joiner follows `@` and
  `#` and breaks `://` and `www.`, so text cannot mention a person, link an issue or become a link.
  Each string is capped at 200 characters, at most 30 findings and 100 checks are listed, and the
  comment stays under 60,000 characters (GitHub's limit is 65,536). Every link is built from the event,
  never from the record.
- There is one comment per pull request. It is found by a hidden marker and by its author (the
  token's bot), so a comment anyone else writes with the same marker is never picked.
- The comment warns when the pull request changes the workflow file that produced the verdict, or a
  path listed in `watch`. It gets those paths from the pull request's file list, through the API.

**Held-out routes leave as counts only.** The record's schema has no field for a held-out route's
name, file, frame or reason. The verify step prints no held-out detail, even when the set cannot be
read. It replays the held-out routes without frames and deletes their run folders. The comment shows
routes and checks passed, failed and needing review. A test runs the gate with a stand-in held-out set
and searches every output file, the log and the comment for its route names.

## Limits

- **The verdict is computed where the pull request's code runs.** A pull request can edit the verify
  workflow: for `pull_request` events GitHub uses the pull request's copy. Code in the game runs as the
  same user as the gate, so it could rewrite files the gate reads before the upload. The comment
  job checks the record's shape, the commit it names and the workflow behind it, and says so when the
  pull request changes that workflow. It cannot prove that the verification itself was not tampered
  with. Use the comment as evidence for a reviewer. Next: run the game in a sandbox inside the verify
  job (no network, writes only to its own run folder).
- **Held-out routes and pull request code share a job.** If you pass `heldout-token`, the pull
  request's game runs in the job that holds the held-out routes and can read them while it runs.
  Pass it only when the people and agents who open pull requests may see the held-out set anyway.
  This repository does not pass it on pull requests (OBAAF-GHA-001). A fork's pull request never gets
  it, because GitHub gives forks no secrets and the action checks the head repository too.
- **The position log is the only observer.** No model key is used, so SAM 3.1 does not judge. The
  harness logs the node named `Player`, and the stand-in observations use the platformer demo's player
  size ([sam.md](sam.md), `agents/observations.py`). A spec about any other object needs review. On
  another game, a spec's `tolerancePx` is measured against that size, so its meaning is approximate.
  Giving the verify job a model key would put the key next to the pull request's code.
- **Godot only, one way to replay.** Each route costs one replay on the head and one on the base. The
  smoke route took about 33 seconds in the 2-core container without a GPU that this was built on.
- **Artifacts of a public repository are public.** Everything in the evidence artifact can be
  downloaded by anyone who can see the repository, which is why held-out material never enters it.

## Verifying it after merge

`workflow_run` uses the workflow file on the default branch. So the comment half cannot run from this
pull request, and the end-to-end flow (verify run, artifact, comment) can only be shown after merge.
Before merge, the unit tests cover the record, the ids, the rendering and the YAML. The verify
workflow runs on this pull request itself, and the run's `expectrail-gate` artifact can be inspected.
After merge:

1. Open a pull request with a comment-only change to `expectrail/gate/page.py`. That path starts
   Expectrail verify, and the comment workflow's `watch` list names it.
2. When verify finishes, the Expectrail comment workflow runs from `main`. Expect one comment that
   starts `### Expectrail: accept`, lists the smoke and combat routes as `PRESERVED`, links the run, and
   warns that the pull request changes `expectrail/`, a path the verdict depends on.
3. Push a second commit to the same pull request. The same comment is edited, not duplicated. Its
   footer shows the new commit.
4. From a fork, open the same kind of pull request. Expect a comment from the same workflow, with
   "Held-out routes: not used. A fork's pull request gets no secrets".
5. A finding needs a pull request that breaks the game, and seeded bugs never go into
   `game/platformer` (CONTRIBUTING.md). See one locally instead (below): expect `REGRESSION` on both
   routes, with the same two finding ids on every run.

Locally, with Godot from `./harness/get_godot.sh`:

    python3 -m expectrail.gate.verify --repo HEAD_CHECKOUT --base BASE_CHECKOUT --game game/platformer \
        --routes 'harness/routes/smoke.json harness/routes/combat.json' --specs agents/specs \
        --out runs/gate --pr 1 --head-sha HEAD_SHA --base-sha BASE_SHA

`contracts/examples/findings.json` came from such a run. The base was the clean game at `618ad50`.
The head was the same game with `bugs/physics-fall-through/v1.patch` applied. A stand-in held-out set
was made from two public routes. Its pull request number and head commit are placeholders. The result
was reject: `REGRESSION` on both routes, first failing frame 5, and both held-out checks failed.
