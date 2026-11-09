"""Zero-dependency Model Context Protocol (MCP) stdio server for Expectrail.

Lets Claude Code, Cursor, Windsurf, or any MCP client invoke Expectrail's deterministic
verification loop directly without leaving the developer's existing IDE or agent workflow.

Add to `.mcp.json` or `.cursor/mcp.json`:
{
  "mcpServers": {
    "expectrail": {
      "command": "python3",
      "args": ["-m", "agents.mcp_server"]
    }
  }
}
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SERVER_INFO = {
    "name": "expectrail-mcp",
    "version": "0.2.0",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "expectrail_draft_spec",
        "description": (
            "Draft an Expectrail test spec (expectrail.test-spec/v0) from one plain-English check, e.g. "
            "'The player never falls through the ground', with the configured model. The draft is "
            "validated and linted, and carries no approval: a person approves it with "
            "`python3 -m expectrail.spec_writer approve <path> --by <name>` before it can gate anything."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["instruction"],
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "One-sentence plain-English behavioral or visual check.",
                },
                "out_path": {
                    "type": "string",
                    "description": "Optional path to save the draft spec JSON.",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional provider (anthropic, openai, gemini, openrouter, ollama, vllm, meta, ...).",
                },
            },
        },
    },
    {
        "name": "expectrail_verify_build",
        "description": (
            "Run Expectrail's loop once (agents.loop --runs 1): triage, fixer, then the verifier's replay "
            "and plain-code checks, ending in a morning report. offline (the default) uses recorded "
            "fixtures and costs nothing; live calls the configured models."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_dir": {
                    "type": "string",
                    "description": "Output directory for run artifacts (default: runs/mcp-verify).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["offline", "live", "auto"],
                    "description": "Execution mode (default: offline).",
                },
            },
        },
    },
    {
        "name": "expectrail_trust_check",
        "description": (
            "Run the Linux Bubblewrap (bwrap) sandbox canary probe (`python3 -m agents.trust`) "
            "to verify that the coding agent cannot access held-out routes, evaluator rules, or "
            "the Ed25519 release signing key."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_dir": {
                    "type": "string",
                    "description": "Output directory for trust probe report (default: runs/mcp-trust).",
                },
            },
        },
    },
]


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute an MCP tool call and return an MCP-formatted content result."""
    if name == "expectrail_draft_spec":
        from expectrail.spec_writer import draft, provider_transport

        instruction = arguments["instruction"]
        transport, cfg = provider_transport(arguments.get("provider"))
        spec, problems = draft(instruction, model=cfg.model, transport=transport)
        if spec is None:
            return {"content": [{"type": "text", "text": "needs review: " + "; ".join(problems)}], "isError": True}
        spec_text = json.dumps(spec, indent=2) + "\n"
        out_path = arguments.get("out_path")
        if out_path:
            p = Path(out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(spec_text, encoding="utf-8")
        return {
            "content": [{"type": "text", "text": spec_text}],
            "isError": False,
        }

    if name == "expectrail_verify_build":
        out_dir = arguments.get("out_dir", "runs/mcp-verify")
        mode = arguments.get("mode", "offline")
        cmd = [sys.executable, "-m", "agents.loop", "--out", out_dir, "--mode", mode, "--runs", "1"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        summary = {
            "returncode": proc.returncode,
            "out_dir": out_dir,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-1000:],
        }
        return {
            "content": [{"type": "text", "text": json.dumps(summary, indent=2)}],
            "isError": proc.returncode != 0,
        }

    if name == "expectrail_trust_check":
        out_dir = arguments.get("out_dir", "runs/mcp-trust")
        cmd = [sys.executable, "-m", "agents.trust", "--out", out_dir]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "returncode": proc.returncode,
                            "stdout": proc.stdout[-2000:],
                            "stderr": proc.stderr[-1000:],
                        },
                        indent=2,
                    ),
                }
            ],
            "isError": proc.returncode != 0,
        }

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def handle_jsonrpc_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Process a single JSON-RPC 2.0 request and return a response dict (or None for notifications)."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            result = handle_tool_call(tool_name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
        else:
            resp = handle_jsonrpc_message(msg) if isinstance(msg, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
