from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

REPO_URL = "https://github.com/Ampersand-Game-Studios/gms-mcp"
STAR_CTA_DISABLE_ENV = "GMS_MCP_DISABLE_STAR_ASK"
HELP_EPILOG = (
    f"Project: {REPO_URL} | "
    "If gms-mcp is useful, you can star the repo on GitHub."
)
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _default_state_path() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "gms-mcp" / "ux.json"
        return Path.home() / "AppData" / "Roaming" / "gms-mcp" / "ux.json"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "gms-mcp" / "ux.json"

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "gms-mcp" / "ux.json"
    return Path.home() / ".config" / "gms-mcp" / "ux.json"


def _load_state(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        # CTA state should never block the command.
        return


def _env_truthy(name: str, env: dict[str, str]) -> bool:
    return env.get(name, "").strip().lower() in _TRUE_VALUES


def _is_ci(env: dict[str, str]) -> bool:
    if env.get("BUILD_BUILDID", "").strip():
        return True
    return any(_env_truthy(name, env) for name in ("CI", "GITHUB_ACTIONS"))


def _is_interactive(stream: TextIO) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)())


def maybe_print_star_cta(
    *,
    stream: TextIO | None = None,
    env: dict[str, str] | None = None,
    no_star_ask: bool = False,
    state_path: Path | None = None,
) -> bool:
    output = stream if stream is not None else sys.stdout
    runtime_env = dict(os.environ if env is None else env)
    path = state_path if state_path is not None else _default_state_path()

    if no_star_ask or _env_truthy(STAR_CTA_DISABLE_ENV, runtime_env) or _is_ci(runtime_env):
        return False
    if not _is_interactive(output):
        return False

    state = _load_state(path)
    star_state = state.get("star_cta")
    if not isinstance(star_state, dict):
        star_state = {}
        state["star_cta"] = star_state

    if star_state.get("shown") or star_state.get("disabled") or star_state.get("dismissed"):
        return False

    print(
        "[INFO] If this setup helped, a GitHub star helps other GameMaker users find gms-mcp.",
        file=output,
    )
    print(f"       {REPO_URL}", file=output)
    print(f"       Hide this note in future runs: {STAR_CTA_DISABLE_ENV}=1", file=output)

    star_state["shown"] = True
    star_state["last_shown_at"] = datetime.now(timezone.utc).isoformat()
    _write_state(path, state)
    return True
