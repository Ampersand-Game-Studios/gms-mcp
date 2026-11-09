"""Regression coverage for CLI and filesystem trust boundaries."""

import argparse
import asyncio
import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from gms_helpers import gms, snapshot_build, transactions, yyp_registry
from gms_helpers.bounded_regex import RegexTimeoutError
from gms_helpers.exceptions import ValidationError
from gms_helpers.path_safety import private_directory
from gms_mcp.project_detection import safe_git_command
from gms_mcp.server.validation import validate_mcp_tool_arguments


def project(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    (root / "game.yyp").write_text('{"resources":[],"Folders":[]}')
    return root


def test_c1_all_parsers_disable_abbreviation():
    def check(parser):
        assert not parser.allow_abbrev
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    check(child)

    check(gms.create_parser())
    with pytest.raises(SystemExit):
        gms.create_parser().parse_args(["--proj=/other", "asset", "create", "script", "scr_test"])


@pytest.mark.parametrize("tool", ["gm_snapshot_compile", "gm_test_run"])
@pytest.mark.parametrize("ref", ["--output=outside.zip", "", "HEAD\x00"])
def test_mcp_snapshot_rejects_git_options_before_resolving_or_building(tmp_path, monkeypatch, tool, ref):
    from gms_mcp.server.tools import snapshot

    registered = {}
    snapshot.register(
        SimpleNamespace(tool=lambda: lambda function: registered.setdefault(function.__name__, function)), object
    )
    monkeypatch.setattr(
        snapshot, "_resolve_project_directory", lambda _: pytest.fail("Unsafe ref must fail before project work")
    )
    result = asyncio.run(registered[tool](project_root=str(tmp_path), ref=ref))
    assert not result["ok"] and result["error_type"] == "ValidationError"
    assert "Invalid ref" in result["error"]


def test_c1_global_promotion_preserves_option_values():
    argv = ["asset", "create", "note", "note_test", "--content", "--project-root=/other"]
    assert gms._promote_global_options(argv) == argv
    assert gms._promote_global_options(["asset", "--", "--project-root=/other"]) == [
        "asset",
        "--",
        "--project-root=/other",
    ]


def test_c1_approved_root_rejects_different_parsed_project(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    monkeypatch.setenv("GMS_MCP_APPROVED_PROJECT_ROOT", str(tmp_path / "approved"))
    monkeypatch.setattr(sys, "argv", ["gms", "--project-root", str(root), "maintenance", "list-orphans"])
    monkeypatch.setattr(gms, "_execute_project_command", lambda args: pytest.fail("must not execute"))
    assert gms.main() is False
    assert "GMS_MCP_APPROVED_PROJECT_ROOT" in capsys.readouterr().out


def test_c1_transaction_rejects_external_writes_and_allows_only_own_infrastructure(tmp_path):
    root = project(tmp_path)
    infrastructure = tmp_path / "transaction"
    context = transactions._TransactionJournalContext(root, infrastructure / "journal", infrastructure / "backup")
    for path in [tmp_path / "outside", infrastructure / "other"]:
        with pytest.raises(ValidationError, match="outside"):
            transactions._journal_relative_path(context, path)
    assert transactions._journal_relative_path(context, infrastructure / "journal") is None
    assert transactions._journal_relative_path(context, infrastructure / "backup" / "asset.yy") is None


def test_c1_transaction_allows_tool_state_but_never_the_user_config(tmp_path, monkeypatch):
    root = project(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    infrastructure = tmp_path / "transaction"
    context = transactions._TransactionJournalContext(root, infrastructure / "journal", infrastructure / "backup")
    for path in [
        home / ".gms-mcp" / "logs" / "run.log",
        Path(tempfile.gettempdir()) / "gms-mcp-direct-runner-x" / "manifest.json",
        tmp_path / "pkg" / "__pycache__",
        tmp_path / "pkg" / "__pycache__" / "module.cpython-312.pyc",
        tmp_path / "pkg" / "__pycache__" / "module.cpython-312.pyc.4366289456",
        Path(os.devnull),
    ]:
        assert transactions._journal_relative_path(context, path) is None
    for path in [
        home / ".gms-mcp" / "config.json",
        home / ".zshrc",
        Path(tempfile.gettempdir()) / "unrelated" / "file",
        tmp_path / "pkg" / "module.pyc",
        tmp_path / "pkg" / "__pycache__" / "payload.py",
    ]:
        with pytest.raises(ValidationError, match="outside"):
            transactions._journal_relative_path(context, path)


def test_c1_windows_null_device_is_allowed_but_other_devices_are_not(tmp_path, monkeypatch):
    root = project(tmp_path)
    context = transactions._TransactionJournalContext(root, tmp_path / "journal", tmp_path / "backup")
    monkeypatch.setattr(transactions.os, "name", "nt")
    monkeypatch.setattr(transactions.os, "devnull", "nul")
    for path in ["nul", "NUL"]:
        assert transactions._journal_relative_path(context, path) is None
    for path in ["con", str(root / "nul"), str(root / "aux.txt")]:
        with pytest.raises(ValidationError, match="device"):
            transactions._journal_relative_path(context, path)


def test_c1_transaction_allows_first_import_to_cache_bytecode(tmp_path, monkeypatch):
    root = project(tmp_path)
    package = tmp_path / "site-packages"
    package.mkdir()
    (package / "first_import_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(package))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "pycache_prefix", None)
    context = transactions._TransactionJournalContext(root, root / ".gms_mcp/journal", root / ".gms_mcp/backup")
    transactions._ensure_transaction_audit_hook()
    token = transactions._ACTIVE_TRANSACTION.set(context)
    try:
        assert importlib.import_module("first_import_module").VALUE == 1
    finally:
        transactions._ACTIVE_TRANSACTION.reset(token)
        sys.modules.pop("first_import_module", None)
    assert list((package / "__pycache__").glob("first_import_module.*.pyc"))


def test_c1_transaction_hook_blocks_actual_external_write(tmp_path):
    root = project(tmp_path)
    context = transactions._TransactionJournalContext(root, root / ".gms_mcp/journal", root / ".gms_mcp/backup")
    transactions._ensure_transaction_audit_hook()
    token = transactions._ACTIVE_TRANSACTION.set(context)
    try:
        with pytest.raises(ValidationError):
            (tmp_path / "outside").write_text("unsafe")
    finally:
        transactions._ACTIVE_TRANSACTION.reset(token)
    assert not (tmp_path / "outside").exists()


def test_cold_temporary_directory_discovery_cannot_deadlock_transaction_audit(tmp_path):
    root = project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    temporary = tmp_path / "system-temp"
    temporary.mkdir()
    program = """
import os, tempfile
from pathlib import Path
from gms_helpers import transactions
from gms_helpers.exceptions import ValidationError
from gms_mcp.server.log_paths import diagnostic_log_dir
root = Path.cwd()
tempfile.tempdir = None
context = transactions._TransactionJournalContext(root, root / '.gms_mcp/journal', root / '.gms_mcp/backup')
transactions._ensure_transaction_audit_hook()
token = transactions._ACTIVE_TRANSACTION.set(context)
try:
    assert diagnostic_log_dir(root).is_dir()
    try:
        (Path(os.environ['TMPDIR']) / 'unrelated-file').write_text('blocked')
    except ValidationError:
        pass
    else:
        raise AssertionError('External write was permitted')
finally:
    transactions._ACTIVE_TRANSACTION.reset(token)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=root,
        env={**os.environ, "HOME": str(home), "USERPROFILE": str(home), "TMPDIR": str(temporary)},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_c1_audit_resolution_errors_fail_closed(tmp_path, monkeypatch):
    root = project(tmp_path)
    context = transactions._TransactionJournalContext(root, root / "journal", root / "backup")
    monkeypatch.setattr(transactions, "_audit_absolute_path", lambda *args: None)
    with pytest.raises(ValidationError, match="cannot resolve"):
        transactions._journal_relative_path(context, root / "file")


@pytest.mark.skipif(os.name == "nt", reason="Directory descriptors require POSIX")
def test_c1_directory_descriptor_paths_are_checked_against_project(tmp_path):
    root = project(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    context = transactions._TransactionJournalContext(root, root / "journal", root / "backup")
    descriptor = os.open(nested, os.O_RDONLY)
    outside = os.open(tmp_path, os.O_RDONLY)
    try:
        assert transactions._journal_relative_path(context, "asset.yy", descriptor) == "nested/asset.yy"
        with pytest.raises(ValidationError):
            transactions._journal_relative_path(context, "outside.yy", outside)
    finally:
        os.close(descriptor)
        os.close(outside)


def test_c1_transaction_allows_its_machine_lock_only(tmp_path, monkeypatch):
    from gms_helpers.gamemaker_machine_lock import GameMakerMachineLock

    root = project(tmp_path)
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    lock_path = lock_dir / "runtime.lock"
    monkeypatch.setenv("GMS_MCP_MACHINE_LOCK_PATH", str(lock_path))
    context = transactions._TransactionJournalContext(
        root, root / "journal", root / "backup", machine_lock_path=lock_path
    )
    token = transactions._ACTIVE_TRANSACTION.set(context)
    try:
        with GameMakerMachineLock("compile", root) as lock:
            assert lock.delegation_environment("compile")
            with pytest.raises(ValidationError):
                (lock_dir / "unrelated").write_text("unsafe")
    finally:
        transactions._ACTIVE_TRANSACTION.reset(token)


def test_c2_journaled_python_disables_cwd_imports(tmp_path):
    (tmp_path / "hijack.py").write_text("raise RuntimeError('hijacked')")
    command = transactions.journaled_gms_cli_command([])
    assert "-P" in command[: command.index("-c")]
    result = subprocess.run(
        [sys.executable, "-P", "-c", "import importlib.util; assert importlib.util.find_spec('hijack') is None"],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_c2_compile_verification_python_uses_safe_path(tmp_path, monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        completed = subprocess.CompletedProcess(
            command, 0, "Final Compile finished\nSaving IFF file\nIgor complete.", ""
        )
        return completed, None

    monkeypatch.setattr(transactions, "transaction_subprocess_environment", lambda: {})
    monkeypatch.setattr(transactions, "_run_compile_verification_child", run)
    result = transactions._compile_verify_project_locked(
        tmp_path,
        platform="Linux",
        runtime="VM",
        timeout_seconds=1,
        machine_lock=SimpleNamespace(delegation_environment=lambda operation: {}),
    )
    assert result["ok"]
    assert "-P" in commands[0][: commands[0].index("-m")]


@pytest.mark.parametrize("tool", ["gm_snapshot_compile", "gm_test_run", "gm_game_start"])
@pytest.mark.parametrize("ref", ["--output=/outside", "-HEAD", "", "a\x00b"])
def test_c3_tool_boundary_rejects_option_refs(tool, ref):
    assert any(error["field"] == "ref" for error in validate_mcp_tool_arguments(tool, {"ref": ref}))


def test_c3_snapshot_rejects_ref_before_removing_destination(tmp_path):
    root = project(tmp_path)
    dest = tmp_path / "snapshot"
    dest.mkdir()
    (dest / "keep").write_text("keep")
    with pytest.raises(ValidationError):
        snapshot_build.create_snapshot(root, dest, ref="--output=/outside")
    assert (dest / "keep").read_text() == "keep"


def test_c3_git_tree_uses_raw_blobs_and_pins_commit(tmp_path, monkeypatch):
    root = project(tmp_path)
    sha = "a" * 40
    oid = "b" * 40
    raw = b'{"resources":[],"Folders":[],"value":"$Format:%H$"}'
    calls = []

    def git(repo, *args, input_bytes=None, env=None):
        calls.append(args)
        data = b""
        if args[:2] == ("rev-parse", "--show-toplevel"):
            data = str(root).encode()
        elif args[0] == "rev-parse":
            assert args == ("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
            data = sha.encode()
        elif args[0] == "ls-tree":
            assert args[3] == sha
            data = f"100755 blob {oid}\tgame.yyp\0".encode()
        elif args[0] == "read-tree":
            assert args == ("read-tree", sha) and env["GIT_INDEX_FILE"]
        else:
            assert args[0] == "checkout-index" and args[2:] == ("--stdin", "-z")
            assert input_bytes == b"game.yyp\0" and env["GIT_INDEX_FILE"]
            Path(args[1].removeprefix("--prefix="), "game.yyp").write_bytes(raw)
        return subprocess.CompletedProcess(args, 0, data, b"")

    monkeypatch.setattr(snapshot_build, "_git", git)
    dest = tmp_path / "snapshot"
    snapshot_build.create_snapshot(root, dest, base_only=True)
    assert (dest / "game.yyp").read_bytes() == raw
    if os.name != "nt":  # Windows has no executable mode bit to restore.
        assert (dest / "game.yyp").stat().st_mode & stat.S_IXUSR
    assert all("archive" not in call for call in calls)


@pytest.mark.parametrize("mode,kind", [("120000", "blob"), ("160000", "commit")])
def test_c3_git_tree_rejects_symlinks_and_submodules(tmp_path, monkeypatch, mode, kind):
    monkeypatch.setattr(
        snapshot_build,
        "_git",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, f"{mode} {kind} {'b' * 40}\tlink\0".encode(), b""),
    )
    with pytest.raises(ValidationError, match="symlink or submodule"):
        snapshot_build._read_git_tree(tmp_path, "a" * 40, tmp_path / "stage", "")


def test_c3_git_disables_repository_commands(tmp_path):
    command = safe_git_command(tmp_path, "ls-files")
    assert "core.fsmonitor=false" in command
    assert f"core.hooksPath={os.devnull}" in command


@pytest.mark.parametrize("module", ["snapshot", "stage", "discovery"])
def test_c3_git_callers_disable_repository_commands(tmp_path, monkeypatch, module):
    from gms_helpers import vcs_stage
    from gms_mcp import project_detection

    (tmp_path / ".git").mkdir()
    (tmp_path / "game.yyp").write_text("{}")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"game.yyp\0", b"")

    monkeypatch.setattr(subprocess, "run", run)
    if module == "snapshot":
        snapshot_build._git(tmp_path, "ls-tree", "HEAD")
    elif module == "stage":
        vcs_stage._git(tmp_path, "ls-files")
    else:
        assert project_detection._tracked_yyp_paths(tmp_path) == [tmp_path / "game.yyp"]
    assert "core.fsmonitor=false" in commands[0]
    assert f"core.hooksPath={os.devnull}" in commands[0]


@pytest.mark.parametrize("path", ["C:/Users/x", "../outside", "/outside", "a\\b", "a:b", "."])
def test_c3_isolate_paths_reject_unsafe_syntax(path):
    with pytest.raises(ValidationError):
        snapshot_build._project_relative(path, "")


def test_c3_snapshot_rejects_directory_link_cycle(tmp_path):
    root = project(tmp_path)
    (root / "cycle").symlink_to(root, target_is_directory=True)
    with pytest.raises(ValidationError, match="Directory symlinks"):
        snapshot_build.create_snapshot(root, tmp_path / "snapshot")


def test_c3_private_work_root_is_private_and_unique(tmp_path, monkeypatch):
    base = tmp_path / "private"
    monkeypatch.setenv("GMS_MCP_SNAPSHOT_WORK_DIR", str(base))
    assert snapshot_build._work_root() == base
    if os.name != "nt":
        assert stat.S_IMODE(base.stat().st_mode) == 0o700
    else:
        from gms_helpers.windows_security import windows_path_trust_issue

        assert windows_path_trust_issue(base, private=True) is None


@pytest.mark.parametrize("kind", ["symlink", "public"])
def test_c3_private_directory_rejects_untrusted_base(tmp_path, kind):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    path = tmp_path / "base"
    if kind == "symlink":
        path.symlink_to(target, target_is_directory=True)
    else:
        path.mkdir(mode=0o755)
        if os.name == "nt":
            from gms_mcp.server.subprocess_runner import _windows_system_executable

            subprocess.run(
                [_windows_system_executable("icacls.exe"), str(path), "/grant", "*S-1-1-0:(OI)(CI)(R)"], check=True
            )
    with pytest.raises(ValidationError):
        private_directory(path)


@pytest.mark.parametrize("path", ["../outside.gml", "/outside.gml", "C:/outside.gml"])
def test_c3_test_source_requires_project_relative_path(tmp_path, path):
    with pytest.raises(ValidationError):
        snapshot_build.load_test_source(tmp_path, path, None)


def test_c3_project_test_prelude_cannot_escape(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("GMS_MCP_SNAPSHOT_WORK_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(snapshot_build, "project_setting", lambda root, key, *args: "../outside.gml")
    with pytest.raises(ValidationError, match="project-relative"):
        snapshot_build.snapshot_compile(root, test_code="function agent_test_step(_frame) {}")


def test_c3_isolated_source_symlink_cannot_escape(tmp_path, monkeypatch):
    root = project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(snapshot_build, "_git", lambda *args, **kwargs: pytest.fail("must validate before Git"))
    with pytest.raises(ValidationError):
        snapshot_build.create_snapshot(root, tmp_path / "snapshot", isolate_paths=["link"])


@pytest.mark.parametrize("field", ["frames", "layers"])
def test_c4_swap_rejects_metadata_filename_escape(tmp_path, field):
    from gms_helpers.workflow import swap_sprite_png

    root = project(tmp_path)
    folder = root / "sprites" / "spr_test"
    folder.mkdir(parents=True)
    data = {"frames": [{"name": "frame"}], "layers": [{"name": "layer"}]}
    data[field][0]["name"] = "../../../outside"
    (folder / "spr_test.yy").write_text(json.dumps(data))
    source = root / "source.png"
    source.write_bytes(b"png")
    with pytest.raises(ValidationError):
        swap_sprite_png(root, "sprites/spr_test/spr_test.yy", source)
    assert not (tmp_path / "outside.png").exists()


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_c5_machine_lock_rejects_link_files(tmp_path, monkeypatch, link):
    from gms_helpers.gamemaker_machine_lock import GameMakerMachineLock

    base = tmp_path / "private"
    base.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(b"untouched")
    lock = base / "runtime.lock"
    if link == "symlink":
        lock.symlink_to(target)
    else:
        os.link(target, lock)
    monkeypatch.setenv("GMS_MCP_MACHINE_LOCK_PATH", str(lock))
    with pytest.raises((OSError, ValueError)):
        GameMakerMachineLock("compile", tmp_path).acquire()
    assert target.read_bytes() == b"untouched"


def test_c5_machine_lock_delegation_still_works(tmp_path, monkeypatch):
    from gms_helpers import gamemaker_machine_lock as locks

    base = tmp_path / "private"
    base.mkdir(mode=0o700)
    monkeypatch.setenv("GMS_MCP_MACHINE_LOCK_PATH", str(base / "runtime.lock"))
    with locks.GameMakerMachineLock("verify", tmp_path) as lock:
        for key, value in lock.delegation_environment("compile").items():
            monkeypatch.setenv(key, value)
        assert locks._consume_valid_delegation("compile", tmp_path)


def test_c6_reference_regex_limits_and_timeout(tmp_path, monkeypatch):
    from gms_helpers import introspection

    (tmp_path / "script.gml").write_text("foo foo\nfoo\nfoo\n")
    results = introspection.search_references(tmp_path, "f.o", is_regex=True, max_results=2)
    assert [(r["line"], r["match"]) for r in results] == [(1, "foo"), (2, "foo")]

    def timeout(*args, **kwargs):
        raise RegexTimeoutError("deadline exceeded")

    monkeypatch.setattr(introspection, "search_many", timeout)
    assert "deadline exceeded" in introspection.search_references(tmp_path, "(a+)+$", is_regex=True)[0]["error"]


def test_c6_doc_regex_limits_and_timeout(monkeypatch):
    import importlib

    search = importlib.import_module("gms_helpers.gml_docs.search")

    monkeypatch.setattr(search, "DocCache", lambda: None)

    entry = lambda name: SimpleNamespace(name=name, category="math", subcategory="numbers")
    monkeypatch.setattr(
        search, "fetch_function_index", lambda cache: {name: entry(name) for name in ["aaa", "aab", "xyz"]}
    )
    assert [e["name"] for e in search.list_functions(pattern="aa", limit=1)["results"]] == ["aaa"]

    def timeout(*args, **kwargs):
        raise RegexTimeoutError("deadline exceeded")

    monkeypatch.setattr(search, "search_many", timeout)
    result = search.list_functions(pattern="(a+)+$")
    assert result["ok"] is False and "deadline exceeded" in result["error"]


@pytest.mark.parametrize("loader", ["load_json", "load_json_loose"])
def test_c7_json_size_limit_and_special_file(tmp_path, monkeypatch, loader):
    from gms_helpers import utils

    monkeypatch.setattr(utils, "MAX_JSON_BYTES", 8)
    path = tmp_path / "large.yy"
    path.write_text('{"long":"value"}')
    with pytest.raises(ValueError, match="size limit"):
        getattr(utils, loader)(path)
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match="regular file"):
            getattr(utils, loader)(fifo)


@pytest.mark.parametrize("path", ["/dev/zero", "../outside.yy", "C:/outside.yy"])
def test_c7_registry_rejects_metadata_paths(tmp_path, path):
    root = project(tmp_path)
    (root / "game.yyp").write_text(json.dumps({"resources": [{"id": {"name": "scr_test", "path": path}}]}))
    with pytest.raises(ValidationError):
        yyp_registry.load_yyp(root)


def test_live_reload_status_rejects_oversized_json(tmp_path, monkeypatch):
    from gms_helpers import live_reload, utils

    (tmp_path / "status.json").write_text('{"running":true}')
    monkeypatch.setattr(live_reload, "project_setting", lambda *_args: "status.json")
    monkeypatch.setattr(utils, "MAX_JSON_BYTES", 8)
    assert live_reload._read_status_file(tmp_path) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_live_reload_status_does_not_block_on_fifo(tmp_path):
    os.mkfifo(tmp_path / "status.json")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from gms_helpers import live_reload; "
            "live_reload.project_setting = lambda *args: 'status.json'; "
            "assert live_reload._read_status_file(Path.cwd()) is None",
        ],
        cwd=tmp_path,
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_c7_metadata_file_rejects_external_symlink(tmp_path):
    from gms_helpers.path_safety import project_file_path

    root = project(tmp_path)
    outside = tmp_path / "outside.yy"
    outside.write_text("{}")
    (root / "link.yy").symlink_to(outside)
    with pytest.raises(ValidationError):
        project_file_path("link.yy", project_root=root)


def test_c7_maintenance_rejects_special_resource_before_read(tmp_path, monkeypatch):
    from gms_helpers.maintenance import validate_paths

    root = project(tmp_path)
    (root / "game.yyp").write_text(json.dumps({"resources": [{"id": {"name": "bad", "path": "/dev/zero"}}]}))
    monkeypatch.setattr(validate_paths, "find_yyp_file", lambda: "game.yyp")
    issues = validate_paths.validate_folder_paths(str(root))
    assert any("asset_load_error" in issue.issue_type for issue in issues)


@pytest.mark.parametrize("layout,dimensions", [("grid", (65, 65)), ("horizontal", (4097, 1)), ("vertical", (1, 4097))])
def test_c8_import_rejects_excess_frames_before_cropping(tmp_path, monkeypatch, layout, dimensions):
    from gms_helpers import sprite_import

    class Image:
        size = dimensions

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def crop(self, box):
            pytest.fail("must reject before allocating frames")

    def open_image(path, *, formats):
        assert formats == ["PNG"]
        return Image()

    monkeypatch.setattr(sprite_import, "_get_pillow", lambda: SimpleNamespace(open=open_image))
    with pytest.raises(ValidationError, match="4096"):
        sprite_import.split_strip(tmp_path / "source.png", 1, 1, layout)


def test_c8_sprite_creation_rejects_excess_frames():
    from gms_helpers.asset_types.visual import SpriteAsset

    with pytest.raises(ValidationError, match="4096"):
        SpriteAsset().create_yy_data("spr_test", "", frame_count=4097)


def test_c9_registration_collision_is_atomic_and_same_path_is_idempotent(tmp_path):
    root = project(tmp_path)
    original_path = "scripts/original/scr_test.yy"
    other_path = "scripts/other/scr_test.yy"
    for path in [original_path, other_path]:
        asset = root / path
        asset.parent.mkdir(parents=True)
        asset.write_text('{"name":"scr_test","parent":{"path":"game.yyp"}}')
    yyp = root / "game.yyp"
    yyp.write_text(json.dumps({"resources": [{"id": {"name": "scr_test", "path": original_path}}]}))
    before = yyp.read_bytes()
    with pytest.raises(ValidationError, match="already registered"):
        yyp_registry.register_assets(root, [other_path])
    assert yyp.read_bytes() == before
    result = yyp_registry.register_assets(root, [original_path])
    assert result["already_registered"] == [original_path]
    assert yyp.read_bytes() == before
