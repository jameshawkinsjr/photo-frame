#!/bin/sh
#
# Builds "Photo Frame.dmg" - a double-clickable disk image with the app and a
# shortcut to Applications, so installing is a drag across the window.
#
#   sh build_dmg.sh
#
# Run this on any Mac; the result installs on macOS 10.9 and later. The image is
# HFS+ so that 10.13 High Sierra can mount it (an APFS image could not).

set -e

SRC=$(cd "$(dirname "$0")" && pwd)
VOL="Photo Frame"
OUT="$SRC/Photo Frame.dmg"
TMP="$SRC/.dmg-build"
RW="$TMP/rw.dmg"

echo "Building $VOL.dmg"
echo "-------------------"

# A leftover mount from an earlier run would send this to "Photo Frame 1".
if [ -d "/Volumes/$VOL" ]; then
    hdiutil detach "/Volumes/$VOL" -quiet -force 2>/dev/null || true
fi

rm -rf "$TMP" "$OUT"
mkdir -p "$TMP/stage"

# --- the app itself --------------------------------------------------------
sh "$SRC/install.sh" "$TMP/stage" > "$TMP/install.log" 2>&1
if [ ! -d "$TMP/stage/Photo Frame.app" ]; then
    echo "!! The app did not build. See $TMP/install.log"
    exit 1
fi
echo "app bundled"

ln -s /Applications "$TMP/stage/Applications"
mkdir -p "$TMP/stage/.background"
cp "$SRC/dmg_background.png" "$TMP/stage/.background/background.png"
chmod -Rf go-w "$TMP/stage" 2>/dev/null || true

# --- writable image we can dress up ----------------------------------------
hdiutil create -srcfolder "$TMP/stage" -volname "$VOL" -fs HFS+ \
    -format UDRW -ov -quiet "$RW"

MOUNT=$(hdiutil attach "$RW" -readwrite -noverify -noautoopen | \
        grep -o '/Volumes/.*' | head -1)
if [ -z "$MOUNT" ]; then
    echo "!! Could not mount the working image."
    exit 1
fi
echo "mounted at $MOUNT"
MOUNTED_NAME=$(basename "$MOUNT")

# --- window layout ---------------------------------------------------------
# Finder is what stores icon positions and the background, so this part needs
# permission to control Finder. If it is refused the image still works; it just
# opens as a plain window instead of a laid-out one.
STYLED=yes
osascript <<APPLESCRIPT >/dev/null 2>&1 || STYLED=no
tell application "Finder"
    tell disk "$MOUNTED_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {240, 140, 880, 540}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to 96
        set text size of opts to 12
        set background picture of opts to file ".background:background.png"
        set position of item "Photo Frame.app" of container window to {160, 190}
        set position of item "Applications" of container window to {480, 190}
        update without registering applications
        delay 1
        close
    end tell
end tell
APPLESCRIPT

if [ "$STYLED" = "yes" ]; then
    echo "window laid out (icons placed, background set)"
else
    echo "note: could not drive Finder, so the window keeps its default layout."
    echo "      The disk image still installs correctly by dragging."
fi

sync
hdiutil detach "$MOUNT" -quiet || hdiutil detach "$MOUNT" -quiet -force

# --- compress to the final, read-only image --------------------------------
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -o "$OUT" -quiet
rm -rf "$TMP"

SIZE=$(du -h "$OUT" | cut -f1)
echo ""
echo "Built: $OUT  ($SIZE)"
echo ""
echo "Copy it to the iMac and double-click it. Drag Photo Frame onto the"
echo "Applications shortcut, then open it from Applications - right-click the"
echo "app and choose Open the first time, as it is not signed by Apple."
