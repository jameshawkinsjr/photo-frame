#!/bin/sh
#
# Builds "Photo Frame.app" from the scripts in this folder.
#
#   sh install.sh                 -> installs into ~/Applications
#   sh install.sh /Applications   -> installs somewhere else
#
# Safe to run again at any time; it just replaces the app in place.

set -e

SRC=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-$HOME/Applications}
APP="$DEST/Photo Frame.app"

echo "Photo Frame installer"
echo "---------------------"

# --- check that this Mac can run it ---------------------------------------
PYTHON=""
for CANDIDATE in /usr/bin/python /usr/bin/python2.7 /usr/bin/python3; do
    if [ -x "$CANDIDATE" ] && "$CANDIDATE" -c "import objc, AppKit, Quartz" >/dev/null 2>&1; then
        PYTHON="$CANDIDATE"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "!! Could not find a Python with the Mac's PyObjC bridge."
    echo "   On macOS 10.13 High Sierra this is /usr/bin/python and it is built in,"
    echo "   so this usually means the system Python has been changed or removed."
    echo "   Photo Frame will still be installed, and will look again when it starts."
else
    echo "Using $PYTHON ($("$PYTHON" -c "import platform;print(platform.python_version())"))"
fi

# --- build the bundle ------------------------------------------------------
mkdir -p "$DEST"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$SRC/photoframe.py" "$APP/Contents/Resources/"
cp "$SRC"/pf_*.py "$APP/Contents/Resources/"

ICON_ENTRY=""
if [ -f "$SRC/PhotoFrame.icns" ]; then
    cp "$SRC/PhotoFrame.icns" "$APP/Contents/Resources/"
    ICON_ENTRY="	<key>CFBundleIconFile</key>
	<string>PhotoFrame</string>"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>Photo Frame</string>
	<key>CFBundleDisplayName</key>
	<string>Photo Frame</string>
	<key>CFBundleIdentifier</key>
	<string>com.jameshawkins.photoframe</string>
	<key>CFBundleExecutable</key>
	<string>PhotoFrame</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>$ICON_ENTRY
	<key>LSMinimumSystemVersion</key>
	<string>10.9</string>
	<key>LSApplicationCategoryType</key>
	<string>public.app-category.photography</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSPrincipalClass</key>
	<string>NSApplication</string>
	<key>NSSupportsAutomaticGraphicsSwitching</key>
	<true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/PhotoFrame" <<'LAUNCHER'
#!/bin/sh
# Finds a Python with the Mac's Cocoa bridge and hands over to the app.
HERE=$(cd "$(dirname "$0")/../Resources" && pwd)
for PY in /usr/bin/python /usr/bin/python2.7 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if [ -x "$PY" ] && "$PY" -c "import objc, AppKit, Quartz" >/dev/null 2>&1; then
        exec "$PY" "$HERE/photoframe.py" "$@"
    fi
done
osascript -e 'display alert "Photo Frame cannot start" message "No Python with the Mac'"'"'s Cocoa (PyObjC) bridge was found. On macOS 10.13 this is built in at /usr/bin/python."' >/dev/null 2>&1
exit 1
LAUNCHER

chmod +x "$APP/Contents/MacOS/PhotoFrame"
touch "$APP"

echo ""
echo "Installed: $APP"
echo ""
echo "Next:"
echo "  1. Open it (double-click Photo Frame in $DEST)."
echo "  2. The Settings window opens the first time - choose your photo folder."
echo "  3. Press Esc at any time to bring Settings back."
echo ""
echo "To have it start by itself, tick \"Open Photo Frame automatically when"
echo "this Mac starts up\" in Settings."
