from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import index
import run


def duplicate_groups(
    folder: Path,
    extensions: frozenset[str] | None = None,
) -> list[list[str]]:
    with tempfile.TemporaryDirectory() as raw_tmpdir:
        tmpdir = Path(raw_tmpdir)
        index_path = tmpdir / "files.jsonl"
        sorted_path = tmpdir / "by_size.jsonl"
        with redirect_stderr(StringIO()):
            index.scan_folder(folder, index_path, set(), extensions)
            index.external_sort(
                index_path, sorted_path, key=lambda rec: rec.size, tmpdir=tmpdir
            )

        groups: list[list[str]] = []
        with redirect_stderr(StringIO()):
            for group_path in index.find_duplicate_files(sorted_path, tmpdir):
                groups.append(
                    sorted(
                        Path(rec.path).name for rec in index.iter_records(group_path)
                    )
                )
                group_path.unlink(missing_ok=True)
        return groups


class DuplicateDetectionTests(unittest.TestCase):
    def test_finds_exact_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")
            (root / "c.txt").write_bytes(b"different")

            self.assertEqual(duplicate_groups(root), [["a.txt", "b.txt"]])

    def test_same_size_different_content_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "a.bin").write_bytes(b"abc")
            (root / "b.bin").write_bytes(b"abd")

            self.assertEqual(duplicate_groups(root), [])

    def test_zero_byte_duplicates_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "empty-a").write_bytes(b"")
            (root / "empty-b").write_bytes(b"")

            self.assertEqual(duplicate_groups(root), [["empty-a", "empty-b"]])

    def test_hardlinks_are_not_reported_as_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            original = root / "original.bin"
            linked = root / "linked.bin"
            original.write_bytes(b"same inode")
            try:
                os.link(original, linked)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")

            self.assertEqual(duplicate_groups(root), [])

    def test_scan_is_nonrecursive_and_can_filter_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            nested = root / "nested"
            nested.mkdir()
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")
            (root / "a.bin").write_bytes(b"same")
            (nested / "nested.txt").write_bytes(b"same")

            self.assertEqual(
                duplicate_groups(root, frozenset({".txt"})), [["a.txt", "b.txt"]]
            )


class ReportTests(unittest.TestCase):
    def test_write_report_can_be_silent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")

            with tempfile.TemporaryDirectory() as raw_tmpdir:
                tmpdir = Path(raw_tmpdir)
                index_path = tmpdir / "files.jsonl"
                sorted_path = tmpdir / "by_size.jsonl"
                report_path = tmpdir / "duplicates.txt"
                with redirect_stderr(StringIO()):
                    scanned, errors = index.scan_folder(root, index_path, set())
                    index.external_sort(
                        index_path, sorted_path, key=lambda rec: rec.size, tmpdir=tmpdir
                    )

                    stats = index.write_report(
                        index.find_duplicate_files(sorted_path, tmpdir),
                        report_path,
                        scanned,
                        errors,
                        tmpdir,
                        echo=None,
                    )

                self.assertEqual(stats.group_count, 1)
                self.assertEqual(stats.extra_copies, 1)
                self.assertEqual(stats.wasted, 4)
                self.assertIn("## group 1", report_path.read_text(encoding="utf-8"))


class RunHelpersTests(unittest.TestCase):
    def test_keep_record_prefers_newest_then_name(self) -> None:
        older = index.Record(size=1, mtime=10.0, dev=1, ino=1, path="b")
        newer_b = index.Record(size=1, mtime=20.0, dev=1, ino=2, path="b")
        newer_a = index.Record(size=1, mtime=20.0, dev=1, ino=3, path="a")

        self.assertIs(run.keep_record([older, newer_b, newer_a]), newer_a)


if __name__ == "__main__":
    unittest.main()
