"""The CI gate: verify a pull request's game change in one job, post the verdict from another.

- ``expectrail.gate.record``: the findings record (contracts/findings.schema.json), finding ids and
  the decision rule. Standard library only; both sides use it.
- ``expectrail.gate.verify``: the untrusted side. Replays the pull request's game, judges the
  approved specs and writes the record, the verdicts and the review page.
- ``expectrail.gate.comment``: the trusted side. Reads the record as data and posts or updates one
  pull request comment. Standard library only.

docs/ci-gate.md explains how a game repository adds the gate.
"""
