"""Isolated builds, scripted test runs, shared locks and partial commits.

These tools never build inside the live project: they work on a throwaway snapshot, so a
build cannot be broken by (or interfere with) someone else's in-flight edits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from .. import background_runs
from ..mcp_types import Context
from ..project import _resolve_project_directory
from ..tool_types import RunnerPlatform


def _failure(tool: str, exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "tool": tool, "error": str(exc), "error_type": type(exc).__name__}


def register(mcp: Any, ContextType: Any, *, read_only: bool = False) -> None:
    globals()["Context"] = ContextType
    mutating_tool = (lambda function: function) if read_only else mcp.tool()

    @mcp.tool()
    def gm_lock_status(
        include_free: bool = False, project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Show who is building on this computer right now, when a build or test run seems stuck.

        Lists the locks that are held (the repository lock, per-project runtime leases, the mobile
        build lock and the Igor build slots) with what each is for and how long it has been held,
        plus the machine's build turn. A build slot's purpose names the project, the run label and
        the attempt; a lock this session holds has this_session=true and `this_session_runs` lists
        the runs this session still has going (empty: none). owner_gone=true marks a lock whose
        process has ended. `include_free=true` lists every lock,
        including the per-run label locks that are otherwise only counted.
        """
        _ = ctx
        import os
        import socket

        from gms_helpers.agent_locks import _owner_process_alive, lock_status
        from gms_helpers.gamemaker_machine_lock import machine_lock_holder
        from gms_helpers.project_config import project_setting

        root = _resolve_project_directory(project_root)
        slots = int(project_setting(root, "build.max_parallel_builds", 4))
        locks = []
        run_labels_held = 0
        for lock in lock_status(slots)["locks"]:
            if not lock.get("held") and not include_free:
                continue
            if str(lock.get("name", "")).startswith("runlabel_") and not include_free:
                # One per named run that is in use, on any project: dozens on a busy machine.
                run_labels_held += bool(lock.get("held"))
                continue
            owner = lock.get("owner") if isinstance(lock.get("owner"), dict) else {}
            entry: Dict[str, Any] = {"name": lock.get("name"), "held": bool(lock.get("held"))}
            if lock.get("held"):
                entry["age_seconds"] = lock.get("age_seconds")
                # The owner record also carries a claim token and process details nobody can act on.
                entry["purpose"] = owner.get("purpose")
                if owner.get("pid") == os.getpid():
                    entry["this_session"] = True
                elif (
                    owner.get("host") == socket.gethostname()
                    and isinstance(owner.get("pid"), int)
                    and not _owner_process_alive(owner, "pid")
                    and not _owner_process_alive(owner, "supervisor_pid")
                ):
                    # Left behind by a process that has ended; the next one to need it takes it over.
                    entry["owner_gone"] = True
            locks.append(entry)
        holder = machine_lock_holder()
        build_turn: Dict[str, Any] = {"held": holder is not None}
        if holder is not None:
            held = holder.get("held_seconds")
            holder_root = holder.get("project_root")
            build_turn.update(
                operation=holder.get("operation"),
                held_seconds=round(held, 1) if isinstance(held, (int, float)) else None,
                this_project=isinstance(holder_root, str)
                and os.path.normcase(holder_root) == os.path.normcase(str(root)),
            )
        held_count = sum(1 for lock in locks if lock["held"])
        return {
            "ok": True,
            "summary": (
                f"{held_count} lock(s) held; build slots: {slots}; "
                f"machine build turn {'held' if build_turn['held'] else 'free'}."
            ),
            "build_turn": build_turn,
            "locks": locks,
            **({"run_labels_in_use": run_labels_held} if run_labels_held else {}),
            # Empty means nothing this session started is still building or running.
            "this_session_runs": background_runs.running_labels(root),
        }

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
        background: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Compile a throwaway copy of the project and report compiler errors. Nothing is written to the project.

        A compile takes one to several minutes. A call that has no result after about 20 seconds
        returns status STILL_RUNNING with the build's stage, and the build carries on: follow it
        with gm_build_status(label=...), which returns this result when it ends. background=true
        returns at once instead.

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
        from gms_helpers.snapshot_build import label_pipeline, runs_directory, safe_label, snapshot_compile
        import shutil

        from gms_helpers.path_safety import validate_git_ref

        try:
            validate_git_ref(ref)
        except Exception as exc:
            return _failure("snapshot", exc)
        root = _resolve_project_directory(project_root)
        label = safe_label(label)  # the name the run is filed and reported under

        def work() -> Dict[str, Any]:
            with label_pipeline(root, label):
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
            run_dir = runs_directory(root, label)
            return await background_runs.run(
                run_dir,
                label,
                "gm_snapshot_compile",
                work,
                wait_seconds=background_runs.call_wait_seconds(root, background),
            )
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
        background: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Compile a throwaway copy of the project with a test script injected, run the game, and return PASS/FAIL.

        The build and the run take minutes. A call that has no result after about 20 seconds
        returns status STILL_RUNNING with the run's stage, and the run carries on: follow it with
        gm_build_status(label=...), which returns this result when it ends. background=true
        returns at once instead.

        The test is GML passed as test_code (or a path in test_file). It must define
        `function agent_test_step(_frame) { ... }`, called once per frame from frame 1 by a
        global time source after Begin Step and before Step. This is NOT a post-Step callback:
        compare completed movement on the next callback against target state saved on the
        preceding callback. Simulated input must span real frames to reach Step; project
        transform systems may require their explicit update before isolated physics checks.
        End Step may clear current input fields: inspect the project's previous-frame sample.
        Position collision fixtures using actual sprite origins and mask bounds.
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
        Different macOS projects run concurrently; waiting for a project lease is reported
        separately and does not count towards the timeout. Read more of the log afterwards
        with gm_run_log(label=...). Running the game needs a macOS host and runtime="VM".
        """
        _ = ctx
        from gms_helpers.snapshot_build import run_test, runs_directory, safe_label

        from gms_helpers.path_safety import validate_git_ref

        try:
            validate_git_ref(ref)
        except Exception as exc:
            return _failure("gm_test_run", exc)
        root = _resolve_project_directory(project_root)
        label = safe_label(label)  # the name the run is filed and reported under

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
            run_dir = runs_directory(root, label)
            return await background_runs.run(
                run_dir, label, "gm_test_run", work, wait_seconds=background_runs.call_wait_seconds(root, background)
            )
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_test_run", exc)

    @mcp.tool()
    async def gm_build_status(
        label: str = "compile",
        wait_seconds: float = 30.0,
        until: str = "end",
        log_lines: int = background_runs.DEFAULT_LOG_LINES,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Follow a build, test run or game start by its label: where it has got to, or its result once it has ended.

        Works for a run started with background=true, for one another call is still waiting on,
        and for one started by another session on this project. A gm_compile run has the label
        "working_tree". Waits up to wait_seconds (at most
        300) for the run to end, so one call usually returns the result; pass 0 to look once.
        until names something sooner to return at: a stage ("compiling" returns as soon as the
        run is compiling, at once if it already is), or "change" for the next change of stage or
        attempt after this call began.

        While the run is going: finished=false with `stage`, stage_seconds and run_seconds,
        `stages_done` (the seconds each earlier stage took, including any that passed between
        two calls), the
        attempt number (of max_attempts: a compiler crash is retried, and previous_attempt says
        so), and `log_tail`, the last log_lines lines of the compiler or game log, with
        log_quiet_seconds since the last line was written. Call again. Stages, in order:
        "starting", "copying the project", "waiting for a build slot" (only when all slots are
        taken), "compiling", "reading the build result"; then for a test "waiting for this
        project's game to be free" (only when it is busy), "starting the game", "running the
        test" (stage_timeout_seconds is its limit, on the stage_seconds clock), "collecting the
        test result"; for a game start "starting the game", "connecting to the game".
        When it has ended: finished=true with the result the tool that started it returns (ok,
        status, errors, error_locations, and so on), run_seconds for the whole run and `stages`,
        the seconds spent in each stage. A run that failed or was stopped is still a successful
        status call: read its `ok` and `status`.
        """
        _ = ctx
        from gms_helpers.snapshot_build import runs_directory

        try:
            run_dir = runs_directory(_resolve_project_directory(project_root), label)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_build_status", exc)
        until = str(until or "end").strip()
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), background_runs.MAX_WAIT_SECONDS))
        first: tuple[Any, Any] | None = None
        while True:
            report = await asyncio.to_thread(background_runs.status, run_dir, log_lines=log_lines)
            if report.get("finished") or "stage" not in report or time.monotonic() >= deadline:
                return report
            at = (report.get("stage"), report.get("attempt"))
            if until not in {"end", "change"} and report.get("stage") == until:
                return report
            if first is None:
                first = at
            elif until == "change" and at != first:
                return report
            # Short enough that a brief stage is seen, cheap because a run of this server is read from memory.
            await asyncio.sleep(min(0.25, max(0.05, deadline - time.monotonic())))

    @mutating_tool
    async def gm_build_stop(
        label: str = "compile", project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Stop a build or test run this session started, by its label, and end its compiler process.

        The project is not affected: builds work on a throwaway copy, and a gm_compile run (label
        "working_tree") only reads the project. A game started with gm_game_start is stopped with
        gm_game_stop instead.
        """
        _ = ctx
        from gms_helpers.snapshot_build import runs_directory

        try:
            run_dir = runs_directory(_resolve_project_directory(project_root), label)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_build_stop", exc)
        return await asyncio.to_thread(background_runs.stop, run_dir)

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
        them: asset .yy paths, "folders/....yy", "included:datafiles/dir/file", "texturegroup:<name>",
        "audiogroup:<name>", "config:<name>"). Room order follows staged rooms, and a composed .yyp
        that would be inconsistent is refused. The .yyp in the working tree is not modified.

        paths are relative to the folder containing the .yyp; a path outside it can be given
        relative to the repository root with a leading "/" (e.g. "/docs/systems/FOO.md"). Deleted
        paths are staged as deletions. Pass commit_message to commit what was staged; nothing is
        ever pushed. Runs under the project mutation lock and the shared repository lock.
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
