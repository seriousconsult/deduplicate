#!/usr/bin/env python3
"""Prompt for two folders, show exact-byte copies, and trash one side if asked."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import index as indexer
import trash as trashcan
import validate


def is_under(path: str, folder: Path) -> bool:
    try:
        Path(path).resolve().relative_to(folder)
        return True
    except ValueError:
        return False


def list_subdirs(current: Path) -> list[Path]:
    dirs: list[Path] = []
    try:
        with os.scandir(current) as listing:
            for entry in listing:
                try:
                    if (
                        entry.is_dir(follow_symlinks=False)
                        and not entry.name.startswith(".")
                        and entry.name not in indexer.SKIP_DIRS
                    ):
                        dirs.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    dirs.sort(key=lambda p: p.name.lower())
    return dirs


def pick_folder(title: str, start: Path) -> Path:
    current = start.resolve()
    print()
    print(title)
    while True:
        print()
        print(f"Current: {current}")
        children = list_subdirs(current)
        print("  [Enter] use this folder")
        if current.parent != current:
            print("  [..]    parent folder")
        shown = children[:50]
        for i, child in enumerate(shown, start=1):
            print(f"  [{i}]    {child.name}")
        if len(children) > 50:
            print(f"  ... {len(children) - 50} more; type a name or path")
        raw = input("Path, number, .., or Enter: ")
        try:
            choice = validate.parse_folder_choice(raw)
        except validate.InputError as exc:
            print(f"Rejected: {exc}")
            continue
        if choice == "":
            if current.is_dir():
                return current
            print("Not a folder.")
            continue
        if choice == "..":
            current = current.parent
            continue
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(shown):
                current = shown[n - 1]
                continue
            print("Invalid number.")
            continue
        nested = current / choice
        if not Path(choice).is_absolute() and nested.is_dir():
            current = nested.resolve()
            continue
        try:
            current = validate.require_existing_dir(choice)
        except validate.InputError as exc:
            print(f"Rejected: {exc}")


def concat_indexes(parts: list[Path], dest: Path) -> None:
    with dest.open("w", encoding="utf-8") as out:
        for part in parts:
            with part.open("r", encoding="utf-8") as inp:
                for line in inp:
                    if line.strip():
                        out.write(line)


def pick_extensions() -> frozenset[str] | None:
    print()
    print("File types: enter one extension at a time (mp4, webm).")
    print("Press Enter with nothing typed to finish. None selected = all files.")
    chosen: list[str] = []
    while True:
        if chosen:
            print(f"Selected: {' '.join(chosen)}")
        raw = input("Extension: ")
        if raw.strip() == "":
            break
        try:
            ext = indexer.parse_extension(raw)
        except indexer.ExtensionError as exc:
            print(f"Rejected: {exc}")
            continue
        if ext not in chosen:
            chosen.append(ext)
    if not chosen:
        print("Types: all")
        return None
    print(f"Types: {' '.join(chosen)}")
    return frozenset(chosen)


PREVIEW_LIMIT = 20
FULL_LIST_MAX = 50


@dataclass(slots=True)
class SideList:
    path: Path
    count: int = 0
    nbytes: int = 0


def _write_side(fp, rec: indexer.Record, side: SideList) -> None:
    fp.write(json.dumps(rec.path))
    fp.write("\n")
    side.count += 1
    side.nbytes += rec.size


def show_matches(
    group_files,
    folder_a: Path,
    folder_b: Path,
    tmpdir: Path,
) -> tuple[int, SideList, SideList]:
    side_a = SideList(tmpdir / "side_a.jsonl")
    side_b = SideList(tmpdir / "side_b.jsonl")
    matches_path = tmpdir / "matches.jsonl"
    matches = 0
    match_bytes = 0
    with (
        side_a.path.open("w", encoding="utf-8") as fa,
        side_b.path.open("w", encoding="utf-8") as fb,
        matches_path.open("w", encoding="utf-8") as fm,
    ):
        for group_path in group_files:
            recs = list(indexer.iter_records(group_path))
            group_path.unlink(missing_ok=True)
            in_a = [rec for rec in recs if is_under(rec.path, folder_a)]
            in_b = [rec for rec in recs if is_under(rec.path, folder_b)]
            if not in_a or not in_b:
                continue
            matches += 1
            size = recs[0].size
            match_bytes += size
            a_paths = []
            b_paths = []
            for rec in sorted(in_a, key=lambda r: r.path):
                a_paths.append(rec.path)
                _write_side(fa, rec, side_a)
            for rec in sorted(in_b, key=lambda r: r.path):
                b_paths.append(rec.path)
                _write_side(fb, rec, side_b)
            fm.write(json.dumps({"size": size, "a": a_paths, "b": b_paths}))
            fm.write("\n")

    print()
    print(f"{matches} matches, {indexer.format_bytes(match_bytes)}")
    print()
    show_limit = PREVIEW_LIMIT if matches > FULL_LIST_MAX else matches
    n = 0
    with matches_path.open("r", encoding="utf-8") as fm:
        for line in fm:
            if not line.strip():
                continue
            n += 1
            if n > show_limit:
                break
            item = json.loads(line)
            print(f"{n}  {indexer.format_bytes(item['size'])}")
            for path in item["a"]:
                print(f"   A  {path}")
            for path in item["b"]:
                print(f"   B  {path}")
            print()
    leftover = matches - show_limit
    if leftover > 0:
        print(f"... {leftover} more")
        print()
    return matches, side_a, side_b


def prompt_side(folder_a: Path, folder_b: Path, side_a: SideList, side_b: SideList) -> str:
    print(f"A = {side_a.count} files, {indexer.format_bytes(side_a.nbytes)} under {folder_a}")
    print(f"B = {side_b.count} files, {indexer.format_bytes(side_b.nbytes)} under {folder_b}")
    while True:
        raw = input("Move matching copies to the trash from A, B, or keep all? [A/B/K] ")
        try:
            return validate.parse_choice(raw, frozenset({"A", "B", "K"}))
        except validate.InputError as exc:
            print(f"Rejected: {exc}")


def confirm_trash(choice: str, folder: Path, side: SideList) -> bool:
    print(
        f"This will move {side.count} files "
        f"({indexer.format_bytes(side.nbytes)}) from {folder} to the trash."
    )
    while True:
        confirm = input("Type TRASH to confirm, or Enter to cancel: ")
        if confirm.strip() == "":
            return False
        try:
            return validate.parse_choice(confirm, frozenset({"TRASH"})) == "TRASH"
        except validate.InputError as exc:
            print(f"Rejected: {exc}")


def trash_listed(list_path: Path) -> tuple[int, int]:
    ok = 0
    failed = 0
    total = 0
    with list_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                total += 1
    progress = indexer.Progress("Moving to trash", total) if total else None
    with list_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            path = json.loads(line)
            try:
                trashcan.send_to_trash(path)
                ok += 1
            except OSError as exc:
                print(f"Failed {path}: {exc}", file=sys.stderr)
                failed += 1
            if progress:
                progress.tick()
    if progress:
        progress.done()
    return ok, failed


def keep_record(recs: list[indexer.Record]) -> indexer.Record:
    """Newest mtime wins; same mtime keeps the first name alphabetically."""
    return min(recs, key=lambda rec: (-rec.mtime, rec.path))


def show_same_folder_matches(
    group_files,
    tmpdir: Path,
) -> tuple[int, SideList]:
    extras = SideList(tmpdir / "extras.jsonl")
    matches_path = tmpdir / "matches.jsonl"
    matches = 0
    match_bytes = 0
    with extras.path.open("w", encoding="utf-8") as fe, matches_path.open(
        "w", encoding="utf-8"
    ) as fm:
        for group_path in group_files:
            recs = list(indexer.iter_records(group_path))
            group_path.unlink(missing_ok=True)
            if len(recs) < 2:
                continue
            matches += 1
            size = recs[0].size
            match_bytes += size
            kept = keep_record(recs)
            extras_recs = [rec for rec in recs if rec.path != kept.path]
            extras_recs.sort(key=lambda rec: rec.path)
            for rec in extras_recs:
                _write_side(fe, rec, extras)
            fm.write(
                json.dumps(
                    {
                        "size": size,
                        "keep": kept.path,
                        "extras": [rec.path for rec in extras_recs],
                    }
                )
            )
            fm.write("\n")

    print()
    print(f"{matches} matches, {indexer.format_bytes(match_bytes)}")
    print()
    show_limit = PREVIEW_LIMIT if matches > FULL_LIST_MAX else matches
    n = 0
    with matches_path.open("r", encoding="utf-8") as fm:
        for line in fm:
            if not line.strip():
                continue
            n += 1
            if n > show_limit:
                break
            item = json.loads(line)
            print(f"{n}  {indexer.format_bytes(item['size'])}")
            print(f"   keep   {item['keep']}")
            for path in item["extras"]:
                print(f"   extra  {path}")
            print()
    leftover = matches - show_limit
    if leftover > 0:
        print(f"... {leftover} more")
        print()
    return matches, extras


def prompt_trash_extras(folder: Path, extras: SideList) -> str:
    print(
        f"Extras = {extras.count} files, {indexer.format_bytes(extras.nbytes)} under {folder}"
    )
    while True:
        raw = input("Move extra copies to the trash? [T/K] ")
        try:
            return validate.parse_choice(raw, frozenset({"T", "K"}))
        except validate.InputError as exc:
            print(f"Rejected: {exc}")


def compare_same_folder(folder: Path, extensions: frozenset[str] | None) -> int:
    print(f"Indexing {folder}")
    if extensions:
        print(f"Types: {' '.join(sorted(extensions))}")

    with tempfile.TemporaryDirectory(prefix="dedupe-same-") as raw_tmpdir:
        tmpdir = Path(raw_tmpdir)
        index_path = tmpdir / "files.jsonl"
        scanned, errors = indexer.scan_folder(folder, index_path, set(), extensions)
        print(f"{scanned} files")
        if errors:
            print(f"Skipped unreadable files: {errors}", file=sys.stderr)

        sorted_path = tmpdir / "by_size.jsonl"
        print("Comparing files in this folder...")
        indexer.external_sort(
            index_path, sorted_path, key=lambda rec: rec.size, tmpdir=tmpdir
        )
        group_files = indexer.find_duplicate_files(sorted_path, tmpdir)
        matches, extras = show_same_folder_matches(group_files, tmpdir)
        if matches == 0:
            return 0

        choice = prompt_trash_extras(folder, extras)
        if choice == "K":
            print("Kept all files.")
            return 0
        if not confirm_trash(choice, folder, extras):
            print("Cancelled.")
            return 0
        ok, failed = trash_listed(extras.path)
        print(f"Moved {ok} extra files to the trash.")
        if failed:
            print(f"Failed to move {failed} files.", file=sys.stderr)
            return 1
    return 0


def compare_folders(
    folder_a: Path,
    folder_b: Path,
    extensions: frozenset[str] | None,
) -> int:
    if folder_a == folder_b:
        return compare_same_folder(folder_a, extensions)

    print(f"Indexing A: {folder_a}")
    print(f"Indexing B: {folder_b}")
    if extensions:
        print(f"Types: {' '.join(sorted(extensions))}")

    with tempfile.TemporaryDirectory(prefix="dedupe-compare-") as raw_tmpdir:
        tmpdir = Path(raw_tmpdir)
        index_a = tmpdir / "a.jsonl"
        index_b = tmpdir / "b.jsonl"
        scanned_a, errors_a = indexer.scan_folder(folder_a, index_a, set(), extensions)
        scanned_b, errors_b = indexer.scan_folder(folder_b, index_b, set(), extensions)
        print(f"A: {scanned_a} files")
        print(f"B: {scanned_b} files")
        if errors_a or errors_b:
            print(
                f"Skipped unreadable files: A={errors_a} B={errors_b}",
                file=sys.stderr,
            )

        combined = tmpdir / "both.jsonl"
        concat_indexes([index_a, index_b], combined)
        sorted_path = tmpdir / "by_size.jsonl"
        print("Comparing across folders...")
        indexer.external_sort(
            combined, sorted_path, key=lambda rec: rec.size, tmpdir=tmpdir
        )
        group_files = indexer.find_duplicate_files(sorted_path, tmpdir)
        matches, side_a, side_b = show_matches(
            group_files, folder_a, folder_b, tmpdir
        )
        if matches == 0:
            return 0

        choice = prompt_side(folder_a, folder_b, side_a, side_b)
        if choice == "K":
            print("Kept all files.")
            return 0
        folder = folder_a if choice == "A" else folder_b
        side = side_a if choice == "A" else side_b
        if not confirm_trash(choice, folder, side):
            print("Cancelled.")
            return 0
        ok, failed = trash_listed(side.path)
        print(f"Moved {ok} files to the trash.")
        if failed:
            print(f"Failed to move {failed} files.", file=sys.stderr)
            return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select two folders and find exact-byte copies between them."
    )
    parser.add_argument("folder_a", type=Path, nargs="?", help="First folder")
    parser.add_argument("folder_b", type=Path, nargs="?", help="Second folder")
    parser.add_argument(
        "--ext",
        action="append",
        default=[],
        metavar="EXT",
        help="Only include this extension (repeatable). Example: --ext mp4 --ext webm",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = Path.cwd()
    if args.folder_a is None:
        folder_a = pick_folder("Select first folder", start)
    else:
        try:
            folder_a = validate.require_existing_dir(str(args.folder_a))
        except validate.InputError as exc:
            print(f"Rejected folder A: {exc}", file=sys.stderr)
            return 2
    if args.folder_b is None:
        folder_b = pick_folder("Select second folder", folder_a.parent)
    else:
        try:
            folder_b = validate.require_existing_dir(str(args.folder_b))
        except validate.InputError as exc:
            print(f"Rejected folder B: {exc}", file=sys.stderr)
            return 2

    if args.ext:
        try:
            extensions = indexer.normalize_extensions(args.ext)
        except indexer.ExtensionError as exc:
            print(f"Invalid --ext: {exc}", file=sys.stderr)
            return 2
    else:
        extensions = pick_extensions()

    print()
    print(f"A = {folder_a}")
    print(f"B = {folder_b}")
    return compare_folders(folder_a, folder_b, extensions)


if __name__ == "__main__":
    raise SystemExit(main())
