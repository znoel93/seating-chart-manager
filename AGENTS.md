# AGENTS.md — Context for AI assistants

This document orients an AI assistant (Claude, etc.) to the Seating Chart Manager project. If you're working with this codebase through an AI, paste this whole file as your first message in a fresh conversation.

## Project overview

**What:** A desktop app for teachers to generate optimal classroom seating charts. Takes a roster and a classroom layout, produces assignments that minimize repeat tablemate pairings across rounds.

**Stack:**
- Python 3.10+
- Tkinter (UI) + Tk 9.0
- SQLite (persistence)
- PuLP + CBC solver (integer linear programming for seat assignment)
- ReportLab (PDF export)
- py2app (macOS packaging)

**Target platform:** macOS (Apple Silicon). Packaged as `.app` + `.dmg`. Teachers don't need Python installed.

**Current version:** v1.0.0 (first shipped release).

**Public repo:** https://github.com/znoel93/seating-chart-manager

## File structure

```
seating_app/
├── main.py                    # Entry point — just launches SeatingApp from ui.py
├── ui.py                      # ~7400 lines. ALL Tkinter UI, main window, dialogs, views
├── db.py                      # ~1460 lines. SQLite schema, queries, migrations
├── theme.py                   # 18 theme palettes + fonts
├── room_canvas.py             # ~1020 lines. Drag-to-arrange room layout widget
├── optimizer.py               # Per-seat ILP optimizer (PuLP)
├── optimizer_table_mode.py    # Per-table ILP optimizer (PuLP)
├── exporter.py                # PDF generation (ReportLab) — table list + room view
├── setup.py                   # py2app build config
├── build_app.sh               # One-command build → dmg
├── packaging/
│   ├── icon.svg               # Source icon (chair on green squircle)
│   └── make_icns.sh           # SVG → .icns converter
├── INSTALL.md                 # For end-user teachers
├── BUILD.md                   # For developers
├── README.md
└── requirements.txt
```

## Critical permanent rules — DO NOT BREAK THESE

These were learned through painful trial and error. Every rule here represents a bug that took nontrivial effort to find.

### Tkinter rules

1. **Never `padx=(N, M)` or `pady=(N, M)` in a widget CONSTRUCTOR.** Tuples for asymmetric padding only go on `.pack()` or `.grid()`. Passing them to the constructor silently fails or renders weirdly. There's a scanner in the codebase; run after any UI edit.

2. **Never use `pack_propagate(False)` for fixed-width-flexible-height layouts.** It locks BOTH dimensions, not just width.

3. **Never re-bind `event_generate` target to itself.** Infinite recursion.

4. **Always-visible scrollbars only.** Dynamic `pack()/pack_forget()` of scrollbars causes SIGSEGV on macOS Tk.

5. **No threading for DB reads on macOS.** Use `self.after_idle()` instead.

6. **`self.master` on Toplevel returns the root `SeatingApp` instance.** Useful for classmethod access across dialogs.

7. **`<Configure>` bindings must live on the widget whose lifecycle matches their target.** Never bind on `parent` if handler touches `child` — causes TclError race when child destroyed first.

### Database rules

1. **Cache invalidation pattern:** Operations that change layout-lock state (delete class/round, generate round, new/edit/duplicate class, archive toggle) MUST invalidate BOTH the "classes" cache AND the "layouts" cache.

2. **Use `rounds.id < target_id` to define "prior" history**, NOT `rounds.id != target_id`. Round N's repeat count must only consider rounds created before it, so it stays stable as later rounds are added. The `!=` pattern was a major bug fixed in v1.0.0.

### Architecture rules

1. **Display vs identity separation for student names.** `students.name` is the stored natural-order full name ("Billy Bob Thornton"). `students.first_name` and `students.last_name` are the authoritative split. `classes.name_display` (one of `full`, `first_initial`, `first_only`) drives rendering. All rendering paths use a `display` field enriched by the DB layer; all identity/matching uses `name`. Never fake a split by parsing `name` at render time — use the stored first/last.

2. **Layout locking = read-only.** When a layout has been used in a round, it's "locked" — its RoomCanvas must be built with `mode="view"` (no mouse bindings at all), not `mode="edit"` with handler guards. Edit mode with guards is still exploitable.

3. **Seating mode is per-round, not per-class.** A round is stamped with the mode it was generated in. Switching class mode affects new rounds only.

### Copyright / safety rules

None relevant — this is a first-party project, no external content.

## Key architectural concepts

### Two seating modes
- **Per-table:** students are assigned to tables only. Fast, simple. Use for most rotations.
- **Per-seat:** students are assigned to specific seats within tables. Use when seat position matters (labs, group work).

A class has one current mode; rounds inherit the mode at generation time.

### Layout lifecycle
- Layouts can be drafted freely until used in a round
- Using a layout in a round LOCKS it (prevents structural edits to preserve historical integrity)
- "Duplicate" an unlocked copy to keep iterating
- Layout editor has a read-only view mode for locked layouts

### Round generation flow
1. User opens class → Rounds tab → Generate New Round
2. Pre-generation dialog: mark absent students, exclude specific tables
3. Optimizer runs (PuLP + CBC) minimizing weighted adjacency score
4. Result displayed with pairing score + "true repeats" count
5. On save, assignments stored + round created
6. `repeat_score` stamped at generation time

### The display-mode feature (for names)
- Three modes per class: `full` / `first_initial` / `first_only`
- Picker lives on the Roster tab header
- All render sites read `display` field (precomputed by DB layer enrichment)
- Parser handles `"Last, First"`, `"First Last"`, mononyms
- Multi-word first/last names preserved ("Billy Bob Thornton", "Jon Van Der Berg")

## Dev habits

- **Run the tuple-in-constructor scanner after any UI edit.** Script in BUILD.md.
- **Regenerate the design doc** at session start if working on design.
- **Always upload `outputs/game.py` or the current session file** at start of deep-dive sessions.
- **Use `ui.py` + `db.py` as the workspace** — most changes touch both.

## User preferences and style

- CS grad
- Strong design sense; catches subtle UX issues
- Pushes back on over-engineering — prefers surgical fixes over architectural overhauls
- Trusts gut calls; likes being asked about design choices with recommendations rather than open-ended "what do you think?"
- Comfortable pausing to verify via test before proceeding
- Prefers natural, matter-of-fact tone — no sycophancy

## Current status

**Shipped:** v1.0.0 — first release to teachers at Zach's school via .dmg.

**Known remaining roadmap (optional, nothing urgent):**
- Attendance persistence between round generations
- PNG / printable HTML export (on-demand only)
- PowerSchool CSV import improvements (blocked on sample file)

**Permanent backlog notes:** anything grab-bag unless real-use friction surfaces.

## Common tasks reference

**To build a new .dmg:**
```
./build_app.sh
```

**To ship a new version:**
1. Bump `CFBundleShortVersionString` + `CFBundleVersion` in `setup.py`
2. Commit, push
3. `./build_app.sh`
4. Tag via GitHub Desktop (right-click commit → Create Tag)
5. Push tag
6. GitHub → Releases → Draft new release → upload .dmg → publish

**To fix a UI bug:**
1. Reproduce
2. Fix
3. Run the tuple-in-constructor scanner
4. Syntax-check: `python3 -c "import ast; ast.parse(open('ui.py').read())"`
5. Copy to outputs, test
6. Commit via GitHub Desktop

## Data location

The app writes to per-user OS convention paths:
- macOS: `~/Library/Application Support/SeatingChartManager/seating_chart.db`
- Windows: `%APPDATA%\SeatingChartManager\seating_chart.db`
- Linux: `~/.local/share/SeatingChartManager/seating_chart.db`

First launch migrates legacy DBs found next to the script/executable.
