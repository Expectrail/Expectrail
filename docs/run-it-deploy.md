# Put Run it on expectrail.tech (#265)

This is Sean's launch checklist. It uses the existing static page at
<https://expectrail.tech/run-it/> and deploys only its visitor API at
`https://api.expectrail.tech`. It requires no model key and makes no model calls:
the three original samples use their recorded vision answers. The fourth card is
not ready until its repair recording exists. Do not run the recording workflow to deploy.

**Status:** the code and smoke checks have been tested offline. This account setup,
DNS change, deployment and live visitor check have **not been run**. Dashboard
labels below follow the linked public documentation, checked November 15, 2026;
they have not been checked inside Sean's accounts. If a screen differs, stop at
that step rather than grant broader access.

## What is needed, and who supplies it

| Item | Exact setting / purpose | Owner |
| --- | --- | --- |
| GitHub account | Access to Expectrail/Expectrail, Actions, repository settings and token approval if the organization requires it | Sean: account |
| Cloudflare account | Workers and SQLite Durable Objects; access to the active `expectrail.tech` zone | Sean: account |
| Domain registrar | Access to change nameservers only if the zone is not already on Cloudflare | Sean: account |
| Browser Codespace | A temporary terminal in the browser; Node 22+ and Python 3; check the account's included usage before creating it | Sean: account; commands below are automatable |
| Deployment API token | One Cloudflare account: **Workers Scripts: Edit**, **Account Settings: Read**. One zone, `expectrail.tech`: **Workers Routes: Edit**, **Zone: Read**. The UI may call Edit “Write”. No KV, R2, DNS-edit, billing or user permissions | Sean: create; typed at hidden terminal prompt only |
| Dispatch token | Fine-grained GitHub PAT; resource owner **Expectrail**, only **Expectrail/Expectrail**; repository **Actions: Read and write**; mandatory **Metadata: Read**; 30-day expiry or a shorter organization limit | Sean: create/approve; typed into Worker secret |
| GitHub App | **Not needed** for this implementation. It does not mint/refresh App installation tokens; do not paste an expiring installation token as a permanent credential | No setup |
| Worker secret `GITHUB_TOKEN` | The dispatch PAT, not a model key or the Cloudflare deploy token | Sean: type in Cloudflare Secrets |
| Worker secret `VISITOR_SALT` | At least 32 randomly generated characters, from a password manager | Sean: type in Cloudflare Secrets |
| `CLOUDFLARE_ACCOUNT_ID` | Public account identifier for the deployment command; not a Worker secret | Sean: copy; terminal environment only |
| Worker and storage | `expectrail-run-it`; binding `RUN_IT`, class `RunIt`, migration `v1` with `new_sqlite_classes`; one Durable Object named `run-it` | Automatable by the supplied Wrangler configuration |
| API DNS and TLS | Worker Custom Domain `api.expectrail.tech`; Cloudflare creates its managed DNS record and certificate. No hand-written CNAME to `workers.dev` | Automatable after Sean authorizes zone access |
| Site DNS / Pages | Preserve existing apex/`www` A, AAAA or CNAME records and verification TXT records. Keep GitHub Pages serving the existing `docs/` site and its HTTPS custom domain | Sean: check account; no change normally needed |
| `RUN_IT_OPEN` | Text `false` at first; text `true` only after the closed smoke check | Sean: launch/stop decision |
| `RECORDED_FIX_OPEN` | Text `false`; keep recorded repair closed until it has its separate budget and concurrency limit | Sean: separate launch decision; default is automated |
| `ALLOWED_ORIGINS` | Text `https://expectrail.tech` (no trailing slash, no wildcard) | Automatable default |
| `PER_VISITOR`, `DAILY_CAP`, `BREAKER` | Text `3`, `40`, `3`: per salted address/day, all reservations/day, consecutive failed runs | Automatable defaults |
| `BREAKER_EPOCH` | Text `0`; change to a new value only after investigating a tripped breaker | Sean: recovery decision |
| `VISITOR_HEADER` | Leave unset: production reads Cloudflare's `CF-Connecting-IP`. Do not substitute a visitor-supplied header | Automatable default |
| GitHub workflow credentials | Existing `github.token`, minted per job: verify has contents-read; publish has contents-write. **No new repository secret or environment** | Automatic; Sean checks existing policy allows publishing to `run-it-results` |

The token can dispatch **any** workflow in this repository, not just Run it; GitHub
has no per-workflow token scope. The service's endpoint allowlist is tested, but a
stolen token is outside that boundary. Before launch, Sean must confirm that
model-spending workflows still require his `main-only` environment approval and
cannot bypass it. Never weaken that protection for this deployment.

## A. Prepare the accounts and domain

1. Open <https://github.com/Expectrail/Expectrail> while signed in as Sean.
2. Select the `main` branch. Continue only after this change has merged there.
3. Open the repository's **Settings → Pages**. Success: the existing site is published at `https://expectrail.tech`; do not change its source for this API deployment.
4. Open <https://expectrail.tech/run-it/>. Success: the sample cards and earlier results page load; a service-unavailable message is expected before deployment.
5. Open **Settings → Environments → main-only** in the repository. Success: required review by Sean remains enabled for workflows that spend model money; do not approve a recording run as part of this guide.
6. Open <https://dash.cloudflare.com/> in another tab and sign in to the account that will own the service.
7. Open **Workers & Pages**. Check the plan before continuing: SQLite Durable Objects are available on the Workers Free plan; this guide does not require upgrading to Paid. Free-plan limit exhaustion stops service rather than being evidence of a successful run.
8. Open **Domains → expectrail.tech** (called **Websites** in some dashboards). Success: the zone says **Active**. If already active, go to section B.

Only if the zone is not active:

9. Select **Add a domain** in Cloudflare.
10. Enter `expectrail.tech`.
11. Choose the Free domain plan.
12. Review the imported DNS records against the current registrar/DNS provider's records. Preserve the site's apex/`www` records, mail MX records and TXT records; automatic discovery is not proof they are all present. If unsure, have Timothy review this list before continuing.
13. Copy the two nameservers Cloudflare assigns to this zone.
14. Open the registrar account's nameserver settings for `expectrail.tech`.
15. If DNSSEC is enabled there, disable it before the nameserver transfer, following the registrar's confirmation screen. Do not leave an old DS record behind.
16. Replace the existing authoritative nameservers with the two assigned in step 13. These values are account-specific; never copy example nameservers from a guide.
17. Return to the Cloudflare zone overview and wait for **Active**. This can take time; do not deploy while it is pending.
18. Reopen <https://expectrail.tech/run-it/> to confirm the existing site still loads.
19. If DNSSEC was enabled before the transfer, open **Cloudflare → expectrail.tech → DNS → Settings → DNSSEC** after the zone becomes Active; otherwise go to section B.
20. Select **Enable DNSSEC**.
21. Copy the DS record values Cloudflare displays.
22. Enter those new DS values in the registrar's DNSSEC screen. Success: the registrar uses Cloudflare's current DS record, not the old provider's; have Timothy check resolution before launch if the registrar's fields differ.

The only **new service DNS record** is the managed Custom Domain for
`api.expectrail.tech`. If that hostname already has a record or another service,
have its owner resolve the conflict before deploying; do not delete it blindly.
The registrar steps vary by registrar; Cloudflare's [zone setup guide](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
is the reference for the transfer. Domain registration and hosting costs remain Sean's account decisions.

## B. Make the short-lived deployment token

23. Open Cloudflare **My Profile → API Tokens**.
24. Select **Create Token → Create Custom Token**.
25. Name it `Expectrail Run it deploy`.
26. Add the account permission **Workers Scripts → Edit**.
27. Add the account permission **Account Settings → Read**.
28. Add the zone permission **Workers Routes → Edit**.
29. Add the zone permission **Zone → Read**.
30. Under **Account Resources**, select **Include → Specific account →** the account from section A.
31. Under **Zone Resources**, select **Include → Specific zone → expectrail.tech**.
32. Set the token's expiry to tomorrow (or the shortest available period covering deployment).
33. Select **Continue to summary**. Success: only the four permissions and the single account/zone above are listed; do not use the broader Workers template unchanged.
34. Select **Create Token**.
35. Copy the token to your password manager temporarily. Never paste it into a repository file, chat, issue, screenshot, command line or `.env` file.

Wrangler uses this token only for deployment. [Worker permissions](https://developers.cloudflare.com/workers/authorization/workers/)
cover code deployment; [Durable Objects inherit Worker permissions](https://developers.cloudflare.com/workers/authorization/durable-objects/).
Changing a Custom Domain also requires Workers Routes access to its zone.

## C. Deploy closed, using the browser terminal

36. On the repository's `main` page, select **Code → Codespaces → Create codespace on main**. This uses Sean's Codespaces allowance; stop if GitHub asks to enable spending you do not want.
37. In the browser editor, select **Terminal → New Terminal**. The panel at the bottom is where the following exact lines go; press Enter after each line.
38. Run `node --version`. Success: `v22` or newer. If older, ask Timothy to provide a current Codespace; do not improvise an install as part of launch.
39. Run `python3 --version`. Success: Python 3 is installed.
40. Run `cd apps/run-it-edge`. Success: the prompt ends in `apps/run-it-edge`.
41. Run `cp wrangler.toml.example wrangler.toml`. Success: no error; this copies only public configuration, with `RUN_IT_OPEN = "false"`.
42. In Cloudflare's zone overview, copy the **Account ID** (not the Zone ID).
43. Run `read -r -p 'Cloudflare account ID: ' CLOUDFLARE_ACCOUNT_ID; export CLOUDFLARE_ACCOUNT_ID`. At the prompt, paste the account ID and press Enter.
44. Run `read -r -s -p 'Cloudflare deploy token (hidden): ' CLOUDFLARE_API_TOKEN; export CLOUDFLARE_API_TOKEN; printf '\n'`. At the prompt, paste the deployment token and press Enter. **Nothing echoes while you type.** The token is held in this terminal's environment, not command history or a file. Do not use `wrangler login`, `echo` the token, or enable shell tracing.
45. Run `npx --yes wrangler@4 deploy --config wrangler.toml`. This downloads the deployment tool and deploys the closed service. If it asks to create the first Durable Object migration, confirm that it names only `RunIt`. Success: output names `expectrail-run-it`, its `RUN_IT` binding and `api.expectrail.tech`, with no error. A permission error is a reason to review section B, not to grant all permissions.
46. Run `unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID`. Success: no error; the deployment credential is no longer in this terminal's environment.
47. In Cloudflare **My Profile → API Tokens**, revoke `Expectrail Run it deploy`. The running service does not use this token.
48. In Cloudflare **Workers & Pages → expectrail-run-it → Settings → Domains & Routes**, confirm `api.expectrail.tech` appears as a **Custom Domain** with its certificate active. DNS/TLS issuance may take time.
49. Open <https://api.expectrail.tech/health>. Success: JSON says `"kind":"health"`, `"open":false`, `"standIn":false` (spacing may differ).

The checked-in [Wrangler example](../apps/run-it-edge/wrangler.toml.example) creates
the binding and custom domain, including managed DNS/TLS. Public workers.dev and
preview URLs are disabled; visitors use the one API hostname. It contains no secrets.
For later code deployments, repeat section C with a new temporary token; the
example deliberately closes admissions again. Preserve the existing Worker name,
Durable Object binding, migration and object identity: a fresh service would have
fresh quota counters. Never delete storage to reset a quota.

## D. Add the two runtime secrets in the dashboard

**Before this section:** the `spend` environment must exist and the change that moves every model-key
job into it must be merged ([spend-environment.md](spend-environment.md)). A fine-grained token cannot be
limited to one workflow: with Actions write it can start any workflow, Run it's or a paid one. With
`spend` in place, a paid run it starts waits for Sean's approval and spends nothing without it.

50. Open GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens** from your profile menu (not repository Settings).
51. Select **Generate new token**.
52. Name it `Expectrail Run it dispatch`.
53. Set **Expiration** to 30 days or the shorter organization limit.
54. Set **Resource owner** to **Expectrail**.
55. Under **Repository access**, choose **Only select repositories → Expectrail** (the `Expectrail/Expectrail` repository).
56. Under **Repository permissions**, set **Actions → Read and write**. Leave every other optional permission unset; Metadata read is automatic.
57. Select **Generate token**. If it says approval is pending, have the Expectrail organization owner approve this exact repository/permission request before continuing.
58. Copy the token to your password manager. Add a reminder to replace it before expiry; replacement is a new token pasted into the same Worker secret, followed by revocation of the old token.
59. Open Cloudflare **Workers & Pages → expectrail-run-it → Settings → Variables and Secrets → Add**.
60. Select type **Secret**.
61. Enter the name `GITHUB_TOKEN`.
62. Paste the GitHub token into **Value**. This is the only deployment field that receives the GitHub token; never add it to GitHub Actions secrets for Run it.
63. Select **Deploy** to save the secret.
64. Generate a random password of at least 32 characters in your password manager for `VISITOR_SALT`.
65. In the same Cloudflare **Variables and Secrets** panel, select **Add**.
66. Select type **Secret**.
67. Enter the name `VISITOR_SALT`.
68. Paste the generated value into **Value**.
69. Select **Deploy** to save the secret.
70. Check that the plain-text variable `RUN_IT_OPEN` is still `false`. Both secrets may be present while the service remains safely closed.

[GitHub's token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
explain repository selection and organization approval. [Cloudflare's secret instructions](https://developers.cloudflare.com/workers/configuration/secrets/)
explain the Secret type and Deploy button. No secret value belongs in `wrangler.toml`,
a shell command, a log, or an artifact. Changing the salt resets visitor identities;
keep it stable during a launch day.

## E. Check closed, then admit one sample

71. In the same Codespace terminal, run `python3 ../../tools/runit_api_smoke.py https://api.expectrail.tech --expect-open false`. Success: PASS for health, disallowed origin and RUN_IT_OPEN, followed by “zero valid start requests sent”. The progress line says it is not applicable while closed. No game run is started.
72. In Cloudflare **Variables and Secrets**, edit the text variable `RUN_IT_OPEN` to `true`.
73. Select **Deploy** to apply that change.
74. Run `python3 ../../tools/runit_api_smoke.py https://api.expectrail.tech --expect-open true`. Success: five PASS lines, ending in a request ID and `running`, `publishing` or `published`. This starts at most **one** fall-through-bug run using recorded vision; it consumes one visitor/day reservation. It does not check the final verdict. Do not run it repeatedly to make a failure disappear.
75. Open GitHub **Actions → Run it**. Find the run whose title contains the request ID printed in step 74. Success: it progresses and both verify and publish finish successfully.
76. Open <https://expectrail.tech/run-it/>. Select the latest finished fall-through-bug evidence. Success: the run's ID/time corresponds to step 74, the decision is reject, recorded vision is labelled, and the evidence opens. An older fallback is not proof that this deployment worked.
77. Select the clean sample's **Run** button once. Success: the page shows waiting, then progress and a fresh accept with evidence. If it says busy, wait for the preceding run to finish before trying once more. Do not bypass quotas from Actions.
78. Copy the two run links, conclusions, smoke output and page result into the deployment PR. This is the live evidence still missing from this change.
79. On <https://github.com/codespaces>, delete the temporary Codespace when finished. Do not commit its generated `wrangler.toml` or terminal files.

The smoke checker never reads a key, follows redirects, retries a dispatch or
starts a valid sample after closed health. Its bad-origin probe uses an invalid
sample so a broken CORS filter cannot make that probe into a game run. The closed
check reads the switch's public effect; the offline service tests additionally
prove that a valid POST while closed is refused. `open:false` can also mean missing
settings or an open circuit breaker, so it is not proof of which setting closed it.

## Stop and recover, without a terminal

80. To stop new visitors, open Cloudflare **Workers & Pages → expectrail-run-it → Settings → Variables and Secrets**.
81. Edit `RUN_IT_OPEN` to `false`.
82. Select **Deploy**. The page can still show earlier evidence. This does **not** cancel a request already dispatched or reserved before the change.
83. If an existing run must stop too, open its GitHub Actions run and select **Cancel workflow**. Read its eventual conclusion; do not assume cancellation already happened.
84. If the circuit breaker tripped, inspect the failed Run it jobs in Actions before reopening. Three consecutive infrastructure failures stop admissions; a correct reject of the seeded bug is not such a failure.
85. After the cause is fixed, edit `BREAKER_EPOCH` to a new string, such as the current date plus `-1`.
86. Select **Deploy**, keeping `RUN_IT_OPEN=false` until ready to repeat the closed/open checks.

A 403/401 dispatch refusal usually means token permission, approval or expiry;
fix the token in Secrets. Explicit refusals refund the reservation and impose a
one-minute dispatch cooldown. A lost reply or upstream server error instead keeps
the reservation: the request ID may already be running. Follow its status rather
than starting another run. Lost runs fail after five minutes; the service gives
up tracking an active run after thirty minutes. Neither timeout asserts that a
GitHub process was cancelled. A queued smoke timeout is a FAIL, not a fresh start.

## Cost boundaries and work still left

The defaults admit at most 40 reservations per UTC day and three per salted
address, with one active reservation. These are tested application limits, not
a dollar budget or user identity proof: non-browser clients can forge Origin;
shared addresses share quotas. The workflow already limits verify to 15 minutes
and publish to 5. The default day’s 40 admissions therefore carry at most **800 configured
job-timeout minutes** (40 × (15 + 5)). This is not measured runtime or a calendar-day
bill cap: jobs admitted yesterday can continue today, billing rules differ, and
manual workflow dispatches are outside this count. Visitor runs have no model key and do not spend on models.
Manual Actions dispatches bypass edge quotas; don't use them to bypass a closed service.

HTTP requests, storage and Actions still have provider limits/costs. A paid hosting
account can incur costs even when no game starts; these quotas do not cap an HTTP
flood's bill. Prefer the Free plan for this launch if its limits suit Sean, review
[Durable Objects plan limits](https://developers.cloudflare.com/durable-objects/platform/pricing/),
and do not treat a budget alert as a hard spending cap. [Wrangler environment variables](https://developers.cloudflare.com/workers/wrangler/system-environment-variables/)
and [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
are the deployment references.

No workflow edit is needed for the first deployment. The #265 nightly platform
check is `.github/workflows/run-it-nightly.yml` ("Run it nightly"): once a day
(09:17 UTC) and by hand, with `contents: read`, no secret, no environment and no
model. It runs the deployed HTTP smoke against `https://api.expectrail.tech` with
`--follow` and keeps its output as the `run-it-nightly` artifact for 30 days.

- While the repository variable `RUN_IT_EXPECT_OPEN` is unset or `false`, it is
  the closed check: health, origin refusal, and that admissions are closed. It
  starts nothing.
- When Sean opens admissions, he also sets `RUN_IT_EXPECT_OPEN` to `true`
  (Settings, Secrets and variables, Actions, Variables). From then on it starts
  one recorded sample a day (`clean`, `fall-through-bug` and
  `fall-through-repair` in turn), waits for `published`, and reads the published
  `status.json`, `findings.json`, the evidence viewer and `latest.json` from the
  address the page uses (`tools/runit_published.py`). It fails if the decision is
  not the sample's expected one, if any vision question went without a recorded
  answer, or if anything cannot be read. It uses one of the day's 40 admissions
  and the address quota of the runner it lands on; if a visitor's run is active
  at that moment it reports the refusal as a FAIL and does not retry.
- If the variable and the service disagree, the run fails at `RUN_IT_OPEN`: that
  is the check telling Sean the switch is not where he thinks.

It depends on the smoke's own `User-Agent` (#576): without it the deployed
service's Cloudflare check refuses the smoke at `health`.
Also still needed: a deployed concurrent burst, a first visitor's usability test,
and signed receipts (#255). The current page honestly labels receipts unsigned.
The live launch has not been demonstrated until section E's evidence exists.
