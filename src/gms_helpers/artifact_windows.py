"""Windows artifact paths pinned against reparse traversal and ancestor replacement."""

from __future__ import annotations

import contextlib
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


@contextlib.contextmanager
def _pinned(path: Path, *, directory: bool, delete_access: bool = False):
    # No FILE_SHARE_DELETE: a checked component cannot be renamed/replaced while
    # descendants are accessed. OPEN_REPARSE_POINT inspects the entry itself.
    # Resolve the Windows-only API when invoked; non-Windows type stubs omit it.
    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    handle = create(
        str(path),
        (0x80 if directory else 0x80000000) | (0x10000 if delete_access else 0),
        0x1 | 0x2,
        None,
        3,
        0x00200000 | 0x02000000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
    try:
        info = AttributeTagInfo()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory or kernel.GetFileType(handle) != 1:
            raise OSError("Artifact paths must be regular files/directories without symlinks or reparse points.")
        yield handle
    finally:
        kernel.CloseHandle(handle)


@contextlib.contextmanager
def pinned_parent(path: Path, *, create: bool = False):
    absolute = Path(os.path.abspath(path))
    if any(":" in part for part in absolute.parts[1:]):
        raise OSError("Artifact paths must not contain alternate data streams.")
    with contextlib.ExitStack() as stack:
        current = Path(absolute.anchor)
        stack.enter_context(_pinned(current, directory=True))
        for part in absolute.parts[1:-1]:
            current /= part
            if create:
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
            stack.enter_context(_pinned(current, directory=True))
        yield None, str(absolute)


@contextlib.contextmanager
def read_source(path: Path, *, delete_on_success: bool = False):
    import msvcrt

    with pinned_parent(path), _pinned(path, directory=False, delete_access=delete_on_success) as handle:
        # Duplicate ownership: fdopen closes its duplicate; _pinned owns the
        # original handle throughout the read and keeps the entry unreplaceable.
        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.DuplicateHandle.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel.DuplicateHandle.restype = wintypes.BOOL
        process = kernel.GetCurrentProcess()
        duplicate = wintypes.HANDLE()
        if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
            raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
        handle_value = duplicate.value
        if handle_value is None:
            raise OSError("Windows did not return a duplicate artifact handle.")
        try:
            descriptor = getattr(msvcrt, "open_osfhandle")(handle_value, os.O_RDONLY | getattr(os, "O_BINARY"))
        except BaseException:
            kernel.CloseHandle(handle_value)
            raise
        # open_osfhandle transfers HANDLE ownership to the CRT descriptor.
        # fdopen takes that ownership only after its wrapper is constructed.
        try:
            incoming = os.fdopen(descriptor, "rb")
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass  # A failing wrapper may already have closed the descriptor.
            raise
        with incoming:
            yield incoming
        if delete_on_success:
            # Delete this exact open file after publication, without releasing
            # its no-delete-sharing protection and re-resolving a leaf path.
            kernel.SetFileInformationByHandle.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            kernel.SetFileInformationByHandle.restype = wintypes.BOOL
            disposition = ctypes.c_ubyte(1)
            if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())


def clear_directory(path: Path) -> None:
    with pinned_parent(path, create=True):
        try:
            pinned = _pinned(path, directory=True)
            with pinned:
                for child in path.iterdir():
                    if (
                        child.is_dir()
                        and not child.is_symlink()
                        and not (getattr(child.lstat(), "st_file_attributes") & 0x400)
                    ):
                        clear_directory(child)
                    else:
                        # unlink/rmdir remove the entry, including junctions;
                        # neither recursively follows a reparse point.
                        if getattr(child.lstat(), "st_file_attributes") & 0x10:
                            child.rmdir()
                        else:
                            child.unlink()
        except FileNotFoundError:
            return
        # Release the target handle before removing its entry; all parent
        # handles remain pinned and rmdir can only remove an empty directory.
        path.rmdir()
