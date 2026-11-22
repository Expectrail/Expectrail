#!/usr/bin/env bash
# Downloads the pinned Godot 4.7.2 for macOS into tools/godot_mac, checks it against the official
# SHA-512 (from the release's SHA512-SUMS.txt), and only then extracts Godot.app.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="4.7.2-stable"
ZIP="Godot_v${VERSION}_macos.universal.zip"
SHA512="38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b9818255d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca"
DIR="$REPO/tools/godot_mac"
APP="$DIR/Godot.app"
BIN="$APP/Contents/MacOS/Godot"

if [ -x "$BIN" ]; then
    echo "$BIN"
    exit 0
fi

mkdir -p "$DIR"
echo "Downloading Godot ${VERSION} for macOS into tools/godot_mac..."
curl -fsSL -o "$DIR/$ZIP" "https://github.com/godotengine/godot/releases/download/${VERSION}/${ZIP}"
echo "Checking SHA-512..."
if ! echo "$SHA512  $DIR/$ZIP" | shasum -a 512 -c - >&2; then
    rm -f "$DIR/$ZIP"
    echo "SHA-512 mismatch: refusing to extract or clear quarantine on an unverified download." >&2
    exit 1
fi
echo "Extracting ${ZIP}..."
unzip -oq "$DIR/$ZIP" -d "$DIR"
rm -f "$DIR/$ZIP"
chmod +x "$BIN"
# Only a verified download gets its quarantine flag cleared.
xattr -cr "$APP" 2>/dev/null || true
echo "Godot for macOS is ready: $BIN" >&2
printf '%s\n' "$BIN"
