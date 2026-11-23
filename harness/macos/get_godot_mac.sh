#!/usr/bin/env bash
# Downloads the pinned Godot 4.7.2 for macOS into the tools cache, checks it against the official
# SHA-512 (from the release's SHA512-SUMS.txt), and only then extracts Godot.app.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="4.7.2-stable"
ZIP="Godot_v${VERSION}_macos.universal.zip"
SHA512="38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b9818255d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca"
DIR="${EXPECTRAIL_TOOLS:-$REPO/tools}/godot_mac"
APP="$DIR/Godot.app"
BIN="$APP/Contents/MacOS/Godot"

exit_if_present() {
    if [ -x "$BIN" ] && [ -f "$BIN" ]; then printf '%s\n' "$BIN"; exit 0; fi
}

exit_if_present
mkdir -p "$DIR"
# Multiple installs may share this user cache. Match the Linux helper's directory lock.
exec 9<"$DIR"
"${PYTHON:-python3}" -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX)'
exit_if_present

stage=$(mktemp -d "$DIR/.install.XXXXXXXX")
cleanup() {
    # Restore a pre-existing incomplete bundle if publishing its replacement failed.
    if [ -e "$stage/previous.app" ] && [ ! -e "$APP" ]; then
        mv "$stage/previous.app" "$APP" || return 1
    fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
echo "Downloading Godot ${VERSION} for macOS into $DIR..." >&2
curl -fsSL -o "$stage/$ZIP" "https://github.com/godotengine/godot/releases/download/${VERSION}/${ZIP}"
if ! (cd "$stage" && printf '%s  %s\n' "$SHA512" "$ZIP" | shasum -a 512 -c - >&2); then
    echo "SHA-512 mismatch: refusing to extract or clear quarantine on an unverified download." >&2
    exit 1
fi
unzip -oq "$stage/$ZIP" -d "$stage"
chmod +x "$stage/Godot.app/Contents/MacOS/Godot"
xattr -cr "$stage/Godot.app" 2>/dev/null || true
if [ -e "$APP" ]; then mv "$APP" "$stage/previous.app"; fi
mv "$stage/Godot.app" "$APP"
echo "Godot for macOS is ready: $BIN" >&2
printf '%s\n' "$BIN"
