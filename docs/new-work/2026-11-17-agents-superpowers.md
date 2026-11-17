# AGENTS.md names which Superpowers skills agents use, and where this file overrides them

## What changed

Sean installed the Superpowers plugin (a library of working disciplines for coding agents) on November 17, 2026 and
asked for a draft of how Expectrail adopts it. This is that draft. `AGENTS.md` may only be changed by a person, so
this pull request is labelled `needs-sean` and is his to edit, merge or close.

- `AGENTS.md`: a new section, "Working disciplines (Superpowers)", between "Rules for every change" and "What only a
  person may do".
  - Six skills agents use, each with when to use it and what it means here: verification before completion,
    systematic debugging, test-driven development, git worktrees, requesting and receiving code review, and writing
    plans.
  - Three places the plugin's defaults give way: design work only when asked, with the design on the issue; finishing
    a branch always by pull request, never a local merge; subagents only when allowed and inside the issue's budget.
  - The section says this file wins over any skill, and that a skill never widens what an agent may do.

The plugin's own rules already say that a project's `AGENTS.md` takes precedence over its skills. The plan and design
skills save files under `docs/superpowers/` by default, and the branch-finishing skill offers a local merge as its
first option; both were read in the installed plugin (version 7.0.2) before writing the overrides.

## What was run

- `python3 -m unittest discover -s tests -t .`: `Ran 4716 tests`, `OK (skipped=54)`.
- `python3 -m tools.merge_guard`: flags the `AGENTS.md` change as `needs-sean`, as intended; the output is on the pull request.

## Not done

- Nothing reaches the ChatGPT and Grok builders that hand over zips; they cannot install the plugin.
- No builder has worked under this section yet, so nothing here is tested in practice.

## Files

- `AGENTS.md`
- `docs/new-work/2026-11-17-agents-superpowers.md`
