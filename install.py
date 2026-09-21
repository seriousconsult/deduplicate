#!/usr/bin/env python3
"""Create a local virtualenv and switch this terminal into it."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import platformutil

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def running_in_project_venv() -> bool:
    if _path_is_under(Path(sys.executable), VENV):
        return True
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def base_python() -> str:
    base = Path(sys.base_prefix)
    if platformutil.is_windows():
        for name in ("python.exe", "python3.exe"):
            candidate = base / name
            if candidate.exists():
                return str(candidate)
        raise SystemExit(f"Could not find system Python under {base}")
    for name in ("python3", "python"):
        candidate = base / "bin" / name
        if candidate.exists():
            return str(candidate)
    raise SystemExit(f"Could not find system Python under {base}")


def env_without_venv() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("VIRTUAL_ENV_PROMPT", None)
    drop = {
        str((VENV / "bin").resolve()),
        str((VENV / "Scripts").resolve()),
    }
    cleaned = []
    for part in env.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        resolved = str(Path(part).resolve()) if Path(part).exists() else part
        if resolved in drop:
            continue
        cleaned.append(part)
    env["PATH"] = os.pathsep.join(cleaned)
    return env


def deactivate_and_reexec() -> None:
    """If this process is the project venv, restart with system Python."""
    if not running_in_project_venv():
        return
    py = base_python()
    env = env_without_venv()
    script = str(Path(__file__).resolve())
    platformutil.exec_or_run([py, script, *sys.argv[1:]], env)


def remove_venv() -> None:
    if not VENV.exists():
        return
    print(f"Deleting {VENV}", flush=True)
    platformutil.remove_tree(VENV)


def create_venv() -> None:
    remove_venv()
    print(f"Creating new virtualenv at {VENV}", flush=True)
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])


def requirement_lines() -> list[str]:
    if not REQUIREMENTS.exists():
        return []
    lines = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def install_requirements() -> None:
    py = platformutil.venv_python(ROOT)
    if not py.exists():
        raise SystemExit(
            f"Expected interpreter not found: {py}\n"
            "This .venv was probably created on another OS. Run install again here."
        )
    packages = requirement_lines()
    if not packages:
        return
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def activate_venv() -> None:
    """Replace this process with an interactive shell that has .venv on PATH."""
    activate = platformutil.activate_script(ROOT)
    os.chdir(ROOT)
    if platformutil.is_windows():
        powershell = platformutil.windows_powershell()
        if not powershell:
            raise SystemExit("PowerShell not found. Activate with .venv\\Scripts\\Activate.ps1")
        root = str(ROOT).replace("'", "''")
        act = str(activate).replace("'", "''")
        platformutil.exec_or_run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-NoExit",
                "-Command",
                f"Set-Location -LiteralPath '{root}'; . '{act}'; Write-Host '(.venv)'",
            ]
        )
        return
    rc = VENV / ".activate_rc"
    rc.write_text(
        "if [ -f \"$HOME/.bashrc\" ]; then . \"$HOME/.bashrc\"; fi\n"
        f". {shlex.quote(str(activate))}\n"
        "printf '(.venv)\\n'\n",
        encoding="utf-8",
    )
    platformutil.exec_or_run(["bash", "--init-file", str(rc), "-i"])


def main() -> int:
    deactivate_and_reexec()
    create_venv()
    install_requirements()
    activate_venv()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
