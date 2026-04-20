# Building Seating Chart Manager

This is a note to future-you (or anyone you hand this to) on how to produce the `.dmg` installer.

## One-time setup

You need three things installed on your Mac:

1. **Python 3.10+** with the project's dependencies installed (whatever you already use to run `main.py`).

2. **py2app** — the tool that packages Python apps into `.app` bundles:
   ```
   pip3 install py2app
   ```

3. **Homebrew packages** for the icon + dmg pipeline:
   ```
   brew install librsvg create-dmg
   ```

   - `librsvg` renders the SVG icon at multiple sizes
   - `create-dmg` wraps the `.app` in a polished installer with drag-to-Applications layout

If you skip `create-dmg`, the build script falls back to a plain `hdiutil` dmg — functional, just less pretty.

4. **Mark the build scripts as executable** (one-time, only needed right after pulling the packaging files):
   ```
   chmod +x build_app.sh packaging/make_icns.sh
   ```

   If you see `permission denied` when running the scripts, you missed this step.

## To build

From the project root (where `main.py` lives):

```
./build_app.sh
```

That's it. The script:

1. Generates `packaging/AppIcon.icns` from `packaging/icon.svg` (only if the SVG changed since last build)
2. Runs py2app to produce `dist/SeatingChartManager.app`
3. Wraps the app in `dist/SeatingChartManager.dmg`

The whole thing takes 1–2 minutes. You'll end up with:

- `dist/SeatingChartManager.app` — the standalone app
- `dist/SeatingChartManager.dmg` — the installer to send to teachers

Send the `.dmg` to your teachers along with `INSTALL.md`.

## If something goes wrong

**"py2app: command not found" or "No module named 'py2app'"**
You didn't install it, or you installed it under a different Python than you're running. Check which Python: `which python3`. Install py2app for that specific Python: `/path/to/python3 -m pip install py2app`.

**"ModuleNotFoundError" at runtime when launching the built app**
py2app missed a dependency. Edit `setup.py` and add the missing module to the `INCLUDES` list, then rebuild.

**"The bundle is not executable" or hang on launch**
Most commonly caused by a stale `build/` directory. `rm -rf build dist` and rebuild — the script does this automatically, but if you ran py2app manually you may have skipped it.

**Icon shows the generic gear icon instead of the chair**
Check that `packaging/AppIcon.icns` exists and is non-empty. Delete it and rerun the build to force regeneration.

**The .dmg opens but dragging the app doesn't install it**
Most likely the user doesn't have permission to write to `/Applications` (some locked-down school Macs). They'd need to drag it to their user Applications folder (`~/Applications`) instead, or ask IT for write access to the main one.

## Updating the icon

Edit `packaging/icon.svg` with any vector editor (Inkscape, Figma export, Illustrator, or by hand — the file is only ~50 lines). Then rebuild — the script detects the SVG is newer than the `.icns` and regenerates.

## Updating the version number

Edit `setup.py` — the `CFBundleShortVersionString` and `CFBundleVersion` fields in the `plist` section. Also update the header string in `build_app.sh` if you want it printed during the build. No automation here — too little value for something that happens every few months.

## Release checklist

Before sending a new build to teachers:

1. Bump version in `setup.py` (both fields)
2. Run `./build_app.sh` — verify it completes without errors
3. **Launch `dist/SeatingChartManager.app` on your own Mac first** — make sure it actually opens and doesn't hit a missing-dependency error
4. Open a class, generate a round — smoke test the core path
5. Send the `.dmg` plus any changelog notes