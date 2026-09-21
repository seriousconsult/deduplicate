#!/usr/bin/env python3
"""Move a file to the platform trash/recycle bin so it can be restored."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import platformutil


def wsl_to_windows_path(path: str) -> str | None:
    """Convert /mnt/c/foo to C:\\foo. Returns None if not a WSL drive path."""
    if not path.startswith("/mnt/") or len(path) < 7:
        return None
    drive = path[5]
    if not drive.isalpha() or path[6] != "/":
        return None
    rest = path[7:].replace("/", "\\")
    return f"{drive.upper()}:\\{rest}"


def _trash_windows(path: str) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.USHORT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete = 3
    fof_allowundo = 0x40
    fof_noconfirmation = 0x10
    fof_silent = 0x04
    fof_noerrorui = 0x400

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = fo_delete
    buf = ctypes.create_unicode_buffer(path + "\0")
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.fFlags = fof_allowundo | fof_noconfirmation | fof_silent | fof_noerrorui
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        raise OSError(result, f"Could not send to Recycle Bin: {path}")


def _trash_via_powershell(win_path: str) -> None:
    escaped = win_path.replace("'", "''")
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        f"'{escaped}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    )
    powershell = platformutil.windows_powershell() or "powershell.exe"
    subprocess.check_call(
        [powershell, "-NoProfile", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _trash_xdg(path: Path) -> None:
    trash = Path.home() / ".local" / "share" / "Trash"
    files_dir = trash / "files"
    info_dir = trash / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)

    dest = files_dir / path.name
    stem = path.stem
    suffix = path.suffix
    n = 1
    while dest.exists() or (info_dir / f"{dest.name}.trashinfo").exists():
        dest = files_dir / f"{stem} {n}{suffix}"
        n += 1

    resolved = path.resolve()
    info = info_dir / f"{dest.name}.trashinfo"
    info.write_text(
        "[Trash Info]\n"
        f"Path={quote(resolved.as_posix(), safe='/')}\n"
        f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n",
        encoding="utf-8",
    )
    shutil.move(str(resolved), str(dest))


def send_to_trash(path: str) -> None:
    """Move path to the trash. Raises OSError on failure."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(path)

    if platformutil.is_windows():
        _trash_windows(str(target.resolve()))
        return

    if platformutil.is_wsl():
        win_path = wsl_to_windows_path(str(target.resolve()))
        if win_path is not None and platformutil.windows_powershell():
            try:
                _trash_via_powershell(win_path)
                return
            except (OSError, subprocess.CalledProcessError):
                pass

    if shutil.which("gio"):
        try:
            subprocess.check_call(
                ["gio", "trash", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except subprocess.CalledProcessError:
            pass

    _trash_xdg(target)
