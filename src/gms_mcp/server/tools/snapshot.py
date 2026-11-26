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
        Show who is building on this computer, when a build or test run seems stuck.

        Lists held locks (repository, per-project runtime leases, mobile build, Igor build slots)
        with each one's purpose and age, and the machine's build turn. this_session=true marks
        this session's locks; `this_session_runs` lists its runs still going. Locks left by an
        ended process block nobody and are only counted in `left_behind`; include_free=true lists
        every lock, those and the per-run label locks included.
        """
        _ = ctx
        import os

        from gms_helpers.agent_locks import lock_status
        from gms_helpers.gamemaker_machine_lock import machine_lock_holder
        from gms_helpers.project_config import project_setting

        root = _resolve_project_directory(project_root)
        slots = int(project_setting(root, "build.max_parallel_builds", 4))
        locks = []
        run_labels_held = 0
        left_behind = 0
        for lock in lock_status(slots)["locks"]:
            if lock.get("left_behind"):
                left_behind += 1
            if not include_free and (not lock.get("held") or lock.get("left_behind")):
                continue
            if str(lock.get("name", "")).startswith("runlabel_") and not include_free:
                # One per named run that is in use, on any project: dozens on a busy machine.
                run_labels_held += 1
                continue
            owner = lock.get("owner") if isinstance(lock.get("owner"), dict) else {}
            entry: Dict[str, Any] = {"name": lock.get("name"), "held": bool(lock.get("held"))}
            if lock.get("held"):
                entry["age_seconds"] = lock.get("age_seconds")
                # The owner record also carries a claim token and process details nobody can act on.
                entry["purpose"] = owner.get("purpose")
                if lock.get("left_behind"):
                    entry["left_behind"] = True
                elif owner.get("pid") == os.getpid() or owner.get("supervisor_pid") == os.getpid():
                    entry["this_session"] = True
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
        held_count = sum(1 for lock in locks if lock["held"] and not lock.get("left_behind"))
        return {
            "ok": True,
            "summary": (
                f"{held_count} lock(s) held; build slots: {slots}; "
                f"machine build turn {'held' if build_turn['held'] else 'free'}."
            ),
            "build_turn": build_turn,
            "locks": locks,
            **({"run_labels_in_use": run_labels_held} if run_labels_held else {}),
            **({"left_behind": left_behind} if left_behind else {}),
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
        Read the log of an earlier gm_test_run or gm_snapshot_compile.

        which: "run" (the game's show_debug_message lines), "build" (Igor's compile log) or
        "runner" (the runner's stderr). pattern, a regular expression, keeps matching lines
        (e.g. "\\[TEST\\]" or "ERROR"). Returns the last `lines` lines and the run's screenshots
        as gm_test_run gives them.
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
        Compile a throwaway copy of the project and report compiler errors; the project is not touched.

        By default the copy is the working tree as it is now, everyone's uncommitted edits
        included. When files that are not yours break the build, pass isolate_paths (relative to
        the .yyp's folder, e.g. ["scripts/my_script", "objects/o_thing", "datafiles/data/items"]):
        the copy is git `ref` plus those paths, with the .yyp registrations they need (inferred,
        or named in yyp_entries: asset .yy paths, "folders/....yy", "included:datafiles/dir/file").
        base_only=true builds `ref` alone.

        Igor's random AccessViolationException crash is retried (`attempts`, default
        build.igor_attempts in .gms-mcp.json); compiler errors are not: fix those in `errors`.
        platform defaults to this OS; Android and iOS package with the IDE's saved SDK/Xcode
        settings and give nothing runnable here.
        Takes minutes: after about 20 s it returns STILL_RUNNING and carries on; follow it with
        gm_build_status(label=...). background=true returns at once.
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
        Build a throwaway copy of the project with a GML test injected, run the game, and return PASS/FAIL.

        test_code (or a file in test_file) must define `function agent_test_step(_frame) { ... }`,
        called once per frame from frame 1, after Begin Step and before Step: it is NOT a
        post-Step callback, so check a movement on the next call against state saved on the one
        before. Simulated input must span real frames to reach Step; End Step may clear current
        input fields (read the project's previous-frame sample); project transform systems may
        need an explicit update before isolated physics checks; place collision fixtures by real
        sprite origins and mask bounds. The test exists only in the copy, never in the project.
        Helpers: test_log(value) adds to `test_lines`; test_check(condition, text) logs PASS/FAIL
        and any FAIL fails the run; test_shot(name) saves a screenshot; test_end() ends the run:
        ALWAYS call it, also on a frame-count timeout inside the test.

        status: TEST_PASSED, TEST_FAILED, BUILD_FAILED, or TEST_TIMEOUT when test_end() is not
        reached within timeout_seconds (default test.timeout_seconds in .gms-mcp.json; waiting for
        this project's game lease does not count). A runtime error in the log always fails the run.
        Test lines come back in order without "[TEST]"; a line repeated back to back ends " [×N]".
        `screenshot_files` is a path pattern and each `screenshots` entry fills its *;
        "f{0001..0240}" is every number from f0001 to f0240.
        A failed run's `log_tail` leaves out the runner's own start-up lines; the whole log:
        gm_run_log(label=...). isolate_paths, yyp_entries, base_only and ref work as in
        gm_snapshot_compile. Needs a macOS host and runtime="VM".
        Takes minutes: after about 20 s it returns STILL_RUNNING and carries on; follow it with
        gm_build_status(label=...). background=true returns at once.
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
        label: str = "",
        wait_seconds: float = 30.0,
        until: str = "end",
        log_lines: int = background_runs.DEFAULT_LOG_LINES,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Follow a build, test run or game start: its stage while it runs, its result once it ends.

        label names the run (gm_compile's is "working_tree"); without it, the run this session
        started last, else the project's latest. Waits up to wait_seconds (at most 300) for the
        end, so one call usually returns the result; 0 looks once. until returns sooner: at a
        named stage (at once if already there), or "change" at the next change of stage or attempt.

        Running: finished=false, `stage`, stage_seconds, run_seconds, `stages_done` (seconds per
        earlier stage), the attempt of max_attempts (a compiler crash is retried; previous_attempt
        says so), `log_tail` (last log_lines lines) and log_quiet_seconds. Call again. Stages:
        starting, copying the project, waiting for a build slot, compiling, reading the build
        result; a test then has waiting for this project's game to be free, starting the game,
        running the test (limited by stage_timeout_seconds; test_frame is the frame reached),
        collecting the test result; a game start has starting the game, connecting to the game;
        gm_compile has starting, waiting for a change to the project to finish, compiling.
        Ended: finished=true with the starting tool's own result (ok, status, errors, ...),
        `stages` (seconds each), build_seconds and run_seconds (waits and a test's game
        included). A failed or stopped run is still a successful call: read its ok and status.
        """
        _ = ctx
        from gms_helpers.snapshot_build import runs_directory

        try:
            root = _resolve_project_directory(project_root)
            if not str(label or "").strip():
                latest = background_runs.latest_label(root)
                if latest is None:
                    return {
                        "ok": False,
                        "finished": False,
                        "error": "No build or test run has been recorded for this project.",
                        "hint": "Start one with gm_snapshot_compile, gm_compile, gm_test_run or gm_game_start.",
                    }
                label = latest
            run_dir = runs_directory(root, label)
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
    async def gm_build_stop(label: str = "", project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Stop a build or test run this session started, and end its compiler process.

        With no label it stops the one run this session has going; when several are going it
        stops none and lists their labels, so name one. The project is not affected: builds work
        on a throwaway copy, and a gm_compile run (label "working_tree") only reads the project.
        A game started with gm_game_start is stopped with gm_game_stop instead.
        """
        _ = ctx
        from gms_helpers.snapshot_build import runs_directory

        try:
            root = _resolve_project_directory(project_root)
            if not str(label or "").strip():
                running = background_runs.running_labels(root)
                if len(running) > 1:
                    return {
                        "ok": False,
                        "running_labels": running,
                        "error": f"This session has {len(running)} runs going ({', '.join(running)}); pass label to say which.",
                    }
                # With nothing going, the latest run answers for itself: it has already ended.
                latest = running[0] if running else background_runs.latest_own_label(root)
                if latest is None:
                    return {
                        "ok": False,
                        "error": "This session has started no build or test run, so there is nothing to stop.",
                        "hint": "Only a run this session started can be stopped. gm_game_stop stops a running game.",
                    }
                label = latest
            run_dir = runs_directory(root, label)
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
        Stage exactly the given paths in git, plus a project file that holds only their registrations.

        `git add` of the .yyp would also commit other people's uncommitted registrations. This
        stages the .yyp as HEAD plus only the registrations `paths` need (inferred, or named in
        yyp_entries: asset .yy paths, "folders/....yy", "included:datafiles/dir/file",
        "texturegroup:<name>", "audiogroup:<name>", "config:<name>"); room order follows staged
        rooms, an inconsistent result is refused, and the working-tree .yyp is left alone.
        paths are relative to the .yyp's folder, or to the repository root with a leading "/"
        ("/docs/FOO.md"); deleted paths are staged as deletions. commit_message commits what was
        staged; nothing is pushed.
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
