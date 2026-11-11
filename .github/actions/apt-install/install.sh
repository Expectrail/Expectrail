#!/usr/bin/env bash
# Install Ubuntu packages without depending on any one package mirror being up.
#
#   install.sh <cache dir> <package> [<package> ...]
#
# Four layers, each tried only when the one before it did not do the job:
#   1. Already installed (many runner images ship `patch`, for one): do nothing, touch no network.
#   2. Cached .deb files from an earlier run on the same runner image: dpkg installs them, no network.
#   3. The live mirror, twice, each command capped in time so a hung resolver cannot use up the job.
#   4. Ubuntu's snapshot archive (snapshot.ubuntu.com, a different host) at APT_SNAPSHOT.
# Layers 3 and 4 download into the cache dir, which the action saves for the next run.
#
# Prints which layer served the install. Writes `source=` and `fetched=` to $GITHUB_OUTPUT.
set -u

cache_dir="$1"; shift
packages=("$@")
attempts="${APT_ATTEMPTS:-2}"
cap="${APT_STEP_SECONDS:-100}"   # no single apt command may hold the job longer than this
pause="${APT_PAUSE_SECONDS:-30}"
snapshot="${APT_SNAPSHOT:-}"
apt_opts=(-o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)

out() { [ -n "${GITHUB_OUTPUT:-}" ] && echo "$1" >> "$GITHUB_OUTPUT"; return 0; }

installed() {
  local p
  for p in "${packages[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || return 1
  done
}

done_with() {
  echo "::notice title=apt-install::${packages[*]}: $1"
  out "source=$2"; out "fetched=$3"
  exit 0
}

if [ "${#packages[@]}" -eq 0 ]; then echo "::error title=apt-install::no packages named"; exit 2; fi

if installed; then done_with "already on the runner image, nothing installed" image false; fi

mkdir -p "$cache_dir/partial"
if ls "$cache_dir"/*.deb >/dev/null 2>&1; then
  if sudo dpkg -i "$cache_dir"/*.deb && installed; then
    done_with "installed from cached packages, no mirror contacted" cache false
  fi
  echo "::warning title=apt-install::the cached packages did not install on this image; fetching afresh"
  rm -f "$cache_dir"/*.deb
fi

fetch() {  # fetch [--snapshot ID]: download into the cache dir, then install from it
  sudo timeout "$cap" apt-get "${apt_opts[@]}" update "$@" \
    && sudo timeout "$cap" apt-get "${apt_opts[@]}" install "$@" -y --no-install-recommends --download-only \
         -o Dir::Cache::Archives="$cache_dir" "${packages[@]}" \
    && sudo timeout "$cap" apt-get "${apt_opts[@]}" install "$@" -y --no-install-recommends \
         -o Dir::Cache::Archives="$cache_dir" "${packages[@]}" \
    && installed
}

keep() { sudo chown -R "$(id -u):$(id -g)" "$cache_dir"; rm -rf "$cache_dir/partial" "$cache_dir/lock"; }

attempt=1
while [ "$attempt" -le "$attempts" ]; do
  if fetch; then keep; done_with "installed from the live mirror (attempt $attempt)" live true; fi
  echo "::warning title=apt-install::live mirror, attempt $attempt of $attempts failed"
  [ "$attempt" -lt "$attempts" ] && sleep "$pause"
  attempt=$((attempt + 1))
done

if [ -n "$snapshot" ]; then
  attempt=1
  while [ "$attempt" -le 2 ]; do
    if fetch --snapshot "$snapshot"; then
      keep
      echo "::warning title=apt-install::the live mirror was unreachable; versions come from the snapshot of $snapshot and may differ from the live archive's"
      done_with "installed from Ubuntu's snapshot archive ($snapshot)" snapshot true
    fi
    echo "::warning title=apt-install::snapshot archive, attempt $attempt of 2 failed"
    [ "$attempt" -lt 2 ] && sleep "$pause"
    attempt=$((attempt + 1))
  done
fi

echo "::error title=apt-install::could not install ${packages[*]}: not on the image, no usable cache, live mirror failed $attempts times, snapshot archive failed"
exit 1
