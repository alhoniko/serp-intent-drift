# Ask your history from an agent (MCP)

`serp-drift mcp` serves the workspace over stdio using the Model Context Protocol, so an agent can read panels, history, comparisons, citations, and insights, and trigger a collection when you allow it. It uses the same code paths as the app and never exposes the API key.

**In the app:** the sidebar's **Connect agent** page shows the exact command for the current project, ready-made configuration for Claude Code, Claude Desktop, Cursor, Codex CLI, VS Code, and any other client (with `PYTHONPATH` filled in when the app runs from a checkout), a **Test the connection** button that launches the server the way a client would and runs the handshake, the tool list, and example prompts. `GET /api/p/<project>/mcp` returns the same data; `POST /api/p/<project>/mcp/check` runs the test.

## Claude Code

```sh
claude mcp add serp-drift -- serp-drift --dir ~/serp-drift mcp
```

## Claude Desktop, Cursor, and others

Add a stdio server whose command is `serp-drift` with arguments `--dir /absolute/path/to/workspace mcp`. If the command is not on the app's PATH, use the absolute path to `serp-drift` or `python3 -m serp_drift`.

```json
{"mcpServers": {"serp-drift": {"command": "serp-drift", "args": ["--dir", "/Users/you/serp-drift", "mcp"]}}}
```

## Codex CLI

Append to `~/.codex/config.toml`:

```toml
[mcp_servers.serp-drift]
command = "serp-drift"
args = ["--dir", "/Users/you/serp-drift", "mcp"]
```

## VS Code

`.vscode/mcp.json` in the workspace, or the user-level file through *MCP: Add Server*:

```json
{"servers": {"serp-drift": {"type": "stdio", "command": "serp-drift", "args": ["--dir", "/Users/you/serp-drift", "mcp"]}}}
```

## Tools

| Tool | What it returns |
| --- | --- |
| `list_panels` | every panel with status, score, market, captures, and reasons |
| `panel` | one panel: status, baseline and latest intent, latest results with rule evidence, page position, AI Overview summary |
| `history` | capture timeline and change log for a panel |
| `compare` | the five change components between two captures or periods |
| `citations` | AI Overview citation history for a panel |
| `insights` | cross-panel statistics, optionally for the last N days |
| `search_host` | every capture in which a host appeared in the top ten |
| `collect_now` | runs a collection; spends credits, so approve it deliberately |

Example prompts: "Which panels changed status this week and why?", "Compare the last 7 days with the previous 7 for topical authority", "Which hosts does Google cite most in AI Overviews across my panels?", "When did nikoalho.fi last appear in the top ten for serp analysis python?"
