#!/usr/bin/env python3
"""Index a folder and report exact-byte duplicate files.

File lists live on disk as JSONL plus temp sort runs. There is no database,
and the whole tree is never held in memory.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeVar

SAMPLE_BYTES = 4096
READ_BYTES = 1024 * 1024
SORT_CHUNK = 8000
SKIP_DIRS = {".venv", ".git", "__pycache__"}


class Progress:
    """One-line status on stderr so long compares do not look hung."""

    def __init__(self, label: str, total: int | None = None) -> None:
        self.label = label
        self.total = total
        self.count = 0
        self._last = 0.0
        self._done = False
        self._tty = sys.stderr.isatty()

    def tick(self, n: int = 1) -> None:
        self.count += n
        now = time.monotonic()
        interval = 0.25 if self._tty else 2.0
        finished = self.total is not None and self.count >= self.total
        if self.count != n and not finished and now - self._last < interval:
            return
        self._last = now
        self._draw()

    def _draw(self) -> None:
        if self.total:
            msg = f"{self.label} {self.count}/{self.total}"
        else:
            msg = f"{self.label} {self.count}"
        if self._tty:
            print(f"\r{msg}   ", end="", file=sys.stderr, flush=True)
        else:
            print(msg, file=sys.stderr, flush=True)

    def done(self) -> None:
        if self._done:
            return
        self._done = True
        self._draw()
        if self._tty:
            print(file=sys.stderr, flush=True)

T = TypeVar("T")
KeyFn = Callable[[T], object]


@dataclass(slots=True)
class Record:
    size: int
    mtime: float
    dev: int
    ino: int
    path: str
    sample: str = ""
    digest: str = ""


def dumps_record(rec: Record) -> str:
    return json.dumps(
        [rec.size, rec.mtime, rec.dev, rec.ino, rec.path, rec.sample, rec.digest],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def loads_record(line: str) -> Record:
    size, mtime, dev, ino, path, sample, digest = json.loads(line)
    return Record(size, mtime, dev, ino, path, sample or "", digest or "")


def write_record(fp: IO[str], rec: Record) -> None:
    fp.write(dumps_record(rec))
    fp.write("\n")


def iter_records(path: Path) -> Iterator[Record]:
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                yield loads_record(line)


def write_records(path: Path, records: Iterable[Record]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for rec in records:
            write_record(fp, rec)


def count_records(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                count += 1
    return count


def first_record(path: Path) -> Record | None:
    for rec in iter_records(path):
        return rec
    return None


def two_records(path: Path) -> tuple[Record, Record] | None:
    it = iter_records(path)
    try:
        return next(it), next(it)
    except StopIteration:
        return None


def new_jsonl(tmpdir: Path, prefix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=tmpdir,
        prefix=prefix,
        suffix=".jsonl",
    )
    handle.close()
    return Path(handle.name)


def external_sort(src: Path, dest: Path, key: KeyFn[Record], tmpdir: Path) -> None:
    """Sort JSONL records using bounded-memory runs on disk."""
    run_paths: list[Path] = []
    chunk: list[Record] = []
    run_id = 0

    def flush() -> None:
        nonlocal run_id
        if not chunk:
            return
        chunk.sort(key=key)  # type: ignore[arg-type]
        run_path = tmpdir / f"run_{run_id}.jsonl"
        run_id += 1
        write_records(run_path, chunk)
        run_paths.append(run_path)
        chunk.clear()

    progress: Progress | None = None
    total = count_records(src)
    if total >= 500:
        progress = Progress("Sorting", total)
    for rec in iter_records(src):
        chunk.append(rec)
        if progress:
            progress.tick()
        if len(chunk) >= SORT_CHUNK:
            flush()
    flush()
    if progress:
        progress.done()

    if not run_paths:
        dest.write_text("", encoding="utf-8")
        return
    if len(run_paths) == 1:
        if dest.exists():
            dest.unlink()
        run_paths[0].replace(dest)
        return

    streams = [iter_records(path) for path in run_paths]
    with dest.open("w", encoding="utf-8") as out:
        for rec in heapq.merge(*streams, key=key):
            write_record(out, rec)
    for path in run_paths:
        path.unlink(missing_ok=True)


MAX_EXTENSION_LEN = 10


class ExtensionError(ValueError):
    """Invalid file-extension token."""


def parse_extension(token: str) -> str:
    """Return a normalized extension like '.mp4'. Raises ExtensionError if invalid."""
    from validate import InputError, parse_single_extension

    try:
        return parse_single_extension(token)
    except InputError as exc:
        raise ExtensionError(str(exc)) from exc


def normalize_extensions(raw: Iterable[str]) -> frozenset[str] | None:
    """Turn 'mp4', '.webm', '*.mkv' into {'.mp4', '.webm', '.mkv'}. Empty means all."""
    exts: set[str] = set()
    for item in raw:
        if not item.strip():
            continue
        exts.add(parse_extension(item))
    return frozenset(exts) if exts else None


def matches_extension(name: str, extensions: frozenset[str] | None) -> bool:
    if not extensions:
        return True
    return Path(name).suffix.lower() in extensions


def walk_files(
    root: Path,
    skip_paths: set[str],
    extensions: frozenset[str] | None = None,
) -> Iterator[os.DirEntry[str]]:
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            listing = os.scandir(current)
        except OSError:
            continue
        with listing:
            for entry in listing:
                try:
                    path = entry.path
                    if path in skip_paths:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in SKIP_DIRS:
                            continue
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        if matches_extension(entry.name, extensions):
                            yield entry
                except OSError:
                    continue


def scan_folder(
    root: Path,
    dest: Path,
    skip_paths: set[str],
    extensions: frozenset[str] | None = None,
) -> tuple[int, int]:
    """Write one record per regular file. Returns (files, errors)."""
    count = 0
    errors = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    progress = Progress("Scanning")
    with dest.open("w", encoding="utf-8") as fp:
        for entry in walk_files(root, skip_paths, extensions):
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                errors += 1
                continue
            write_record(
                fp,
                Record(
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    dev=stat.st_dev,
                    ino=stat.st_ino,
                    path=entry.path,
                ),
            )
            count += 1
            progress.tick()
    progress.done()
    return count, errors


def sample_digest(path: str, size: int) -> str:
    hasher = hashlib.blake2b()
    with open(path, "rb") as fp:
        hasher.update(fp.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            mid = max(0, (size // 2) - (SAMPLE_BYTES // 2))
            fp.seek(mid)
            hasher.update(fp.read(SAMPLE_BYTES))
            fp.seek(max(0, size - SAMPLE_BYTES))
            hasher.update(fp.read(SAMPLE_BYTES))
    return hasher.hexdigest()


def full_digest(path: str) -> str:
    hasher = hashlib.blake2b()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(READ_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def files_equal(left: str, right: str) -> bool:
    with open(left, "rb") as fa, open(right, "rb") as fb:
        while True:
            a = fa.read(READ_BYTES)
            b = fb.read(READ_BYTES)
            if a != b:
                return False
            if not a:
                return True


def map_records(
    src: Path,
    dest: Path,
    mapper: Callable[[Record], Record | None],
    label: str | None = None,
) -> int:
    count = 0
    progress = Progress(label, count_records(src)) if label else None
    with dest.open("w", encoding="utf-8") as fp:
        for rec in iter_records(src):
            mapped = mapper(rec)
            if mapped is None:
                continue
            write_record(fp, mapped)
            count += 1
            if progress:
                progress.tick()
    if progress:
        progress.done()
    return count


def collapse_hardlinks(src: Path, dest: Path, tmpdir: Path) -> int:
    """Keep one path per inode using an on-disk sort. Returns remaining count."""
    ordered = new_jsonl(tmpdir, "by_ino_")
    external_sort(src, ordered, key=lambda rec: (rec.dev, rec.ino, rec.path), tmpdir=tmpdir)
    count = 0
    previous: Record | None = None
    with dest.open("w", encoding="utf-8") as fp:
        for rec in iter_records(ordered):
            if (
                previous is not None
                and rec.ino
                and rec.dev == previous.dev
                and rec.ino == previous.ino
            ):
                continue
            write_record(fp, rec)
            previous = rec
            count += 1
    ordered.unlink(missing_ok=True)
    return count


def iter_colliding_keys(
    src: Path,
    key: KeyFn[Record],
    tmpdir: Path,
    prefix: str,
    label: str | None = None,
) -> Iterator[tuple[object, Path, int]]:
    """Yield on-disk groups for keys that appear more than once in a sorted file.

    Unique keys stay in a single in-memory record so 200k distinct sizes do not
    create 200k temp files.
    """
    first: Record | None = None
    current_key: object = None
    group_path: Path | None = None
    group_fp: IO[str] | None = None
    count = 0

    def flush() -> tuple[object, Path, int] | None:
        nonlocal group_fp, group_path, count, first
        result = None
        if count >= 2 and group_path is not None and group_fp is not None:
            group_fp.close()
            result = (current_key, group_path, count)
        elif group_fp is not None and group_path is not None:
            group_fp.close()
            group_path.unlink(missing_ok=True)
        group_fp = None
        group_path = None
        first = None
        count = 0
        return result

    progress: Progress | None = None
    if label:
        total = count_records(src)
        if total >= 500:
            progress = Progress(label, total)
    for rec in iter_records(src):
        if progress:
            progress.tick()
        rec_key = key(rec)
        if first is None:
            first = rec
            current_key = rec_key
            count = 1
            continue
        if rec_key == current_key:
            if group_fp is None:
                group_path = new_jsonl(tmpdir, prefix)
                group_fp = group_path.open("w", encoding="utf-8")
                write_record(group_fp, first)
            write_record(group_fp, rec)
            count += 1
            continue
        closed = flush()
        if closed is not None:
            yield closed
        first = rec
        current_key = rec_key
        count = 1

    closed = flush()
    if closed is not None:
        yield closed
    if progress:
        progress.done()


def confirm_pair_file(path: Path) -> Path | None:
    pair = two_records(path)
    if pair is None:
        return None
    left, right = pair
    try:
        if files_equal(left.path, right.path):
            return path
    except OSError:
        return None
    return None


def groups_from_hashes(src: Path, tmpdir: Path) -> Iterator[Path]:
    hashed = new_jsonl(tmpdir, "hashed_")

    def add_digest(rec: Record) -> Record | None:
        try:
            rec.digest = full_digest(rec.path)
        except OSError:
            return None
        return rec

    if map_records(src, hashed, add_digest, label="Hashing") < 2:
        hashed.unlink(missing_ok=True)
        return

    ordered = new_jsonl(tmpdir, "by_digest_")
    external_sort(hashed, ordered, key=lambda rec: rec.digest, tmpdir=tmpdir)
    hashed.unlink(missing_ok=True)
    for digest, group_path, count in iter_colliding_keys(
        ordered, lambda rec: rec.digest, tmpdir, "digestgrp_"
    ):
        if digest and count > 1:
            yield group_path
        else:
            group_path.unlink(missing_ok=True)
    ordered.unlink(missing_ok=True)


def confirm_unique_file(src: Path, size: int, tmpdir: Path) -> Iterator[Path]:
    count = count_records(src)
    if count < 2:
        return
    if size == 0:
        yield src
        return
    if count == 2 and size <= SAMPLE_BYTES * 3:
        matched = confirm_pair_file(src)
        if matched is not None:
            yield matched
        return
    if size <= SAMPLE_BYTES * 3:
        yield from groups_from_hashes(src, tmpdir)
        return

    sampled = new_jsonl(tmpdir, "sampled_")

    def add_sample(rec: Record) -> Record | None:
        try:
            rec.sample = sample_digest(rec.path, rec.size)
        except OSError:
            return None
        return rec

    if map_records(src, sampled, add_sample, label="Sampling") < 2:
        sampled.unlink(missing_ok=True)
        return

    ordered = new_jsonl(tmpdir, "by_sample_")
    external_sort(sampled, ordered, key=lambda rec: rec.sample, tmpdir=tmpdir)
    sampled.unlink(missing_ok=True)
    for sample, group_path, group_count in iter_colliding_keys(
        ordered, lambda rec: rec.sample, tmpdir, "samplegrp_"
    ):
        if not sample or group_count < 2:
            group_path.unlink(missing_ok=True)
            continue
        if group_count == 2:
            matched = confirm_pair_file(group_path)
            if matched is not None:
                yield matched
            else:
                group_path.unlink(missing_ok=True)
            continue
        yield from groups_from_hashes(group_path, tmpdir)
        group_path.unlink(missing_ok=True)
    ordered.unlink(missing_ok=True)


def find_duplicate_files(sorted_by_size: Path, tmpdir: Path) -> Iterator[Path]:
    for size, group_path, count in iter_colliding_keys(
        sorted_by_size, lambda rec: rec.size, tmpdir, "sizegrp_", label="Comparing"
    ):
        try:
            if count < 2:
                continue
            unique = new_jsonl(tmpdir, "unique_")
            if collapse_hardlinks(group_path, unique, tmpdir) < 2:
                unique.unlink(missing_ok=True)
                continue
            yield from confirm_unique_file(unique, int(size), tmpdir)
        finally:
            group_path.unlink(missing_ok=True)


def format_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def write_report(
    group_files: Iterable[Path],
    report_path: Path,
    scanned: int,
    errors: int,
    tmpdir: Path,
) -> tuple[int, int, int]:
    group_count = 0
    extra_copies = 0
    wasted = 0
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fp:
        for group_path in group_files:
            n = count_records(group_path)
            if n < 2:
                group_path.unlink(missing_ok=True)
                continue
            if n > SORT_CHUNK:
                ordered = new_jsonl(tmpdir, "grp_paths_")
                external_sort(
                    group_path, ordered, key=lambda rec: rec.path, tmpdir=tmpdir
                )
                group_path.unlink(missing_ok=True)
                group_path = ordered
                records: Iterable[Record] = iter_records(group_path)
            else:
                records = sorted(iter_records(group_path), key=lambda rec: rec.path)
                group_path.unlink(missing_ok=True)

            first = None
            extra = n - 1
            group_count += 1
            extra_copies += extra
            for rec in records:
                if first is None:
                    first = rec
                    wasted += rec.size * extra
                    header = (
                        f"## group {group_count}  size={rec.size}  "
                        f"copies={n}  wasted={rec.size * extra}"
                    )
                    print(header)
                    fp.write(header)
                    fp.write("\n")
                print(rec.path)
                fp.write(rec.path)
                fp.write("\n")
            print()
            fp.write("\n")
            if n > SORT_CHUNK:
                group_path.unlink(missing_ok=True)
        summary = (
            f"# scanned={scanned} errors={errors} groups={group_count} "
            f"extra_copies={extra_copies} wasted={wasted}"
        )
        fp.write(summary)
        fp.write("\n")
    return group_count, extra_copies, wasted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find exact-byte duplicate files with low memory."
    )
    parser.add_argument("folder", type=Path, help="Folder to scan recursively")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("dedupe-index.jsonl"),
        help="Where to write the on-disk file list (default: ./dedupe-index.jsonl)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("duplicates.txt"),
        help="Where to write the duplicate report (default: ./duplicates.txt)",
    )
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
    folder = args.folder.resolve()
    if not folder.is_dir():
        print(f"Not a folder: {folder}", file=sys.stderr)
        return 2

    index_path = args.index.resolve()
    report_path = args.report.resolve()
    skip_paths = {str(index_path), str(report_path)}
    try:
        extensions = normalize_extensions(args.ext)
    except ExtensionError as exc:
        print(f"Invalid --ext: {exc}", file=sys.stderr)
        return 2

    print(f"Scanning {folder}")
    if extensions:
        print(f"Types: {' '.join(sorted(extensions))}")
    scanned, errors = scan_folder(folder, index_path, skip_paths, extensions)
    print(f"Wrote file list ({scanned} files) to {index_path}")
    if errors:
        print(f"Skipped {errors} unreadable files", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="dedupe-") as raw_tmpdir:
        tmpdir = Path(raw_tmpdir)
        sorted_path = tmpdir / "by_size.jsonl"
        print("Sorting by size...")
        external_sort(index_path, sorted_path, key=lambda rec: rec.size, tmpdir=tmpdir)
        print("Comparing same-size candidates...")
        group_files = find_duplicate_files(sorted_path, tmpdir)
        group_count, extra, wasted = write_report(
            group_files, report_path, scanned, errors, tmpdir
        )

    print(f"Wrote report to {report_path}")
    print(
        f"Scanned {scanned} files, {group_count} duplicate groups, "
        f"{extra} extra copies, {format_bytes(wasted)} wasted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
