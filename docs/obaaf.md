# OBAAF in Expectrail

OBAAF (the Open Build and Agent Assurance Framework, https://github.com/Obaaf/OBAAF) is a
dependency pinned to commit `d014b6366b5f1b14b8bf13a3b07c6d3727a4a1e4`. It checks whether a
change may cause an effect, such as a pull request or release, given its origin and approvals.
Expectrail checks whether the change does what the player needs. These are separate decisions,
and both are needed: an OBAAF check does not establish that the fix is correct, and a passing
Expectrail verdict does not grant write access by itself.

**Status: Phase A, no new findings (Nov 9).** No protected effect is enabled, but a pull request
that adds a finding now fails. What runs, in the `obaaf-audit` CI job on every push and pull request:

| What | How | Gated? |
| --- | --- | --- |
| Lane inventory | `.github/obaaf.yml` declares the 10 jobs that hand a Meta model untrusted input and act on its output as agent lanes (OBAAF does not recognise `python -m agents.*`). `agents/assurance/audit.py` fails CI if one is not classified as an agent, or if any job holds a model key without being a declared agent or a listed perception-only job (SAM, Glimmer). | Yes: a new model job needs a declaration and review |
| Pipeline findings | `obaaf check . --format json --fail-on never`; one notice per rule | Reported |
| No new findings | `obaaf check . --baseline .github/obaaf-baseline.json --fail-on low`. The baseline lists the findings accepted today (below); any other finding fails, and so does a baseline entry that no longer matches, so a fix is locked in by regenerating it with `--write-baseline`. A line added to the baseline is an accepted new finding: review it like a workflow change (CODEOWNERS covers `.github/`). | Yes |
| Protected secrets | `protected_secrets` in `.github/obaaf.yml`: `HELDOUT_TOKEN` and every `*_API_KEY` only in `main-only` (OBAAF-GHA-024) | Yes, through the baseline |
| Proposals | `agents/assurance/proposal.py` turns a candidate fix into an OBAAF proposal bundle and checks it with `obaaf proposal check --repo` plus Expectrail's own allowlist | Tests only, see below |

## Where the secrets live (Nov 9)

Anyone with write access, or a coding agent acting for them, could read any repository secret by
pushing a branch with a workflow that prints it; branch protection does not apply to a workflow
running from its own branch. So no secret is a repository secret any more:

| Environment | Holds | Who can use it |
| --- | --- | --- |
| `main-only` | `HELDOUT_TOKEN` and every model key: today `MODEL_API_KEY`, `META_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `FIREWORKS_API_KEY` and `BASETEN_API_KEY`; the workflows also read `GEMINI_API_KEY`, `OPENROUTER_API_KEY` and `GLIMMER_API_KEY` if you add them, and those go here too, never as repository secrets | Workflows on `main` only (deployment branch rule) |
| `unity` | The Unity licence | Any branch, after Sean approves each run (required reviewer) |

- Every job that uses one of these secrets declares the environment; `tests/test_main_only_environment.py`
  fails if one does not, or if a job in `main-only` can be started by a pull request. No key lives in
  an approval-only environment: approving a run would hand that branch's code the key.
- Pull requests run keyless: `discovery` (planner off) and `reported-bench` (traces only) hold no key,
  and their keyed twins `discovery-planner` and `reported-bench-sam` run only on a dispatch from main.
  `mutation-fix` rehearses keyless on a pull request; its live jobs are dispatch-only. `byo-smoke`
  no longer runs on pull requests: its live calls run daily and on a dispatch from main (dispatch it
  right after merging a provider-layer change), and its logic is tested offline on every pull request.
- A held-out or live bench can only be dispatched from `main`.
- The private scan of a pull request is the one `main-only` job that a pull request's run leads to,
  and it no longer uses `pull_request_target` (#247; GitHub blocks that trigger by default in public
  repositories from December 2, 2026). It has two halves:
  - `private-scan-request.yml` runs on the pull request with no secret, checks nothing out, and
    makes one API call: start `private-scan.yml` on the default branch (`workflow_dispatch`) with
    the head commit's id.
  - `private-scan.yml` then runs from main's copy of the file, in `main-only`. It checks the commit
    out as data, main's scanner reads it, and the result is posted as the check
    `private-export-scan` on that commit. Nothing from the pull request is run or imported;
    `tests/test_private_scan.py` holds that shape. A run started on any other branch is refused by
    the environment before a step runs.
  - The first design used `workflow_run`; every run GitHub started that way ended in
    `startup_failure` (November 11), while the same workflow started by `workflow_dispatch` ran.
  - What it does not close: pass or fail is still an oracle a writer could probe across pushes, and
    a pull request that edits its own copy of the request gets no scan and no check, so
    `private-export-scan` should be a required check. The scan on main after a merge is unchanged.
- `main` is protected (ruleset "Protect main"): no force pushes or deletion, a pull request with one
  approval of its latest push and a passing `test` check. Sean and Timothy can merge their own pull
  requests without waiting (organization admins may bypass, for pull requests only); nobody pushes to
  `main` directly. Without this, anyone with write access could put a workflow on `main` and read
  every key in `main-only`.
- What the checker cannot see, check in the settings: no repository or organization copy of these
  secrets, `main-only` limited to `main`, and required reviewers on `unity`. Create the environment before any workflow names it:
  GitHub creates a missing environment on first use, with no protection.

## Findings (Nov 9, with OBAAF at d014b63)

The baseline (`.github/obaaf-baseline.json`) accepts exactly these; anything else fails CI.

| Rule | Oct 30 | Nov 10 | What it means |
| --- | --- | --- | --- |
| OBAAF-GHA-005: secret in an agent job | 8 high | 19 high (baseline) | Every agent job holds a model key, now from `main-only`. Muse Code and, when `EXPECTRAIL_BYO_GATEWAY=on`, a BYO agent never see the key itself (the key gateway below), but OBAAF's static check still sees it in the job, where the gateway runs. Clearing it needs the gateway hosted outside the job. The count grew with the BYO and web benches and the generated-checks proposer and its revision (`jit.yml#propose`, `#revise`, dispatch from main) and the blind run (`jit-blind.yml#entry`), not with new exposure. |
| OBAAF-GHA-020: agent job without egress restriction | 8 low | 19 low (baseline) | No agent job has an enforced network policy. `OBAAF_EGRESS` would only record intent, so it is not set. |
| OBAAF-GHA-001: secret in a pull-request job | 0 | 1, reviewed with an expiry in `.github/obaaf.yml` | `private-scan` (twice: `pull_request_target` and its data-only checkout) and `unity`, behind a required reviewer. On Nov 11 `private-scan` moved off `pull_request_target` to a `workflow_dispatch` that a keyless pull-request job starts (#247); its entries were removed from `.github/obaaf.yml`, and the audit reports no finding on it. Between Oct 30 and Nov 9 six unreviewed ones had appeared in reporting mode; they are gone (keyless pull-request jobs) or reviewed. |
| OBAAF-GHA-012: agent reads the pull request's instruction files | 0 | 0 | One appeared in reporting mode (`discovery` on pull requests); the planner now runs only on a dispatch from main. |
| OBAAF-REPO-001: no CODEOWNERS | 0 | 0 | `.github/CODEOWNERS` names an owner for workflows and everything that decides a verdict. |

## Proposals

A candidate fix is a game-relative diff made against the seeded game (`player/player.tscn`). OBAAF
checks repository-relative Git diffs, as a pull request would see them. `normalize()` clones this
repository's committed HEAD into a disposable repository, commits the seeded defect there (benchmark
lineage: never on main), applies the candidate to a second clone, and asks Git for the diff. No game
code runs. The bundle holds `patch.diff` and untrusted `meta.json` only; the verification report
and frames stay outside it, which OBAAF requires.

Two rule sets, both required:

- **OBAAF** (`obaaf proposal check --repo`): no workflow, instruction, CODEOWNERS or OBAAF file; no
  symlink, submodule or rename; at most 100 paths and 1,000,000 bytes; the patch is applied again to
  a temporary index of the base. Expectrail adds its trust boundary to the protected paths:
  `agents/**`, `harness/**`, `expectrail/**`, `contracts/**`, `specs/**`, `tests/**`, `bench/**`,
  `bugs/**`, `requirements*.txt`.
- **Expectrail**: every changed path is under `game/platformer/` and matches the request's editable
  globs.

What the tests show (`tests/test_assurance.py`, run with OBAAF installed in `obaaf-audit`): the real
fall-through fix passes both; the same fix plus a workflow edit, a verifier edit, a spec edit or a
seeded-bug edit is refused; a symlink is refused; the raw game-relative fixture and a bundle with
`verification.json` in it are refused; a bundle changed after normalization fails its digest; a fix
to a game file outside the editable globs passes OBAAF and is refused by Expectrail. The fakes that
hide or sink the robot pass the proposal check, as they should: they are wrong in meaning, not in
where they write, and Expectrail's verifier is what rejects them.

    python3 -m agents.assurance.proposal --seed bugs/physics-fall-through/v1.patch \
        --candidate agents/fixtures/fix-collision-mask.patch --out runs/proposal

## Muse Code without the key (experiment, Oct 30)

Muse Code can run without ever holding the Meta API key. `agents/muse_gateway.py` gives Muse a
placeholder of the key's length and an HTTPS proxy (mitmproxy 12.2.3 with
`agents/muse_gateway_addon.py`) that holds the real key, swaps it in for `*.meta.ai` only, refuses
every other host, and logs host, path, status and header names, never values. Muse trusts the
proxy's certificate and nothing else. `fix-matrix.yml`, `bench: gateway`; run 41073919731, repeated on the
code as merged in run 41074472926 (19 requests, 5.5 s inside the sandbox):

| Variant | Result |
| --- | --- |
| Placeholder, no proxy (control) | Rejected: "your API key from META_API_KEY was rejected" |
| Through the proxy, on the host | Answered; 21 requests, all to api.meta.ai, key swapped into `Authorization` |
| Through the proxy, inside the fixer's bubblewrap sandbox, `~/.local/bin` bound read-only | **Answered; 18 requests, all to api.meta.ai; 8 s; no download** |
| Through the proxy, inside the sandbox as the fixer runs it today | Answered only when the proxy also passed lookaside.facebook.com |

The real key appeared in neither Muse's output nor the proxy log.

**Now the default for every live Muse Code run in CI** (`EXPECTRAIL_MUSE_GATEWAY=on` in the fix
matrix, judge and demo jobs and the live jobs in ci.yml; `agents/gateway.py`):

- Every `muse exec` goes through `agents.sandbox.run_muse`, which starts the proxy for that run,
  gives Muse the placeholder, the proxy and its certificate, and stops the proxy afterwards. On and
  unavailable (no mitmproxy, no key) is an error, never a fallback to giving Muse the key.
- Inside bubblewrap the sandbox has **no network** (`--unshare-net`). Its only way out is
  `agents/gateway_bridge.py`, which forwards 127.0.0.1:8899 in the sandbox to the proxy through a
  Unix socket bound at `/gateway`. Muse cannot ignore the proxy and reach another host.
- On the host (the screenshot judge's unsandboxed path, the live trust probe) the placeholder and
  the proxy apply, but nothing stops a process from opening its own connections.
- Each run records `gateway` in `sandbox.json` (requests, hosts, blocked hosts, the header names
  the key went into), and each job ends with a "Muse key gateway" notice summing them.
- The proxy runs in the same CI job, so OBAAF still counts the key in that job (GHA-005). A gateway
  hosted elsewhere, which agent jobs reach with their GitHub identity, would clear it.

**Every fix attempt no longer downloads Muse Code.** `muse` is a shell launcher that runs a 415 MB
program installed beside it (`~/.local/bin/muse-bin-<version>`, with three small version files).
The sandbox replaces the home directory and used to bind only the launcher, so every attempt
downloaded the program again, inside the sandbox. Those files are now bound read-only
(`agents/sandbox.py`, `muse_install_files`), and the launcher runs once on the host first
(`muse --version`, no key) so an update falls due outside the sandbox, not inside it.

## Not done, in order

1. **The replay runs the candidate's code with the verifier's authority.** `harness/run.py` gives
   the patched game an allowlisted environment (no keys or private paths, PR #82), but it still runs
   on the verifier's file system with network access. A network-less, file-scoped worker for the
   replay is the real fix.
2. **Evidence binding (Phase B):** a closed candidate manifest, an evidence manifest, and a signed
   statement naming the exact proposal and verification report, verified before any effect.
3. **Protected pull requests (Phase C):** a model gateway so agent jobs hold no provider key,
   enforced egress, separate jobs for capture, attestation, approval and effect, and an independent
   approval in a protected environment. Until then no agent opens a pull request.
