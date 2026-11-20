# Connecting a Godot project to Expectrail

This is the proposed service design for [#712](https://github.com/Expectrail/Expectrail/issues/712). A developer signs in with GitHub and installs the Expectrail GitHub App on the repositories they choose. Their own CI runner replays their game. The capture job runs candidate code without secrets. A separate trusted job judges the saved replay and publishes the result, receipt and evidence.

The hub lets the developer open those published results. It shows the verdict as issued and checks the receipt against the trust store. A missing artifact or an unverifiable receipt must be labelled as such. The hub never checks out the connected repository, downloads game source, imports a project, runs an executable or starts a replay. Connecting a repository gives the hub no reason to request repository contents permission.

## Data and deletion

| Data | Purpose | Proposed lifetime and removal |
| --- | --- | --- |
| Installation ID and selected repository names | List the repositories a signed-in developer currently has permission to see. An installation ID alone grants no access. | Keep while connected. Remove a deselected or deleted repository and its run references when notified. Reconcile permissions with GitHub before showing private results. Remove the entire installation on uninstall. |
| Repository and GitHub Actions run ID | Locate a published verification. GitHub remains the source of the run and its artifacts. | Keep references for up to 30 days from run completion. A developer can forget a run sooner. Disconnecting drops all associated references. |
| Browser session | A signed, short-lived cookie identifies the GitHub user and carries an expiry. Check current access for each repository. | Expire after one hour. Sign-out clears this browser’s cookie. Keep tokens, names of repositories and installation permissions out of the cookie. |
| OAuth state and temporary credentials | Match the callback to the browser that started sign-in and complete the GitHub exchange. | Consume state once within ten minutes. Use credentials only for the request that needs them and discard them afterwards. Never log cookies, tokens, callback codes or artifact URLs. |

Serve evidence on demand from the artifacts the developer's CI published. Treat it as untrusted data. Do not retain frames, telemetry, receipt bodies or game files in a hub database, cache or backup. Forgetting a run removes its hub reference. To remove the source artifacts, the developer deletes them in GitHub. Uninstalling the App revokes its GitHub access. Signing out only ends the browser session.

## Before live sign-in

Sean creates the GitHub App with a callback on the chosen HTTPS hub origin, records its client ID, generates its client secret and private key, provisions the hosting account and adds the DNS record for that origin. Sean configures the host's secret store for App credentials, cookie signing and authenticated installation deliveries. He publishes the privacy statement covering the fields above, retention, deletion, provider processing and a contact for requests. Host logs and backup settings must honor those lifetimes.

The service should start with all of that absent and show that GitHub sign-in is unconfigured. Offline tests will exercise sign-in, installation, removal and sign-out against a local GitHub stub. The runs and receipts slice owns how published results appear. The architecture decision and its rationale are in [#711](https://github.com/Expectrail/Expectrail/issues/711).
