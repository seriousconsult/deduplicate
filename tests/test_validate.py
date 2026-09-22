from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import validate


class ValidateTests(unittest.TestCase):
    def test_existing_dir_accepts_common_path_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            folder = root / "Photos #1 & family!"
            folder.mkdir()

            self.assertEqual(
                validate.require_existing_dir(str(folder)), folder.resolve()
            )

    def test_path_command_shape_is_still_rejected(self) -> None:
        with self.assertRaises(validate.InputError):
            validate.parse_folder_choice("rm -rf photos")

    def test_extensions_remain_strict(self) -> None:
        self.assertEqual(validate.parse_single_extension("*.MP4"), ".mp4")
        with self.assertRaises(validate.InputError):
            validate.parse_single_extension("mp4,webm")


if __name__ == "__main__":
    unittest.main()
