"""Partial commits for a working tree shared by several agents.

``git add project.yyp`` stages every registration in the working tree, including assets
that belong to someone else's unfinished work. ``stage_paths`` stages the named paths and
a project file that is the committed version plus only the registrations those paths need.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable

from . import yyp_registry
from .agent_locks import REPOSITORY_LOCK, DirectoryLock
from .exceptions import ValidationError
from .utils import find_yyp


class VcsError(ValidationError):
    """A git operation failed; the message carries git's own explanation."""


def _git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text.encode("utf-8") if input_text is not None else None,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise VcsError(f"git {' '.join(args[:2])} failed: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout.decode("utf-8", "replace")


def stage_paths(
    project_root: str | Path,
    paths: Iterable[str],
    *,
    yyp_entries: Iterable[str] | None = None,
    commit_message: str | None = None,
    lock_timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, check=False)
    if top.returncode != 0:
        raise VcsError("This project is not inside a git repository, so there is nothing to stage.")
    repo = Path(top.stdout.decode("utf-8").strip()).resolve()
    prefix = root.relative_to(repo).as_posix()
    prefix = "" if prefix == "." else prefix
    yyp_name = find_yyp(root).name
    yyp_repo_path = f"{prefix}/{yyp_name}" if prefix else yyp_name

    project_paths: list[str] = []
    repo_paths: list[str] = []
    for raw in paths:
        text = str(raw).replace("\\", "/").strip()
        if not text:
            continue
        if ".." in text.split("/"):
            raise VcsError(f"'{raw}' leaves the repository; paths may not contain '..'.")
        if text.startswith("/"):
            repo_paths.append(text.lstrip("/"))
        else:
            relative = text.strip("/")
            if prefix and (relative == prefix or relative.startswith(prefix + "/")):
                relative = relative[len(prefix) :].strip("/")
            project_paths.append(relative)
            repo_paths.append(f"{prefix}/{relative}" if prefix else relative)
    if not repo_paths:
        raise VcsError("No paths were given. Pass the files or folders that make up your change.")
    whole_yyp = yyp_repo_path in repo_paths

    lock = DirectoryLock(REPOSITORY_LOCK, purpose="gm_vcs_stage")
    lock.acquire(timeout_seconds=lock_timeout_seconds)
    try:
        for path in repo_paths:
            _git(repo, "add", "-A", "--", path)
        staged_entries: list[str] = []
        if not whole_yyp:
            head = subprocess.run(
                ["git", "-C", str(repo), "show", f"HEAD:{yyp_repo_path}"], capture_output=True, check=False
            )
            if head.returncode != 0:
                raise VcsError(
                    f"{yyp_repo_path} is not in HEAD yet, so there is no committed project file to build on. "
                    f"Include '{yyp_name}' in paths to stage the whole file for the first commit."
                )
            # Build on the project file already in the index, so registrations another call staged
            # earlier are kept. An untouched index entry is identical to HEAD.
            indexed = subprocess.run(
                ["git", "-C", str(repo), "show", f":{yyp_repo_path}"], capture_output=True, check=False
            )
            base_text = (indexed if indexed.returncode == 0 else head).stdout.decode("utf-8")
            staged_entries = [str(e) for e in (yyp_entries or []) if str(e).strip()]
            if not staged_entries:
                staged_entries = yyp_registry.derive_yyp_entries(root, base_text, project_paths)
            if staged_entries:
                composed = yyp_registry.compose_yyp(
                    base_text, (root / yyp_name).read_text(encoding="utf-8"), staged_entries
                )
                blob = _git(repo, "hash-object", "-w", "--stdin", input_text=composed).strip()
                _git(repo, "update-index", "--cacheinfo", f"100644,{blob},{yyp_repo_path}")
        staged = [line for line in _git(repo, "diff", "--cached", "--name-status").splitlines() if line.strip()]
        result: dict[str, Any] = {
            "ok": True,
            "staged": staged[:400],
            "staged_count": len(staged),
            "yyp_entries": staged_entries,
            "yyp_mode": "whole file"
            if whole_yyp
            else ("HEAD plus named registrations" if staged_entries else "not staged"),
            "committed": False,
        }
        if commit_message:
            if not staged:
                raise VcsError("Nothing is staged, so there is nothing to commit. Check the paths.")
            staged_names = [line for line in _git(repo, "diff", "--cached", "--name-only").splitlines() if line.strip()]
            unrelated = [
                name
                for name in staged_names
                if name != yyp_repo_path
                and not any(name == path or name.startswith(path.rstrip("/") + "/") for path in repo_paths)
            ]
            if unrelated:
                shown = ", ".join(unrelated[:8]) + (" ..." if len(unrelated) > 8 else "")
                raise VcsError(
                    "The index also holds staged changes outside the given paths, and committing would "
                    f"include them: {shown}. Your paths are staged; nothing was committed. Unstage the "
                    "other changes (git restore --staged <path>), add them to paths, or commit by hand."
                )
            _git(repo, "commit", "-q", "-m", commit_message)
            result["committed"] = True
            result["commit"] = _git(repo, "log", "-1", "--format=%h %s").strip()
        else:
            result["message"] = (
                "Staged. Review with `git diff --cached`, then commit, or call again with commit_message."
            )
        return result
    finally:
        lock.release()
