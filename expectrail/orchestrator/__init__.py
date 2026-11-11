"""Verification as a job: one service behind the CLI, MCP, the Action and the site (docs/orchestrator.md).

A verification request becomes a job with a folder of its own, a status file that is always whole,
and an output that appears only when the job has finished. The orchestrator runs the verifier; it
never starts a fixer and never falls back to saved data.
"""
