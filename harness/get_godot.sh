#!/usr/bin/env bash
# Puts the pinned Godot editor binary in tools/godot and prints its path.
#
# The download is checked against the official SHA-512 every time it is used, whether it came from
# the network just now or from tools/godot_cache (which CI restores from its cache, see
# .github/actions/get-godot). A file that does not match is deleted and fetched again.
# The download is retried: one HTTP 500 from GitHub failed a required check on November 11, 2026.
set -euo pipefail
VERSION="4.7.2-stable"
ZIP="Godot_v${VERSION}_linux.x86_64.zip"
SHA512="9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b1467edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65"
URL="https://github.com/godotengine/godot/releases/download/${VERSION}/${ZIP}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/tools/godot"
CACHE="$ROOT/tools/godot_cache"
BIN="$DIR/Godot_v${VERSION}_linux.x86_64"
ATTEMPTS="${GODOT_DOWNLOAD_ATTEMPTS:-5}"
PAUSE="${GODOT_DOWNLOAD_PAUSE_SECONDS:-5}"

note() { [ -n "${GITHUB_OUTPUT:-}" ] && echo "$1" >> "$GITHUB_OUTPUT"; return 0; }
matches() { [ -f "$1" ] && echo "$SHA512  $1" | sha512sum -c - >/dev/null 2>&1; }

if [ -x "$BIN" ]; then note "source=present"; echo "$BIN"; exit 0; fi
mkdir -p "$DIR" "$CACHE"

source=cache
if ! matches "$CACHE/$ZIP"; then
  [ -e "$CACHE/$ZIP" ] && { echo "get_godot: the cached download does not match its SHA-512; fetching again" >&2; rm -f "$CACHE/$ZIP"; }
  source=download
  attempt=1
  while :; do
    if curl -fsSL --connect-timeout 20 --max-time 300 -o "$CACHE/$ZIP.part" "$URL" && matches "$CACHE/$ZIP.part"; then
      mv "$CACHE/$ZIP.part" "$CACHE/$ZIP"
      break
    fi
    rm -f "$CACHE/$ZIP.part"
    if [ "$attempt" -ge "$ATTEMPTS" ]; then
      echo "get_godot: could not download $URL with a matching SHA-512 in $ATTEMPTS attempts" >&2
      exit 1
    fi
    echo "get_godot: download attempt $attempt of $ATTEMPTS failed; trying again in ${PAUSE}s" >&2
    sleep "$PAUSE"
    attempt=$((attempt + 1))
  done
fi

unzip -oq "$CACHE/$ZIP" -d "$DIR"
chmod +x "$BIN"
# CI keeps the download for its cache (GODOT_KEEP_DOWNLOAD=1); elsewhere it is removed, as before.
if [ "$source" = download ] && [ "${GODOT_KEEP_DOWNLOAD:-}" != 1 ]; then rm -f "$CACHE/$ZIP"; fi
note "source=$source"
echo "get_godot: Godot $VERSION from $source, SHA-512 checked" >&2
echo "$BIN"
