"""Agent-agnostic fixer adapter for Expectrail (`claude-code`, `codex`, `aider`, `llm-patch`, `custom-cmd`).

agents.fixer.run_fixer calls run_byo_agent when EXPECTRAIL_FIXER_AGENT (or --agent) names one of these.
The agent works in the same fixer workspace as Muse Code (agents.fixer.prepare_fixer_workspace: a copy
of the game with the seeded bug, never the verifier's code, the held-out routes or the signing key),
under the same bubblewrap mount when bwrap is usable, with only its own provider's key in its
environment (agents.keys.byo_agent_env). The candidate is then diffed and checked against the
editable globs exactly as for Muse.

One difference, recorded in each attempt's sandbox.json: Muse Code can run behind the key gateway
with no network of its own; a BYO agent runs with the host's network, because the gateway proxies
Meta's API only. That record states the network, the gateway as off with the reason, and the names
(never the values) of the provider key envs the agent received.
`llm-patch` runs nothing in the sandbox: Expectrail sends the failing check and the editable files to
the configured model and applies the diff it returns.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from expectrail.providers import chat_completion, extract_message_text, resolve_provider

SUPPORTED_AGENTS = (
    "claude-code",
    "codex",
    "aider",
    "llm-patch",
    "custom-cmd",
    "muse-code",
)
PROMPT_FILE = ".expectrail-fixer-prompt.txt"


def resolve_fixer_agent(explicit_agent: str | None = None) -> str:
    """Determine which coding agent backend to run inside the sandboxed worktree."""
    if explicit_agent and explicit_agent != "auto":
        return explicit_agent.lower()
    env_agent = os.environ.get("EXPECTRAIL_FIXER_AGENT", "").strip().lower()
    if env_agent:
        return env_agent
    if shutil.which("claude"):
        return "claude-code"
    if shutil.which("codex"):
        return "codex"
    if shutil.which("aider"):
        return "aider"
    if shutil.which("muse"):
        return "muse-code"
    return "llm-patch"


def build_agent_cli_command(
    agent: str,
    prompt_text: str,
    worktree: Path,
    *,
    model: str | None = None,
    root_as_agent_sees_it: str | None = None,
) -> list[str]:
    """Build the subprocess command list for CLI-based coding agents (`claude-code`, `codex`, `aider`, `custom-cmd`, `muse-code`).

    ``root_as_agent_sees_it`` is the workspace path inside the sandbox (bwrap binds it at /fixer);
    paths handed to the agent use it, while the prompt file is written through ``worktree`` on the host.
    """
    agent = agent.lower()
    (worktree / PROMPT_FILE).write_text(prompt_text, encoding="utf-8")
    root = root_as_agent_sees_it or str(worktree)
    prompt_file = f"{root.rstrip('/')}/{PROMPT_FILE}"

    if agent == "claude-code":
        cmd = [
            "claude",
            "-p",
            prompt_text,
            "--allowedTools",
            "Edit,Write,Read,Glob,Grep,Bash",
        ]
        if model and model not in ("muse-code", "claude-code"):
            cmd.extend(["--model", model])
        return cmd

    if agent == "codex":
        cmd = [
            "codex",
            "--quiet",
            "--approval-mode",
            "full-auto",
        ]
        if model and model not in ("muse-code", "codex"):
            cmd.extend(["--model", model])
        cmd.append(prompt_text)
        return cmd

    if agent == "aider":
        cmd = [
            "aider",
            "--yes-always",
            "--no-auto-commits",
            "--message-file",
            prompt_file,
        ]
        if model and model not in ("muse-code", "aider"):
            cmd.extend(["--model", model])
        return cmd

    if agent == "custom-cmd":
        template = os.environ.get("EXPECTRAIL_FIXER_CMD", "").strip()
        if not template:
            raise RuntimeError(
                "EXPECTRAIL_FIXER_AGENT=custom-cmd requires EXPECTRAIL_FIXER_CMD "
                "(e.g. 'my-agent --workdir {worktree} --prompt-file {prompt_file}')"
            )
        rendered = template.format(
            worktree=root,
            prompt_file=prompt_file,
            model=model or "",
        )
        return shlex.split(rendered)

    if agent == "muse-code":
        from agents.sandbox import MUSE_ARGV

        return [*MUSE_ARGV, prompt_text]

    raise ValueError(f"Unsupported CLI agent '{agent}'. Expected one of: {SUPPORTED_AGENTS}")


def extract_unified_diff(text: str) -> str:
    """Extract a unified git diff (`--- a/...`, `+++ b/...`, `@@ ... @@`) from an LLM response."""
    fenced = re.findall(r"```(?:diff|patch)?\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
    for block in fenced:
        if "--- " in block and "+++ " in block:
            return block.strip() + "\n"
    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- a/") or line.startswith("--- "):
            start_idx = idx
            break
    if start_idx is not None:
        return "\n".join(lines[start_idx:]).strip() + "\n"
    return ""


def _collect_candidate_files(worktree: Path, max_files: int = 12, max_bytes: int = 32000) -> str:
    """Gather editable text/scene/script files in the worktree for direct BYO-LLM patch generation."""
    exts = {".gd", ".tscn", ".tres", ".py", ".js", ".ts", ".html", ".css", ".json"}
    chunks: list[str] = []
    total = 0
    for path in sorted(worktree.rglob("*")):
        if not path.is_file() or path.suffix not in exts:
            continue
        rel = path.relative_to(worktree)
        if any(part.startswith(".") or part in ("addons", "node_modules", "__pycache__") for part in rel.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if total + len(content) > max_bytes:
            continue
        chunks.append(f"=== FILE: {rel.as_posix()} ===\n{content}")
        total += len(content)
        if len(chunks) >= max_files:
            break
    return "\n\n".join(chunks)


def run_llm_patch_fixer(
    prompt_text: str,
    worktree: Path,
    out_patch: Path,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Generate and apply a unified git diff directly via any BYO-LLM API without requiring a local agent CLI."""
    cfg = resolve_provider(role="FIXER", model=model if model not in ("muse-code", "llm-patch") else None)
    repo_context = _collect_candidate_files(worktree)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert software and game engine bug-fixing agent inside an Expectrail sandbox. "
                "Given the failure triage report and the source files, return ONLY a minimal unified git diff "
                "(starting with `--- a/<path>` and `+++ b/<path>`) inside a ```diff code block that fixes the bug "
                "without introducing visual offsets or reward hacks."
            ),
        },
        {
            "role": "user",
            "content": f"{prompt_text}\n\nRepository Files:\n{repo_context}",
        },
    ]
    raw = chat_completion(messages, role="FIXER", config=cfg, max_tokens=4096, temperature=0.0)
    reply_text = extract_message_text(cfg, raw)
    diff_text = extract_unified_diff(reply_text)
    if not diff_text:
        raise RuntimeError(f"BYO-LLM fixer ({cfg.provider}/{cfg.model}) did not return a valid unified diff.")

    out_patch.parent.mkdir(parents=True, exist_ok=True)
    out_patch.write_text(diff_text, encoding="utf-8")
    return {
        "agent": "llm-patch",
        "provider": cfg.provider,
        "model": cfg.model,
        "patch_path": str(out_patch),
        "patch_bytes": len(diff_text),
    }


def agent_install_paths(agent: str) -> list[Path]:
    """Read-only binds an agent CLI needs inside bwrap: its launcher's directory and the directory
    of what the launcher resolves to, plus EXPECTRAIL_FIXER_RO_BINDS (colon-separated)."""
    from agents.keys import BYO_AGENT_BINARIES

    paths: list[Path] = []
    binary = BYO_AGENT_BINARIES.get(agent)
    found = shutil.which(binary) if binary else None
    if found:
        paths += [Path(found).parent, Path(found).resolve().parent]
    for extra in os.environ.get("EXPECTRAIL_FIXER_RO_BINDS", "").split(":"):
        if extra.strip():
            paths.append(Path(extra.strip()))
    system = ("/usr", "/bin", "/lib", "/lib64")
    return sorted({p for p in paths if not str(p).startswith(system)})


def run_byo_agent(
    prompt_text: str,
    work: Path,
    out: Path,
    *,
    agent: str,
    model: str | None = None,
    timeout: int = 900,
    require_sandbox: bool = False,
    detected: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    """Run a BYO coding agent in the fixer workspace ``work``; the caller diffs ``work`` afterwards.

    Returns (process, sandbox meta). ``llm-patch`` applies the model's diff to ``work`` itself and
    returns a synthetic process (exit 0 when the diff applied, 1 when it did not).
    """
    from agents.keys import BYO_AGENT_KEY_ENVS, byo_agent_env
    from agents.sandbox import detect_sandbox, muse_kind_for, run_sandboxed

    if agent not in SUPPORTED_AGENTS or agent == "muse-code":
        raise ValueError(f"run_byo_agent does not run {agent!r} (Muse Code goes through agents.sandbox.run_muse)")
    if agent == "llm-patch":
        from harness.run import apply_patches

        info = run_llm_patch_fixer(prompt_text, work, out / "llm-patch.diff", model=model)
        try:
            apply_patches(work, [out / "llm-patch.diff"])
            proc = subprocess.CompletedProcess(["llm-patch"], 0, json.dumps(info), "")
        except (SystemExit, subprocess.CalledProcessError, RuntimeError) as exc:
            proc = subprocess.CompletedProcess(["llm-patch"], 1, json.dumps(info), f"diff did not apply: {exc}")
        return proc, {"kind": "none", "agent": agent, "requireSandbox": require_sandbox,
                      "network": "not applicable: no agent process runs", "provider": info["provider"],
                      "model": info["model"]}

    detected = detected if detected is not None else detect_sandbox()
    kind = muse_kind_for(detected)
    if require_sandbox and kind == "none":
        raise SystemExit("--require-sandbox needs bubblewrap (bwrap) on PATH to confine the fixer agent")
    root = "/fixer" if kind == "bwrap" else str(work.resolve())
    cmd = build_agent_cli_command(agent, prompt_text, work, model=model, root_as_agent_sees_it=root)
    agent_env = byo_agent_env(agent)
    # The record says what this run did, not what some run could do. It used to read
    # "host network (the key gateway speaks only to Meta's API)" for every bwrap run whatever the
    # agent, next to a gateway recorded as off: a Claude Code run named a Meta constraint that was
    # never applied. The network is stated plainly, the reason no gateway applies sits with the
    # gateway, and keyEnvs names the provider key the agent actually received (names, never values).
    meta: dict[str, Any] = {
        "kind": kind, "agent": agent, "requireSandbox": require_sandbox, "detect": detected,
        "network": "host network" if kind == "bwrap" else "host network (no sandbox)",
        "keyEnvs": sorted(set(BYO_AGENT_KEY_ENVS.get(agent, ())) & set(agent_env)),
        "gateway": {
            "mode": "off",
            "why": "the key gateway proxies Meta's API only, so a BYO agent reaches its own "
                   "provider over the host network",
        },
    }
    try:
        proc = run_sandboxed(cmd, work=work, env=agent_env, network=True, kind=kind,
                             timeout=timeout, extra_ro=agent_install_paths(agent))
    except subprocess.TimeoutExpired as exc:
        exc.sandbox_meta = meta
        raise
    finally:
        (work / PROMPT_FILE).unlink(missing_ok=True)
    return proc, meta
