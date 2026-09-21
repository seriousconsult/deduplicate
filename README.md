# deduplicate

Find exact-byte duplicate files in a folder. Only files in the folder you pick are scanned; nested folders are ignored. The scanner is built for large directories (hundreds of thousands of files) and keeps memory low by writing file lists to disk instead of a database.

Same-size files are compared with small head/mid/tail samples first. A full read happens only when those samples still match: two survivors are stream-compared (stop at the first different byte); three or more are hashed with BLAKE2b.

## Setup

```bash
python3 install.py
# or
./install.py
```

That deletes any existing `.venv`, creates a new one, and leaves you in an activated shell.

## Compare two folders

```bash
python3 run.py
```

Pick two folders, then add zero or more extensions (one at a time; Enter with no text finishes). None selected means all files. Extensions longer than 10 characters are rejected. Each pick is scanned as that folder only (not its subfolders). You can navigate into a nested folder first if you want that one.

Matching files are listed with size. If there are more than 50 matches, it prints the count and total size, shows the first 20, then `... N more`. Then you can move every match from A or from B to the trash (Windows Recycle Bin on `/mnt/c` and Windows; Linux trash otherwise). Type `TRASH` to confirm, or `K` to keep everything.

If you pick the same folder twice, it looks for duplicates **inside that folder**. The newest file in each group is kept; you can send the extras to the trash (`T`) or keep all (`K`).

```bash
python3 run.py /path/to/folder-a /path/to/folder-b
python3 run.py /path/to/folder-a /path/to/folder-b --ext mp4 --ext webm
```

## Index one folder

```bash
python3 index.py /path/to/folder
```

Options:

```text
python3 index.py /path/to/folder --index dedupe-index.jsonl --report duplicates.txt --ext mp4 --ext webm
```

- `dedupe-index.jsonl` — one line per file (path, size, times). Used as a temp-friendly file list, not a database.
- `duplicates.txt` — confirmed exact-byte duplicate groups.

While it runs, sort runs and same-size candidate lists go into a temporary directory and are deleted afterward.
