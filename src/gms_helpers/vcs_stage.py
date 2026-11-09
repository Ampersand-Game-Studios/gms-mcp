"""Partial commits for a working tree shared by several agents.

``git add project.yyp`` stages every registration in the working tree, including assets
that belong to someone else's unfinished work. ``stage_paths`` stages the named paths and
a project file that is the committed version plus only the registrations those paths need.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from gms_mcp.project_detection import safe_git_command
from typing import Any, Iterable

from . import yyp_registry
from .exceptions import ValidationError
from .transactions import project_mutation_lock
from .utils import _read_text_preserving_newlines, find_yyp

# The tool's private per-project state; never part of a commit unless named explicitly.
_PRIVATE_STATE_DIR = ".gms_mcp"


class VcsError(ValidationError):
    """A git operation failed; the message carries git's own explanation."""


def _git_run(repo: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    # Literal pathspecs: a path such as ":(glob)*" or "*.yy" names exactly that file, never a pattern.
    return subprocess.run(
        safe_git_command(repo, "--literal-pathspecs", *args),
        input=input_text.encode("utf-8") if input_text is not None else None,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> str:
    completed = _git_run(repo, *args, input_text=input_text)
    if check and completed.returncode != 0:
        raise VcsError(f"git {' '.join(args[:2])} failed: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout.decode("utf-8", "replace")


def _staged_names(repo: Path) -> list[str]:
    """Staged paths exactly as they are on disk (NUL-delimited, so git never quotes non-ASCII names).

    Rename detection is off: a renamed asset must report its old path too, or its old registration
    would stay in the composed project file.
    """
    return [name for name in _git(repo, "diff", "--cached", "--name-only", "--no-renames", "-z").split("\0") if name]


def _index_blob(repo: Path, path: str) -> str | None:
    completed = _git_run(repo, "rev-parse", "-q", "--verify", f":{path}")
    return completed.stdout.decode("utf-8").strip() if completed.returncode == 0 else None


def _clean_relative(text: str) -> str:
    """Forward slashes without empty or "." segments ("./objects//o_x/" -> "objects/o_x"; "." -> "")."""
    return "/".join(part for part in text.split("/") if part not in ("", "."))


def _on_disk_case(repo: Path, relative: str, known: Iterable[str]) -> str:
    """``relative`` spelled the way the file system (or, for deleted paths, the index) spells it.

    On a case-insensitive volume "./GAME.yyp" and "game.yyp" are one file but different git paths,
    so every path is given the casing it actually has before it is compared or staged.
    """
    if not relative:
        return relative
    parts = relative.split("/")
    current = repo
    resolved: list[str] = []
    for index, part in enumerate(parts):
        try:
            names = os.listdir(current)
        except OSError:
            names = []
        if part in names:
            match = part
        else:
            folded = [name for name in names if name.casefold() == part.casefold()]
            match = folded[0] if len(folded) == 1 else None
        if match is None:
            # Not on disk (a deletion): take the casing git already records for it, if unambiguous.
            wanted = "/".join([*resolved, *parts[index:]]).casefold()
            spellings = {
                name[: len(wanted)]
                for name in known
                if name.casefold() == wanted or name.casefold().startswith(wanted + "/")
            }
            return spellings.pop() if len(spellings) == 1 else "/".join([*resolved, *parts[index:]])
        resolved.append(match)
        current = current / match
    return "/".join(resolved)


def stage_paths(
    project_root: str | Path,
    paths: Iterable[str],
    *,
    yyp_entries: Iterable[str] | None = None,
    commit_message: str | None = None,
    lock_timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    top = subprocess.run(safe_git_command(root, "rev-parse", "--show-toplevel"), capture_output=True, check=False)
    if top.returncode != 0:
        raise VcsError("This project is not inside a git repository, so there is nothing to stage.")
    repo = Path(top.stdout.decode("utf-8").strip()).resolve()
    prefix = root.relative_to(repo).as_posix()
    prefix = "" if prefix == "." else prefix
    yyp_name = find_yyp(root).name
    yyp_repo_path = f"{prefix}/{yyp_name}" if prefix else yyp_name
    raw_paths = [str(raw) for raw in paths if str(raw).replace("\\", "/").strip()]
    if not raw_paths:
        raise VcsError("No paths were given. Pass the files or folders that make up your change.")

    # Staging is a project-file mutation: it must never interleave with a transaction on this
    # project (which could be rewriting the .yyp being read here), nor with another stager.
    with project_mutation_lock(root, "gm_vcs_stage", timeout_seconds=lock_timeout_seconds, repository_lock=True):
        return _stage_locked(repo, root, prefix, yyp_name, yyp_repo_path, raw_paths, yyp_entries, commit_message)


def _stage_locked(
    repo: Path,
    root: Path,
    prefix: str,
    yyp_name: str,
    yyp_repo_path: str,
    raw_paths: list[str],
    yyp_entries: Iterable[str] | None,
    commit_message: str | None,
) -> dict[str, Any]:
    deleted = {
        name
        for name in _git(repo, "diff", "--cached", "--name-only", "--diff-filter=D", "--no-renames", "-z").split("\0")
        if name
    }
    indexed = {name for name in _git(repo, "ls-files", "-z").split("\0") if name}
    known = indexed | deleted

    project_known = [n[len(prefix) + 1 :] for n in known if n.startswith(prefix + "/")] if prefix else list(known)
    project_paths: list[str] = []
    repo_paths: list[str] = []
    for raw in raw_paths:
        text = raw.replace("\\", "/").strip()
        if ".." in text.split("/"):
            raise VcsError(f"'{raw}' leaves the repository; paths may not contain '..'.")
        cleaned = _clean_relative(text)
        folded_prefix = prefix.casefold()
        if text.startswith("/") or (
            prefix and (cleaned.casefold() == folded_prefix or cleaned.casefold().startswith(folded_prefix + "/"))
        ):
            # Repository-relative: an explicit leading "/", or a project path that already names the project folder.
            repo_path = _on_disk_case(repo, cleaned, known)
        else:
            relative = _on_disk_case(root, cleaned, project_known)
            repo_path = f"{prefix}/{relative}".rstrip("/") if prefix else relative
        if not prefix:
            project_paths.append(repo_path)
        elif repo_path == prefix or repo_path.startswith(prefix + "/"):
            project_paths.append(repo_path[len(prefix) :].strip("/"))
        repo_paths.append(repo_path)
    whole_yyp = yyp_repo_path in repo_paths

    def _covers(path: str) -> bool:
        return path == "" or yyp_repo_path.startswith(path + "/")

    private_dir = f"{prefix}/{_PRIVATE_STATE_DIR}" if prefix else _PRIVATE_STATE_DIR
    named_private = any(path == private_dir or path.startswith(private_dir + "/") for path in repo_paths)
    staged_before = set(_staged_names(repo))
    # The project file as it is in the index before this call (kept registrations from earlier calls).
    indexed_before = subprocess.run(
        safe_git_command(repo, "show", f":{yyp_repo_path}"), capture_output=True, check=False
    )
    blob_before = _index_blob(repo, yyp_repo_path)
    for path in repo_paths:
        # git add rejects a deletion already absent from both disk and index.
        # Only skip a known staged deletion, never an unknown/misspelled path
        # or a directory with remaining tracked files needing to be staged.
        target = repo / path if path else repo
        matches = lambda name: path == "" or name == path or name.startswith(path + "/")  # noqa: E731
        if (
            not target.exists()
            and not target.is_symlink()
            and any(matches(name) for name in deleted)
            and not any(matches(name) for name in indexed)
        ):
            continue
        _git(repo, "add", "-A", "--", path or ".")
    if not named_private:
        # A folder that holds the project also holds the tool's lock and cache files.
        for name in sorted(set(_staged_names(repo)) - staged_before):
            if name == private_dir or name.startswith(private_dir + "/"):
                _git(repo, "reset", "-q", "--", name)
    # However the project file got staged (".", the project folder, another spelling of its path),
    # it is recomposed to this call's registrations unless it was named on purpose.
    covers_yyp = not whole_yyp and (
        any(_covers(path) for path in repo_paths) or _index_blob(repo, yyp_repo_path) != blob_before
    )

    staged_entries: list[str] = []
    if not whole_yyp:
        head = subprocess.run(safe_git_command(repo, "show", f"HEAD:{yyp_repo_path}"), capture_output=True, check=False)
        if head.returncode != 0:
            raise VcsError(
                f"{yyp_repo_path} is not in HEAD yet, so there is no committed project file to build on. "
                f"Include '{yyp_name}' in paths to stage the whole file for the first commit."
            )
        # Build on the project file that was in the index before this call, so registrations another
        # call staged earlier are kept. An untouched index entry is identical to HEAD.
        base_text = (indexed_before if indexed_before.returncode == 0 else head).stdout.decode("utf-8")
        staged_entries = [str(e) for e in (yyp_entries or []) if str(e).strip()]
        if not staged_entries:
            derive_from = project_paths
            if covers_yyp:
                # Derive from what this call actually staged under the project.
                derive_from = [
                    (n[len(prefix) + 1 :] if prefix and n.startswith(prefix + "/") else n)
                    for n in _staged_names(repo)
                    if n != yyp_repo_path and (not prefix or n.startswith(prefix + "/"))
                ]
            staged_entries = yyp_registry.derive_yyp_entries(root, base_text, derive_from)
        if staged_entries:
            working_text = _read_text_preserving_newlines(root / yyp_name)
            composed = yyp_registry.compose_yyp(base_text, working_text, staged_entries)
            already = set(yyp_registry.validate_yyp_text(base_text))
            introduced = [problem for problem in yyp_registry.validate_yyp_text(composed) if problem not in already]
            if introduced:
                _restore_index_entry(repo, yyp_repo_path, blob_before)
                raise VcsError(
                    f"The project file composed for these paths would be inconsistent, so {yyp_repo_path} was "
                    "left as it was in the index (the other paths are staged): "
                    + "; ".join(introduced[:8])
                    + ". Add the paths (or yyp_entries) the change also needs, for example the enclosing "
                    "folder or the room it replaces, and stage again.",
                    details={"problems": introduced, "yyp_entries": staged_entries},
                )
            blob = _git(repo, "hash-object", "-w", "--stdin", input_text=composed).strip()
            _git(repo, "update-index", "--cacheinfo", f"100644,{blob},{yyp_repo_path}")
        elif covers_yyp:
            # Nothing of this call needs a registration: put the earlier project file back.
            blob = _git(repo, "hash-object", "-w", "--stdin", input_text=base_text).strip()
            _git(repo, "update-index", "--cacheinfo", f"100644,{blob},{yyp_repo_path}")
    staged = [
        line
        for line in _git(repo, "-c", "core.quotePath=false", "diff", "--cached", "--name-status").splitlines()
        if line.strip()
    ]
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
        unrelated = [
            name
            for name in _staged_names(repo)
            if name != yyp_repo_path
            and not any(path == "" or name == path or name.startswith(path + "/") for path in repo_paths)
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
        result["message"] = "Staged. Review with `git diff --cached`, then commit, or call again with commit_message."
    return result


def _restore_index_entry(repo: Path, path: str, blob: str | None) -> None:
    """Put the index entry for ``path`` back to ``blob`` (None: the path was not in the index)."""
    if blob is None:
        _git(repo, "rm", "--cached", "-q", "--ignore-unmatch", "--", path)
    else:
        _git(repo, "update-index", "--cacheinfo", f"100644,{blob},{path}")
