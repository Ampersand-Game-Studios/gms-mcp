from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".cursor",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
}

_FORWARDED_ENV_VARS = [
    "GMS_MCP_GMS_PATH",
    "GMS_MCP_DEFAULT_TIMEOUT_SECONDS",
    "GMS_MCP_ENABLE_DIRECT",
]
_SAFE_PROFILE_TIMEOUT_SECONDS = 600
_REDACTED_VALUE = "***REDACTED***"
_SAFE_ENV_OUTPUT_KEYS = {
    "GM_PROJECT_ROOT",
    "GMS_MCP_DEFAULT_TIMEOUT_SECONDS",
    "GMS_MCP_ENABLE_DIRECT",
    "GMS_MCP_GMS_PATH",
    "GMS_MCP_REQUIRE_DRY_RUN",
    "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST",
    "PYTHONUNBUFFERED",
}


def _as_posix_path(path: Path) -> str:
    return path.as_posix()


def _normalize_config_key(key: str) -> str:
    return key.strip().replace("-", "_")


def _looks_secret_key(key: str) -> bool:
    normalized = _normalize_config_key(key)
    if normalized.upper() in _SAFE_ENV_OUTPUT_KEYS:
        return False

    lowered = normalized.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if not tokens:
        return False

    if any(
        token in {"authorization", "bearer", "cookie", "password", "passwd", "secret", "session", "token"}
        for token in tokens
    ):
        return True
    if "api" in tokens and "key" in tokens:
        return True
    if "access" in tokens and "key" in tokens:
        return True
    if "client" in tokens and ("key" in tokens or "secret" in tokens):
        return True
    if "consumer" in tokens and ("key" in tokens or "secret" in tokens):
        return True
    if "private" in tokens and "key" in tokens:
        return True
    if lowered.endswith("_key") and lowered.upper() not in _SAFE_ENV_OUTPUT_KEYS:
        return True
    return False


def _looks_secret_flag(token: object) -> bool:
    if not isinstance(token, str):
        return False
    stripped = token.strip()
    if not stripped.startswith("-"):
        return False
    flag = stripped.lstrip("-").split("=", 1)[0]
    return _looks_secret_key(flag)


def _redact_args_list(values: list[object]) -> list[object]:
    redacted: list[object] = []
    redact_next = False

    for value in values:
        if redact_next:
            redacted.append(_REDACTED_VALUE)
            redact_next = False
            continue

        if not isinstance(value, str):
            redacted.append(_redact_config_value(value))
            continue

        if not value.startswith("-"):
            redacted.append(value)
            continue

        flag, sep, remainder = value.partition("=")
        if _looks_secret_flag(flag):
            if sep:
                redacted.append(f"{flag}={_REDACTED_VALUE}")
            else:
                redacted.append(value)
                redact_next = True
            continue

        redacted.append(value)

    return redacted


def _redact_config_value(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _looks_secret_key(key_text):
                redacted[key] = _REDACTED_VALUE
                continue
            if key_text == "args" and isinstance(item, list):
                redacted[key] = _redact_args_list(item)
                continue
            redacted[key] = _redact_config_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_config_value(item) for item in value]
    return value


def _find_yyp_dirs(workspace_root: Path, max_results: int = 5) -> list[Path]:
    results: list[Path] = []
    ignored = {d.lower() for d in _DEFAULT_IGNORED_DIRS}

    for root, dirs, files in os.walk(workspace_root):
        dirs[:] = [d for d in dirs if d.lower() not in ignored]
        if any(f.lower().endswith(".yyp") for f in files):
            results.append(Path(root))
            if len(results) >= max_results:
                break

    return results


def _detect_gm_project_roots(workspace_root: Path, max_results: int = 50) -> list[Path]:
    candidates: list[Path] = []

    if sorted(workspace_root.glob("*.yyp")):
        candidates.append(workspace_root)

    gm = workspace_root / "gamemaker"
    if gm.exists() and gm.is_dir() and sorted(gm.glob("*.yyp")):
        candidates.append(gm)

    candidates.extend(_find_yyp_dirs(workspace_root, max_results=max_results))

    # Unique + stable order (by relative path)
    uniq: dict[str, Path] = {}
    for p in candidates:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        uniq[key] = p

    def _sort_key(p: Path) -> str:
        try:
            return _as_posix_path(p.relative_to(workspace_root))
        except Exception:
            return _as_posix_path(p)

    return sorted(uniq.values(), key=_sort_key)


def _select_gm_project_root(
    *,
    workspace_root: Path,
    requested_root: str | None,
    non_interactive: bool,
) -> tuple[Path | None, list[Path]]:
    """
    Returns (selected_root, all_candidates).
    """
    if requested_root:
        p = Path(requested_root).expanduser()
        if not p.is_absolute():
            p = (workspace_root / p).resolve()
        if p.is_file():
            p = p.parent
        return p, []

    candidates = _detect_gm_project_roots(workspace_root)
    if len(candidates) == 0:
        return None, candidates
    if len(candidates) == 1:
        return candidates[0], candidates

    # Multiple projects found: prompt if interactive, otherwise fall back safely.
    if non_interactive or not (sys.stdin and sys.stdin.isatty()):
        return None, candidates

    print("[WARN] Multiple GameMaker projects (.yyp) detected in this workspace:")
    for i, p in enumerate(candidates, start=1):
        try:
            rel = p.relative_to(workspace_root)
            label = f"./{_as_posix_path(rel)}"
        except Exception:
            label = str(p)
        print(f"  {i}. {label}")
    print("Select which project root to target, or press Enter to skip (defaults to ${workspaceFolder}).")

    while True:
        choice = input("Project number (1..N) or Enter: ").strip()
        if choice == "":
            return None, candidates
        try:
            idx = int(choice)
        except ValueError:
            print("[ERROR] Enter a number or press Enter.")
            continue
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1], candidates
        print("[ERROR] Out of range.")


def _workspace_folder_var(client: str) -> str:
    """Return the workspace/project directory variable for a given client."""
    if client in ("claude-code", "claude-code-global"):
        return "${CLAUDE_PROJECT_DIR}"
    return "${workspaceFolder}"


def _write_json(path: Path, data: dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _relpath_posix_or_none(target: Path | None, base: Path) -> str | None:
    if target is None:
        return None
    try:
        rel = target.relative_to(base)
    except ValueError:
        return None
    return _as_posix_path(rel)


def _make_server_config(
    *,
    client: str,
    server_name: str,
    command: str,
    args: list[str],
    gm_project_root_rel_posix: str | None,
    safe_profile: bool = False,
) -> dict:
    workspace_var = _workspace_folder_var(client)
    env: dict[str, str] = {}

    if gm_project_root_rel_posix:
        env["GM_PROJECT_ROOT"] = f"{workspace_var}/{gm_project_root_rel_posix}".replace("//", "/")
    else:
        env["GM_PROJECT_ROOT"] = workspace_var

    # Polish: Auto-detect and write relevant environment variables from current process
    # This helps when running gms-mcp-init from a shell where these are already set.
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
                "cwd": workspace_var,
                "env": env,
            }
        }
    }


def _default_antigravity_config_path() -> Path:
    return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


def _resolve_antigravity_config_path(config_path: str | None) -> Path:
    if not config_path:
        return _default_antigravity_config_path()
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _apply_safe_profile_env(env: dict[str, str], *, enabled: bool) -> None:
    if not enabled:
        return
    env["GMS_MCP_ENABLE_DIRECT"] = "0"
    env["GMS_MCP_REQUIRE_DRY_RUN"] = "1"
    timeout = env.get("GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "").strip()
    if timeout:
        try:
            parsed_timeout = int(timeout)
            if parsed_timeout <= 0 or parsed_timeout > _SAFE_PROFILE_TIMEOUT_SECONDS:
                env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)
        except ValueError:
            env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)
    else:
        env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = str(_SAFE_PROFILE_TIMEOUT_SECONDS)


@dataclass
class ReadinessResult:
    ready: bool
    problems: list[str]
    not_applicable: bool = False


@dataclass
class ConfigState:
    client: str
    scope: str
    server_name: str
    path: str
    exists: bool
    entry: dict | None
    readiness: ReadinessResult

    def as_dict(self) -> dict:
        redacted = _redact_config_value(
            {
                "ok": True,
                "client": self.client,
                "scope": self.scope,
                "server_name": self.server_name,
                "config": {
                    "path": self.path,
                    "exists": self.exists,
                    "entry": self.entry,
                },
                "active": {
                    "scope": self.scope,
                    "path": self.path,
                    "entry": self.entry,
                },
                "ready": self.readiness.ready,
                "problems": self.readiness.problems,
                "not_applicable": self.readiness.not_applicable,
            }
        )
        assert isinstance(redacted, dict)
        return redacted


def _validate_common_entry(
    entry: object,
    *,
    require_project_root: bool = True,
    env_required: bool = True,
) -> ReadinessResult:
    if not isinstance(entry, dict):
        return ReadinessResult(ready=False, problems=["Active server entry is missing or not an object."])

    problems: list[str] = []

    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        problems.append("`command` must be a non-empty string.")

    args = entry.get("args")
    if not isinstance(args, list):
        problems.append("`args` must be a list.")

    env = entry.get("env")
    if env_required and not isinstance(env, dict):
        problems.append("`env` must be an object.")
    elif isinstance(env, dict):
        if require_project_root:
            gm_project_root = env.get("GM_PROJECT_ROOT")
            if not isinstance(gm_project_root, str) or not gm_project_root.strip():
                problems.append("`env.GM_PROJECT_ROOT` must be a non-empty string.")
        if env.get("PYTHONUNBUFFERED") != "1":
            problems.append('`env.PYTHONUNBUFFERED` should be "1" for unbuffered logs.')

    return ReadinessResult(ready=len(problems) == 0, problems=problems)


def _resolve_json_entry_root(parsed: dict, *, server_name: str, allow_plain_top_level: bool) -> dict | None:
    mcp_servers = parsed.get("mcpServers")
    if isinstance(mcp_servers, dict):
        entry = mcp_servers.get(server_name)
        return entry if isinstance(entry, dict) else None

    if allow_plain_top_level:
        plain_entry = parsed.get(server_name)
        if isinstance(plain_entry, dict):
            return plain_entry

    return None


def _read_json_server_entry(
    *,
    config_path: Path,
    server_name: str,
    allow_plain_top_level: bool,
) -> tuple[dict | None, bool]:
    if not config_path.exists():
        return None, False

    text = config_path.read_text(encoding="utf-8")
    parsed = _parse_json_object_or_raise(text=text, source_label=str(config_path))
    entry = _resolve_json_entry_root(parsed, server_name=server_name, allow_plain_top_level=allow_plain_top_level)
    return entry, True


def _collect_standard_check_state(
    *,
    client: str,
    scope: str,
    config_path: Path,
    server_name: str,
    allow_plain_top_level: bool = False,
    require_project_root: bool = True,
    env_required: bool = True,
    not_applicable_reason: str | None = None,
) -> ConfigState:
    if not_applicable_reason is not None:
        readiness = ReadinessResult(ready=False, problems=[not_applicable_reason], not_applicable=True)
        return ConfigState(
            client=client,
            scope=scope,
            server_name=server_name,
            path=str(config_path),
            exists=False,
            entry=None,
            readiness=readiness,
        )

    entry, exists = _read_json_server_entry(
        config_path=config_path,
        server_name=server_name,
        allow_plain_top_level=allow_plain_top_level,
    )
    readiness = _validate_common_entry(
        entry,
        require_project_root=require_project_root,
        env_required=env_required,
    )
    return ConfigState(
        client=client,
        scope=scope,
        server_name=server_name,
        path=str(config_path),
        exists=exists,
        entry=entry,
        readiness=readiness,
    )


def _print_standard_check(state: ConfigState) -> int:
    print(f"[INFO] {state.client} {state.scope} config: {state.path} ({'exists' if state.exists else 'missing'})")
    if state.entry is None:
        print(f"[INFO] Active server entry '{state.server_name}': not found")
    else:
        print(f"[INFO] Active server entry '{state.server_name}' source: {state.path}")
        print("[INFO] Active server entry payload:")
        print(json.dumps(_redact_config_value(state.entry), indent=2, sort_keys=True))
    print(f"[INFO] Ready for {state.client}: {'yes' if state.readiness.ready else 'no'}")
    for problem in state.readiness.problems:
        level = "WARN" if not state.readiness.not_applicable else "INFO"
        print(f"[{level}] {problem}")
    return 0


def _print_standard_check_json(state: ConfigState) -> int:
    print(json.dumps(state.as_dict(), indent=2, sort_keys=True))
    return 0


def _print_standard_app_setup_summary(state: ConfigState) -> int:
    print(f"[INFO] {state.client} app readiness summary:")
    print(f"[INFO] Scope: {state.scope}")
    print(f"[INFO] Config path: {state.path}")
    print(f"[INFO] Ready for {state.client}: {'yes' if state.readiness.ready else 'no'}")
    for problem in state.readiness.problems:
        level = "WARN" if not state.readiness.not_applicable else "INFO"
        print(f"[{level}] {problem}")
    return 0


def _make_antigravity_server_config(
    *,
    server_name: str,
    command: str,
    args: list[str],
    workspace_root: Path,
    gm_project_root: Path | None,
    safe_profile: bool,
) -> dict:
    env: dict[str, str] = {
        "GM_PROJECT_ROOT": str(gm_project_root if gm_project_root is not None else workspace_root),
        "PYTHONUNBUFFERED": "1",
    }
    for env_var in _FORWARDED_ENV_VARS:
        val = os.environ.get(env_var)
        if val:
            env[env_var] = val
    _apply_safe_profile_env(env, enabled=safe_profile)

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }


def _resolve_launcher(*, mode: str, python_command: str) -> tuple[str, list[str]]:
    """
    Return (command, args_prefix) for launching the server.
    """
    if mode == "command":
        return "gms-mcp", []
    if mode == "python-module":
        resolved_python = _resolve_python_command(python_command)
        return resolved_python, ["-m", "gms_mcp.bootstrap_server"]
    raise ValueError(f"Unknown mode: {mode}")


def _default_python_command() -> str:
    """
    Return a practical Python command default per host OS.

    On Unix-like systems `python3` is often available while `python` may not be.
    """
    if os.name == "nt":
        return "python"
    if shutil.which("python3"):
        return "python3"
    return "python"


def _resolve_python_command(python_command: str) -> str:
    """
    Resolve a usable Python command for --mode=python-module.

    Keeps caller-provided values when available and falls back to common
    interpreter commands if needed.
    """
    requested = (python_command or "").strip() or _default_python_command()
    if shutil.which(requested):
        return requested

    fallback_candidates: list[str] = []
    if sys.executable:
        fallback_candidates.append(sys.executable)
    fallback_candidates.extend(["python3", "python"])

    for candidate in fallback_candidates:
        if candidate and shutil.which(candidate):
            return candidate

    return requested



def _parse_json_object_or_raise(*, text: str, source_label: str) -> dict:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError(f"Malformed JSON in {source_label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Malformed JSON in {source_label}: root must be an object.")
    return parsed

