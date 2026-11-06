"""Fail-closed Windows filesystem trust checks using native security descriptors."""

from pathlib import Path
import ctypes
from ctypes import wintypes


# Stable SIDs avoid trusting localized account names or a same-named local user.
SYSTEM_SIDS = {
    "S-1-5-18",
    "S-1-5-32-544",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
}
WRITE_MASK = 0x500D0156  # Generic write/all, delete, change ACL/owner, and file/directory writes.
REPLACE_MASK = 0x100D0040  # Replace an existing child or change/delete the ancestor.
READ_MASK = 0xA0000001  # Generic read/execute and file data/directory listing.


# OWNER RIGHTS grants only to the object's owner, which must already be trusted.
# Python's mkdir(mode=0o700) on Windows creates exactly SYSTEM, Administrators and OWNER RIGHTS.
OWNER_RIGHTS_SID = "S-1-3-4"


def _descriptor_issue(owner, entries, current_sid, *, private=False, ancestor=False):
    trusted = SYSTEM_SIDS | {current_sid}
    if owner not in trusted:
        return "filesystem owner is not trusted"
    trusted = trusted | {OWNER_RIGHTS_SID}
    if entries is None:
        return "filesystem has an unrestricted DACL"
    forbidden = REPLACE_MASK if ancestor else WRITE_MASK | (READ_MASK if private else 0)
    for kind, flags, mask, sid in entries:
        if flags & 0x08 or kind == 1:  # Inherit-only and deny ACEs do not grant access here.
            continue
        if kind != 0:
            return "filesystem DACL contains an unsupported access entry"
        if sid not in trusted and mask & forbidden:
            return "filesystem DACL grants access to another account"
    return None


def _api():
    loader = getattr(ctypes, "WinDLL")
    security = loader("advapi32", use_last_error=True)
    kernel = loader("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    pointer_out = ctypes.POINTER(pointer)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, pointer_out]
    security.GetTokenInformation.argtypes = [
        pointer,
        ctypes.c_int,
        pointer,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        pointer_out,
        pointer_out,
        pointer_out,
        pointer_out,
        pointer_out,
    ]
    security.GetNamedSecurityInfoW.restype = wintypes.DWORD
    security.GetAce.argtypes = [pointer, wintypes.DWORD, pointer_out]
    security.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]

    def sid_string(sid):
        value = wintypes.LPWSTR()
        if not sid or not security.ConvertSidToStringSidW(sid, ctypes.byref(value)):
            raise OSError("Cannot read Windows security identifier")
        try:
            return value.value
        finally:
            kernel.LocalFree(value)

    return security, kernel, sid_string


def _current_sid(security, kernel, sid_string):
    pointer = ctypes.c_void_p
    token = pointer()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError("Cannot query Windows process identity")
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            raise OSError("Cannot query Windows process identity")
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)):
            raise OSError("Cannot query Windows process identity")
        return sid_string(pointer.from_buffer(buffer))
    finally:
        kernel.CloseHandle(token)


def _read_descriptor(path):
    security, kernel, sid_string = _api()
    current_sid = _current_sid(security, kernel, sid_string)
    pointer = ctypes.c_void_p
    owner, dacl, descriptor = pointer(), pointer(), pointer()
    if security.GetNamedSecurityInfoW(
        str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor)
    ):
        raise OSError("Cannot read Windows filesystem security")
    try:
        owner_sid = sid_string(owner)
        entries = None
        if dacl.value:
            # ACL.AceCount is a WORD at byte offset 4.
            count = ctypes.c_uint16.from_address(dacl.value + 4).value
            entries = []
            for index in range(count):
                ace = pointer()
                if not security.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                    raise OSError("Cannot read Windows access entry")
                header = ctypes.string_at(ace, 4)
                kind, flags = header[:2]
                if kind != 0 or flags & 0x08:
                    entries.append((kind, flags, 0, ""))
                    continue
                if int.from_bytes(header[2:], "little") < 16:
                    raise OSError("Invalid Windows access entry")
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                entries.append((kind, flags, mask, sid_string(pointer(ace.value + 8))))
        return owner_sid, entries, current_sid
    finally:
        kernel.LocalFree(descriptor)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def create_private_directory(path: Path) -> None:
    """Create a directory whose protected DACL admits only this user and the system accounts.

    Windows ignores mkdir's mode, so a plain mkdir inherits whatever its parent grants.
    An existing directory is left unchanged for the caller's trust checks.
    """
    security, kernel, sid_string = _api()
    current_sid = _current_sid(security, kernel, sid_string)
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
    ]
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_SecurityAttributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    # P blocks inherited entries; OICI passes the same grants to new children.
    sddl = "D:P" + "".join(f"(A;OICI;FA;;;{sid})" for sid in (current_sid, "SY", "BA"))
    descriptor = ctypes.c_void_p()
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError("Cannot build a private Windows security descriptor")
    try:
        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor.value, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            error = getattr(ctypes, "get_last_error")()
            if error != 183:  # ERROR_ALREADY_EXISTS
                raise OSError(error, "Cannot create private directory", str(path))
    finally:
        kernel.LocalFree(descriptor)


def windows_path_trust_issue(path: Path, *, private=False, ancestor=False) -> str | None:
    try:
        return _descriptor_issue(*_read_descriptor(path), private=private, ancestor=ancestor)
    except (AttributeError, OSError, ValueError):
        return "Windows filesystem security could not be verified"
