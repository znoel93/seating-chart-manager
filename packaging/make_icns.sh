#!/bin/bash
# make_icns.sh — Convert icon.svg to a proper macOS .icns file.
#
# This generates every size macOS might ask for and packages them into
# an .icns bundle. Run this once (or whenever you change icon.svg).
# Output: AppIcon.icns in the same directory.
#
# Requires: macOS (uses the built-in iconutil and sips tools).

set -e

cd "$(dirname "$0")"

SRC="icon.svg"
ICONSET="AppIcon.iconset"
OUT="AppIcon.icns"

if [ ! -f "$SRC" ]; then
    echo "Error: $SRC not found in $(pwd)" >&2
    exit 1
fi

echo "→ Generating icon sizes from $SRC..."

# macOS's iconutil expects a directory with specifically-named PNGs.
# Clean any stale iconset from a previous run.
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# macOS icons need these sizes. The @2x variants are Retina-resolution
# versions of the standard size (e.g. 32x32@2x is a 64x64 image used
# at the 32pt size on Retina displays).
#
# Format: "target_size:output_filename"
declare -a sizes=(
    "16:icon_16x16.png"
    "32:icon_16x16@2x.png"
    "32:icon_32x32.png"
    "64:icon_32x32@2x.png"
    "128:icon_128x128.png"
    "256:icon_128x128@2x.png"
    "256:icon_256x256.png"
    "512:icon_256x256@2x.png"
    "512:icon_512x512.png"
    "1024:icon_512x512@2x.png"
)

# We'll use sips (built into macOS) to resize, but sips can't read SVG
# directly. Try rsvg-convert first (from librsvg, often installed via
# Homebrew), then fall back to Inkscape, then to qlmanage.
RENDERER=""
if command -v rsvg-convert >/dev/null 2>&1; then
    RENDERER="rsvg-convert"
elif command -v inkscape >/dev/null 2>&1; then
    RENDERER="inkscape"
else
    echo "Error: Need either rsvg-convert or Inkscape installed." >&2
    echo "Install with:  brew install librsvg" >&2
    exit 1
fi
echo "  Using renderer: $RENDERER"

for entry in "${sizes[@]}"; do
    size="${entry%%:*}"
    fname="${entry##*:}"
    out="$ICONSET/$fname"

    if [ "$RENDERER" = "rsvg-convert" ]; then
        rsvg-convert -w "$size" -h "$size" "$SRC" -o "$out"
    else
        # Inkscape 1.x
        inkscape -w "$size" -h "$size" "$SRC" -o "$out" 2>/dev/null
    fi
    echo "  ✓ $fname ($size x $size)"
done

echo "→ Packaging into $OUT..."
iconutil -c icns -o "$OUT" "$ICONSET"

# Clean up the intermediate iconset dir — the .icns is self-contained
rm -rf "$ICONSET"

echo
echo "✓ Done: $(pwd)/$OUT"
echo "  Size: $(du -h "$OUT" | cut -f1)"
