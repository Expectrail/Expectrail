# Verify local commits (#250)

```bash
expectrail verify --repo /path/to/repo --base main --head feature \
    --jobs-root /path/to/jobs
```

The orchestrator resolves both references to full local commit IDs before creating a job. Each
commit gets a separate, clean snapshot owned by that job. The caller's working tree is never
checked out or modified. Queued jobs keep using those pinned snapshots even if a branch moves or
the repository goes away. An idempotency key compares resolved commits and computed inputs, so
moving a branch cannot silently reuse a job for a different commit.

With no layout options, `expectrail.project.json` in the **base commit** selects the adapter,
game, routes, checks and recorded observer settings. Use `--project relative/path` for a nested
configured project. Both snapshots use that base configuration; head-side configuration cannot
replace the policy that judges it. As with folder inputs, an explicit layout is also supported:

```bash
expectrail verify --repo /path/to/repo --base v1 --head feature \
    --game game/platformer --routes 'harness/routes/*.json' --specs agents/specs \
    --jobs-root /path/to/jobs
```

Give all three layout options together. `--project` and explicit layout options cannot be mixed.
The root CLI and `python3 -m expectrail.orchestrator` use the same implementation. Existing
`--head FOLDER --base FOLDER` and `--project FOLDER` inputs keep their folder semantics.

## What was resolved

New job records have `inputSources.head` and `inputSources.base` (null when there is no base).
Each non-null side is one of:

| Kind | Recorded identity |
| --- | --- |
| `commit` | Local repository, requested ref, resolved full commit, Git tree ID and computed SHA-256 snapshot digest |
| `folder` | Caller-supplied folder; no authenticated commit identity |

`inputs.headTree`, `inputs.baseTree` and `inputs.policyDigest` still describe the game bytes and
base policy the evaluator uses. `gitTree` identifies the complete committed Git tree;
`snapshotDigest` uses the harness tree-digest convention on the extracted repository. The saved
request holds these identities and the job-owned snapshot paths in `commitInputs.resolved`.
Client-supplied resolved claims are never trusted when creating a job: the store resolves again.
The reader checks the job's origins against its saved request and confines commit snapshot paths
to that job. Before replay it checks the retained snapshot digest and read-only modes.

Legacy requests and records remain readable. New folder jobs discard `--head-commit` and
`--base-commit` metadata and explicitly record `kind: folder`; those flags cannot authenticate a
folder as a commit. An old record with no `inputSources` has no recorded provenance. Commit mode
refuses these label flags because it obtains the identities itself.

## Refusals before replay

An unknown or ambiguous reference, equal resolved base/head commits, a non-repository path,
missing local objects or an unsupported tree is a command refusal (exit 5). No replay starts and
no job is queued. Branch names, tags, full IDs and unambiguous short IDs work; qualify a name with
`refs/heads/` or `refs/tags/` when a branch and tag share it.

Literal `HEAD` (also `@`) means the committed snapshot. When the working tree or index has
changes, Expectrail refuses it and prints the committed ID with that distinction. Commit or stash
the changes, use an explicit commit ID to select committed bytes despite a dirty working tree,
or use folder inputs to judge working-tree bytes. Ignored untracked output does not make HEAD
dirty. The check compares tracked bytes directly, without running filters; a filter-normalized
or line-ending-normalized working tree can therefore be refused conservatively.
Initial staging happens outside the source repository, before creating the job store, so
Expectrail's own output cannot make that initial HEAD check dirty. Keep the store outside the
source repository (as above), or ignore its output when using HEAD again. Temporary storage must
also be outside the working tree; an unsuitable `TMPDIR` is a named refusal.

## Snapshot boundary

The resolver reads raw local Git objects through private Git metadata with no repository or
user config, hooks, filters, remotes, replacement objects or inherited Git environment. It
rechecks object hashes and materializes regular files itself, without `checkout` or `archive`.
Object reads cannot fetch missing objects. No submodule is initialized or fetched. Committed
attributes remain ordinary data. Read-only files and directories live under `jobs/ID/inputs/`;
replays use the existing replay-copy and sandbox rules. These file permissions do not grant a
protected evidence grade or prevent the file owner from changing permissions; detected snapshot
changes stop the job before replay.

SHA-1 and SHA-256 repositories, packed objects, bare repositories and linked worktrees are tested.
All committed symlinks (including internal ones) and submodule entries are refused. External
object alternates, symlinked object storage, reftable repositories and reflog/worktree selectors
such as `main@{yesterday}` are unsupported. References and metadata are bounded; a snapshot is
limited to 100,000 files, 64 directory levels, 128 MiB per object and 2 GiB of file bytes per
commit. These are named stops, with no fallback to the caller's working tree or to a fetch.

This adds commit inputs to the orchestrator. It does not migrate the legacy MCP or split Action
interfaces or add a trusted private-suite request; those remain separate parts of #250.
