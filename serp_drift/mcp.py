"""A minimal MCP server over stdio (JSON-RPC 2.0, newline-delimited) exposing the workspace to agents. Standard library only."""

import json
import sys
import traceback

from . import __version__
from .server import AppState
from .storage import Store
from .workspace import Workspace

PROTOCOL = "2025-06-18"

TOOLS = [
    {"name": "list_panels", "description": "Every monitored panel with its status, change score, market, and capture count.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "panel", "description": "One panel in depth: status and reasons, baseline and latest intent, the latest ranked results with rule evidence, your page's position, and the AI Overview summary.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "description": "Panel id from list_panels."}}, "required": ["id"], "additionalProperties": False}},
    {"name": "history", "description": "A panel's capture timeline (score, intent, page position, AI Overview status per capture) and the change log between captures, newest first.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30}}, "required": ["id"], "additionalProperties": False}},
    {"name": "compare", "description": "Compare two captures or periods of one panel with the five change components. Each side is {preset} (baseline, latest, last_7_days, previous_7_days, last_30_days, first_week), {capture: iso timestamp}, or {from, to} dates.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "left": {"type": "object"}, "right": {"type": "object"}}, "required": ["id"], "additionalProperties": False}},
    {"name": "citations", "description": "AI Overview citation history for a panel: cited hosts per capture, how often your page or host was cited, and host frequency.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False}},
    {"name": "insights", "description": "Cross-panel statistics: AI Overview and feature prevalence, turnover, intent stability, most cited hosts, and splits by language, device, and engine.",
     "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 3650}}, "additionalProperties": False}},
    {"name": "search_host", "description": "Every capture in which a host appeared in the top ten, across panels.",
     "inputSchema": {"type": "object", "properties": {"host": {"type": "string", "description": "Hostname without www, e.g. example.com"}}, "required": ["host"], "additionalProperties": False}},
    {"name": "collect_now", "description": "Run a collection for the panels that are due (or the given ids, forced). Spends SearchApi credits and blocks until done.",
     "inputSchema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}, "force": {"type": "boolean", "default": False}}, "additionalProperties": False}},
]


class McpServer:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.state = AppState(workspace)

    # --- tools ----------------------------------------------------------------------------------------------------------
    def call(self, name: str, arguments: dict) -> dict:
        if name == "list_panels":
            report = self.state.report()
            return {"analysis_version": report["analysis_version"], "panels": [
                {"id": query["id"], "query": query["query"], "search": query["search"], "status": query["status"], "score": query["score"],
                 "dimensions": query.get("dimensions"), "decision": query.get("decision"), "evidence": query.get("evidence"), "reviews": query.get("reviews"),
                 "captures": query["snapshot_count"], "page_position": query.get("page_position"), "reasons": query["reasons"]} for query in report["queries"]]}
        if name == "panel":
            panel = self.state.panel(str(arguments["id"]))
            analysis = panel["analysis"]
            latest = analysis["latest"] or {}
            return {"dimensions": analysis.get("dimensions"), "decision": analysis.get("decision"), "evidence": analysis.get("evidence"), "reviews": analysis.get("reviews"), "observations": panel.get("observations"),
                    "target": panel["target"], "status": analysis["status"], "score": analysis["score"], "reasons": analysis["reasons"],
                    "baseline_intent": analysis["baseline_intent"], "latest_intent": latest.get("dominant_intent"), "classified_coverage": latest.get("classified_coverage"),
                    "captured_at": latest.get("captured_at"), "features": latest.get("features"), "ai_overview_status": latest.get("ai_overview_status"),
                    "ai_overview": latest.get("ai_overview"), "page_position": analysis.get("page_position"), "comparison": analysis.get("comparison"),
                    "results": [{key: result[key] for key in ("position", "url", "title", "intent", "type", "evidence")} for result in latest.get("results", [])],
                    "stability": panel["stability"], "captures": len(panel["captures"])}
        if name == "history":
            panel = self.state.panel(str(arguments["id"]))
            limit = int(arguments.get("limit", 30))
            return {"timeline": panel["timeline"][-limit:], "changes": panel["changes"][:limit], "captures": len(panel["captures"])}
        if name == "compare":
            return self.state.compare(str(arguments["id"]), arguments.get("left") or {"preset": "baseline"}, arguments.get("right") or {"preset": "latest"})
        if name == "citations":
            return self.state.panel(str(arguments["id"]))["citations"]
        if name == "insights":
            data = self.state.insights(int(arguments["days"]) if arguments.get("days") else None)
            data["panel_metrics"] = data["panel_metrics"][:20]
            return data
        if name == "search_host":
            host = str(arguments["host"]).lower().removeprefix("www.")
            with Store(self.workspace.database) as store:
                rows = store.host_appearances(host)
            return {"host": host, "appearances": rows[:500], "total": len(rows)}
        if name == "collect_now":
            ids = arguments.get("ids")
            return self.state.run("mcp", force=bool(arguments.get("force")), only=set(ids) if ids else None)
        raise KeyError(name)

    # --- JSON-RPC ---------------------------------------------------------------------------------------------------------
    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        identifier = message.get("id")
        params = message.get("params") or {}
        if method == "notifications/initialized" or (isinstance(method, str) and method.startswith("notifications/")):
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "serp-drift", "version": __version__},
                          "instructions": f"Workspace {self.workspace.root}. Intent labels are lexical estimates; read reasons and evidence before drawing conclusions. collect_now spends SearchApi credits."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name = params.get("name")
                if name not in {tool["name"] for tool in TOOLS}:
                    return self.error(identifier, -32602, f"Unknown tool {name!r}.")
                try:
                    payload = self.call(name, params.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}], "isError": False}
                except KeyError as error:
                    result = {"content": [{"type": "text", "text": f"Unknown panel or host: {error.args[0]}"}], "isError": True}
                except (ValueError, OSError) as error:
                    result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
            else:
                return self.error(identifier, -32601, f"Method not found: {method}")
        except Exception as error:
            return self.error(identifier, -32603, f"{type(error).__name__}: {error}")
        return {"jsonrpc": "2.0", "id": identifier, "result": result}

    @staticmethod
    def error(identifier, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        print(f"serp-drift mcp {__version__} · workspace {self.workspace.root}", file=sys.stderr, flush=True)
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                stdout.write(json.dumps(self.error(None, -32700, "Parse error")) + "\n")
                stdout.flush()
                continue
            messages = message if isinstance(message, list) else [message]
            for item in messages:
                try:
                    response = self.handle(item) if isinstance(item, dict) else self.error(None, -32600, "Invalid request")
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    response = self.error(item.get("id") if isinstance(item, dict) else None, -32603, "Internal error")
                if response is not None:
                    stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    stdout.flush()
