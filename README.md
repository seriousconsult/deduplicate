# deduplicate

Find exact-byte duplicate files in a folder. The scanner is built for large directories (hundreds of thousands of files) and keeps memory low by writing file lists to disk instead of a database.

Same-size files are compared with small head/mid/tail samples first. A full read happens only when those samples still match: two survivors are stream-compared (stop at the first different byte); three or more are hashed with BLAKE2b.

## Setup

```bash
python3 install.py
# or
./install.py
```

That deletes any existing `.venv`, creates a new one, and leaves you in an activated shell.

## Index a folder

```bash
python3 index.py /path/to/folder
```

Options:

```text
python3 index.py /path/to/folder --index dedupe-index.jsonl --report duplicates.txt
```

- `dedupe-index.jsonl` — one line per file (path, size, times). Used as a temp-friendly file list, not a database.
- `duplicates.txt` — confirmed exact-byte duplicate groups.

While it runs, sort runs and same-size candidate lists go into a temporary directory and are deleted afterward.
