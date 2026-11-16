# Evidence storage

A claim needs a readable summary and retrievable evidence, not every capture in
main's checkout. This rule applies to new evidence and to an existing evidence
file when a pull request replaces it. It does not silently retire old evidence.

This reduces main's checkout and shallow-CI payload; it does not erase old Git
objects. A full clone that fetches all branches can still download results-branch
history. For a source-only checkout, fetch main alone and fetch evidence on demand:

```sh
git clone --single-branch --branch main --depth=1 https://github.com/Expectrail/Expectrail.git
```

## What stays on main

Keep the claim, result and denominator, limitations, reproduction commands, run
link and pin on main. Keep the capability ledger, dossier inputs, records an
offline test reads, and small fixtures that demonstrate a specific case. Keep
specs, routes and seeded patches. A summary must distinguish a measured finding
from something not run; moving evidence changes none of its meaning.

Move bulk traces, observations, capture images, videos and raw execution logs
that no test or generator needs to `evidence-results`. This follows the existing
[`run-it-results`](run-it.md) and [`sam-probe-results`](sam.md) pattern: a separate
results branch, a unique run directory, and immutable commit links. It introduces
no storage service, credentials or workflow. Existing results branches retain
their existing owners and files; this tool never edits them.

Before moving a folder, inspect its readers in tests, `tools/dossier.py`, the
capability ledger and other generators. Move no required input without updating
its reader in the same change. A network fetch must not become a hidden
prerequisite of an offline test. Never archive secrets, private or held-out
material; run the export scan before handing over either branch.

## The per-pull-request limit

The limit is **262,144 bytes (256 KiB)** of added or replaced non-manifest files
under `docs/`. To make it mechanical and avoid extension loopholes, this includes
Markdown summaries, HTML and logs as well as JSON, images and archives. It counts
**the entire new file**, not only the added lines or net size growth. Renames
count; deletions do not buy more allowance. Unchanged files are not charged.
A validated `evidence.manifest.json` is exempt; arbitrary JSON or an invalid
manifest is not. The reader uses Expectrail's strict JSON/schema validation:
no duplicate keys, non-finite numbers or newline-suffixed digests. Each manifest
is capped at 4 MiB before parsing. Generated evidence indexes count toward the limit.

`tests.test_evidence_storage.RepositoryEvidenceTest.test_pr_docs_evidence_stays_within_reviewed_budget`
runs in the existing `test` job through unittest discovery. In CI it compares
with the immutable PR base SHA in the event, fetching that exact public commit
from `origin` if the checkout is shallow. It refuses an unavailable or ambiguous
base instead of skipping. No workflow edit, secret or permission is needed.
Locally, it uses `origin/main`'s merge base, or the first parent if no such ref is
available. Review the reported base; for an explicit comparison use:

```sh
python3 tools/evidence_storage.py budget --base BASE_COMMIT
```

A file read by a test or generator may have a **named, reviewed exemption** in
[`evidence-exemptions.json`](evidence-exemptions.json). Each entry must give an
exact file path, a name, the existing Python reader path, a reason, a review PR
URL, and a maximum byte count (`maxBytes`). No glob or directory exemption is
supported. The guard uses the exemption list **from the comparison base**. A PR
cannot exempt its own payload: land the exemption in a separate reviewed PR
first, then add the fixture in a later PR. Increasing its bound needs the same
review. The initial list is empty; this document grants no exemption.

## Prepare a move locally

The `prepare` command writes a local evidence commit and bundle, the main-branch
manifest/index, and links in Markdown/HTML docs. It never accesses the network
or pushes.
Choose a unique run ID, audit the folder's readers, and check whether the branch
exists:

```sh
git ls-remote --heads origin evidence-results
```

If it does not exist, prepare the first evidence commit with:

```sh
python3 tools/evidence_storage.py prepare docs/example/raw \
  --id issue-123-run-1 --new-branch --bundle evidence-results.bundle
```

If it exists, fetch it yourself and pass its **full commit SHA** as the parent:

```sh
git fetch --no-tags origin evidence-results
git rev-parse FETCH_HEAD
python3 tools/evidence_storage.py prepare docs/example/raw \
  --id issue-123-run-2 --parent FULL_EVIDENCE_COMMIT --bundle evidence-results.bundle
```

Replace the example folder/ID/commit with the actual run. The folder must contain
only the raw evidence being moved. Put summaries and retained fixtures outside
it first, updating their readers and links together. The tool refuses unsafe
paths, symlinks, duplicate run IDs and an existing output bundle. It checks
archive digests and the bundle before deleting any source file. A failure after
bundle creation is recoverable from that bundle; retain it until both branches
are published. It is not a concurrent editing transaction: do not edit the
source while preparing a move.

The source folder retains `evidence.manifest.json` and `EVIDENCE.md`. The manifest
records each relative path, byte count and SHA-256, the source main commit, the
evidence branch/commit, archive directory and exact fetch command. The index
links each file to that commit. Existing local Markdown links and HTML href
references to moved files are rewritten to the index's per-file anchors.
Markdown image embeds become links. An HTML `src` pointing at a moved file is
refused: replace the embed with an ordinary link first. Audit non-link references and any other
readers yourself; the tool does not rewrite code or JSON readers.

```sh
python3 tools/evidence_storage.py links docs/example/raw/evidence.manifest.json
```

The repository test verifies each index against its manifest and catches stale
docs links or missing anchors. It does not claim that an unpushed commit is
already available on GitHub.

## Read and check evidence

The manifest's `fetch` line names a full commit. Read it, run it, then verify the
stored Git objects without checking out any files:

```sh
python3 tools/evidence_storage.py verify docs/example/raw/evidence.manifest.json --git .
```

For an offline handover, first import the supplied bundle:

```sh
git bundle verify evidence-results.bundle
git fetch evidence-results.bundle refs/heads/evidence-results
python3 tools/evidence_storage.py verify docs/example/raw/evidence.manifest.json --git .
```

Or clone the bundle and pass that checkout as `--tree` instead of `--git`. The
reader checks the archive directory named in the manifest, reports **every**
missing file, extra file, size difference, digest difference and unsafe entry,
and exits nonzero on a mismatch. It never executes the manifest's command or
accesses the network. Directory-level symlinks are refused. Git verification
uses the pinned commit, not whichever branch happens to be checked out.

## Publication and retention

Sean or the architect verifies the bundle, pushes the evidence commit to
`evidence-results`, then publishes the main change. Publish evidence **first**,
so the main-branch index links resolve when the PR merges. Keep the evidence
branch and the indexed commits; never rewrite or garbage-collect their history.
The bundle is a second copy, not a substitute for the published branch.

Push without force. If somebody has advanced the evidence branch, fetch it and
prepare again on that parent, using the original files from the old bundle.
Review the new manifest, links and digests as part of the main change. Never
force-push away another run. This mirrors the append-only results-branch pattern
used by the existing recording workflows.

## First migration and pending folders

The merged Breakout menu trial's [summary](outside-trials/breakout/report.md)
stays on main. Its [raw evidence index](outside-trials/breakout/evidence/EVIDENCE.md)
and [manifest](outside-trials/breakout/evidence/evidence.manifest.json) replace
only its raw `evidence/` folder. Trial inputs, summary JSON, selection, numbered
command log and screenshot remain readable on main; no test, dossier or ledger
reader was redirected to the network.

At this change's base, #556 (pointer routes) and #559 (menu routes) are still
open. Their evidence is absent from main and is **not migrated here**. The later
Breakout retrial folders are also absent. After each relevant PR merges, audit
its readers and run `prepare` on the raw subfolder, with the then-current evidence
branch as `--parent`. Do not apply those unmerged product patches merely to move
their evidence. The handover lists the pending folder names and the follow-up
steps. This is **Part of #566**, not a claim that those later migrations ran.
