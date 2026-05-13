# Seating Chart Manager — v2.0.0

A major release built on the v1.0.0 foundation. New ways to organize
your class (activity rounds, student tags), unified analytics, manual
editing for everything, and quality-of-life improvements throughout.

## What's new

### Activity Rounds
Manage non-seating groupings — tutoring rotations, helper assignments,
study circles. Define **activities** for a class (with capacity and
description), then generate weekly rounds that distribute students
across them.

The optimizer balances two things at once: avoiding repeat pairings
(students who've shared a group before) and avoiding repeat activities
(a student doing tutoring three weeks in a row). You can also **pin** a
student to a specific activity, or mark them as **excluded** from one
they can't participate in.

Activity round results show a card per activity with the assigned
students. Export to PDF (landscape by default to match your seating
PDFs), edit assignments manually, or browse past rounds.

### Student Tags
Track student attributes — reading level, study buddies, drama-prone
pairs, whatever matters in your classroom — and tell the optimizer
how to use them:

- **Distribute** — spread students with the same value evenly
- **Cluster** — try to keep same-value students together
- **Keep apart** — try to keep same-value students in different groups
- **Ignore** — track but don't influence the optimizer

Set this up via **🚫 Pair Rules → Tag Rules** on a class roster. Then
click the **🏷️ Tags** button to assign values to individual students.
Tags are soft hints — they nudge the optimizer but won't override your
pins, exclusions, or hard pair rules. When the optimizer can't satisfy
every preference, manual edit lets you adjust.

The Stats panel's Tags sub-tab shows how well each round honored your
rules — at a glance you can see "Reading Level: ✓ Perfectly
distributed" or "Drama Pairs: 1 violation" for the most recent round.

### Unified Stats panel
Stats now lives in one place — the **Stats** tab on every class. Sub-
tabs organize the views:

- **Overview** — coverage percentage, most-repeated pair, rotation
  momentum, and (for classes with activities) a student-activity
  heatmap showing repetition counts.
- **Pair History** — searchable table of every pair and how many
  times they've shared a group.
- **Heatmap** — full N×N color-coded pair count grid. Click a cell to
  see the rounds that pair shared.
- **Per Student** — pick a student, see who they've sat with and
  who they haven't.
- **Tags** — per-category respect summary for the most recent round.

A filter at the top — **All / Seating only / Activities only** —
applies across every sub-tab so you can see metrics for just one
context or both combined.

### Manual edit for activity rounds
Activity rounds now have the same hand-edit capability as seating
rounds. Click **✎ Edit Assignments** on any activity round result.
Click a student to pick them up, then click another student to swap or
an empty slot to move them. Full undo with Cmd+Z, Esc cancels.

Warnings show up when an edit creates conflicts (pin violations,
exclusion violations, forbidden-pair pairings) so you can decide
whether to proceed.

### Layout sharing
Export any classroom layout from the Layouts page to a `.json` file.
Tables, seats, positions, shapes, rotations — everything round-trips.
Import a colleague's layout file to use their template. Useful for
sharing standard configurations across a grade level or department.

### Balanced student distribution
The seating optimizer now distributes students evenly across active
tables. Previously, small classes could leave some tables empty while
others clustered. Now N students across T tables target `N/T` per
table (with the remainder spread to larger tables first), enforced as
a hard constraint. Pins are honored; conflicts surface clearly.

If you specifically want uneven distribution, you can still use the
"excluded tables" mechanism to shrink the active pool.

### Backups and data migration
- **Manual backups** — create labeled snapshots any time from
  Settings → Data. Listed with timestamps and preview info.
- **Automatic backups** — created before any risky operation (import,
  restore). Capped at 5; manual backups are unlimited.
- **Restore** — roll back to any saved backup. Your current data is
  preserved first so you can recover from a bad restore.
- **Export / Import data** — save your full database to a file or
  load one from elsewhere. Good for moving between Macs or keeping
  off-site copies.

### Other improvements
- The roster's **Pinned To** column surfaces both seating pins (📌)
  and activity pins (🎯) plus exclusion counts.
- The per-student pin dialog adapts to what the class has configured —
  seating-only, activity-only, or both.
- PDFs honor your class's name-display setting (full, first only,
  first + last initial). Middle names are trimmed in abbreviated
  modes so "Alice Marie Johnson" becomes "Alice J." cleanly.
- Larger seat circles on PDFs (22pt up from 16pt) for better
  readability when printed. Identical font sizing in-app and on PDF
  so what you see matches what prints.
- Rotated tables now render correctly on PDFs — previously a known
  bug.

## Migration notes

- **No manual migration required.** First launch of v2.0.0 runs the
  schema migrations automatically. Existing data is preserved.
- **Take a manual backup right after upgrading.** Settings → Data →
  Create Backup. Habit for the long run; insurance for this upgrade.
- **The Pair History tab is now part of Stats.** Same data,
  reorganized; the table you used before is the "Pair History"
  sub-tab.
- **Force-fill may change your seating outputs.** If your class had
  small enrollment and the old optimizer left some tables empty,
  v2.0.0 will distribute evenly instead. The pair-repeat score is
  typically unchanged or better; the visible difference is the spread.

## Known potential surprises

- Classes with both seating AND activity rounds now share pair
  history by default ("combined" mode). If you want them tracked
  independently, switch to "separate" mode in Edit Class.
- Tag rules are deliberately soft. The optimizer will break them if
  necessary to satisfy pins, exclusions, or capacity. Use the Stats
  → Tags view to see what was honored each round, and manual edit
  to override.

---

For developers / agents: see `CHANGELOG.md` for the full internal
change log organized by phase. For build instructions, `BUILD.md`.
