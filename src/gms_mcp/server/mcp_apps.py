from __future__ import annotations

import json

from mcp.server.apps import Apps, ResourceCsp
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .project import ProjectAccessError, ProjectAccessPolicy
from .results import mcp_tool_result, public_mcp_result


_DASHBOARD_URI = "ui://gms-mcp/project-dashboard.html"

_DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GameMaker Project Dashboard</title>
  <style>
    :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; padding: 16px; background: var(--color-background-primary, Canvas); color: var(--color-text-primary, CanvasText); }
    header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
    h1 { margin: 0; font-size: 1.05rem; }
    #status { color: var(--color-text-secondary, GrayText); font-size: .8rem; }
    #summary { margin: 12px 0; font-size: .92rem; }
    #counts { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
    .card { border: 1px solid color-mix(in srgb, CanvasText 18%, transparent); border-radius: 10px; padding: 10px; background: color-mix(in srgb, Canvas 94%, CanvasText 6%); }
    .value { display: block; font-size: 1.25rem; font-weight: 650; }
    .label { display: block; margin-top: 2px; color: var(--color-text-secondary, GrayText); font-size: .75rem; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <header><h1 id="title">GameMaker Project</h1><span id="status">Connecting…</span></header>
  <p id="summary">Waiting for project data.</p>
  <section id="counts" aria-live="polite"></section>
  <script>
    (() => {
      const status = document.getElementById("status");
      const title = document.getElementById("title");
      const summary = document.getElementById("summary");
      const counts = document.getElementById("counts");
      const initializeId = "gms-dashboard-initialize";

      function send(message) { window.parent.postMessage(message, "*"); }
      function applyHostContext(context) {
        if (context && context.theme) document.documentElement.style.colorScheme = context.theme;
      }
      function toolPayload(result) {
        if (result && result.structuredContent) return result.structuredContent;
        const text = result && Array.isArray(result.content)
          ? result.content.find((item) => item && item.type === "text")?.text
          : null;
        if (!text) return null;
        try { return JSON.parse(text); } catch (_) { return null; }
      }
      function render(result) {
        const payload = toolPayload(result);
        if (!payload) { status.textContent = "No data"; summary.textContent = "Project data was unavailable."; return; }
        title.textContent = payload.project_name || "GameMaker Project";
        summary.textContent = payload.summary || "Project overview";
        counts.replaceChildren();
        const values = { "Assets": payload.total_resources, "Folders": payload.total_folders, ...payload.counts_by_type };
        Object.entries(values).filter(([, value]) => Number.isFinite(value)).sort(([a], [b]) => a.localeCompare(b)).forEach(([label, value]) => {
          const card = document.createElement("div");
          card.className = "card";
          const number = document.createElement("span");
          number.className = "value";
          number.textContent = String(value);
          const name = document.createElement("span");
          name.className = "label";
          name.textContent = label;
          card.append(number, name);
          counts.append(card);
        });
        status.textContent = payload.ok === false ? "Unavailable" : "Current";
      }

      window.addEventListener("message", (event) => {
        if (event.source !== window.parent || !event.data || event.data.jsonrpc !== "2.0") return;
        const message = event.data;
        if (message.id === initializeId && message.result) {
          applyHostContext(message.result.hostContext);
          send({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} });
          status.textContent = "Waiting for data…";
        } else if (message.method === "ui/notifications/tool-result") {
          render(message.params);
        } else if (message.method === "ui/notifications/host-context-changed") {
          applyHostContext(message.params);
        } else if (message.method === "ui/resource-teardown" && message.id !== undefined) {
          send({ jsonrpc: "2.0", id: message.id, result: {} });
        }
      });

      send({
        jsonrpc: "2.0",
        id: initializeId,
        method: "ui/initialize",
        params: {
          appInfo: { name: "gms-mcp-project-dashboard", version: "1.0.0" },
          appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
          protocolVersion: "2026-01-26"
        }
      });
    })();
  </script>
</body>
</html>"""


def create_project_dashboard_app(
    project_access_policy: ProjectAccessPolicy,
    expose_host_diagnostics: bool,
) -> Apps:
    """Create the read-only MCP Apps project dashboard extension."""
    apps = Apps()

    @apps.tool(
        resource_uri=_DASHBOARD_URI,
        visibility=["model", "app"],
        name="gm_project_dashboard",
        title="GameMaker Project Dashboard",
        description="Show a read-only dashboard summarizing the active GameMaker project.",
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def gm_project_dashboard() -> CallToolResult:
        try:
            project_directory = project_access_policy.authorize(".")
            from gms_helpers.introspection import get_project_stats

            stats = get_project_stats(project_directory)
            project_files = sorted(project_directory.glob("*.yyp"))
            project_name = project_files[0].stem if project_files else "GameMaker Project"
            payload = public_mcp_result(
                {
                    "ok": "error" not in stats,
                    "project_name": project_name,
                    **stats,
                },
                project_root=project_directory,
                expose_host_diagnostics=expose_host_diagnostics,
            )
        except ProjectAccessError:
            return mcp_tool_result(
                {
                    "ok": False,
                    "tool": "gm_project_dashboard",
                    "error": "Project access denied.",
                    "error_type": "ProjectAccessError",
                },
                project_root=project_access_policy.project_root,
                expose_host_diagnostics=expose_host_diagnostics,
            )
        except Exception:
            return mcp_tool_result(
                {
                    "ok": False,
                    "tool": "gm_project_dashboard",
                    "error": "Internal tool error; host details were withheld.",
                    "error_type": "InternalToolError",
                },
                project_root=project_access_policy.project_root,
                expose_host_diagnostics=False,
            )
        total = int(payload.get("total_resources", 0)) if isinstance(payload, dict) else 0
        summary = (
            f"{project_name} contains {total} project assets."
            if isinstance(payload, dict) and payload.get("ok")
            else f"Project statistics are unavailable for {project_name}."
        )
        if isinstance(payload, dict):
            payload["summary"] = summary
        return CallToolResult(
            content=[TextContent(type="text", text=summary + "\n" + json.dumps(payload, sort_keys=True))],
            structured_content=payload,
            is_error=bool(isinstance(payload, dict) and payload.get("ok") is False),
        )

    apps.add_html_resource(
        _DASHBOARD_URI,
        _DASHBOARD_HTML,
        name="gm_project_dashboard_ui",
        title="GameMaker Project Dashboard",
        description="Self-contained read-only GameMaker project summary dashboard.",
        csp=ResourceCsp(),
        prefers_border=True,
    )
    return apps
