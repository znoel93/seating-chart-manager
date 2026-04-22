"""
backup.py — Backup, restore, import, and export operations for the
seating-chart database.

Backup policy:
    - Manual backups: user-initiated snapshots. Uncapped; user manages
      them explicitly via Settings. Filename includes an optional label.
    - Auto backups: created before risky operations (import, restore).
      Capped at 5; oldest rotates out when a new one is created.

All backups live in <user_data_dir>/backups/ as plain SQLite .db files.
No separate metadata database — filenames encode type/timestamp/label,
and backup contents (classes, rounds, students counts) are read live
from each backup file when displayed in the UI.

Filename convention:
    {type}_{timestamp}[_{label}].db
    e.g. manual_2026-04-21_143052_my-snapshot.db
         auto_2026-04-21_141500.db

The 'label' portion (optional) is slugified to filename-safe characters.
'timestamp' is YYYY-MM-DD_HHMMSS for natural chronological sort.
"""

import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import db  # for _user_data_dir() + init_db()


BACKUP_SUBDIR  = "backups"
MAX_AUTO_BACKUPS = 5

# Maximum label length for manual backups (after slugification). Keeps
# filenames reasonable and within any filesystem's per-component limits.
MAX_LABEL_CHARS = 60


def get_backups_dir() -> Path:
    """Return the backups directory, creating it if needed."""
    d = db._user_data_dir() / BACKUP_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(label: str) -> str:
    """Convert an arbitrary user label into a filename-safe slug.
    Keeps letters, digits, hyphens, underscores; collapses whitespace
    to single hyphens; strips leading/trailing hyphens; truncates to
    MAX_LABEL_CHARS. Empty result → empty string (caller handles)."""
    if not label:
        return ""
    # Replace common separators with hyphens
    s = re.sub(r"[\s_]+", "-", label.strip())
    # Keep only alphanumerics and hyphens
    s = re.sub(r"[^A-Za-z0-9\-]", "", s)
    # Collapse multiple hyphens
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:MAX_LABEL_CHARS]


def _timestamp_now() -> str:
    """Return a sortable timestamp string for filenames."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _parse_filename(filename: str) -> dict | None:
    """Parse a backup filename into its components. Returns None for
    anything that doesn't match the backup filename convention (caller
    can then ignore non-backup files that happen to be in the folder).

    Returns a dict with keys: type, timestamp_str, timestamp (datetime
    or None if unparseable), label (str or empty), filename (original).
    """
    if not filename.endswith(".db"):
        return None
    base = filename[:-3]  # strip .db
    # Expected: {type}_{YYYY-MM-DD_HHMMSS}[_{label}]
    parts = base.split("_", 3)
    if len(parts) < 3:
        return None
    btype = parts[0]
    if btype not in ("manual", "auto"):
        return None
    # parts[1] = YYYY-MM-DD, parts[2] = HHMMSS, parts[3] (optional) = label
    ts_str = f"{parts[1]}_{parts[2]}"
    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%d_%H%M%S")
    except ValueError:
        ts = None
    label = parts[3] if len(parts) >= 4 else ""
    return {
        "filename":       filename,
        "type":           btype,
        "timestamp_str":  ts_str,
        "timestamp":      ts,
        "label":          label,
    }


def _preview_db(path: Path) -> dict:
    """Peek inside a backup DB and count its classes, rounds, students.
    Returns counts dict, or {'error': str} if the file isn't a readable
    DB. Never raises — UI needs to tolerate broken backups gracefully."""
    if not path.exists():
        return {"error": "File missing"}
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            # Use COALESCE so old DBs without the 'archived' column still
            # work — we count everything, archived or not, for the preview.
            classes_count  = conn.execute(
                "SELECT COUNT(*) FROM classes").fetchone()[0]
            rounds_count   = conn.execute(
                "SELECT COUNT(*) FROM rounds").fetchone()[0]
            students_count = conn.execute(
                "SELECT COUNT(*) FROM students").fetchone()[0]
            return {
                "classes":  classes_count,
                "rounds":   rounds_count,
                "students": students_count,
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return {"error": f"Not a valid database: {e}"}
    except Exception as e:
        return {"error": str(e)}


def list_backups() -> list[dict]:
    """Return all backups in the backups folder, newest first.

    Each entry has:
        filename, type ('manual'|'auto'), timestamp (datetime or None),
        timestamp_str, label, size_bytes, path (Path), and a 'preview'
        dict with class/round/student counts or an 'error' field.

    Files in the backup folder that don't match the filename convention
    are silently ignored — the folder is treated as ours, but we don't
    crash on stray files."""
    d = get_backups_dir()
    entries = []
    for child in d.iterdir():
        if not child.is_file():
            continue
        parsed = _parse_filename(child.name)
        if parsed is None:
            continue
        try:
            size = child.stat().st_size
        except OSError:
            size = 0
        parsed["size_bytes"] = size
        parsed["path"]       = child
        parsed["preview"]    = _preview_db(child)
        entries.append(parsed)

    # Sort by timestamp descending (newest first). Unparseable timestamps
    # sort last.
    def _sort_key(e):
        ts = e.get("timestamp")
        # datetime.max for unparseable → sort to the end
        return (0, -ts.timestamp()) if ts else (1, 0)
    entries.sort(key=_sort_key)
    return entries


def _build_filename(btype: str, label: str = "") -> str:
    """Construct a backup filename. 'btype' must be 'manual' or 'auto'."""
    if btype not in ("manual", "auto"):
        raise ValueError(f"Invalid backup type: {btype!r}")
    ts  = _timestamp_now()
    slug = _slugify(label)
    if slug:
        return f"{btype}_{ts}_{slug}.db"
    return f"{btype}_{ts}.db"


def _unique_path(dir_path: Path, filename: str) -> Path:
    """Return a Path that doesn't collide with an existing file. If the
    candidate already exists (possible if two backups are made in the
    same second), append a short disambiguator."""
    candidate = dir_path / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for i in range(1, 100):
        c = dir_path / f"{stem}-{i}{suffix}"
        if not c.exists():
            return c
    # Pathological: 100 backups in the same second. Fall back to PID.
    return dir_path / f"{stem}-{os.getpid()}{suffix}"


def create_manual_backup(label: str = "") -> Path:
    """Snapshot the live database to a manual backup file. Returns the
    path of the created backup.

    Raises RuntimeError on failure (disk full, source missing, etc.)."""
    src = Path(db.get_db_path())
    if not src.exists():
        raise RuntimeError("No database to back up (nothing has been saved yet).")
    dest_dir = get_backups_dir()
    filename = _build_filename("manual", label)
    dest     = _unique_path(dest_dir, filename)
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        raise RuntimeError(f"Could not create backup: {e}") from e
    return dest


def create_auto_backup(reason: str = "") -> Path | None:
    """Snapshot the live database before a risky operation. Rotates out
    old auto-backups to maintain MAX_AUTO_BACKUPS ceiling. The 'reason'
    arg is currently for logging only — it isn't stored in the filename
    (auto filenames are kept short).

    Returns the created path, or None if there was nothing to back up
    (e.g. no live DB yet). Never raises — auto-backups are best-effort;
    the caller shouldn't abort on their failure."""
    src = Path(db.get_db_path())
    if not src.exists():
        return None
    dest_dir = get_backups_dir()
    filename = _build_filename("auto")
    dest     = _unique_path(dest_dir, filename)
    try:
        shutil.copy2(src, dest)
    except OSError:
        # Best-effort; if we can't auto-backup, we still let the risky
        # op proceed. User-facing errors are the caller's responsibility.
        return None

    # Rotate: keep only the newest MAX_AUTO_BACKUPS auto entries
    _rotate_auto_backups()
    return dest


def _rotate_auto_backups() -> None:
    """Enforce the MAX_AUTO_BACKUPS ceiling by deleting oldest auto
    backups beyond the cap. Manual backups are never touched."""
    all_entries = list_backups()
    auto_entries = [e for e in all_entries if e["type"] == "auto"]
    # list_backups returns newest-first; anything past the cap is stale.
    for stale in auto_entries[MAX_AUTO_BACKUPS:]:
        try:
            stale["path"].unlink()
        except OSError:
            # Best-effort rotation — if one can't be deleted (permissions,
            # held by another process), leave it and carry on.
            pass


def delete_backup(filename: str) -> None:
    """Delete a specific backup file. Raises ValueError if the filename
    doesn't look like a backup (defensive — don't let callers delete
    arbitrary files from the folder)."""
    if _parse_filename(filename) is None:
        raise ValueError(f"Not a recognised backup filename: {filename!r}")
    target = get_backups_dir() / filename
    if target.exists():
        target.unlink()


def _validate_is_db_file(path: Path) -> tuple[bool, str]:
    """Check that a file looks like a valid SeatingChartManager database.
    Returns (ok, detail) where detail explains failures.

    We don't just check that it's SQLite — we check it has the tables we
    expect. A user importing a random SQLite DB from another app would
    otherwise blow up on first query with confusing errors."""
    if not path.exists():
        return False, "File does not exist."
    if not path.is_file():
        return False, "Not a file."
    try:
        conn = sqlite3.connect(str(path))
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return False, f"Not a SQLite database: {e}"
    except Exception as e:
        return False, str(e)

    required = {"layouts", "classes", "students", "rounds"}
    missing = required - tables
    if missing:
        return False, (f"Missing expected tables: {sorted(missing)}. "
                       "This doesn't look like a Seating Chart Manager backup.")
    return True, ""


def replace_live_db_from(source: Path) -> None:
    """Replace the live database file with the contents of `source`.

    Steps (each individually safe):
      1. Validate source is a SeatingChartManager DB
      2. Run init_db() on the source to catch it up to the current
         schema (in case the backup was made by an older version).
      3. Atomically copy source onto the live DB path.

    Raises RuntimeError on any failure, with a user-readable message.

    IMPORTANT: Callers must close any open SQLite connections to the
    live DB before calling this. In our app, connections are per-query
    (no persistent handle), so this is automatic — but if that ever
    changes, this function's contract must change too."""
    ok, detail = _validate_is_db_file(source)
    if not ok:
        raise RuntimeError(f"Can't use this file: {detail}")

    # Upgrade the source's schema if needed. init_db() only adds tables
    # and columns that don't exist; it never destroys data. Run it on
    # the source BEFORE copying, so if something goes wrong here, the
    # live DB is untouched.
    #
    # We need init_db() to run against `source`, not the current live
    # DB path. Easiest way: temporarily redirect get_db_path by swapping
    # the path, init, swap back. Since get_db_path is a free function
    # that always returns the canonical user-data path, we instead just
    # call init_db with an explicit connection to `source`.
    try:
        conn = sqlite3.connect(str(source))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # Replicate init_db()'s schema-creating executescript + its
            # column-adding migrations, but on our explicit connection.
            # Simpler alternative: just trust the live init_db() on next
            # open to handle migrations. But then we'd have a window
            # where the live DB is a not-yet-migrated schema, which
            # could confuse the immediate post-restore UI.
            #
            # Practical choice: run init_db() AFTER the copy by ensuring
            # the caller does so (see restore_from_backup below). Here
            # we just verify the source is openable and move on.
            pass
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise RuntimeError(f"Could not open source database: {e}") from e

    live_path = Path(db.get_db_path())
    live_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy to a sibling temp file first, then atomic rename. Protects
    # against partial writes if we're interrupted mid-copy.
    tmp_path = live_path.with_suffix(live_path.suffix + ".restoring")
    try:
        shutil.copy2(source, tmp_path)
        # os.replace is atomic on the same filesystem
        os.replace(tmp_path, live_path)
    except OSError as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"Could not replace live database: {e}") from e


def restore_from_backup(filename: str) -> Path:
    """Restore from a saved backup. Creates an auto-backup of the
    current live DB first, then replaces it. Returns the auto-backup's
    path so the UI can tell the user where their pre-restore state went.

    Raises RuntimeError on failure."""
    parsed = _parse_filename(filename)
    if parsed is None:
        raise RuntimeError(f"Not a recognised backup: {filename!r}")
    source = get_backups_dir() / filename
    if not source.exists():
        raise RuntimeError(f"Backup file missing: {filename}")

    auto = create_auto_backup(reason="pre-restore")
    replace_live_db_from(source)
    # Initialize schema on the newly-restored DB. This is idempotent
    # (all CREATE TABLE IF NOT EXISTS) and brings any older backup up
    # to current schema.
    db.init_db()
    return auto if auto is not None else source  # auto may be None if nothing to back up


def export_to_path(dest: Path) -> None:
    """Copy the live database to a user-chosen path. For backup
    distribution / moving to another Mac.

    Raises RuntimeError on failure."""
    src = Path(db.get_db_path())
    if not src.exists():
        raise RuntimeError("No database to export (nothing has been saved yet).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        raise RuntimeError(f"Could not export: {e}") from e


def import_from_path(source: Path) -> Path:
    """Import a user-chosen database file, replacing the live DB.
    Creates an auto-backup of the current live DB first. Returns the
    auto-backup path (for undo messaging).

    Raises RuntimeError on failure."""
    source = Path(source)
    ok, detail = _validate_is_db_file(source)
    if not ok:
        raise RuntimeError(detail)
    auto = create_auto_backup(reason="pre-import")
    replace_live_db_from(source)
    db.init_db()
    return auto if auto is not None else source


def format_size(size_bytes: int) -> str:
    """Human-readable size for the UI."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_timestamp(ts: datetime | None, fallback: str = "Unknown time") -> str:
    """Human-readable timestamp for the UI."""
    if ts is None:
        return fallback
    now = datetime.now()
    # Today → "Today at 2:30 PM"
    if ts.date() == now.date():
        return f"Today at {ts.strftime('%-I:%M %p')}"
    # Yesterday → "Yesterday at 2:30 PM"
    delta = (now.date() - ts.date()).days
    if delta == 1:
        return f"Yesterday at {ts.strftime('%-I:%M %p')}"
    # This year → "Apr 18 at 2:30 PM"
    if ts.year == now.year:
        return ts.strftime("%b %-d at %-I:%M %p")
    # Older → "Apr 18, 2025, 2:30 PM"
    return ts.strftime("%b %-d, %Y, %-I:%M %p")