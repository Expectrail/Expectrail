# Working on Expectrail

This file is for anyone picking up work here: a Claude agent, a ChatGPT agent, or a person. Read it before you start.
The roadmap is at https://claude.ai/artifact/19H7AMWjV7K6fVpt18DLQx and every deliverable is an issue under a milestone.

## Picking up an issue

1. Take the open issue with the lowest milestone, then the highest priority (`P0` before `P1`), that is labelled
   `agent-ready`, is not labelled `status:in-progress` or `human`, and whose "Depends on" issues are closed.
   An issue labelled `needs-sean` as well as `agent-ready` has a part only Sean can do: build the rest.
2. Claim it: add the label `status:in-progress` and comment "Claimed by <who>, <UTC time>". A claim with no pull
   request and no comment for 12 hours is released: anyone may remove the label and take it.
3. Work on a new branch from main. One issue may take several pull requests; say in each what is left.
4. Open a pull request that says `Closes #N` or `Part of #N`, what was built, and what was run with its result.
   Agents label their pull request `agent-pr`.
5. If you cannot finish, comment on the issue with what is done and what blocks it, and remove `status:in-progress`.

## Rules for every change

- Be plain about what was shown. Never write that something works without a recorded run: a test, a CI run or a
  command with its output. "Not yet run" is an acceptable sentence; a guess presented as a result is not.
- Never push to main and never push to someone else's branch under review. Changes reach main by pull request.
- Run `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7` once, then
  `python3 -m unittest discover -s tests -t .` before pushing. Do not open a pull request with a failing suite.
- Add one file under `docs/new-work/` for every change, named `YYYY-MM-DD-short-name.md`: what changed, what was
  or was not run, the files (`docs/new-work/README.md` has the layout). Never add to another change's file.
- Contracts first: a schema, its example, the writer and the reader change in one pull request.
- Never edit `game/platformer` or `game/unity-platformer`. Seeded bugs and their fixes are patches.
- Never weaken a test to make it pass. Deleting or skipping a test needs a reason in the pull request and a line
  `Guard: test change intended (#issue)`.
- Use only the name Expectrail.
- No secrets in files, logs or artifacts. Never create accounts or enter credentials.
- No model spend unless the issue says so and states a budget.

## What only a person may do

Agents stop and label the issue or pull request `needs-sean` for any of these, and never do them:

- **Approve a check.** Never add or change an `approval` in a spec or contract, and never run the approve commands.
  An agent may draft a spec; a person approves it.
- **Read held-out material.** Never open the private repository `Expectrail-heldout`, anything under `fresh-*`, the
  private web patches or sessions, or the content of a blind set. Never use the private scan to test a guess.
  Publish counts only.
- **Change these rules.** Any change to `AGENTS.md` or `.github/CODEOWNERS`.
- **Change what holds a secret.** A workflow change that adds a secret, an `environment:`, `pull_request_target`,
  `id-token: write` or wider `permissions`, and any change to `.github/obaaf-baseline.json` that adds findings.
- **Approve a protected environment's run** (`unity`, `main-only`), rotate a key, create an account, change
  repository settings or branch protection.
- **Score the blind set, tag a release, submit to the fund.**

## How a pull request reaches main

Agents may merge, under these conditions. The merge guard, a separate agent that did not write the change, checks
each open pull request labelled `agent-pr` and merges it only when all of these hold:

1. No open issue is labelled `freeze`.
2. Main's latest CI run is green. A red main is fixed first.
3. Every check on the pull request's head is green and the branch is up to date with main, or merges cleanly and the
   full suite passes on the merged result.
4. Nothing in the diff is on the list above. If something is, the guard labels it `needs-sean` and leaves it.
5. No test was deleted, skipped or loosened without the stated reason, and every claim in the description is backed
   by a run it can see.
6. The issue's "Done when" is met for the part the pull request claims, and `docs/new-work/` has its entry.

No agent merges its own pull request. When the guard finds a problem it comments with the exact reason and labels the
pull request `changes-requested`; the builder fixes it on the same branch. If main turns red after a merge, the guard
opens a revert of that merge first and reports on the issue.

A person's pull request is reviewed and merged by a person, unless they label it `agent-pr` to ask for the guard.

## Labels

| Label | Meaning |
| --- | --- |
| `P0`, `P1`, `P2` | Needed for the release; first to cut if a milestone slips; after the fund |
| `agent-ready` | Self-contained: an agent can start from the issue alone |
| `status:in-progress` | Claimed |
| `needs-sean` | Has a step only Sean can do; the step is named in the issue or a comment |
| `human` | Not for agents |
| `agent-pr`, `changes-requested` | A pull request for the merge guard; the guard asked for changes |
| `freeze` | While an issue with this label is open, nothing merges |
| `found-by-tester` | Opened by the nightly platform test |
