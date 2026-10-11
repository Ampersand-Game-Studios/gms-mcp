"""Isolated builds, scripted test runs, shared locks and partial commits.

These tools never build inside the live project: they work on a throwaway snapshot, so a
build cannot be broken by (or interfere with) someone else's in-flight edits.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ..mcp_types import Context
from ..project import _resolve_project_directory
from ..tool_types import RunnerPlatform


def _failure(tool: str, exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "tool": tool, "error": str(exc), "error_type": type(exc).__name__}


def register(mcp: Any, ContextType: Any, *, read_only: bool = False) -> None:
    globals()["Context"] = ContextType
    mutating_tool = (lambda function: function) if read_only else mcp.tool()

    @mcp.tool()
    def gm_lock_status(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Show the machine-wide locks shared by everyone building on this computer.

        Use it when a build or test run seems stuck: it lists the repository lock, the
        one-game-at-a-time run lock, the mobile build lock and the Igor build slots, with who
        holds each and for how long.
        """
        _ = ctx
        from gms_helpers.agent_locks import lock_status
        from gms_helpers.project_config import project_setting

        root = _resolve_project_directory(project_root)
        return {"ok": True, **lock_status(int(project_setting(root, "build.max_parallel_builds", 4)))}

    @mcp.tool()
    def gm_run_log(
        label: str = "test",
        which: str = "run",
        lines: int = 200,
        pattern: str = "",
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Read the log of an earlier gm_test_run / gm_snapshot_compile.

        which: "run" = the game's own log (every show_debug_message line), "build" = Igor's
        compile log, "runner" = the runner's stderr. pattern is an optional regular expression
        that keeps only matching lines (for example "\\[TEST\\]" or "ERROR"). Returns the last
        `lines` lines and the run's screenshot paths.
        """
        _ = ctx
        from gms_helpers.snapshot_build import read_run_artifact

        try:
            return read_run_artifact(_resolve_project_directory(project_root), label, which, lines, pattern or None)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_run_log", exc)

    @mutating_tool
    async def gm_snapshot_compile(
        label: str = "compile",
        isolate_paths: List[str] | None = None,
        yyp_entries: List[str] | None = None,
        base_only: bool = False,
        ref: str = "HEAD",
        platform: RunnerPlatform | None = None,
        runtime: str = "VM",
        runtime_version: str | None = None,
        attempts: int | None = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Compile a throwaway copy of the project and report compiler errors. Nothing is written to the project.

        Default: the copy is the working tree exactly as it is now (including everyone's
        uncommitted edits).

        Isolated build: pass isolate_paths (paths relative to the folder containing the .yyp,
        e.g. ["scripts/my_script", "objects/o_thing", "datafiles/data/items"]). The copy is then
        git revision `ref` plus only those paths, and its .yyp is that revision plus only the
        registrations those paths need (worked out automatically; pass yyp_entries to name them
        yourself: asset .yy paths, "folders/....yy" folder paths, "included:datafiles/dir/file").
        Use this when the working tree does not compile because of files that are not yours.
        base_only=true builds revision `ref` with nothing added.

        Igor's random System.AccessViolationException crash is retried automatically
        (`attempts`, default from .gms-mcp.json build.igor_attempts). A build that fails with
        compiler errors is never retried: fix the errors listed in `errors`.

        platform: default is this computer's OS. Android and iOS package the game with the
        SDK/Xcode settings saved in the GameMaker IDE; they produce no runnable result here.
        """
        _ = ctx
        from gms_helpers.snapshot_build import snapshot_compile
        import shutil

        root = _resolve_project_directory(project_root)

        def work() -> Dict[str, Any]:
            public, _build, work_dir, _tools = snapshot_compile(
                root,
                label=label,
                isolate_paths=isolate_paths,
                yyp_entries=yyp_entries,
                ref=ref,
                base_only=base_only,
                platform=platform,
                runtime=runtime,
                runtime_version=runtime_version,
                attempts=attempts,
            )
            shutil.rmtree(work_dir, ignore_errors=True)
            return public

        try:
            return await asyncio.to_thread(work)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_snapshot_compile", exc)

    @mutating_tool
    async def gm_test_run(
        test_code: str = "",
        test_file: str = "",
        label: str = "test",
        timeout_seconds: int = 0,
        isolate_paths: List[str] | None = None,
        yyp_entries: List[str] | None = None,
        base_only: bool = False,
        ref: str = "HEAD",
        runtime: str = "VM",
        runtime_version: str | None = None,
        attempts: int | None = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Compile a throwaway copy of the project with a test script injected, run the game, and return PASS/FAIL.

        The test is GML passed as test_code (or a path in test_file). It must define
        `function agent_test_step(_frame) { ... }`, which is called once per frame from frame 1.
        Helpers available to the test:
          test_log(value)             adds a "[TEST] ..." line to the result
          test_check(condition, text) "[TEST] PASS/FAIL text"; any failed check fails the run
          test_shot(name)             saves a screenshot, returned in `screenshots`
          test_end()                  prints the result and quits the game; ALWAYS call it,
                                      including on a frame-count timeout inside the test
        The test script exists only in the snapshot; it is never written into the project.

        status is one of TEST_PASSED, TEST_FAILED, TEST_TIMEOUT, BUILD_FAILED. A GameMaker
        runtime error in the log always fails the run. The completion signal is the result line
        in the game log, so a test that never calls test_end() ends as TEST_TIMEOUT after
        timeout_seconds (default from .gms-mcp.json test.timeout_seconds).

        isolate_paths / yyp_entries / base_only / ref work as in gm_snapshot_compile.
        Only one game runs at a time on a machine; waiting for that lock is reported
        separately and does not count towards the timeout. Read more of the log afterwards
        with gm_run_log(label=...). Running the game needs a macOS host.
        """
        _ = ctx
        from gms_helpers.snapshot_build import run_test

        root = _resolve_project_directory(project_root)

        def work() -> Dict[str, Any]:
            return run_test(
                root,
                test_code=test_code or None,
                test_file=test_file or None,
                label=label,
                timeout_seconds=timeout_seconds or None,
                isolate_paths=isolate_paths,
                yyp_entries=yyp_entries,
                base_only=base_only,
                ref=ref,
                runtime=runtime,
                runtime_version=runtime_version,
                attempts=attempts,
            )

        try:
            return await asyncio.to_thread(work)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_test_run", exc)

    @mutating_tool
    def gm_vcs_stage(
        paths: List[str],
        yyp_entries: List[str] | None = None,
        commit_message: str = "",
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Stage exactly the given paths in git, plus a project file that contains only your registrations.

        When several people have uncommitted assets in one working tree, `git add` of the .yyp
        would commit all of their registrations too. This stages the .yyp as "HEAD plus only the
        registrations belonging to `paths`" (worked out automatically; pass yyp_entries to name
        them: asset .yy paths, "folders/....yy", "included:datafiles/dir/file"). The .yyp in the
        working tree is not modified.

        paths are relative to the folder containing the .yyp; a path outside it can be given
        relative to the repository root with a leading "/" (e.g. "/docs/systems/FOO.md"). Deleted
        paths are staged as deletions. Pass commit_message to commit what was staged; nothing is
        ever pushed. Runs under the shared repository lock.
        """
        _ = ctx
        from gms_helpers.vcs_stage import stage_paths

        try:
            return stage_paths(
                _resolve_project_directory(project_root),
                paths,
                yyp_entries=yyp_entries,
                commit_message=commit_message or None,
            )
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_vcs_stage", exc)
