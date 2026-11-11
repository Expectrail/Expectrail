# Discovery inputs

What advisory discovery ([docs/discovery.md](../docs/discovery.md)) reads, as opposed to the checks
people write ([`specs/`](../specs)).

- [`platformer.profile.json`](platformer.profile.json): the mechanics profile. Four claims read from
  the game's code and settings (the double jump, the gun's cooldown, the sprite's facing, the
  enemies' patrol), each with its parameters, where in the code it comes from, and its known
  exceptions, plus the twelve templates that turn the claims into trace contracts. Every claim is
  `inferred_code` and no template is approved (`approvalRef` is null), so every contract built from
  them is advisory.
- [`freeze.json`](freeze.json): freeze 2, the one fresh set 2 is written against. The sha256 of
  every file that decides a finding and of the clean game, and the exact blind command. It was
  retired on November 9, 2026: it is kept as the record of the baseline commit `c169a5e`, and
  frozen files have changed on main since, so `python -m expectrail.discovery.freeze verify` exits
  1 on main, naming them. Check the record against a checkout of the baseline instead:
  `git worktree add --detach runs/baseline c169a5e0da304773587304ed47bc8aabcec80da7`, then
  `python -m expectrail.discovery.freeze verify --root runs/baseline`.
  `tests/test_discovery_freeze.py` does the same in CI. A new blind claim needs a new freeze.
- [`freeze-1.json`](freeze-1.json): freeze 1, the one fresh set 1 was written against (commit
  `0b6556c`), kept so set 1's runs stay checkable. It differs from freeze 2 only in the planner's
  request and the blind command.
