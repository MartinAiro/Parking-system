"""Make a safe copy of the SQLite database (works while the system is running).
Usage: python backup.py            -> backups/parking-YYYYmmdd-HHMM.db
Schedule it daily (Windows Task Scheduler or cron) and copy the backups folder off the computer."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from config import Config

uri = Config.SQLALCHEMY_DATABASE_URI
if not uri.startswith("sqlite:///"):
    sys.exit("backup.py handles SQLite only; use your database server's own backup tool.")
src = Path(uri.replace("sqlite:///", "", 1))
dest_dir = Path(__file__).resolve().parent / "backups"
dest_dir.mkdir(exist_ok=True)
dest = dest_dir / f"parking-{datetime.now():%Y%m%d-%H%M}.db"
with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
    a.backup(b)
print("Backup written:", dest)
