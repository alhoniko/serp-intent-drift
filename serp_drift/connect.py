"""Connect an agent: the exact stdio command for one workspace, per-client configuration, and a self-test that runs the handshake."""

import json
import os
import shlex
import shutil
import subprocess
import sys

from .mcp import PROTOCOL, TOOLS
from .schedule import environment_for
from .workspace import Workspace

PROMPTS = [
    "Which panels changed status this week, and why?",
    "Compare the last 7 days with the previous 7 for the panel 'topical authority'.",
    "Which hosts does Google cite most in AI Overviews across my panels?",
    "When did my site last appear in the top ten for 'serp analysis python'?",
    "List every panel where the ranking URL changed since the baseline.",
]


def server_command(workspace: Workspace) -> tuple[str, list[str], dict[str, str]]:
    """The installed console script when present, else this interpreter with -m (plus PYTHONPATH for a checkout)."""
    executable = shutil.which("serp-drift")
    if executable:
        command, args = executable, ["--dir", str(workspace.root), "mcp"]
    else:
        command, args = sys.executable, ["-m", "serp_drift", "--dir", str(workspace.root), "mcp"]
    env = {}
    pythonpath = environment_for().get("PYTHONPATH")
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    return command, args, env


def describe(workspace: Workspace) -> dict:
    """Everything the Connect agent page shows: one entry rendered for each client's config format."""
    command, args, env = server_command(workspace)
    entry = {"command": command, "args": args, **({"env": env} if env else {})}
    mcp_json = json.dumps({"mcpServers": {"serp-drift": entry}}, indent=2)
    env_flags = "".join(f" -e {key}={shlex.quote(value)}" for key, value in env.items())
    claude_code = f"claude mcp add serp-drift{env_flags} -- {shlex.join([command, *args])}"
    codex = f"[mcp_servers.serp-drift]\ncommand = {json.dumps(command)}\nargs = {json.dumps(args)}\n"
    if env:
        codex += "\n[mcp_servers.serp-drift.env]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in env.items())
    vscode = json.dumps({"servers": {"serp-drift": {"type": "stdio", **entry}}}, indent=2)
    clients = [
        {"id": "claude-code", "label": "Claude Code", "kind": "shell", "text": claude_code,
         "where": "Run it in a terminal inside the project you work in; add --scope user before -- to make it available everywhere. `claude mcp list` shows it as connected."},
        {"id": "claude-desktop", "label": "Claude Desktop", "kind": "json", "text": mcp_json,
         "where": "Merge into ~/Library/Application Support/Claude/claude_desktop_config.json (macOS) or %APPDATA%\\Claude\\claude_desktop_config.json (Windows), then restart Claude Desktop. The server appears under the tools menu."},
        {"id": "cursor", "label": "Cursor", "kind": "json", "text": mcp_json,
         "where": "~/.cursor/mcp.json for every project, or .cursor/mcp.json inside one. Cursor Settings → MCP shows the server and its tools."},
        {"id": "codex", "label": "Codex CLI", "kind": "toml", "text": codex,
         "where": "Append to ~/.codex/config.toml. Codex lists the server's tools at the start of a session."},
        {"id": "vscode", "label": "VS Code", "kind": "json", "text": vscode,
         "where": ".vscode/mcp.json in the workspace, or the user-level mcp.json through the command MCP: Add Server. Copilot agent mode picks it up."},
        {"id": "other", "label": "Other", "kind": "json", "text": mcp_json,
         "where": "Any client that launches stdio servers takes the same command and arguments. Windsurf: ~/.codeium/windsurf/mcp_config.json. Gemini CLI: ~/.gemini/settings.json."},
    ]
    return {"command": command, "args": args, "env": env, "shell": shlex.join([command, *args]), "protocol": PROTOCOL, "workspace": str(workspace.root),
            "clients": clients, "tools": [{"name": tool["name"], "description": tool["description"]} for tool in TOOLS], "prompts": PROMPTS}


def self_test(workspace: Workspace, timeout: float = 20.0) -> dict:
    """Launch the server the way a client would and run initialize + tools/list over stdio."""
    command, args, env = server_command(workspace)
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "serp-drift-app", "version": "self-test"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    shell = shlex.join([command, *args])
    try:
        completed = subprocess.run([command, *args], input="".join(json.dumps(message) + "\n" for message in messages), capture_output=True, text=True,
                                   timeout=timeout, env={**os.environ, **env}, cwd=str(workspace.root))
    except FileNotFoundError:
        return {"ok": False, "command": shell, "error": f"Command not found: {command}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": shell, "error": f"No answer within {timeout:.0f} seconds."}
    replies = {}
    for line in completed.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") is not None:
            replies[message["id"]] = message
    stderr = completed.stderr.strip().splitlines()
    initialized = (replies.get(1) or {}).get("result") or {}
    tools = ((replies.get(2) or {}).get("result") or {}).get("tools") or []
    if not initialized or not tools:
        error = (replies.get(1) or replies.get(2) or {}).get("error", {}).get("message") or (stderr[-1] if stderr else f"Exit code {completed.returncode}, no JSON-RPC replies.")
        return {"ok": False, "command": shell, "error": error, "exit_code": completed.returncode}
    return {"ok": True, "command": shell, "server": initialized.get("serverInfo"), "protocol": initialized.get("protocolVersion"), "tools": [tool["name"] for tool in tools], "exit_code": completed.returncode}
