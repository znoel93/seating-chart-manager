"""
layout_io.py — Export and import classroom layouts as JSON.

A layout is self-contained (tables + seats, no cross-references to
classes, students, or rounds) so round-tripping it through JSON is
clean: we capture structure, not database identity. Every import
creates a brand-new layout with fresh DB IDs; two imports of the
same file produce two distinct layouts.

File format uses a small wrapper object with metadata so we can
validate what we're looking at and detect version mismatches:

    {
      "format": "seating-chart-manager-layout",
      "schema_version": 1,
      "exported_at": "2026-04-21T18:30:00Z",
      "exported_from_version": "1.1.0",
      "layout": {
        "name": "U-Shape Classroom",
        "tables": [
          {
            "label": "Table 1",
            "shape": "rect",
            "capacity": 4,
            "pos_x": 120.0,
            "pos_y": 80.0,
            "width": 140.0,
            "height": 90.0,
            "rotation": 0.0,
            "decorative": false,
            "seats": [
              {"x_offset": -60.0, "y_offset": -45.0},
              ...
            ]
          },
          ...
        ]
      }
    }

Name collisions on import are handled by appending " (imported)" or
" (imported N)" suffixes — silent for a first import, visibly
suffixed on re-imports so the teacher can see and rename if desired.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import db


FORMAT_TAG     = "seating-chart-manager-layout"
SCHEMA_VERSION = 1


# Mirror of the app version. Kept in sync manually for now — this gets
# stamped into every export for debugging future imports. If we ever
# have a runtime version constant we can import, swap this for that.
APP_VERSION = "1.1.0"


def export_layout_to_dict(layout_id: int) -> dict:
    """Build the JSON-serialisable dict for a layout. Raises
    ValueError if the layout doesn't exist."""
    layout = db.get_layout(layout_id)
    if layout is None:
        raise ValueError(f"Layout {layout_id} not found")

    tables_data = []
    for t in db.get_tables_for_layout(layout_id):
        seats = db.get_seats_for_table(t["id"])
        tables_data.append({
            "label":      t["label"],
            "shape":      t["shape"],
            "capacity":   t["capacity"],
            "pos_x":      t["pos_x"],
            "pos_y":      t["pos_y"],
            "width":      t["width"],
            "height":     t["height"],
            "rotation":   t["rotation"],
            "decorative": bool(t["decorative"]),
            "seats": [
                {"x_offset": s["x_offset"], "y_offset": s["y_offset"]}
                for s in seats
            ],
        })

    return {
        "format":                FORMAT_TAG,
        "schema_version":        SCHEMA_VERSION,
        "exported_at":           datetime.now(timezone.utc).isoformat(),
        "exported_from_version": APP_VERSION,
        "layout": {
            "name":   layout["name"],
            "tables": tables_data,
        },
    }


def export_layout_to_path(layout_id: int, dest: Path) -> Path:
    """Export a layout to a JSON file at `dest`. Returns the resolved
    path written. Raises ValueError if layout not found, OSError for
    file-system issues."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = export_layout_to_dict(layout_id)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return dest


def _validate_payload(payload) -> dict:
    """Check that `payload` is a parsed layout-export dict with all
    required structure. Returns the validated payload; raises
    ValueError with a user-readable message on any problem.

    Validates the wrapper (format tag + schema version), the layout
    object (name + tables), and each table (all required fields with
    reasonable types). Seats are validated structurally but accept any
    numeric offsets — extreme values are the teacher's problem, not a
    reason to reject an import.
    """
    if not isinstance(payload, dict):
        raise ValueError("File is not a layout export (expected a JSON object).")

    tag = payload.get("format")
    if tag != FORMAT_TAG:
        raise ValueError(
            "This doesn't look like a layout file."
            + (f" (format: {tag!r})" if tag else "")
        )

    version = payload.get("schema_version")
    if not isinstance(version, int):
        raise ValueError("Missing or invalid schema_version.")
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"This layout was exported by a newer version of the app "
            f"(schema {version}, this app understands {SCHEMA_VERSION}). "
            "Please update the app to open it."
        )

    layout = payload.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("Missing 'layout' object.")

    name = layout.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Layout has no name.")

    tables = layout.get("tables")
    if not isinstance(tables, list):
        raise ValueError("Layout has no 'tables' list.")

    valid_shapes = {"rect", "round"}
    for i, t in enumerate(tables):
        if not isinstance(t, dict):
            raise ValueError(f"Table #{i+1} is not an object.")
        for required_str, typ in [("label", str), ("shape", str)]:
            v = t.get(required_str)
            if not isinstance(v, typ):
                raise ValueError(f"Table #{i+1} missing or invalid {required_str!r}.")
        if t["shape"] not in valid_shapes:
            raise ValueError(
                f"Table #{i+1} has unknown shape {t['shape']!r}. "
                f"Expected one of: {sorted(valid_shapes)}.")
        cap = t.get("capacity")
        if not isinstance(cap, int) or cap < 0:
            raise ValueError(f"Table #{i+1} has invalid capacity {cap!r}.")
        for numeric_field in ("pos_x", "pos_y", "width", "height", "rotation"):
            v = t.get(numeric_field)
            if v is not None and not isinstance(v, (int, float)):
                raise ValueError(
                    f"Table #{i+1} has invalid {numeric_field}: {v!r}")
        seats = t.get("seats", [])
        if not isinstance(seats, list):
            raise ValueError(f"Table #{i+1} has invalid 'seats' list.")
        for j, s in enumerate(seats):
            if not isinstance(s, dict):
                raise ValueError(
                    f"Table #{i+1}, seat #{j+1} is not an object.")
            for field in ("x_offset", "y_offset"):
                v = s.get(field)
                if not isinstance(v, (int, float)):
                    raise ValueError(
                        f"Table #{i+1}, seat #{j+1} has invalid "
                        f"{field}: {v!r}")

    return payload


def _unique_name(requested: str) -> str:
    """Return `requested` if no layout has that name, otherwise
    append ' (imported)' and incremental disambiguators until a
    free name is found."""
    existing = {l["name"] for l in db.get_all_layouts()}
    if requested not in existing:
        return requested
    base = f"{requested} (imported)"
    if base not in existing:
        return base
    for i in range(2, 100):
        candidate = f"{requested} (imported {i})"
        if candidate not in existing:
            return candidate
    # Pathological; user has imported the same file 100 times
    return f"{requested} (imported {len(existing)})"


def import_layout_from_path(src: Path) -> tuple[int, str]:
    """Load a JSON file and create a new layout from its contents.
    Returns (new_layout_id, final_name). Raises ValueError with a
    user-readable message on any problem."""
    src = Path(src)
    if not src.exists():
        raise ValueError(f"File does not exist: {src}")
    try:
        with open(src, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"This doesn't look like a valid layout file (invalid JSON: "
            f"line {e.lineno}, column {e.colno}).")
    except OSError as e:
        raise ValueError(f"Could not read file: {e}")

    return _import_payload(payload)


def _import_payload(payload) -> tuple[int, str]:
    """Shared guts of import: validate, resolve name collision, insert.
    Separated out so tests can exercise the core path without writing
    and re-reading a file."""
    payload = _validate_payload(payload)
    requested_name = payload["layout"]["name"].strip()
    final_name = _unique_name(requested_name)

    new_id = db.create_layout(final_name)
    try:
        for t in payload["layout"]["tables"]:
            # Use a dedicated helper that inserts without auto-seeding
            # seats (we want to preserve exact seat positions from the
            # export, not let _seed_default_seats re-place them).
            table_id = _insert_table_verbatim(new_id, t)
            for s in t.get("seats", []):
                db.add_seat(table_id, float(s["x_offset"]),
                                       float(s["y_offset"]))
            # add_seat() updates the table capacity as a side effect
            # (syncing to seat count). If the imported capacity differs
            # from the number of seats (e.g. a decorative table or
            # intentionally over/under-seated), restore the original
            # capacity after seats are added.
            desired_cap = int(t.get("capacity", 0))
            _sync_table_capacity(table_id, desired_cap)
    except Exception:
        # Roll back the partial layout on any import failure
        try:
            db.delete_layout(new_id)
        except Exception:
            pass
        raise

    return new_id, final_name


def _insert_table_verbatim(layout_id: int, table_data: dict) -> int:
    """Insert a table with ALL its structural fields set from
    `table_data`, without triggering any seat auto-seeding. Returns
    the new table_id.

    Separate from db.add_preset_table (which auto-seeds) because on
    import we've already got the exact seat layout to preserve."""
    # Use a direct SQL insert so we can set every column in one shot
    # without going through add_preset_table's seat-seeding path.
    with db.get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tables
               (layout_id, label, capacity, pos_x, pos_y,
                shape, width, height, rotation, decorative)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (layout_id,
             table_data["label"],
             int(table_data["capacity"]),
             table_data.get("pos_x"),
             table_data.get("pos_y"),
             table_data["shape"],
             float(table_data.get("width", 140)),
             float(table_data.get("height", 90)),
             float(table_data.get("rotation", 0)),
             1 if table_data.get("decorative") else 0))
        return cur.lastrowid


def _sync_table_capacity(table_id: int, desired: int) -> None:
    """Force a table's capacity column to `desired`, overriding any
    auto-sync that db.add_seat() may have applied."""
    with db.get_connection() as conn:
        conn.execute("UPDATE tables SET capacity=? WHERE id=?",
                      (desired, table_id))