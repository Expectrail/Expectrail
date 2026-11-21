"""The Expectrail hub service (#711, #712).

A developer signs in with GitHub and installs the Expectrail GitHub App on repositories they choose.
Verification runs in the developer's own CI; the hub reads what that run published and executes none
of their code. docs/hub-design.md is the design in plain words.

Files and owners: `hub/runs*.py`, `hub/receipts*.py` and `hub/templates/runs*` are #713's; the rest
of `hub/` is #712's. #713 registers its routes from a `hub/runs*.py` module that defines
`register(registry)` (see `hub.routes`); `hub.server` finds those modules by name, so neither issue
edits the other's files.
"""
