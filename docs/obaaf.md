# OBAAF in Expectrail

OBAAF (the Open Build and Agent Assurance Framework, https://github.com/Obaaf/OBAAF) is a
dependency pinned to commit `ef34304214923953cf7d67343b912385d4ce5906`. It checks whether a
change may cause an effect, such as a pull request or release, given its origin and approvals.
Expectrail checks whether the change does what the player needs. These are separate decisions,
and both are needed: an OBAAF check does not establish that the fix is correct, and a passing
Expectrail verdict does not grant write access by itself.

**Status: Phase A, reporting only (Oct 30).** Nothing is enforced and no protected effect is
enabled. What runs, in the `obaaf-audit` CI job on every push and pull request:

| What | How | Gated? |
| --- | --- | --- |
| Lane inventory | `.github/obaaf.yml` declares the 10 jobs that hand a Meta model untrusted input and act on its output as agent lanes (OBAAF does not recognise `python -m agents.*`). `agents/assurance/audit.py` fails CI if one is not classified as an agent, or if any job holds a model key without being a declared agent or a listed perception-only job (SAM, Glimmer). | Yes: a new model job needs a declaration and review |
| Pipeline findings | `obaaf check . --format json --fail-on never`; one notice per rule | No, reported |
| Proposals | `agents/assurance/proposal.py` turns a candidate fix into an OBAAF proposal bundle and checks it with `obaaf proposal check --repo` plus Expectrail's own allowlist | Tests only, see below |

## Where the secrets live (Nov 9)

Anyone with write access, or a coding agent acting for them, could read any repository secret by
pushing a branch with a workflow that prints it; branch protection does not apply to a workflow
running from its own branch. So no secret is a repository secret any more:

| Environment | Holds | Who can use it |
| --- | --- | --- |
| `main-only` | `HELDOUT_TOKEN` and every model key (`MODEL_API_KEY`, `META_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `FIREWORKS_API_KEY`, `BASETEN_API_KEY`) | Workflows on `main` only (deployment branch rule) |
| `unity` | The Unity licence | Any branch, after Sean approves each run (required reviewer) |

- Every job that uses one of these secrets declares the environment; `tests/test_main_only_environment.py`
  fails if one does not, or if a job in `main-only` can be started by a pull request.
- Pull requests run keyless: `discovery` (planner off) and `reported-bench` (traces only) hold no key,
  and their keyed twins `discovery-planner` and `reported-bench-sam` run only on a dispatch from main.
  `mutation-fix` rehearses keyless on a pull request; its live jobs are dispatch-only. `byo-smoke`
  no longer runs on pull requests at all: its live provider calls run daily and on dispatch, and its
  logic is tested offline on every pull request.
- A held-out or live bench can only be dispatched from `main`.
- `private-scan.yml` is the exception: `pull_request_target` runs as main, so the branch rule does not
  stop it. It reads a same-repository pull request's files as data and prints counts only. The
  residual risk is that counts are an oracle a writer could probe; it is recorded, with an expiry,
  as a reviewed finding in `.github/obaaf.yml`.
- What the checker cannot see, check in the settings: no repository or organization copy of these
  secrets, and `main-only` limited to `main`.

## Findings (Oct 30, main at e19b378 plus this change)

| Rule | Before | Now | What it means |
| --- | --- | --- | --- |
| OBAAF-GHA-001: secret in a pull-request job | 1 low | **0** | `agents-harness-verify` checked out the private held-out set on every same-repository pull request, then ran that branch's code: anyone who could push a branch could print the private set. That job now never sees it; `agents-harness-private` checks the private routes on pushes to main, the schedule and manual runs only. |
| OBAAF-REPO-001: no CODEOWNERS | 1 medium | **0** | `.github/CODEOWNERS` names an owner for workflows and everything that decides a verdict. It binds merges only once branch protection requires code-owner review (a repository setting). |
| OBAAF-GHA-005: secret in an agent job | 8 high | 8 high | The Muse key is in every agent job. Since Oct 30 Muse Code itself never receives it (the key gateway below); OBAAF's static check still sees it in the job, where the gateway runs. Clearing it needs the gateway hosted outside the job. Not suppressed. |
| OBAAF-GHA-020: agent job without egress restriction | 8 low | 8 low | No agent job has an enforced network policy. `OBAAF_EGRESS` would only record intent, so it is not set. |

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
