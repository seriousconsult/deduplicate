"""Strict checks for user-typed paths, extensions, and menu choices.

Nothing here is passed to a shell. Rejected input is treated as a typing
mistake, not executed.
"""

from __future__ import annotations

import re
from pathlib import Path

SHELL_CHARS = frozenset(';&|`$<>\n\r\x00')
COMMAND_WORDS = frozenset(
    {
        "alias",
        "bash",
        "bitsadmin",
        "cat",
        "certutil",
        "chmod",
        "chown",
        "cmd",
        "copy",
        "cscript",
        "curl",
        "del",
        "diskpart",
        "doas",
        "echo",
        "erase",
        "eval",
        "exec",
        "export",
        "fish",
        "format",
        "kill",
        "mkdir",
        "move",
        "msiexec",
        "net",
        "node",
        "perl",
        "pkill",
        "powershell",
        "printf",
        "pwsh",
        "py",
        "python",
        "python3",
        "rd",
        "reg",
        "rm",
        "rmdir",
        "robocopy",
        "ruby",
        "sc",
        "set",
        "sh",
        "start",
        "sudo",
        "wget",
        "wscript",
        "xcopy",
        "zsh",
    }
)
SCRIPT_SUFFIXES = frozenset({".exe", ".bat", ".cmd", ".ps1", ".sh", ".com", ".vbs", ".js"})
EXT_BODY = re.compile(r"^[a-z0-9]{1,10}$")
MENU_NUMBER = re.compile(r"^[1-9][0-9]*$")
PATH_EXTRA = frozenset("._-~/\\: ()[]',+@")


class InputError(ValueError):
    """User text was not a path, extension, or allowed choice."""


def _has_shell_chars(raw: str) -> bool:
    return any(ch in SHELL_CHARS for ch in raw)


def looks_like_command(raw: str) -> bool:
    if _has_shell_chars(raw):
        return True
    tokens = raw.split()
    if not tokens:
        return False
    first = Path(tokens[0]).name.lower()
    if any(first.endswith(suffix) for suffix in SCRIPT_SUFFIXES):
        return True
    return first in COMMAND_WORDS and len(tokens) > 1


def path_chars_ok(text: str) -> bool:
    if _has_shell_chars(text):
        return False
    for ch in text:
        if ch.isalnum() or ch in PATH_EXTRA or ch.isalpha():
            continue
        return False
    return True


def reject_if_command(raw: str, expect: str) -> None:
    if looks_like_command(raw):
        raise InputError(f"that looks like a command, not {expect}")


def parse_folder_choice(raw: str) -> str:
    """Return 'stay', 'parent', a menu number, or a path string."""
    text = raw.strip()
    if text != raw:
        text = text.strip()
    if "\x00" in raw or any(ord(ch) < 32 for ch in raw if ch not in "\t"):
        raise InputError("control characters are not allowed")
    if text == "":
        return ""
    if text == "..":
        return ".."
    if MENU_NUMBER.fullmatch(text):
        return text
    reject_if_command(text, "a folder path")
    if not path_chars_ok(text):
        raise InputError("only a folder path is allowed")
    return text


def parse_single_extension(raw: str) -> str:
    """One extension token such as mp4 or .webm. No lists or commands."""
    text = raw.strip()
    if text != raw.strip() or any(ord(ch) < 32 for ch in raw):
        raise InputError("control characters are not allowed")
    if not text:
        raise InputError("empty extension")
    reject_if_command(text, "a file extension")
    if any(ch.isspace() for ch in text) or "," in text:
        raise InputError("enter one extension, like mp4")
    token = text.lower()
    if token.startswith("*."):
        token = token[1:]
    body = token[1:] if token.startswith(".") else token
    if not EXT_BODY.fullmatch(body):
        raise InputError("use 1-10 letters or digits only")
    return "." + body


def parse_choice(raw: str, allowed: frozenset[str]) -> str:
    text = raw.strip()
    if any(ord(ch) < 32 for ch in raw):
        raise InputError("control characters are not allowed")
    reject_if_command(text, "a menu choice")
    key = text.upper()
    if key not in allowed:
        raise InputError(f"enter one of: {' '.join(sorted(allowed))}")
    return key


def require_existing_dir(text: str) -> Path:
    reject_if_command(text, "a folder path")
    expanded = str(Path(text).expanduser())
    if not path_chars_ok(text) and not path_chars_ok(expanded):
        raise InputError("only a folder path is allowed")
    path = Path(text).expanduser()
    if not path.is_dir():
        raise InputError(f"not a folder: {text}")
    return path.resolve()
