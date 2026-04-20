# Seating Chart Manager

A desktop app for teachers to generate optimal classroom seating charts that minimize repeat tablemate pairings across rounds.

Built with Python + Tkinter + SQLite + integer linear programming (via PuLP), with a ReportLab-backed PDF exporter. Packages as a standalone macOS `.app` — teachers don't need Python installed.

## Features

- **Two seating modes.** Per-table (fast, for simple rotations) and per-seat (handles specific seat assignments for group work / labs).
- **ILP-backed optimizer.** Generates rounds that minimize repeat tablemates while honoring per-pair constraints, absent students, and pinned seats.
- **Multi-layout support.** Design classroom layouts visually with a drag-to-arrange room editor. Lock layouts to prevent accidental edits.
- **Pair history.** Tracks which students have sat together how many times, with a full dashboard showing heatmaps, per-student pairings, and recent trends.
- **PDF export.** Both table-list and room-view PDFs, with optional notes.
- **Class archive.** Archive old classes without deleting their data.
- **18 themes.** From default to Retro Terminal to Notebook to Lab.

## Screenshots

_(Add screenshots here once you want to show the app off.)_

## For teachers / end users

See [INSTALL.md](INSTALL.md) for install instructions.

Short version: download the `.dmg` from [Releases](../../releases), drag the app into Applications, right-click → Open on first launch to bypass the unsigned-app warning.

## For developers

### Running from source

```bash
pip3 install -r requirements.txt
python3 main.py
```

Python 3.10+ required. All other dependencies are pip-installable; Tkinter is stdlib.

### Building the macOS app

See [BUILD.md](BUILD.md) for complete build instructions.

Short version:

```bash
# One-time setup
pip3 install py2app
brew install librsvg create-dmg
chmod +x build_app.sh packaging/make_icns.sh

# Every build
./build_app.sh
```

Produces `dist/SeatingChartManager.dmg` ready for distribution.

### Project structure

```
seating_app/
├── main.py                    # Entry point
├── ui.py                      # All Tkinter UI (main window, dialogs, views)
├── db.py                      # SQLite schema + data access
├── theme.py                   # Color palettes and theme system
├── room_canvas.py             # Drag-to-arrange room layout widget
├── optimizer.py               # Per-seat ILP optimizer
├── optimizer_table_mode.py    # Per-table ILP optimizer
├── exporter.py                # PDF generation (table list + room view)
├── setup.py                   # py2app build configuration
├── build_app.sh               # One-command build script
├── requirements.txt           # Python runtime dependencies
├── packaging/
│   ├── icon.svg               # Source icon (edit to change)
│   └── make_icns.sh           # SVG → macOS .icns converter
├── INSTALL.md                 # For teachers
└── BUILD.md                   # For developers
```

### Data location

The app stores its SQLite database at the OS-conventional per-user data path:

| OS      | Path                                                                |
|---------|---------------------------------------------------------------------|
| macOS   | `~/Library/Application Support/SeatingChartManager/seating_chart.db`  |
| Windows | `%APPDATA%\SeatingChartManager\seating_chart.db`                    |
| Linux   | `~/.local/share/SeatingChartManager/seating_chart.db`               |

First launch migrates any legacy DB found next to the script or executable.

## License

All rights reserved. © 2026 Zach Noel.

This software is distributed as a compiled application for free use by
teachers. The source code is published publicly for transparency. If you
want to use, modify, or redistribute the source code, please contact me.
