"""The apt-install action: packages come from the image, a cache, the live mirror or the snapshot
archive, in that order, so a mirror outage does not fail a job (November 9 and 11).

install.sh is run here against stand-ins for sudo, apt-get, dpkg and dpkg-query; nothing is installed
and no network is touched. Not covered here: the action on a real runner (CI covers that) and
actions/cache itself.
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ACTION = REPO / ".github" / "actions" / "apt-install"
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
# unity.yml pins every package to the snapshot for identical frames across runners (its header).
OWN_APT = {"unity.yml"}

STUBS = {
    "sudo": '#!/bin/bash\nexec "$@"\n',
    # Installed packages are lines of $STATE/installed.
    "dpkg-query": '#!/bin/bash\np="${@: -1}"\ngrep -qx "$p" "$STATE/installed" 2>/dev/null && printf "install ok installed" || exit 1\n',
    # dpkg -i installs whatever .deb names it is given, unless $STATE/dpkg-fails exists.
    "dpkg": '#!/bin/bash\necho "dpkg $*" >> "$STATE/calls"\n[ -e "$STATE/dpkg-fails" ] && exit 1\n'
            'for f in "$@"; do case "$f" in *.deb) basename "$f" .deb >> "$STATE/installed";; esac; done\n',
    # apt-get fails while $STATE/live-failures (or snapshot-failures, with --snapshot) is above zero,
    # counted once per `update`. --download-only writes a .deb per package; install marks them installed.
    "apt-get": r'''#!/bin/bash
echo "apt-get $*" >> "$STATE/calls"
which=live; for a in "$@"; do [ "$a" = "--snapshot" ] && which=snapshot; done
left=$(cat "$STATE/$which-failures" 2>/dev/null || echo 0)
verb=; for a in "$@"; do case "$a" in update|install) verb=$a;; esac; done
if [ "$verb" = update ]; then
  if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$STATE/$which-failures"; touch "$STATE/down"; exit 100; fi
  rm -f "$STATE/down"; exit 0
fi
[ -e "$STATE/down" ] && exit 100
dir=; download=0; pkgs=()
for a in "$@"; do
  case "$a" in
    Dir::Cache::Archives=*) dir="${a#Dir::Cache::Archives=}";;
    --download-only) download=1;;
    -*|install|[0-9]*T*Z|Acquire::*) ;;
    *) pkgs+=("$a");;
  esac
done
for p in "${pkgs[@]}"; do
  if [ "$download" = 1 ]; then : > "$dir/$p.deb"; else echo "$p" >> "$STATE/installed"; fi
done
''',
}


class InstallScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin, self.state, self.cache = root / "bin", root / "state", root / "cache"
        for d in (self.bin, self.state):
            d.mkdir()
        for name, body in STUBS.items():
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.output = root / "output"

    def run_install(self, *packages, snapshot="20261108T000000Z"):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   GITHUB_OUTPUT=str(self.output), APT_PAUSE_SECONDS="0", APT_ATTEMPTS="3", APT_SNAPSHOT=snapshot)
        return subprocess.run(["bash", str(ACTION / "install.sh"), str(self.cache), *packages],
                              env=env, capture_output=True, text=True)

    def calls(self):
        path = self.state / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def outputs(self):
        return dict(line.split("=", 1) for line in self.output.read_text(encoding="utf-8").splitlines())

    def test_packages_already_on_the_image_touch_nothing(self):
        (self.state / "installed").write_text("patch\n", encoding="utf-8")
        done = self.run_install("patch")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.outputs(), {"source": "image", "fetched": "false"})

    def test_cached_packages_install_with_no_mirror(self):
        self.cache.mkdir()
        (self.cache / "bubblewrap.deb").write_bytes(b"")
        (self.state / "live-failures").write_text("99", encoding="utf-8")   # the mirror is down
        done = self.run_install("bubblewrap")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([c.split()[0] for c in self.calls()], ["dpkg"])
        self.assertEqual(self.outputs(), {"source": "cache", "fetched": "false"})
        self.assertIn("no mirror contacted", done.stdout)

    def test_a_cache_that_does_not_install_falls_back_to_the_mirror(self):
        self.cache.mkdir()
        (self.cache / "stale.deb").write_bytes(b"")
        (self.state / "dpkg-fails").write_text("", encoding="utf-8")
        done = self.run_install("bubblewrap")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.outputs(), {"source": "live", "fetched": "true"})
        self.assertFalse((self.cache / "stale.deb").exists())
        self.assertTrue((self.cache / "bubblewrap.deb").exists())

    def test_the_live_mirror_is_retried(self):
        (self.state / "live-failures").write_text("2", encoding="utf-8")
        done = self.run_install("bubblewrap", "xvfb")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("attempt 3", done.stdout)
        self.assertEqual(self.outputs(), {"source": "live", "fetched": "true"})
        self.assertEqual(sorted(p.name for p in self.cache.glob("*.deb")), ["bubblewrap.deb", "xvfb.deb"])
        self.assertFalse((self.cache / "partial").exists())   # only the packages are cached

    def test_the_snapshot_archive_serves_when_the_live_mirror_stays_down(self):
        (self.state / "live-failures").write_text("99", encoding="utf-8")
        done = self.run_install("bubblewrap")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.outputs(), {"source": "snapshot", "fetched": "true"})
        self.assertIn("may differ from the live archive", done.stdout)
        self.assertTrue(any("--snapshot 20261108T000000Z" in c for c in self.calls()))

    def test_everything_down_fails_and_says_why(self):
        for which in ("live", "snapshot"):
            (self.state / f"{which}-failures").write_text("99", encoding="utf-8")
        done = self.run_install("bubblewrap")
        self.assertEqual(done.returncode, 1)
        self.assertIn("could not install bubblewrap", done.stdout)
        self.assertFalse(self.output.exists())

    def test_no_snapshot_means_no_fallback(self):
        (self.state / "live-failures").write_text("99", encoding="utf-8")
        done = self.run_install("bubblewrap", snapshot="")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(any("--snapshot" in c for c in self.calls()))

    def test_a_reported_success_that_installed_nothing_is_not_success(self):
        # `apt-get update` exits 0 with only warnings when a mirror cannot be resolved (the November 11
        # log); the script judges by what dpkg-query says afterwards, not by an exit code alone.
        (self.bin / "apt-get").write_text('#!/bin/bash\necho "apt-get $*" >> "$STATE/calls"\nexit 0\n', encoding="utf-8")
        done = self.run_install("bubblewrap")
        self.assertEqual(done.returncode, 1)


class EveryWorkflowUsesIt(unittest.TestCase):
    def test_no_workflow_calls_apt_get_itself(self):
        for path in WORKFLOWS:
            if path.name in OWN_APT:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                self.assertNotRegex(code, r"\bapt(-get)?\s+(update|install)\b",
                                    f"{path.name}:{number}: use ./.github/actions/apt-install")

    def test_the_repository_is_checked_out_before_the_local_action(self):
        used = 0
        for path in WORKFLOWS:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for name, job in (doc.get("jobs") or {}).items():
                checked_out = False
                for step in job.get("steps") or []:
                    uses = str(step.get("uses", ""))
                    if uses.startswith("actions/checkout@") and "path" not in (step.get("with") or {}):
                        checked_out = True
                    if uses == "./.github/actions/apt-install":
                        used += 1
                        self.assertTrue(checked_out, f"{path.name}#{name}: check out before apt-install")
                        self.assertTrue(str((step.get("with") or {}).get("packages", "")).strip(), f"{path.name}#{name}")
        self.assertGreaterEqual(used, 30)

    def test_the_action_pins_the_cache_action_and_passes_inputs_by_env(self):
        text = (ACTION / "action.yml").read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        for step in doc["runs"]["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^actions/cache/(restore|save)@[0-9a-f]{40}$")
            if "run" in step:
                self.assertNotIn("${{", step["run"])   # inputs reach the script through env only
        self.assertEqual(doc["runs"]["steps"][-1]["if"], "steps.install.outputs.fetched == 'true'")
        self.assertIn("ImageVersion", text)             # a new runner image fetches afresh


if __name__ == "__main__":
    unittest.main()
