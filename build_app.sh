#!/bin/bash
# build_app.sh — One-command build for Seating Chart Manager.
#
# Runs the complete packaging pipeline:
#   1. Generate the .icns icon from icon.svg (if not already built
#      or if icon.svg is newer)
#   2. Run py2app to produce dist/SeatingChartManager.app
#   3. Wrap the .app in a .dmg installer
#
# Output: dist/SeatingChartManager.dmg
#
# Run from the project root:
#     ./build_app.sh
#
# Prerequisites (one-time setup):
#     pip3 install py2app
#     brew install librsvg create-dmg

set -e  # Exit on any error
cd "$(dirname "$0")"

APP_NAME="SeatingChartManager"
DISPLAY_NAME="Seating Chart Manager"
VERSION="1.0.0"

echo
echo "=========================================="
echo "  Building $DISPLAY_NAME v$VERSION"
echo "=========================================="
echo

# ── Step 1: Build the icon ───────────────────────────────────────────
# Only rebuild if the .icns is missing or icon.svg is newer.
ICNS="packaging/AppIcon.icns"
SVG="packaging/icon.svg"

if [ ! -f "$ICNS" ] || [ "$SVG" -nt "$ICNS" ]; then
    echo "→ Step 1: Building app icon..."
    bash packaging/make_icns.sh
    echo
else
    echo "→ Step 1: Icon up-to-date, skipping."
    echo
fi

# ── Step 2: Clean previous build artifacts ──────────────────────────
# py2app is fussy about stale build dirs — wipe them so we get a clean
# output every time.
echo "→ Step 2: Cleaning previous build..."
rm -rf build dist
echo "  ✓ Removed build/ and dist/"
echo

# ── Step 3: Run py2app ───────────────────────────────────────────────
echo "→ Step 3: Running py2app..."
echo "  (this takes a minute — Python + Tk + PuLP + ReportLab is a lot)"
python3 setup.py py2app 2>&1 | tail -20

# py2app names the .app after CFBundleName from the plist, which has
# spaces ("Seating Chart Manager.app"). We want a shell-friendly no-
# space filename for the output, while keeping the display name the
# user sees. Post-rename is the cleanest way: leaves the plist as
# the source of truth, doesn't fight py2app's internal naming logic.
SPACED_APP="dist/Seating Chart Manager.app"
TARGET_APP="dist/$APP_NAME.app"

if [ -d "$SPACED_APP" ] && [ ! -d "$TARGET_APP" ]; then
    mv "$SPACED_APP" "$TARGET_APP"
    echo "  ✓ Renamed bundle to $TARGET_APP"
fi

if [ ! -d "$TARGET_APP" ]; then
    echo "Error: py2app did not produce a .app bundle" >&2
    echo "  Looked for:  $TARGET_APP" >&2
    echo "  Also tried:  $SPACED_APP" >&2
    echo "  What's in dist/:" >&2
    ls -la dist/ >&2
    exit 1
fi

echo "  ✓ Built $TARGET_APP"
echo "  Size: $(du -sh "$TARGET_APP" | cut -f1)"
echo

# ── Step 4: Package into a .dmg ──────────────────────────────────────
echo "→ Step 4: Creating .dmg installer..."

DMG_PATH="dist/$APP_NAME.dmg"
rm -f "$DMG_PATH"

if command -v create-dmg >/dev/null 2>&1; then
    # create-dmg produces a polished installer with a custom layout:
    # the app icon on the left, an arrow to the Applications alias on
    # the right. Users drag one to the other to install.
    create-dmg \
        --volname "$DISPLAY_NAME" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 128 \
        --icon "$APP_NAME.app" 150 190 \
        --app-drop-link 450 190 \
        --no-internet-enable \
        "$DMG_PATH" \
        "dist/$APP_NAME.app" \
        2>&1 | tail -5
else
    # Fallback: plain hdiutil-based dmg. Functional but not as pretty.
    # No Applications symlink, no custom layout.
    echo "  (create-dmg not installed — using basic hdiutil fallback)"
    echo "  For a prettier installer, run:  brew install create-dmg"
    hdiutil create -volname "$DISPLAY_NAME" \
                   -srcfolder "dist/$APP_NAME.app" \
                   -ov -format UDZO \
                   "$DMG_PATH" \
                   2>&1 | tail -3
fi

echo
echo "=========================================="
echo "  ✓ Build complete"
echo "=========================================="
echo
echo "  App:  dist/$APP_NAME.app"
echo "  DMG:  dist/$APP_NAME.dmg"
echo "  Size: $(du -h "$DMG_PATH" | cut -f1)"
echo
echo "  To distribute: send the .dmg file to your teachers."
echo "  See INSTALL.md for install instructions they should follow."
echo