# CHANGELOG

Running log of changes between v1.0.0 (current public release) and
v2.0.0 (next release, in development). Organized by user-facing theme
rather than build order.

This file is for internal tracking during development. At ship time,
the user-facing release notes will be distilled from this.

---

## [Unreleased] — v2.0.0

### New features

#### Backup, Restore, and Data Migration
- **Manual backups** — create a labeled snapshot of your current data
  any time from Settings → Data. Backups are stored in your user data
  folder and listed in Settings with timestamps, sizes, and a preview
  of each backup's contents (class/round/student counts).
- **Automatic backups** — before any risky operation (import, restore),
  an automatic backup of your current state is created so you can undo
  the change. Auto-backups are capped at 5 (oldest rotates out);
  manual backups are unlimited.
- **Restore** — roll back to any saved backup with one click. Your
  current data is automatically preserved first. After restore, the app
  refreshes to show the restored state.
- **Export data** — save your full database to a `.db` file you choose
  (external drive, cloud folder, etc.). Good for migrating between
  Macs or creating off-site backups.
- **Import data** — replace your current data with the contents of a
  previously-exported file. Validates the source file before replacing;
  rejects files that aren't valid Seating Chart Manager databases.
- Scroll position is preserved across backup/restore operations — no
  jumps to the top of Settings.

#### Layout Export and Import
- **Per-layout Export** — export any layout to a `.json` file from the
  Layouts page. File is self-contained: tables, seats, positions,
  shapes, rotation, and decorative flags all round-trip faithfully.
- **Layout Import** — import a previously-exported `.json` file. If a
  layout with the same name exists, the imported copy is automatically
  renamed (e.g. "U-Shape (imported)"). Schema versioning built in for
  future format changes.
- Good for sharing classroom templates with colleagues.

#### Balanced Student Distribution
- **Force-fill** — the optimizer now distributes students evenly
  across active tables. Previously, small classes could end up with
  students clustered at a few tables and others empty. Now, the target
  per table is computed automatically (`N // tables` with remainder
  distributed to larger tables first) and enforced as a hard
  constraint. Works with both per-table and per-seat seating modes.
- Pins are honored — if students are pinned to specific tables, the
  distribution adjusts to accommodate them. Infeasible pin
  configurations surface clearly.
- Teachers who want uneven distribution (e.g. small-group sessions) can
  still use the existing "excluded tables" mechanism to shrink the
  active table pool.

### Under the hood

#### New modules
- `backup.py` — all backup/restore/import/export logic. No Tk or PuLP
  dependencies; pure file and SQLite operations.
- `layout_io.py` — layout JSON serialization/deserialization with
  strict validation and atomic rollback on mid-import failures.
- `seating_distribution.py` — balanced-distribution algorithm shared
  between both optimizers. Pure function, fully unit-tested.

#### Packaging
- `setup.py` now explicitly lists all local modules in `INCLUDES` to
  protect against py2app missing deferred imports.

#### UI helpers
- `_page_header` now accepts a `secondary_actions` list for pages with
  multiple peer actions (e.g. Layouts has both "+ New Layout" and
  "Import…").

### Rules and lessons learned (developer-facing)

These will NOT appear in user-facing release notes but are worth
recording for future reference.

- **Scroll preservation across content rebuild uses pixel offsets, not
  fractions.** Fractions are only safe when content above the viewport
  changes. When content within or below the viewport changes (cards
  added or removed), snapshot the absolute pixel offset
  (`top_fraction × content_height`) and restore as
  `pixel_offset / new_content_height`. Tk's yview_moveto clamps to
  content bounds automatically, which handles the "scrolled to bottom
  when content shrinks" case cleanly.

- **Local modules imported inside methods (deferred imports) need
  explicit `INCLUDES` in setup.py.** py2app's static analyzer follows
  top-level imports reliably but can miss deferred ones.

- **Every SQLite connection in this app is per-query, opened and
  closed via `get_connection()`.** This is what makes the
  file-replace-then-rebuild pattern safe in backup/restore without
  connection bookkeeping.

### Migration notes for users upgrading from v1.0.0

- No schema migration required for existing features. `init_db()` runs
  idempotently on first launch of v2.0.0.
- First-time launch of v2.0.0 will automatically migrate pre-v1.0.0
  databases (if found in legacy locations) to the user data folder,
  as before.
- Existing layouts, classes, rounds, and pair history are fully
  preserved.
- Backup/restore is the recommended first action after upgrading —
  take a manual backup before exploring the new features.

### Known changes in behavior (potential surprises)

- **Force-fill changes seating output for some classes.** Where
  previously the optimizer might have left a table empty and clustered
  students elsewhere, it now distributes evenly. This is the intended
  improvement but may look different from what teachers got used to
  in v1.0.0. The total pair-repeat score is typically unchanged or
  slightly better; the distribution is the visible difference.

---

## [Released] — v1.0.0 (initial public release)

Baseline release. Features not listed here are assumed to have been
in v1.0.0.