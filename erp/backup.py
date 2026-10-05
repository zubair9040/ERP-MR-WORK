"""Automatic daily backup of the database (kept for 30 days) - runs quietly in the background."""
import os
import sqlite3
import threading
import time
from datetime import datetime

KEEP_DAYS = 30
_started = False


def make_backup(db_path, folder):
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"erp_{datetime.now():%Y%m%d_%H%M}.sqlite3")
    src = sqlite3.connect(db_path)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if f.startswith("erp_") and os.path.getmtime(p) < cutoff:
            os.remove(p)
    return dest


def start_auto_backup(app):
    """One backup shortly after start-up if today's is missing, then one every 24 hours."""
    global _started
    if _started:
        return
    _started = True
    db_path, folder = app.config["DATABASE"], os.path.join(app.config["DATA_DIR"], "backups")

    def loop():
        time.sleep(30)
        while True:
            try:
                today = f"erp_{datetime.now():%Y%m%d}"
                if os.path.exists(db_path) and not any(f.startswith(today) for f in os.listdir(folder) if os.path.isdir(folder)):
                    make_backup(db_path, folder)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="erp-auto-backup").start()
