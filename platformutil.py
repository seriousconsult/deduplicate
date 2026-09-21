"""Windows, WSL, and Linux helpers. No shell interpolation of user paths here."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    for source in (Path("/proc/sys/kernel/osrelease"), Path("/proc/version")):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if "microsoft" in text or "wsl" in text:
            return True
    return False


def venv_python(root: Path) -> Path:
    """Interpreter path this OS expects inside root/.venv."""
    if is_windows():
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def find_venv_python(root: Path) -> Path | None:
    """Return a venv interpreter built for this OS, or None."""
    expected = venv_python(root)
    if expected.exists():
        return expected
    if not is_windows():
        alt = root / ".venv" / "bin" / "python3"
        if alt.exists():
            return alt
    return None


def activate_script(root: Path) -> Path:
    if is_windows():
        return root / ".venv" / "Scripts" / "Activate.ps1"
    return root / ".venv" / "bin" / "activate"


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    if is_windows():
        try:
            subprocess.check_call(["cmd", "/c", "rmdir", "/s", "/q", str(path)])
            return
        except (OSError, subprocess.CalledProcessError):
            pass
    else:
        try:
            subprocess.check_call(["rm", "-rf", str(path)])
            return
        except (OSError, subprocess.CalledProcessError):
            pass
    shutil.rmtree(path, ignore_errors=True)


def exec_or_run(argv: list[str], env: dict[str, str] | None = None) -> None:
    """Replace this process, or run and exit if exec is unavailable."""
    executable = argv[0]
    try:
        os.execve(executable, argv, env if env is not None else os.environ)
    except (OSError, AttributeError):
        raise SystemExit(subprocess.call(argv, env=env))


def windows_powershell() -> str | None:
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None
