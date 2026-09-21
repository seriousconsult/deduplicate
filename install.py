#!/usr/bin/env python3
"""Create a local virtualenv and switch this terminal into it."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
DEBUG_LOG = ROOT / "debug-c522b0.log"


# #region agent log
def _agent_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "c522b0",
        "id": f"log_{int(time.time() * 1000)}_{hypothesis_id}",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data,
        "runId": os.environ.get("AGENT_RUN_ID", "pre-fix"),
        "hypothesisId": hypothesis_id,
    }
    with DEBUG_LOG.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload) + "\n")


# #endregion


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def running_in_project_venv() -> bool:
    if _path_is_under(Path(sys.executable), VENV):
        return True
    return Path(sys.prefix).resolve() == VENV.resolve()


def base_python() -> str:
    base = Path(sys.base_prefix)
    if sys.platform == "win32":
        candidate = base / "python.exe"
        if candidate.exists():
            return str(candidate)
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
    env["AGENT_RUN_ID"] = "post-fix"
    script = str(Path(__file__).resolve())
    # #region agent log
    _agent_log(
        "H1",
        "install.py:deactivate_and_reexec",
        "Re-exec with system Python",
        {
            "from_executable": sys.executable,
            "to_executable": py,
            "VIRTUAL_ENV_cleared": "VIRTUAL_ENV" not in env,
        },
    )
    # #endregion
    os.execve(py, [py, script, *sys.argv[1:]], env)


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def activate_script() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "Activate.ps1"
    return VENV / "bin" / "activate"


def remove_venv() -> None:
    if not VENV.exists():
        return
    print(f"Deleting {VENV}", flush=True)
    # #region agent log
    exe = Path(sys.executable)
    _agent_log(
        "H1",
        "install.py:remove_venv:before",
        "About to delete .venv",
        {
            "sys_executable": sys.executable,
            "exe_exists": exe.exists(),
            "exe_under_venv": str(exe).startswith(str(VENV)),
            "venv_exists": VENV.exists(),
        },
    )
    # #endregion
    if sys.platform == "win32":
        subprocess.check_call(["cmd", "/c", "rmdir", "/s", "/q", str(VENV)])
        return
    subprocess.check_call(["rm", "-rf", str(VENV)])
    # #region agent log
    _agent_log(
        "H4",
        "install.py:remove_venv:after",
        "Deleted .venv",
        {
            "sys_executable": sys.executable,
            "exe_exists": Path(sys.executable).exists(),
            "venv_exists": VENV.exists(),
        },
    )
    # #endregion


def create_venv() -> None:
    remove_venv()
    print(f"Creating new virtualenv at {VENV}", flush=True)
    # #region agent log
    _agent_log(
        "H3",
        "install.py:create_venv:before_call",
        "Calling python -m venv",
        {
            "sys_executable": sys.executable,
            "exe_exists": Path(sys.executable).exists(),
            "venv_exists": VENV.exists(),
        },
    )
    # #endregion
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
    py = venv_python()
    if not py.exists():
        raise SystemExit(f"Expected interpreter not found: {py}")
    packages = requirement_lines()
    if not packages:
        return
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def activate_venv() -> None:
    """Replace this process with an interactive shell that has .venv on PATH."""
    activate = activate_script()
    os.chdir(ROOT)
    if sys.platform == "win32":
        os.execvp(
            "powershell",
            [
                "powershell",
                "-NoExit",
                "-Command",
                f"Set-Location -LiteralPath '{ROOT}'; . '{activate}'; Write-Host '(.venv)'",
            ],
        )
    rc = VENV / ".activate_rc"
    rc.write_text(
        "if [ -f \"$HOME/.bashrc\" ]; then . \"$HOME/.bashrc\"; fi\n"
        f". {shlex.quote(str(activate))}\n"
        "printf '(.venv)\\n'\n",
        encoding="utf-8",
    )
    os.execvp("bash", ["bash", "--init-file", str(rc), "-i"])


def main() -> int:
    # #region agent log
    path_head = os.environ.get("PATH", "").split(os.pathsep)[:6]
    _agent_log(
        "H2",
        "install.py:main:start",
        "Interpreter and env at start",
        {
            "sys_executable": sys.executable,
            "exe_exists": Path(sys.executable).exists(),
            "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV"),
            "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            "prefix": sys.prefix,
            "base_prefix": getattr(sys, "base_prefix", ""),
            "path_head": path_head,
        },
    )
    # #endregion
    deactivate_and_reexec()
    try:
        create_venv()
    except Exception as exc:
        # #region agent log
        _agent_log(
            "H5",
            "install.py:main:create_failed",
            "venv creation failed",
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "sys_executable": sys.executable,
                "exe_exists": Path(sys.executable).exists(),
            },
        )
        # #endregion
        raise
    install_requirements()
    activate_venv()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
