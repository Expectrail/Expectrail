#!/usr/bin/env bash
# Launches the 2D platformer demo locally in an interactive window on macOS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
PINNED_GODOT="${EXPECTRAIL_TOOLS:-$REPO/tools}/godot_mac/Godot.app/Contents/MacOS/Godot"

# 1. Prefer the pinned Godot 4.7.2 in tools/godot_mac, or download it
if [ -x "$PINNED_GODOT" ]; then
    GODOT="$PINNED_GODOT"
else
    echo "Downloading pinned Godot 4.7.2 for macOS..."
    "$SCRIPT_DIR/get_godot_mac.sh"
    GODOT="$PINNED_GODOT"
fi

# 2. Clear Gatekeeper quarantine flags if needed
xattr -cr "$(dirname "$(dirname "$(dirname "$GODOT")")")" 2>/dev/null || true

# 3. Ensure assets are pre-imported so all animation libraries load without errors
if [ ! -d "$REPO/game/platformer/.godot/imported" ]; then
    echo "Pre-importing platformer assets with Godot..."
    "$GODOT" --headless --path "$REPO/game/platformer" --import || true
fi

# 4. Parse optional --patch arguments
PATCHES=()
GODOT_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --patch)
            PATCHES+=("$2")
            shift 2
            ;;
        --patch=*)
            PATCHES+=("${1#*=}")
            shift
            ;;
        *)
            GODOT_ARGS+=("$1")
            shift
            ;;
    esac
done

PLAY_PATH="$REPO/game/platformer"
if [[ ${#PATCHES[@]} -gt 0 ]]; then
    PLAY_PATH="$REPO/runs/local_play"
    rm -rf "$PLAY_PATH"
    mkdir -p "$PLAY_PATH"
    cp -R "$REPO/game/platformer/." "$PLAY_PATH/"
    for p in "${PATCHES[@]}"; do
        echo "Applying patch: $p"
        patch -p1 --forward --batch -d "$PLAY_PATH" < "$p"
    done
fi

echo "Launching Platformer 2D ($PLAY_PATH)..."
exec "$GODOT" --path "$PLAY_PATH" ${GODOT_ARGS[@]+"${GODOT_ARGS[@]}"}

