"""
db.py — SQLite schema setup and all data access functions.
Single .db file, entirely self-contained.
"""

import sqlite3
import json
import os
import shutil
import sys
from pathlib import Path


APP_NAME = "SeatingChartManager"
DB_FILENAME = "seating_chart.db"


def _user_data_dir() -> Path:
    """Return the OS-appropriate per-user data directory for this app.

    Chosen per-platform:
      - macOS:    ~/Library/Application Support/SeatingChartManager
      - Windows:  %APPDATA%\\SeatingChartManager
                    (typically C:\\Users\\<user>\\AppData\\Roaming\\)
      - Linux:    $XDG_DATA_HOME/SeatingChartManager,
                    falling back to ~/.local/share/SeatingChartManager

    These locations are:
      - Always writable by the current user
      - Survive app reinstalls and updates (unlike data next to the code)
      - Backed up by Time Machine on macOS
      - Per-user on multi-user systems (each login gets its own DB)
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        # %APPDATA% is set on any real Windows install; fall back just
        # in case an exotic environment lacks it.
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        # Linux and other Unix-likes: XDG Base Directory spec
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def _legacy_db_candidates() -> list[Path]:
    """Return every place an older build might have put the DB, in the
    order we should check them. Used once on first launch to migrate
    any existing database into the user-data location.

    Covers:
      - Next to the script (dev runs of main.py)
      - Next to the executable (PyInstaller --onefile builds)
      - Next to db.py itself (package-dir runs)
    """
    candidates = []
    # Next to the executable (PyInstaller, py2app, frozen bundles)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / DB_FILENAME)
    # Next to the main script (python3 main.py from the project root)
    try:
        main_mod = sys.modules.get("__main__")
        main_file = getattr(main_mod, "__file__", None)
        if main_file:
            candidates.append(Path(main_file).resolve().parent / DB_FILENAME)
    except Exception:
        pass
    # Next to db.py itself (fallback — matches the legacy get_db_path)
    candidates.append(Path(__file__).resolve().parent / DB_FILENAME)
    # De-duplicate while preserving order
    seen = set()
    unique = []
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def get_db_path() -> str:
    """Return the DB path, creating the user-data directory if needed.

    On first launch, if a database exists in a legacy location (next to
    the script or executable from a pre-migration build), copy it over
    to the user-data location before returning. The legacy file is left
    in place for safety — the user can delete it manually if they want.
    A marker file (.migrated) is created alongside the new DB so the
    migration check only runs once.
    """
    target_dir = _user_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_db = target_dir / DB_FILENAME
    marker    = target_dir / ".migrated_from_legacy"

    # If the target DB already exists, we're good — nothing to migrate.
    # The marker prevents re-migration if the user deletes the target
    # (fresh-start scenario) but still has a legacy file lying around.
    if not target_db.exists() and not marker.exists():
        for legacy in _legacy_db_candidates():
            if legacy == target_db:
                continue
            if legacy.exists() and legacy.is_file():
                try:
                    shutil.copy2(legacy, target_db)
                    # Drop a marker so we don't re-import the legacy DB
                    # if the user later wipes the target to start fresh.
                    marker.write_text(f"Migrated from: {legacy}\n")
                    break
                except Exception:
                    # If copy fails (permissions, disk full, whatever),
                    # fall through to a fresh DB at the target path.
                    # Don't let migration block startup.
                    continue

    return str(target_db)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def parse_name_input(raw: str) -> tuple[str, str]:
    """Parse a user-entered name string into (first_name, last_name).

    Handles three input patterns:
      - "Last, First"  → exactly two comma-separated tokens (after strip)
                         → first=token2, last=token1
                         (e.g. "Smith, Alice" → ("Alice", "Smith"),
                               "Van Der Berg, Jon" → ("Jon", "Van Der Berg"),
                               "Thornton, Billy Bob" → ("Billy Bob", "Thornton"))
      - "First Last"   → no comma, has whitespace
                         → first=first_token, last=remaining_tokens
                         (e.g. "Alice Smith" → ("Alice", "Smith"),
                               "Mary Jane Watson" → ("Mary", "Jane Watson"))
      - "Mononym"      → no comma, no whitespace
                         → first=token, last=""
                         (e.g. "Hyerin" → ("Hyerin", ""))

    Edge cases:
      - Empty / whitespace input → ("", "")
      - Trailing comma ("Smith, Alice,") → treated as two tokens, same result
      - Multiple commas ("Alice, Bob, Carol") → NOT a Last,First pattern
        (would be a bulk separator case); returns ("Alice, Bob, Carol", "")
        since caller is expected to have split on commas already for that
        case. The parser does not try to guess.
      - Blank first after comma (", Alice") → ("Alice", "")
      - Blank last before comma ("Smith,") → ("Smith", "")

    Note: multi-word first names without a comma (e.g. "Mary Jane Watson")
    get split as first="Mary", last="Jane Watson". This is the best we
    can do without a comma to disambiguate — teachers who need "Mary
    Jane" as the first name should use the "Watson, Mary Jane" form.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    # Check for Last, First pattern: must have exactly two non-empty
    # tokens after splitting on commas.
    if "," in raw:
        parts = [p.strip() for p in raw.split(",")]
        non_empty = [p for p in parts if p]
        if len(non_empty) == 2:
            last, first = non_empty[0], non_empty[1]
            return first, last
        if len(non_empty) == 1:
            # "Smith," or ", Alice" — only one real token. Use it as first.
            return non_empty[0], ""
        # 3+ tokens (e.g. "Alice, Bob, Carol") — ambiguous, keep as-is.
        # This shouldn't normally hit parse_name_input directly because
        # bulk import already splits on commas before calling; but if it
        # does, returning the raw input as first-name keeps it intact.
        return raw, ""
    # No comma → split on whitespace. First word = first name, rest = last.
    tokens = raw.split()
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], " ".join(tokens[1:])


def compose_full_name(first: str, last: str) -> str:
    """Inverse of parse_name_input: produce the natural 'First Last'
    display string. Mononyms (empty last) return first alone."""
    first = (first or "").strip()
    last  = (last  or "").strip()
    if not last:
        return first
    if not first:
        return last
    return f"{first} {last}"


def init_db():
    """Create all tables if they don't exist. Run migrations for existing DBs."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS layouts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS tables (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                layout_id   INTEGER NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                capacity    INTEGER NOT NULL CHECK(capacity >= 0),
                pos_x       REAL,
                pos_y       REAL,
                shape       TEXT NOT NULL DEFAULT 'rect',
                width       REAL NOT NULL DEFAULT 140,
                height      REAL NOT NULL DEFAULT 90,
                rotation    REAL NOT NULL DEFAULT 0,
                decorative  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS seats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id    INTEGER NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
                x_offset    REAL NOT NULL,
                y_offset    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS classes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                layout_id    INTEGER REFERENCES layouts(id) ON DELETE SET NULL,
                seating_mode TEXT NOT NULL DEFAULT 'per_table',
                archived     INTEGER NOT NULL DEFAULT 0,
                name_display TEXT NOT NULL DEFAULT 'full'
            );

            CREATE TABLE IF NOT EXISTS students (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                name            TEXT NOT NULL,
                first_name      TEXT NOT NULL DEFAULT '',
                last_name       TEXT NOT NULL DEFAULT '',
                active          INTEGER NOT NULL DEFAULT 1,
                pinned_table_id INTEGER REFERENCES tables(id) ON DELETE SET NULL,
                pinned_seat_id  INTEGER REFERENCES seats(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS pair_constraints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                student_a       INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                student_b       INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                kind            TEXT NOT NULL DEFAULT 'never_together'
            );

            CREATE TABLE IF NOT EXISTS rounds (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id            INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                label               TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                excluded_tables     TEXT NOT NULL DEFAULT '[]',
                repeat_score        INTEGER NOT NULL DEFAULT 0,
                notes               TEXT NOT NULL DEFAULT '',
                edited              INTEGER NOT NULL DEFAULT 0,
                seating_mode        TEXT NOT NULL DEFAULT 'per_table'
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id    INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                table_id    INTEGER NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
                seat_id     INTEGER REFERENCES seats(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );
        """)
        # Migration: add repeat_score to existing DBs that predate this column
        cols = [r[1] for r in conn.execute("PRAGMA table_info(rounds)").fetchall()]
        if "repeat_score" not in cols:
            conn.execute("ALTER TABLE rounds ADD COLUMN repeat_score INTEGER NOT NULL DEFAULT 0")
        if "notes" not in cols:
            conn.execute("ALTER TABLE rounds ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "edited" not in cols:
            conn.execute("ALTER TABLE rounds ADD COLUMN edited INTEGER NOT NULL DEFAULT 0")
        # Migration: add pos_x / pos_y / shape / dims / rotation to tables
        tcols = [r[1] for r in conn.execute("PRAGMA table_info(tables)").fetchall()]
        if "pos_x" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN pos_x REAL")
        if "pos_y" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN pos_y REAL")
        if "shape" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN shape TEXT NOT NULL DEFAULT 'rect'")
        if "width" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN width REAL NOT NULL DEFAULT 140")
        if "height" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN height REAL NOT NULL DEFAULT 90")
        if "rotation" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN rotation REAL NOT NULL DEFAULT 0")
        if "decorative" not in tcols:
            conn.execute("ALTER TABLE tables ADD COLUMN decorative INTEGER NOT NULL DEFAULT 0")
        # Migration: add pinned_table_id / pinned_seat_id to students
        scols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
        if "pinned_table_id" not in scols:
            conn.execute(
                "ALTER TABLE students ADD COLUMN pinned_table_id INTEGER "
                "REFERENCES tables(id) ON DELETE SET NULL"
            )
        if "pinned_seat_id" not in scols:
            conn.execute(
                "ALTER TABLE students ADD COLUMN pinned_seat_id INTEGER "
                "REFERENCES seats(id) ON DELETE SET NULL"
            )
        # Migration: add first_name / last_name columns for structured name
        # storage. Backfill by heuristically parsing the existing 'name'
        # column — split on first whitespace, first token = first name,
        # rest = last name, mononyms get last="". This mostly does the
        # right thing on existing rosters; rare edge cases (teachers who
        # stored names in non-standard forms) can be fixed via Rename.
        scols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
        need_first = "first_name" not in scols
        need_last  = "last_name" not in scols
        if need_first:
            conn.execute(
                "ALTER TABLE students ADD COLUMN first_name TEXT NOT NULL DEFAULT ''"
            )
        if need_last:
            conn.execute(
                "ALTER TABLE students ADD COLUMN last_name TEXT NOT NULL DEFAULT ''"
            )
        if need_first or need_last:
            # Backfill: parse 'name' into (first, last) for every row.
            # Use a simple heuristic split — first whitespace token is
            # first name, remainder is last. Mononyms keep last="".
            existing = conn.execute(
                "SELECT id, name FROM students"
            ).fetchall()
            for row in existing:
                first, last = parse_name_input(row["name"])
                conn.execute(
                    "UPDATE students SET first_name=?, last_name=? WHERE id=?",
                    (first, last, row["id"])
                )
        # Migration: add seat_id to assignments
        acols = [r[1] for r in conn.execute("PRAGMA table_info(assignments)").fetchall()]
        if "seat_id" not in acols:
            conn.execute(
                "ALTER TABLE assignments ADD COLUMN seat_id INTEGER "
                "REFERENCES seats(id) ON DELETE SET NULL"
            )
        # Migration: add seating_mode to classes + rounds. For EXISTING DBs,
        # stamp everything as 'per_seat' since that's what was in use pre-
        # toggle. New DBs get 'per_table' via the column default (set via
        # the CREATE TABLE clauses above). The distinction matters because
        # the CREATE TABLE only runs on fresh DBs, whereas ALTER TABLE runs
        # on upgraded DBs.
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(classes)").fetchall()]
        if "seating_mode" not in ccols:
            conn.execute(
                "ALTER TABLE classes ADD COLUMN seating_mode TEXT NOT NULL "
                "DEFAULT 'per_seat'"
            )
        # Migration: add archived flag to existing classes (default 0 = active).
        # Refresh the column list in case the previous ALTER ran above.
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(classes)").fetchall()]
        if "archived" not in ccols:
            conn.execute(
                "ALTER TABLE classes ADD COLUMN archived INTEGER NOT NULL "
                "DEFAULT 0"
            )
        # Migration: add name_display preference (full / first_initial / first_only).
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(classes)").fetchall()]
        if "name_display" not in ccols:
            conn.execute(
                "ALTER TABLE classes ADD COLUMN name_display TEXT NOT NULL "
                "DEFAULT 'full'"
            )
        rcols = [r[1] for r in conn.execute("PRAGMA table_info(rounds)").fetchall()]
        if "seating_mode" not in rcols:
            conn.execute(
                "ALTER TABLE rounds ADD COLUMN seating_mode TEXT NOT NULL "
                "DEFAULT 'per_seat'"
            )
        # Migration: pair_constraints table may not exist in old DBs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pair_constraints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                student_a       INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                student_b       INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                kind            TEXT NOT NULL DEFAULT 'never_together'
            )
        """)
        # Migration: ensure seats table exists (in case the main block didn't run on an
        # existing DB due to SQLite execscript behavior)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id    INTEGER NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
                x_offset    REAL NOT NULL,
                y_offset    REAL NOT NULL
            )
        """)
        # Phase 8 transition: clear test rounds/assignments since per-seat model
        # invalidates previous data. Classes, students, and layouts preserved.
        # Only clear if no seats exist yet (i.e. first migration to per-seat).
        has_seats = conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
        if has_seats == 0:
            # Check if there are any assignments with null seat_id (old data)
            old_assignments = conn.execute(
                "SELECT COUNT(*) FROM assignments WHERE seat_id IS NULL"
            ).fetchone()[0]
            if old_assignments > 0:
                conn.execute("DELETE FROM assignments")
                conn.execute("DELETE FROM rounds")
                # Seed seats from capacity for existing tables
                for row in conn.execute(
                    "SELECT id, capacity, width, height, shape FROM tables"
                ).fetchall():
                    _seed_default_seats(conn, row[0], row[1], row[2], row[3], row[4])


def _seed_default_seats(conn, table_id: int, capacity: int, w: float, h: float, shape: str):
    """Create default seat positions for a table based on its shape and capacity.

    Seats are placed as offsets from the table's center. Called during:
    (1) migration for existing tables with no seats yet
    (2) when a new table is created via a preset
    """
    import math
    if capacity <= 0:
        return
    if shape == "round":
        # Evenly spaced around a circle just outside the table edge
        r = max(w, h) / 2 + 22
        for i in range(capacity):
            angle = (2 * math.pi * i / capacity) - math.pi / 2  # start at top
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            conn.execute(
                "INSERT INTO seats (table_id, x_offset, y_offset) VALUES (?,?,?)",
                (table_id, x, y))
    else:
        # Rectangle: place seats around the perimeter. For capacity 2, put them
        # on the long sides. For 4, split 2 per long side. For 6, split 3 per
        # long side. For odd/other, distribute around perimeter evenly.
        long_side_seats = capacity // 2
        remainder = capacity % 2
        margin = 22
        # Top row
        if long_side_seats > 0:
            spacing = w / long_side_seats
            for i in range(long_side_seats):
                x = -w/2 + spacing * (i + 0.5)
                y = -h/2 - margin
                conn.execute(
                    "INSERT INTO seats (table_id, x_offset, y_offset) VALUES (?,?,?)",
                    (table_id, x, y))
        # Bottom row
        bottom_count = long_side_seats + remainder
        if bottom_count > 0:
            spacing = w / bottom_count
            for i in range(bottom_count):
                x = -w/2 + spacing * (i + 0.5)
                y = h/2 + margin
                conn.execute(
                    "INSERT INTO seats (table_id, x_offset, y_offset) VALUES (?,?,?)",
                    (table_id, x, y))


# ── Settings queries ──────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

def set_setting(key: str, value: str):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                     (key, value))


# ── Layout queries ────────────────────────────────────────────────────────────

def create_layout(name: str) -> int:
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO layouts (name) VALUES (?)", (name,))
        return cur.lastrowid

def get_all_layouts() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM layouts ORDER BY name")]

def get_layout(layout_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM layouts WHERE id=?", (layout_id,)).fetchone()
        return dict(row) if row else None

def rename_layout(layout_id: int, new_name: str):
    with get_connection() as conn:
        conn.execute("UPDATE layouts SET name=? WHERE id=?", (new_name, layout_id))

def delete_layout(layout_id: int):
    """Only callable if layout is not used by any class or round."""
    with get_connection() as conn:
        conn.execute("DELETE FROM layouts WHERE id=?", (layout_id,))

def is_layout_in_use(layout_id: int) -> bool:
    """Returns True if any class uses this layout (lock check)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM classes WHERE layout_id=?", (layout_id,)
        ).fetchone()
        return row[0] > 0

def layout_has_rounds(layout_id: int) -> bool:
    """Returns True if any round has been recorded using this layout's tables."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM assignments a
            JOIN tables t ON a.table_id = t.id
            WHERE t.layout_id = ?
        """, (layout_id,)).fetchone()
        return row[0] > 0

def duplicate_layout(layout_id: int, new_name: str) -> int:
    """Deep-copy a layout and all its tables (including positions) under a new name."""
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO layouts (name) VALUES (?)", (new_name,))
        new_layout_id = cur.lastrowid
        tables = conn.execute(
            "SELECT label, capacity, pos_x, pos_y FROM tables WHERE layout_id=?", (layout_id,)
        ).fetchall()
        for t in tables:
            conn.execute(
                "INSERT INTO tables (layout_id, label, capacity, pos_x, pos_y) VALUES (?,?,?,?,?)",
                (new_layout_id, t["label"], t["capacity"], t["pos_x"], t["pos_y"])
            )
        return new_layout_id


# ── Table queries ─────────────────────────────────────────────────────────────

def add_table(layout_id: int, label: str, capacity: int) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tables (layout_id, label, capacity) VALUES (?,?,?)",
            (layout_id, label, capacity)
        )
        return cur.lastrowid

def add_preset_table(layout_id: int, label: str, shape: str, capacity: int,
                     width: float, height: float,
                     x: float = 0, y: float = 0,
                     decorative: int = 0) -> int:
    """Create a table of a given shape + dimensions and auto-seed its seats.

    Used by quick-add presets in the layout editor: "Round 4", "Rect 6", etc.
    Seats are automatically placed around the table according to its shape
    and capacity. Returns the new table_id.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tables
               (layout_id, label, capacity, pos_x, pos_y,
                shape, width, height, rotation, decorative)
               VALUES (?,?,?,?,?,?,?,?,0,?)""",
            (layout_id, label, capacity, x, y, shape, width, height, decorative)
        )
        tid = cur.lastrowid
        if not decorative and capacity > 0:
            _seed_default_seats(conn, tid, capacity, width, height, shape)
        return tid

def get_tables_for_layout(layout_id: int) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tables WHERE layout_id=? ORDER BY label", (layout_id,)
        )]

def update_table(table_id: int, label: str, capacity: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tables SET label=?, capacity=? WHERE id=?",
            (label, capacity, table_id)
        )

def update_table_position(table_id: int, x: float, y: float):
    """Update only the visual position of a table. Always allowed, even on locked layouts."""
    with get_connection() as conn:
        conn.execute("UPDATE tables SET pos_x=?, pos_y=? WHERE id=?", (x, y, table_id))

def update_table_rotation(table_id: int, rotation: float):
    with get_connection() as conn:
        conn.execute("UPDATE tables SET rotation=? WHERE id=?", (rotation, table_id))

def update_table_shape(table_id: int, shape: str, width: float, height: float):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tables SET shape=?, width=?, height=? WHERE id=?",
            (shape, width, height, table_id)
        )

def clear_table_positions(layout_id: int):
    """Reset all positions to NULL, triggering auto-placement on next open."""
    with get_connection() as conn:
        conn.execute("UPDATE tables SET pos_x=NULL, pos_y=NULL WHERE layout_id=?", (layout_id,))

def delete_table(table_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM tables WHERE id=?", (table_id,))


# ── Seat queries ──────────────────────────────────────────────────────────────

def add_seat(table_id: int, x_offset: float, y_offset: float) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO seats (table_id, x_offset, y_offset) VALUES (?,?,?)",
            (table_id, x_offset, y_offset)
        )
        # Sync table capacity to reflect the new total
        total = conn.execute(
            "SELECT COUNT(*) FROM seats WHERE table_id=?", (table_id,)).fetchone()[0]
        conn.execute("UPDATE tables SET capacity=? WHERE id=?", (total, table_id))
        return cur.lastrowid

def get_seats_for_table(table_id: int) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM seats WHERE table_id=? ORDER BY id", (table_id,)
        )]

def get_seats_for_layout(layout_id: int) -> list:
    """All seats across all tables in a layout, with the parent table info joined."""
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT s.*, t.pos_x AS table_x, t.pos_y AS table_y,
                   t.rotation AS table_rotation, t.layout_id
            FROM seats s
            JOIN tables t ON s.table_id = t.id
            WHERE t.layout_id=?
            ORDER BY s.table_id, s.id
        """, (layout_id,))]

def update_seat_position(seat_id: int, x_offset: float, y_offset: float):
    with get_connection() as conn:
        conn.execute("UPDATE seats SET x_offset=?, y_offset=? WHERE id=?",
                     (x_offset, y_offset, seat_id))

def delete_seat(seat_id: int):
    with get_connection() as conn:
        # Find parent table to update capacity after deletion
        row = conn.execute("SELECT table_id FROM seats WHERE id=?", (seat_id,)).fetchone()
        if not row:
            return
        tid = row[0]
        conn.execute("DELETE FROM seats WHERE id=?", (seat_id,))
        total = conn.execute(
            "SELECT COUNT(*) FROM seats WHERE table_id=?", (tid,)).fetchone()[0]
        conn.execute("UPDATE tables SET capacity=? WHERE id=?", (total, tid))

def total_seats_for_layout(layout_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM seats s
            JOIN tables t ON s.table_id = t.id
            WHERE t.layout_id=?
        """, (layout_id,)).fetchone()
        return row[0]


# ── Class queries ─────────────────────────────────────────────────────────────

def create_class(name: str, layout_id: int | None = None,
                  seating_mode: str = "per_table") -> int:
    """Create a class. seating_mode is 'per_table' (default) or 'per_seat'."""
    if seating_mode not in ("per_table", "per_seat"):
        raise ValueError(f"Invalid seating_mode: {seating_mode!r}")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO classes (name, layout_id, seating_mode) VALUES (?,?,?)",
            (name, layout_id, seating_mode)
        )
        return cur.lastrowid

def set_class_seating_mode(class_id: int, mode: str):
    """Change a class's seating mode. Existing rounds are unaffected — their
    own seating_mode stamp decides how they render."""
    if mode not in ("per_table", "per_seat"):
        raise ValueError(f"Invalid seating_mode: {mode!r}")
    with get_connection() as conn:
        conn.execute("UPDATE classes SET seating_mode=? WHERE id=?",
                      (mode, class_id))

def get_all_classes(include_archived: bool = False) -> list:
    """Return all classes. By default, archived classes are excluded so
    teachers see only their active roster. Pass include_archived=True to
    see archived classes (e.g., for the 'Show archived' view).
    """
    with get_connection() as conn:
        if include_archived:
            return [dict(r) for r in conn.execute(
                "SELECT c.*, l.name as layout_name FROM classes c "
                "LEFT JOIN layouts l ON c.layout_id=l.id ORDER BY c.name"
            )]
        return [dict(r) for r in conn.execute(
            "SELECT c.*, l.name as layout_name FROM classes c "
            "LEFT JOIN layouts l ON c.layout_id=l.id "
            "WHERE COALESCE(c.archived,0)=0 "
            "ORDER BY c.name"
        )]


def set_class_archived(class_id: int, archived: bool):
    """Archive (hide from default list) or unarchive a class. Archiving
    is purely a visibility toggle — all data (roster, rounds, pair
    history, constraints, pins) is preserved unchanged.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE classes SET archived=? WHERE id=?",
            (1 if archived else 0, class_id)
        )


def set_class_name_display(class_id: int, mode: str):
    """Set how student names render for this class. Valid modes:
      - 'full'          — 'Alice Smith'
      - 'first_initial' — 'Alice S.'
      - 'first_only'    — 'Alice'
    This is a display preference; stored student names are unchanged.
    """
    if mode not in ("full", "first_initial", "first_only"):
        raise ValueError(f"Invalid name_display mode: {mode!r}")
    with get_connection() as conn:
        conn.execute(
            "UPDATE classes SET name_display=? WHERE id=?",
            (mode, class_id)
        )


def format_student_name(name: str, mode: str = "full",
                          first: str | None = None,
                          last:  str | None = None) -> str:
    """Apply a display-mode transform to a stored name.

    Prefers the explicit (first, last) split when supplied — this is
    the authoritative form for names imported or added after the
    first_name/last_name columns were introduced.

    Falls back to parsing `name` heuristically (first whitespace token
    = first name, rest = last) when no split is supplied. Legacy rows
    that predate the split columns hit this path.

    Modes:
      - 'full'          → 'Alice Smith' / 'Jon Van Der Berg' / 'Hyerin'
      - 'first_initial' → 'Alice S.'    / 'Jon V.'           / 'Hyerin'
      - 'first_only'    → 'Alice'       / 'Jon'              / 'Hyerin'
    """
    # Resolve first/last. Prefer the explicit args; fall back to parsing
    # the flat `name` field (legacy path).
    if first is None and last is None:
        first, last = parse_name_input(name or "")
    first = (first or "").strip()
    last  = (last  or "").strip()

    if mode == "full":
        # Compose the natural order; mononym returns first alone
        if not last:
            return first
        if not first:
            return last
        return f"{first} {last}"
    if mode == "first_only":
        return first if first else last
    if mode == "first_initial":
        if not last:
            # Mononym — no initial to append
            return first if first else ""
        initial = next((ch for ch in last if ch.isalpha()), "")
        if not initial:
            return first
        return f"{first} {initial.upper()}."
    # Unknown mode → be conservative, return the natural form
    if not last:
        return first
    return f"{first} {last}"


def get_class(class_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT c.*, l.name as layout_name FROM classes c "
            "LEFT JOIN layouts l ON c.layout_id=l.id WHERE c.id=?", (class_id,)
        ).fetchone()
        return dict(row) if row else None

def update_class(class_id: int, name: str, layout_id: int | None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE classes SET name=?, layout_id=? WHERE id=?",
            (name, layout_id, class_id)
        )

def delete_class(class_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM classes WHERE id=?", (class_id,))

def duplicate_class(class_id: int, new_name: str) -> int:
    """
    Create a copy of a class with a fresh name. Copies:
      - roster (with pins preserved)
      - layout assignment
      - never-together pair constraints (remapped to new student IDs)
    Does NOT copy:
      - pair history (rounds/assignments)
      - the class itself is a fresh row
    Returns the new class's id.
    """
    src = get_class(class_id)
    if not src:
        raise ValueError(f"Class {class_id} not found")

    with get_connection() as conn:
        # Create new class (carrying mode from source)
        cur = conn.execute(
            "INSERT INTO classes (name, layout_id, seating_mode, name_display) "
            "VALUES (?,?,?,?)",
            (new_name, src["layout_id"],
             src.get("seating_mode", "per_table"),
             src.get("name_display", "full"))
        )
        new_class_id = cur.lastrowid

        # Copy students; build id mapping from old -> new
        old_students = [dict(r) for r in conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY id",
            (class_id,)
        )]
        id_map: dict[int, int] = {}
        for s in old_students:
            cur = conn.execute(
                "INSERT INTO students (class_id, name, first_name, last_name, "
                "active, pinned_table_id, pinned_seat_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (new_class_id, s["name"],
                 s.get("first_name") or "", s.get("last_name") or "",
                 s["active"],
                 s.get("pinned_table_id"), s.get("pinned_seat_id"))
            )
            id_map[s["id"]] = cur.lastrowid

        # Copy pair constraints with remapped IDs
        old_constraints = conn.execute(
            "SELECT * FROM pair_constraints WHERE class_id=?",
            (class_id,)
        ).fetchall()
        for c in old_constraints:
            new_a = id_map.get(c["student_a"])
            new_b = id_map.get(c["student_b"])
            if new_a is not None and new_b is not None:
                conn.execute(
                    "INSERT INTO pair_constraints (class_id, student_a, student_b, kind) "
                    "VALUES (?,?,?,?)",
                    (new_class_id, new_a, new_b, c["kind"])
                )

        return new_class_id


# ── Student queries ───────────────────────────────────────────────────────────

def add_student(class_id: int, name: str,
                 first_name: str | None = None,
                 last_name:  str | None = None) -> int:
    """Insert a student. If first_name/last_name are omitted, they are
    parsed from `name` using parse_name_input (supports 'Last, First'
    and 'First Last' and mononym). `name` stored is always the
    natural-order composed form so legacy reads keep working."""
    if first_name is None and last_name is None:
        first_name, last_name = parse_name_input(name)
    first_name = (first_name or "").strip()
    last_name  = (last_name  or "").strip()
    stored_name = compose_full_name(first_name, last_name) or name.strip()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO students (class_id, name, first_name, last_name) "
            "VALUES (?,?,?,?)",
            (class_id, stored_name, first_name, last_name)
        )
        return cur.lastrowid

def bulk_add_students(class_id: int,
                      entries: list) -> int:
    """Insert multiple students in one transaction. Returns count inserted.

    Each entry may be either:
      - a str (parsed via parse_name_input), OR
      - a dict {'first_name': ..., 'last_name': ...} when the caller has
        already split the name (e.g. bulk importer which used commas to
        detect Last,First). The dict form is preferred because it
        preserves the caller's parse decision.
    """
    if not entries:
        return 0
    rows = []
    for e in entries:
        if isinstance(e, dict):
            first = (e.get("first_name") or "").strip()
            last  = (e.get("last_name")  or "").strip()
        else:
            first, last = parse_name_input(e)
        stored = compose_full_name(first, last)
        rows.append((class_id, stored, first, last))
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO students (class_id, name, first_name, last_name) "
            "VALUES (?,?,?,?)",
            rows
        )
    return len(rows)

def get_students_for_class(class_id: int, active_only: bool = False) -> list:
    """Return students with an extra 'display' key showing the name as
    rendered per this class's name_display preference. 'name' remains
    the canonical stored value (natural-order full name); 'first_name'
    and 'last_name' are the authoritative split if populated. 'display'
    is a UI convenience so call sites don't have to look up the mode
    each time."""
    with get_connection() as conn:
        query = "SELECT * FROM students WHERE class_id=?"
        params = [class_id]
        if active_only:
            query += " AND active=1"
        query += " ORDER BY name"
        rows = [dict(r) for r in conn.execute(query, params)]
        # Resolve the class's display mode once and apply to every row.
        mode_row = conn.execute(
            "SELECT name_display FROM classes WHERE id=?",
            (class_id,)
        ).fetchone()
        mode = (mode_row["name_display"]
                if mode_row and "name_display" in mode_row.keys()
                else "full")
        for r in rows:
            r["display"] = format_student_name(
                r["name"], mode,
                first=r.get("first_name"), last=r.get("last_name"))
        return rows

def update_student(student_id: int, name: str, active: bool,
                    first_name: str | None = None,
                    last_name:  str | None = None):
    """Rename/toggle a student. If first_name/last_name are omitted
    they are parsed from `name`; pass them explicitly when the caller
    has already split the name."""
    if first_name is None and last_name is None:
        first_name, last_name = parse_name_input(name)
    first_name = (first_name or "").strip()
    last_name  = (last_name  or "").strip()
    stored_name = compose_full_name(first_name, last_name) or name.strip()
    with get_connection() as conn:
        conn.execute(
            "UPDATE students SET name=?, first_name=?, last_name=?, active=? "
            "WHERE id=?",
            (stored_name, first_name, last_name, int(active), student_id)
        )

def delete_student(student_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))

def set_student_pin(student_id: int, table_id: int | None):
    """Pin a student to a specific table, or unpin with None.

    Clears both table AND seat pins — 'unpin' means unpin everything.
    When setting a table pin, the seat pin is also cleared so they can't
    end up pointing at a different table than the new table pin.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE students SET pinned_table_id=?, pinned_seat_id=NULL "
            "WHERE id=?",
            (table_id, student_id)
        )


def set_student_pin_full(student_id: int, table_id: int | None,
                          seat_id: int | None):
    """Pin a student to a table AND optionally a specific seat.

    Design contract:
      - If seat_id is set, table_id MUST also be set and must be the
        table that owns that seat. Caller is responsible.
      - If seat_id is None, only the table pin applies.
      - If table_id is None, seat_id is also forced to None (can't pin
        to a seat without its table).
    """
    if table_id is None:
        seat_id = None
    with get_connection() as conn:
        conn.execute(
            "UPDATE students SET pinned_table_id=?, pinned_seat_id=? "
            "WHERE id=?",
            (table_id, seat_id, student_id)
        )


def reconcile_pins_for_layout(class_id: int) -> int:
    """Ensure every student's pinned_seat_id is consistent with their
    pinned_table_id: the seat (if set) must exist AND belong to the
    pinned table. If it doesn't, clear the seat pin (table pin kept).

    Run after a mode switch or when a layout changes to keep the pin
    data sane. Returns the number of seat pins cleared.

    Note: SQLite's ON DELETE SET NULL foreign key already clears
    pinned_seat_id if the seat itself is deleted. This helper handles
    the other case — a seat that still exists but belongs to a
    different table than the student's pinned_table_id.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT s.id, s.pinned_table_id, s.pinned_seat_id, "
            "       seat.table_id AS seat_table_id "
            "FROM students s "
            "LEFT JOIN seats seat ON seat.id = s.pinned_seat_id "
            "WHERE s.class_id=? AND s.pinned_seat_id IS NOT NULL",
            (class_id,)
        ).fetchall()
        cleared = 0
        for r in rows:
            # seat_table_id is None if the seat no longer exists (shouldn't
            # happen thanks to the FK cascade, but defensive). If it does,
            # or if it doesn't match pinned_table_id, clear the seat pin.
            if (r["seat_table_id"] is None
                    or r["seat_table_id"] != r["pinned_table_id"]):
                conn.execute(
                    "UPDATE students SET pinned_seat_id=NULL WHERE id=?",
                    (r["id"],))
                cleared += 1
        return cleared


# ── Pair constraint queries ───────────────────────────────────────────────────

def get_pair_constraints(class_id: int, kind: str = "never_together") -> list:
    """Return list of {id, student_a, student_b, name_a, name_b,
    display_a, display_b} for the class."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT pc.id, pc.student_a, pc.student_b, "
            "       sa.name AS name_a, sb.name AS name_b, "
            "       sa.first_name AS first_a, sa.last_name AS last_a, "
            "       sb.first_name AS first_b, sb.last_name AS last_b "
            "FROM pair_constraints pc "
            "JOIN students sa ON sa.id = pc.student_a "
            "JOIN students sb ON sb.id = pc.student_b "
            "WHERE pc.class_id=? AND pc.kind=? "
            "ORDER BY sa.name, sb.name",
            (class_id, kind)
        ).fetchall()
        result = [dict(r) for r in rows]
        # Resolve class display mode once, apply to both endpoints
        mode_row = conn.execute(
            "SELECT name_display FROM classes WHERE id=?",
            (class_id,)
        ).fetchone()
        mode = (mode_row["name_display"]
                if mode_row and "name_display" in mode_row.keys()
                else "full")
        for r in result:
            r["display_a"] = format_student_name(
                r["name_a"], mode,
                first=r.get("first_a"), last=r.get("last_a"))
            r["display_b"] = format_student_name(
                r["name_b"], mode,
                first=r.get("first_b"), last=r.get("last_b"))
        return result

def add_pair_constraint(class_id: int, student_a: int, student_b: int,
                        kind: str = "never_together") -> int:
    # Store with lower id first to prevent dupes like (5,7) and (7,5)
    a, b = sorted([student_a, student_b])
    with get_connection() as conn:
        # Check for existing duplicate
        existing = conn.execute(
            "SELECT id FROM pair_constraints "
            "WHERE class_id=? AND student_a=? AND student_b=? AND kind=?",
            (class_id, a, b, kind)
        ).fetchone()
        if existing:
            return existing[0]
        cur = conn.execute(
            "INSERT INTO pair_constraints (class_id, student_a, student_b, kind) "
            "VALUES (?,?,?,?)",
            (class_id, a, b, kind)
        )
        return cur.lastrowid

def delete_pair_constraint(constraint_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM pair_constraints WHERE id=?", (constraint_id,))


# ── Round queries ─────────────────────────────────────────────────────────────

def create_round(class_id: int, label: str, created_at: str,
                 excluded_tables: list[int], repeat_score: int = 0,
                 seating_mode: str = "per_table") -> int:
    """Create a round. seating_mode is stamped at generation time so the round
    always renders according to how it was generated, even if the class's
    current mode changes later."""
    if seating_mode not in ("per_table", "per_seat"):
        raise ValueError(f"Invalid seating_mode: {seating_mode!r}")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO rounds (class_id, label, created_at, excluded_tables, "
            "repeat_score, seating_mode) VALUES (?,?,?,?,?,?)",
            (class_id, label, created_at, json.dumps(excluded_tables),
             repeat_score, seating_mode)
        )
        return cur.lastrowid

def get_rounds_for_class(class_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM rounds WHERE class_id=? ORDER BY created_at DESC",
            (class_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["excluded_tables"] = json.loads(d["excluded_tables"])
            result.append(d)
        return result

def delete_round(round_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM rounds WHERE id=?", (round_id,))

def update_round_notes(round_id: int, notes: str):
    with get_connection() as conn:
        conn.execute("UPDATE rounds SET notes=? WHERE id=?", (notes, round_id))

def update_round_label(round_id: int, label: str):
    with get_connection() as conn:
        conn.execute("UPDATE rounds SET label=? WHERE id=?", (label, round_id))


# ── Assignment queries ────────────────────────────────────────────────────────

def save_assignments(round_id: int, assignments: list):
    """assignments: list of (student_id, seat_id, table_id) or legacy (student_id, table_id).
    Writes seat_id when provided."""
    rows = []
    for a in assignments:
        if len(a) == 3:
            sid, kid, tid = a
            rows.append((round_id, sid, tid, kid))
        else:
            sid, tid = a
            rows.append((round_id, sid, tid, None))
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO assignments (round_id, student_id, table_id, seat_id) VALUES (?,?,?,?)",
            rows
        )

def replace_assignments(round_id: int,
                         assignments: list,
                         mark_edited: bool = True,
                         new_repeat_score: int | None = None):
    """Fully replace a round's assignments. Used by the manual-override editor.
    assignments: list of (student_id, seat_id, table_id) or legacy (student_id, table_id)."""
    rows = []
    for a in assignments:
        if len(a) == 3:
            sid, kid, tid = a
            rows.append((round_id, sid, tid, kid))
        else:
            sid, tid = a
            rows.append((round_id, sid, tid, None))
    with get_connection() as conn:
        conn.execute("DELETE FROM assignments WHERE round_id=?", (round_id,))
        conn.executemany(
            "INSERT INTO assignments (round_id, student_id, table_id, seat_id) VALUES (?,?,?,?)",
            rows
        )
        if mark_edited:
            conn.execute("UPDATE rounds SET edited=1 WHERE id=?", (round_id,))
        if new_repeat_score is not None:
            conn.execute("UPDATE rounds SET repeat_score=? WHERE id=?",
                         (new_repeat_score, round_id))

def get_assignments_for_round(round_id: int) -> list:
    """Return assignments for a round, enriched with 'student_name'
    (stored form) and 'student_display' (formatted per the class's
    name_display preference). UI display sites should prefer
    student_display; operational code that refers to specific students
    should use student_name."""
    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute("""
            SELECT a.*,
                   s.name       as student_name,
                   s.first_name as student_first,
                   s.last_name  as student_last,
                   t.label      as table_label
            FROM assignments a
            JOIN students s ON a.student_id = s.id
            JOIN tables t ON a.table_id = t.id
            WHERE a.round_id = ?
            ORDER BY t.label, s.name
        """, (round_id,))]
        # Resolve display mode via the round's class
        mode_row = conn.execute("""
            SELECT c.name_display
            FROM rounds r
            JOIN classes c ON r.class_id = c.id
            WHERE r.id = ?
        """, (round_id,)).fetchone()
        mode = (mode_row["name_display"]
                if mode_row and "name_display" in mode_row.keys()
                else "full")
        for r in rows:
            r["student_display"] = format_student_name(
                r["student_name"], mode,
                first=r.get("student_first"), last=r.get("student_last"))
        return rows

def get_pair_history(class_id: int) -> dict:
    """
    Returns a dict: {(student_id_a, student_id_b): count}
    where a < b always, counting how many times they've shared a table.
    """
    with get_connection() as conn:
        # Get all assignments grouped by round+table
        rows = conn.execute("""
            SELECT a.round_id, a.table_id, a.student_id
            FROM assignments a
            JOIN rounds r ON a.round_id = r.id
            WHERE r.class_id = ?
            ORDER BY a.round_id, a.table_id
        """, (class_id,)).fetchall()

    # Group by (round_id, table_id)
    from collections import defaultdict
    table_groups: dict = defaultdict(list)
    for row in rows:
        key = (row["round_id"], row["table_id"])
        table_groups[key].append(row["student_id"])

    pair_counts: dict = defaultdict(int)
    for students in table_groups.values():
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                a, b = sorted([students[i], students[j]])
                pair_counts[(a, b)] += 1

    return dict(pair_counts)


def get_seat_history(class_id: int) -> dict:
    """
    Returns {(student_id, seat_id): count} — how many times each student
    has occupied each seat across all rounds for this class. Used by the
    optimiser as a tiebreaker to rotate students through different seats
    over time, not just different tablemates.

    Only rounds that have seat_id populated (post-per-seat migration) are
    counted. Earlier rounds may have NULL seat_id and contribute nothing.
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT a.student_id, a.seat_id
            FROM assignments a
            JOIN rounds r ON a.round_id = r.id
            WHERE r.class_id = ? AND a.seat_id IS NOT NULL
        """, (class_id,)).fetchall()

    from collections import defaultdict
    counts: dict = defaultdict(int)
    for row in rows:
        counts[(row["student_id"], row["seat_id"])] += 1
    return dict(counts)


def count_repeat_pairs(class_id: int, assignments: list,
                        exclude_round_id: int | None = None) -> int:
    """
    Count how many pairs in the given assignment set have sat together
    at the same table in any PRIOR round of this class.

    assignments: list of (student_id, seat_id, table_id) tuples — the
        post-optimiser output format. Only student_id and table_id are used.
    exclude_round_id: if set, treat this as the target round — only
        rounds created BEFORE it (i.e. with a lower id) contribute to
        the "prior" history. This matches what the optimizer scored
        against at generation time, so a round's repeat count stays
        stable as later rounds are added. Also excludes the target
        itself so it doesn't compare against its own pairs.

        If None, the full history is used as prior — this is the mode
        callers use when evaluating a candidate assignment that isn't
        tied to a specific existing round yet (e.g. the generator
        computing a display metric before the round is saved).

    Returns a count of unique repeat pairings. Used as a human-meaningful
    metric independent of the ILP objective.
    """
    # Build prior pair history. When a target round is specified, only
    # rounds created before it contribute — this keeps the count stable
    # as later rounds are added.
    with get_connection() as conn:
        if exclude_round_id is not None:
            rows = conn.execute("""
                SELECT a.round_id, a.table_id, a.student_id
                FROM assignments a
                JOIN rounds r ON a.round_id = r.id
                WHERE r.class_id = ? AND r.id < ?
            """, (class_id, exclude_round_id)).fetchall()
        else:
            rows = conn.execute("""
                SELECT a.round_id, a.table_id, a.student_id
                FROM assignments a
                JOIN rounds r ON a.round_id = r.id
                WHERE r.class_id = ?
            """, (class_id,)).fetchall()

    from collections import defaultdict
    table_groups: dict = defaultdict(list)
    for row in rows:
        table_groups[(row["round_id"], row["table_id"])].append(row["student_id"])
    prior_pairs: set = set()
    for students in table_groups.values():
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                a, b = sorted([students[i], students[j]])
                prior_pairs.add((a, b))

    # Build current-round pairs
    current_by_table: dict = defaultdict(list)
    for item in assignments:
        # Accept both (student_id, seat_id, table_id) 3-tuples and
        # (student_id, table_id) 2-tuples
        if len(item) == 3:
            stu_id, _seat, tid = item
        else:
            stu_id, tid = item
        current_by_table[tid].append(stu_id)

    repeats = 0
    for students in current_by_table.values():
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                a, b = sorted([students[i], students[j]])
                if (a, b) in prior_pairs:
                    repeats += 1
    return repeats


def count_new_pairs_in_round(class_id: int, round_id: int) -> int:
    """
    Count how many pairings in `round_id` were BRAND NEW — i.e., those two
    students had not shared a table in any prior round of this class. Used
    as a human-meaningful rotation-momentum metric on the class detail page.

    "Prior" is determined by created_at: we look only at rounds that came
    before round_id chronologically.
    """
    with get_connection() as conn:
        # Get created_at for the target round
        target = conn.execute(
            "SELECT created_at FROM rounds WHERE id=? AND class_id=?",
            (round_id, class_id)
        ).fetchone()
        if target is None:
            return 0

        # Pairs from rounds strictly before this one
        prior_rows = conn.execute("""
            SELECT a.round_id, a.table_id, a.student_id
            FROM assignments a
            JOIN rounds r ON a.round_id = r.id
            WHERE r.class_id = ? AND r.created_at < ?
        """, (class_id, target["created_at"])).fetchall()

        # Pairs from the target round itself
        current_rows = conn.execute("""
            SELECT table_id, student_id
            FROM assignments
            WHERE round_id = ?
        """, (round_id,)).fetchall()

    from collections import defaultdict
    prior_by_group: dict = defaultdict(list)
    for row in prior_rows:
        prior_by_group[(row["round_id"], row["table_id"])].append(row["student_id"])
    prior_pairs: set = set()
    for students in prior_by_group.values():
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                a, b = sorted([students[i], students[j]])
                prior_pairs.add((a, b))

    current_by_table: dict = defaultdict(list)
    for row in current_rows:
        current_by_table[row["table_id"]].append(row["student_id"])
    current_pairs: set = set()
    for students in current_by_table.values():
        for i in range(len(students)):
            for j in range(i + 1, len(students)):
                a, b = sorted([students[i], students[j]])
                current_pairs.add((a, b))

    # Brand-new pairs = current minus prior
    return len(current_pairs - prior_pairs)


def get_rounds_for_pair(class_id: int, student_a: int, student_b: int) -> list:
    """
    Returns the list of rounds where student_a and student_b shared a table.
    Each entry is a dict with id, label, created_at, notes, table_label.
    """
    a, b = sorted([student_a, student_b])
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT r.id, r.label, r.created_at, r.notes, t.label AS table_label
            FROM assignments a1
            JOIN assignments a2 ON a1.round_id = a2.round_id
                                AND a1.table_id = a2.table_id
            JOIN rounds r ON a1.round_id = r.id
            JOIN tables t ON a1.table_id = t.id
            WHERE r.class_id = ? AND a1.student_id = ? AND a2.student_id = ?
            ORDER BY r.created_at DESC
        """, (class_id, a, b)).fetchall()
        return [dict(r) for r in rows]

def get_pair_stats(class_id: int) -> dict:
    """
    Compute aggregate statistics for a class in one pass.
    Returns a dict with:
        total_students: N
        active_students: count of currently-active students
        total_rounds: how many rounds have been generated
        total_possible_pairs: N * (N-1) / 2 for ALL students (active + inactive)
        unique_pairs_seen: number of distinct pairs that have shared a table
        total_pairings: total count of pair-sharing events (sum of pair_counts)
        pair_counts: {(a, b): count}  — full history
        most_repeated: {"student_a_id", "student_b_id", "name_a", "name_b", "count"} or None
        recent_rate: avg new pairs introduced per round over the last 3 rounds
    """
    pair_counts = get_pair_history(class_id)
    students = get_students_for_class(class_id, active_only=False)
    rounds = get_rounds_for_class(class_id)

    total_students = len(students)
    active_students = sum(1 for s in students if s["active"])
    total_possible_pairs = total_students * (total_students - 1) // 2 if total_students > 1 else 0
    unique_pairs_seen = len(pair_counts)
    total_pairings = sum(pair_counts.values())

    # Most repeated pair
    most_repeated = None
    if pair_counts:
        (a, b), cnt = max(pair_counts.items(), key=lambda kv: kv[1])
        name_by_id = {s["id"]: s["name"] for s in students}
        display_by_id = {s["id"]: s.get("display", s["name"]) for s in students}
        most_repeated = {
            "student_a_id": a,
            "student_b_id": b,
            "name_a": name_by_id.get(a, f"#{a}"),
            "name_b": name_by_id.get(b, f"#{b}"),
            "display_a": display_by_id.get(a, f"#{a}"),
            "display_b": display_by_id.get(b, f"#{b}"),
            "count": cnt,
        }

    # Recent rate: count new pairs introduced in the last N rounds.
    # rounds are sorted DESC by created_at, so rounds[:3] is the most recent.
    recent_rate = 0.0
    if rounds:
        recent = rounds[:3]
        # Walk rounds oldest-to-newest among these, tracking cumulative pair set
        recent_ids = [r["id"] for r in reversed(recent)]
        with get_connection() as conn:
            placeholders = ",".join("?" * len(recent_ids))
            assignment_rows = conn.execute(
                f"SELECT round_id, table_id, student_id FROM assignments "
                f"WHERE round_id IN ({placeholders}) ORDER BY round_id, table_id",
                recent_ids
            ).fetchall() if recent_ids else []
        # Reconstruct per-round pair sets
        from collections import defaultdict
        round_tables: dict = defaultdict(lambda: defaultdict(list))
        for row in assignment_rows:
            round_tables[row["round_id"]][row["table_id"]].append(row["student_id"])
        # Count new-pair introductions in each round (assuming pre-history
        # from earlier rounds). Approximation: use recent rounds only, treating
        # those as the window. First round in window counts all pairs as "new"
        # to the window; later ones count only pairs not yet seen in window.
        seen: set = set()
        new_per_round = []
        for rid in recent_ids:
            this_round_pairs = set()
            for students_at_table in round_tables[rid].values():
                for i in range(len(students_at_table)):
                    for j in range(i + 1, len(students_at_table)):
                        a, b = sorted([students_at_table[i], students_at_table[j]])
                        this_round_pairs.add((a, b))
            new_this = len(this_round_pairs - seen)
            new_per_round.append(new_this)
            seen.update(this_round_pairs)
        if new_per_round:
            recent_rate = sum(new_per_round) / len(new_per_round)

    return {
        "total_students":        total_students,
        "active_students":       active_students,
        "total_rounds":          len(rounds),
        "total_possible_pairs":  total_possible_pairs,
        "unique_pairs_seen":     unique_pairs_seen,
        "total_pairings":        total_pairings,
        "pair_counts":           pair_counts,
        "most_repeated":         most_repeated,
        "recent_rate":           recent_rate,
    }

def get_student_pairings(class_id: int, student_id: int) -> dict:
    """
    Returns info about who this student has paired with.
    {
      "paired": [{"id", "name", "count"}, ...]  sorted by count desc, then name
      "never_paired": [{"id", "name"}, ...]     sorted by name
    }
    """
    pair_counts = get_pair_history(class_id)
    students = get_students_for_class(class_id, active_only=False)
    name_by_id = {s["id"]: s["name"] for s in students}

    paired_counts: dict = {}
    for (a, b), cnt in pair_counts.items():
        if a == student_id:
            paired_counts[b] = cnt
        elif b == student_id:
            paired_counts[a] = cnt

    paired = [
        {"id": sid, "name": name_by_id.get(sid, f"#{sid}"), "count": cnt}
        for sid, cnt in paired_counts.items()
    ]
    paired.sort(key=lambda p: (-p["count"], p["name"]))

    never_paired = [
        {"id": s["id"], "name": s["name"]}
        for s in students
        if s["id"] != student_id and s["id"] not in paired_counts
    ]
    never_paired.sort(key=lambda s: s["name"])

    return {"paired": paired, "never_paired": never_paired}