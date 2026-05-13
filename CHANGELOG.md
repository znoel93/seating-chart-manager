# CHANGELOG

Running log of changes by release. Organized by user-facing theme
rather than build order. v2.0.0 is the current public release;
v1.0.0 was the initial public release.

This file is for internal tracking. User-facing release notes are
distilled from this into `RELEASE_NOTES_v<version>.md`.

---

## [Released] — v2.0.0

### New features

#### Activities — a new kind of round
- **Activity definitions** — alongside seating, classes can now define
  named activities with capacity and description (tutoring, shadowing,
  helper rotations, etc.). Activities are managed on the new
  **Activity Rounds** tab inside a class.
- **Activity rounds** — generate weekly assignments of students to
  activities with one click. The activity optimizer balances two goals:
  minimize repeat pairings (students who shared a group before) and
  minimize repeat activities (a student doing the same activity week
  after week). Pair-repeat is the dominant signal; activity rotation
  is a secondary preference.
- **Force-fill for activities** — the same balanced-distribution
  algorithm used for seating. Activities fill evenly rather than
  clustering students.
- **Activity pins** — pin a student to a specific activity to force
  the optimizer to assign them there every round. Separate from
  seating pins; the two can coexist on the same student.
- **Per-student activity exclusions** — mark students as ineligible
  for specific activities ("Alice cannot do tutoring"). Hard
  constraint enforced by the optimizer.
- **Round-level exclusions** — skip specific activities for a given
  week without removing them from the class entirely.
- **Result view** — each activity gets its own column-card showing
  the students assigned to it. Success/concern coloring on the
  headline. Separate display of pair-repeat count and activity-repeat
  count.
- **Round history** — every activity round is saved. Browse past
  rounds, view their results, or delete stale rounds (with a warning
  that past rounds contribute to pair history).
- **View past activity rounds** — reopen any saved round's result
  view from the Rounds list.

#### Unified Stats panel (initial v2.0 work — see "Stats panel redesign" below for the shipped version)
- The old **Pair History** tab has been replaced by a new **Stats**
  tab with richer, class-wide analytics:
  - Summary line showing round counts for each type
  - Mode filter (All / Seating only / Activities only) for classes
    that use both round types
  - Pair History section (same search + treeview UX as before,
    filtered by the mode)
  - Student-Activity history heatmap — see how many times each
    student has done each activity, with color tinting for
    at-a-glance scanning
- Stats are now accessible from a single tab regardless of whether
  a class uses seating, activities, or both.

#### Student Tags — soft optimizer hints (Phase 4)
- **Custom tag categories** per class (Reading Level, Study Buddies,
  Drama-Prone, anything teachers want to track). Each category has an
  **operation** that tells the optimizer what to do:
  - **Distribute** — spread students with the same value across
    different tables/activities (e.g. one strong reader per group)
  - **Cluster** — try to put students with the same value together
    (e.g. study buddies who work well as a unit)
  - **Keep apart** — try to keep students with the same value in
    DIFFERENT groups (e.g. classroom-management pairs)
  - **Ignore** — track for organization only, no optimizer effect
- **Per-student tag assignment** via the new 🏷️ Tags button on the
  roster. Click a value pill to assign or unassign.
- **Tag Rules** dialog (roster action bar) — manage categories,
  values, colors, and operations all in one place.
- **Soft constraints, not hard ones.** Tag rules nudge the optimizer
  but never override pair-history rotation or pin/exclusion
  requirements. When in doubt, manual override is always available.
- **Roster Tags column** shows each student's tag values for quick
  scanning. Hidden when no tags are defined.
- **Tag distribution in Stats** — the Tags sub-tab shows a per-category
  breakdown of how the most recent round honored each rule, with
  quality verdicts (Perfectly distributed / Well distributed / Mixed,
  All N clustered / K of N clustered, Fully respected / N violations).
- **Zero performance overhead for classes without tags.** All tag
  code paths short-circuit when a class has no non-ignore categories.

#### Activity round manual edit
- New **✎ Edit Assignments** button in the activity round result
  dialog, mirroring the seating equivalent. Click a student to pick
  them up, click another student to swap, or click an empty slot to
  move them. Full undo stack with descriptive labels (Cmd+Z), Esc
  cancels a pickup.
- Warnings on changes that create rule conflicts: 📌 pin violations,
  ⛔ exclusion violations, 🚫 forbidden-pair pairings. Teacher can
  proceed anyway after confirming.
- Pair-repeat score is recomputed on save against the full activity
  pair history. The round is marked as edited so teachers can see at
  a glance which rounds were hand-tweaked.

#### Stats panel redesign
- The Stats tab now houses **everything** — the previous Stats and the
  old "Full Stats" Toplevel are merged into one unified panel
  accessible from the main tab bar.
- **Sub-tabs within Stats**: Overview, Pair History, Heatmap, Per
  Student, and Tags (when applicable). The mode filter
  (All / Seating only / Activities only) sits above all sub-tabs and
  applies to every view uniformly.
- The Seating Rounds tab's banner button is now **View Stats →** and
  switches to the Stats tab instead of opening a separate window.
- **Rotation momentum is now mode-aware** — for "Seating only" the
  metric counts new pairings across seating rounds; for "Activities
  only", across activity rounds; for "All", across the merged
  timeline (a pair counts as new only if they hadn't been paired in
  EITHER kind of prior round).


- **New class-level setting** (Edit Class → Pair history) controlling
  whether seating and activity rounds share one pair-history pool
  (combined, default) or track independently (separate). Only shown
  when a class has activities defined.
- Combined mode means the optimizer treats all co-occurrences
  equally — a pair who sat together once and did an activity together
  twice counts as having been paired three times.
- Separate mode means seating and activities rotate independently.
  Use this if you want variety at the group level regardless of how
  students have interacted in the other context.

#### Roster improvements
- The per-student pin dialog now adapts to what the class has
  configured. Classes with only a layout see the seating pin picker;
  classes with only activities see the activity pin + exclusions
  picker; classes with both show a chooser first.
- The **Pinned To** column now surfaces activity pins (🎯) and
  exclusion counts alongside seating pins (📌), giving teachers a
  single-glance view of every student's pinning state.

#### Layout Export and Import (Phase 2)
- **Per-layout Export** — export any layout to a `.json` file from the
  Layouts page. File is self-contained: tables, seats, positions,
  shapes, rotation, and decorative flags all round-trip faithfully.
- **Layout Import** — import a previously-exported `.json` file. If a
  layout with the same name exists, the imported copy is automatically
  renamed (e.g. "U-Shape (imported)"). Schema versioning built in for
  future format changes.
- Good for sharing classroom templates with colleagues.

#### Balanced Student Distribution (Phase 2)
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

#### Backup, Restore, and Data Migration (Phase 1)
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

### Under the hood

#### New modules
- `backup.py` — all backup/restore/import/export logic. No Tk or PuLP
  dependencies; pure file and SQLite operations.
- `layout_io.py` — layout JSON serialization/deserialization with
  strict validation and atomic rollback on mid-import failures.
- `seating_distribution.py` — balanced-distribution algorithm shared
  by seating AND activity optimizers. Pure function, fully unit-tested.
- `activity_optimizer.py` — ILP-based student-to-activity assignment.
  Weighted objective combining pair-repeat cost (dominant) with
  student-activity repeat cost (secondary). Uses the shared
  distribution algorithm for balanced filling. Handles pins,
  exclusions, and forbidden pairs.

#### Schema additions
- Four new tables: `activities`, `activity_rounds`,
  `activity_assignments`, `activity_exclusions`
- Two new columns: `classes.pair_history_mode`,
  `students.pinned_activity_id`
- All migrations idempotent; existing v1.x databases upgrade cleanly.

#### Packaging
- `setup.py` now explicitly lists all local modules in `INCLUDES` to
  protect against py2app missing deferred imports.

#### UI helpers
- `_page_header` now accepts a `secondary_actions` list for pages with
  multiple peer actions (e.g. Layouts has both "+ New Layout" and
  "Import…").
- `_blend_colors` module helper for the Stats heatmap tinting.

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

- **`pack_propagate(False)` + `width=N` produces zero-height widgets.**
  If you need a fixed-width but flexible-height card, control width
  via `wraplength` on the inner labels, not by constraining the frame.
  See the activity result card rendering — originally suppressed
  card heights to 0 until this was fixed.

- **Integration tests should use the app's own creation functions.**
  When testing something like layout round-trip, don't manually
  construct test data — it may use values (like `shape="circle"`)
  that the app never produces. Tests then pass against the wrong
  assumptions. Use `db.add_preset_table` or equivalent so the test
  exercises real data shapes.

### Migration notes for users upgrading from v1.0.0

- No manual migration required. `init_db()` runs idempotently on
  first launch of v2.0.0 and adds all new schema.
- Existing layouts, classes, rounds, and pair history are fully
  preserved.
- The **Pair History** tab has been renamed to **Stats** and gained
  new capabilities (mode filter, student-activity heatmap). Existing
  bookmarks or muscle memory will need to adjust.
- Backup/restore is the recommended first action after upgrading —
  take a manual backup before exploring the new features.

### Known changes in behavior (potential surprises)

- **Force-fill changes seating output for some classes.** Where
  previously the optimizer might have left a table empty and clustered
  students elsewhere, it now distributes evenly. This is the intended
  improvement but may look different from what teachers got used to
  in v1.0.0. The total pair-repeat score is typically unchanged or
  slightly better; the distribution is the visible difference.

- **The "Pair History" tab is gone.** Its content moved into the new
  Stats tab, with more functionality added. The data underneath is
  identical; only the presentation changed.

- **Classes with both seating and activity rounds share pair
  history by default.** This is the new "combined" mode. If a teacher
  wants the old seating-only behavior, they can switch to "separate"
  mode in Edit Class. This setting only appears for classes with
  activities defined.

---

## [Released] — v1.0.0 (initial public release)

Baseline release. Features not listed here are assumed to have been
in v1.0.0.