# Breakout trial inputs — drafts only

Upstream: https://github.com/mike0697/Breakout

Pin: `0ac7aed444ea593a023d9b666c211d7ab8acd51e`; MIT, copyright 2025 Michele
Pizzeghello. Fetch at that pin; no game source or assets are vendored here.
The `changes/` patches change only the fetched copy's `scripts/paddle.gd`.

Copy this config, `routes/` and `checks/` into the fetched project. The config
retains `draft: true`; neither check has an approval. The ball-launch check is
not ready to approve: the attempted route did not start the game.

The harmless patch adds a comment. The broken patch pins the paddle at x=8 after
its physics step, putting part of its 47-pixel drawing outside the left edge
once physics runs. In this trial the round never started, so that line was never
exercised. No detection success is claimed.

See the [trial report](../../../docs/outside-trials/breakout/report.md), frozen
choice, numbered commands, raw traces and proposed follow-ups. This project is
not in the working outside-trial list.
