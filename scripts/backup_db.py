#!/usr/bin/env python3
"""Create a consistent SQLite backup using the SQLite backup API."""
import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = Path(os.environ.get("TAJ_DB_PATH", ROOT / "data" / "taj-opticals.sqlite3")).expanduser().resolve()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", help="Backup .sqlite3 path (default: data/backups/taj-opticals-UTCSTAMP.sqlite3)")
args = parser.parse_args()
if not source.exists():
    raise SystemExit(f"Database not found: {source}")
if args.output:
    target = Path(args.output).expanduser().resolve()
else:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = ROOT / "data" / "backups" / f"taj-opticals-{stamp}.sqlite3"
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
os.chmod(target, 0o600)
print(f"SQLite backup written: {target}")
print("Back up the uploads directory separately; database records reference media files there.")
