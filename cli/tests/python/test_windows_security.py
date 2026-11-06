"""Access-control regression tests, including native Windows integration."""

import os
import subprocess
import ctypes
from types import SimpleNamespace

import pytest

from gms_helpers import windows_security as security
from gms_helpers.path_safety import private_directory


USER = "S-1-5-21-100-200-300-1001"
OTHER = "S-1-5-21-100-200-300-1002"


@pytest.mark.parametrize("owner", [USER, *security.SYSTEM_SIDS])
def test_private_current_user_and_system_access(owner):
    entries = [(0, 0, 0x1F01FF, sid) for sid in security.SYSTEM_SIDS | {USER}]
    assert security._descriptor_issue(owner, entries, USER, private=True) is None


@pytest.mark.parametrize("sid", [OTHER, "S-1-1-0", "S-1-5-11", "S-1-5-32-545"])
@pytest.mark.parametrize("access", [0x2, 0x4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000])
def test_untrusted_write_grants_are_rejected(sid, access):
    assert security._descriptor_issue(USER, [(0, 0, access, sid)], USER)


def test_private_reads_and_ancestor_replacement_have_distinct_boundaries():
    read = [(0, 0, 0x120089, OTHER)]
    assert security._descriptor_issue(USER, read, USER) is None
    assert security._descriptor_issue(USER, read, USER, private=True)
    assert security._descriptor_issue(USER, [(0, 0, 4, OTHER)], USER, ancestor=True) is None
    assert security._descriptor_issue(USER, [(0, 0, 0x40, OTHER)], USER, ancestor=True)


def test_owner_rights_is_trusted_only_through_a_trusted_owner():
    python_private = [(0, 3, 0x1F01FF, sid) for sid in ("S-1-5-18", "S-1-5-32-544", security.OWNER_RIGHTS_SID)]
    assert security._descriptor_issue("S-1-5-32-544", python_private, USER, private=True) is None
    assert security._descriptor_issue(OTHER, python_private, USER)


def test_deny_inherit_only_unknown_and_null_acl_handling():
    assert security._descriptor_issue(USER, [(1, 0, 0x1F01FF, OTHER), (0, 8, 0x1F01FF, OTHER)], USER) is None
    assert security._descriptor_issue(USER, [(9, 0, 0, "")], USER)
    assert security._descriptor_issue(USER, None, USER)
    assert security._descriptor_issue(OTHER, [], USER)


@pytest.mark.parametrize("error", [OSError, ValueError, AttributeError])
def test_unavailable_security_descriptor_fails_closed(monkeypatch, tmp_path, error):
    def unavailable(_path):
        raise error("unavailable")

    monkeypatch.setattr(security, "_read_descriptor", unavailable)
    assert "could not be verified" in security.windows_path_trust_issue(tmp_path)


def test_descriptor_policy_is_used_for_each_requested_path(monkeypatch, tmp_path):
    monkeypatch.setattr(security, "_read_descriptor", lambda path: (USER, [(0, 0, 1, OTHER)], USER))
    assert security.windows_path_trust_issue(tmp_path) is None
    assert security.windows_path_trust_issue(tmp_path, private=True)


@pytest.mark.parametrize("failure", ["", "open", "size", "token", "descriptor", "ace", "short", "sid"])
def test_native_descriptor_buffer_handling_and_cleanup(monkeypatch, tmp_path, failure):
    """Exercise native buffer ownership and parsing without relying on the host OS."""
    identity = ctypes.create_string_buffer(16)
    acl = ctypes.create_string_buffer(bytes([2, 0, 8, 0, 3, 0, 0, 0]))
    allow = ctypes.create_string_buffer(bytes([0, 0, 16 if failure != "short" else 8, 0, 2, 0, 0, 0]) + b"\0" * 8)
    deny = ctypes.create_string_buffer(bytes([1, 0, 16, 0]) + b"\0" * 12)
    inherited = ctypes.create_string_buffer(bytes([0, 8, 16, 0]) + b"\0" * 12)
    aces = [allow, deny, inherited]
    closed, freed = [], []

    class Function:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    def open_token(_process, _rights, output):
        output._obj.value = 7
        return failure != "open"

    def token_info(_token, _kind, buffer, _length, needed):
        needed._obj.value = 0 if failure == "size" else 16
        if buffer is None:
            return False
        ctypes.c_void_p.from_buffer(buffer).value = ctypes.addressof(identity)
        return failure != "token"

    def descriptor(_path, _kind, _flags, owner, _group, dacl, _sacl, output):
        owner._obj.value = ctypes.addressof(identity)
        dacl._obj.value = ctypes.addressof(acl)
        output._obj.value = 99
        return 5 if failure == "descriptor" else 0

    def get_ace(_acl, index, output):
        output._obj.value = ctypes.addressof(aces[index])
        return failure != "ace"

    def sid_string(_sid, output):
        output._obj.value = USER
        return failure != "sid"

    api = SimpleNamespace(
        **{
            name: Function(function)
            for name, function in {
                "OpenProcessToken": open_token,
                "GetTokenInformation": token_info,
                "GetNamedSecurityInfoW": descriptor,
                "GetAce": get_ace,
                "ConvertSidToStringSidW": sid_string,
            }.items()
        }
    )
    kernel = SimpleNamespace(
        GetCurrentProcess=Function(lambda: 3),
        CloseHandle=Function(lambda handle: closed.append(handle.value)),
        LocalFree=Function(lambda pointer: freed.append(pointer.value)),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: api if name == "advapi32" else kernel, raising=False)
    if failure:
        with pytest.raises(OSError):
            security._read_descriptor(tmp_path)
    else:
        owner, entries, current = security._read_descriptor(tmp_path)
        assert owner == current == USER
        assert entries == [(0, 0, 2, USER), (1, 0, 0, ""), (0, 8, 0, "")]
    assert closed == ([] if failure == "open" else [7])
    if failure in {"", "ace", "short"}:
        assert 99 in freed


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows filesystem ACLs")
def test_native_private_directory_and_untrusted_runtime_acl(tmp_path):
    from gms_helpers.runtime_manager import runtime_trust_issue
    from gms_mcp.server.subprocess_runner import _windows_system_executable

    private = private_directory(tmp_path / "private")
    assert security.windows_path_trust_issue(private, private=True) is None
    runtime = private / "runtime-example"
    igor = runtime / "bin" / "Igor.exe"
    igor.parent.mkdir(parents=True)
    igor.write_bytes(b"fixture")
    assert runtime_trust_issue(runtime, igor) is None
    subprocess.run([_windows_system_executable("icacls.exe"), str(igor), "/grant", "*S-1-1-0:(W)"], check=True)
    assert runtime_trust_issue(runtime, igor)


@pytest.mark.parametrize("failure", ["", "exists", "sddl", "create"])
def test_private_directory_creation_uses_protected_owner_only_dacl(monkeypatch, tmp_path, failure):
    calls, freed = [], []

    def convert(sddl, revision, output, _size):
        calls.append(("sddl", sddl, revision))
        output._obj.value = 42
        return failure != "sddl"

    def create(path, attributes):
        calls.append(("create", path, attributes._obj.lpSecurityDescriptor))
        return failure not in {"exists", "create"}

    class Function:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    api = SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=Function(convert))
    kernel = SimpleNamespace(CreateDirectoryW=Function(create), LocalFree=Function(lambda p: freed.append(p.value)))
    monkeypatch.setattr(security, "_api", lambda: (api, kernel, None))
    monkeypatch.setattr(security, "_current_sid", lambda *_args: USER)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 183 if failure == "exists" else 5, raising=False)
    target = tmp_path / "private"
    if failure in {"sddl", "create"}:
        with pytest.raises(OSError):
            security.create_private_directory(target)
    else:
        security.create_private_directory(target)
    assert calls[0] == ("sddl", f"D:P(A;OICI;FA;;;{USER})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1)
    if failure != "sddl":
        assert calls[1] == ("create", str(target), 42)
        assert freed == [42]


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows filesystem ACLs")
def test_native_private_directories_under_home_and_temp_are_trusted(tmp_path):
    import tempfile
    from pathlib import Path

    for base in (Path.home(), Path(tempfile.gettempdir()), tmp_path):
        for ancestor in [base, *base.parents]:
            issue = security.windows_path_trust_issue(ancestor, ancestor=True)
            assert issue is None, (str(ancestor), issue, security._read_descriptor(ancestor))
    for base in (tmp_path / "nested" / "private", Path(tempfile.mkdtemp(prefix="gms-mcp-test-")) / "private"):
        created = private_directory(base)
        for path in (created, created.parent):
            issue = security.windows_path_trust_issue(path, private=True)
            assert issue is None, (str(path), issue, security._read_descriptor(path))
        assert private_directory(base) == created
