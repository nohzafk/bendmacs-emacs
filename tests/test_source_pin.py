#!/usr/bin/env python3
"""Offline source-lock checks. No build stages, source downloads, or dependencies."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/emacs-source.sh"
PIN = "a360712c9d272d950d8d8255ef74570f7e90b7d9"
ORIGIN = "https://github.com/emacs-mirror/emacs.git"
LOCAL = (ROOT / "scripts/build.sh").read_text()
CI = (ROOT / ".github/workflows/build.yml").read_text()


def run_block(name):
    pattern = rf"      - name: {re.escape(name)}\n        run: \|\n((?:          .*\n|\n)+)"
    match = re.search(pattern, CI)
    if not match:
        raise AssertionError(f"Missing workflow run block: {name}")
    return "\n".join(line[10:] for line in match[1].splitlines())


class SourcePinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.env = dict(os.environ)
        self.env.update(HELPER=str(HELPER), ROOT=str(ROOT),
                        TRACE=str(self.work / "trace"),
                        FAKE_HEAD=PIN, FAKE_ORIGIN=ORIGIN)
        tools = self.work / "bin"
        tools.mkdir()
        git = tools / "git"
        git.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TRACE"
if [[ "$1" == init ]]; then mkdir -p "$2/.git"; exit; fi
[[ "$1" == -C ]] || exit 90
shift 2
case "$1" in
  rev-parse) printf '%s\\n' "$FAKE_HEAD" ;;
  remote)
    if [[ "$2" == get-url ]]; then printf '%s\\n' "$FAKE_ORIGIN"; fi ;;
  fetch) [[ "${FAIL_FETCH:-0}" == 0 ]] ;;
  -c) [[ "$3" == checkout && "$4" == --detach ]] ;;
  *) exit 91 ;;
esac
''')
        git.chmod(0o755)
        # Any unintended download/build command fails loudly, without running it.
        for name in ("curl", "make", "autogen.sh", "configure", "ditto"):
            command = tools / name
            command.write_text('#!/usr/bin/env bash\necho "Forbidden test command" >&2\nexit 99\n')
            command.chmod(0o755)
        self.env["PATH"] = str(tools) + os.pathsep + self.env["PATH"]

    def shell(self, code, ok=True):
        p = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c",
                            'source "$HELPER"\n' + code],
                           cwd=self.work, env=self.env, text=True,
                           capture_output=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout)
        return p

    def trace(self):
        path = self.work / "trace"
        return path.read_text() if path.exists() else ""

    def fixture(self, name="src"):
        (self.work / name / ".git").mkdir(parents=True)

    def test_local_and_ci_share_lock_and_labels(self):
        # Evaluate local setup only; never evaluate any stage or mkdir/export setup.
        setup = LOCAL.split('mkdir -p "$PREFIX" "$WORK"', 1)[0]
        self.assertIn('source "$REPO_ROOT/scripts/emacs-source.sh"', setup)
        # Supply REPO_ROOT, then evaluate only declarations after its assignment.
        declarations = setup.split('REPO_ROOT="', 1)[1].split('\n', 1)[1]
        self.env["REPO_ROOT"] = str(ROOT)
        self.env["JOBS"] = "1"
        for key in ("PREFIX", "WORK", "OUT"):
            self.env.pop(key, None)
        local = subprocess.run(["bash", "-eu", "-c", declarations +
                                '\nprintf "%s\\n" "$EMACS_SOURCE_REVISION" "$EMACS_SOURCE_LABEL" "$OUT"'],
                               env=self.env, text=True, capture_output=True)
        self.assertEqual(local.returncode, 0, local.stderr)
        self.assertEqual(local.stdout.splitlines(), [PIN, f"31-snapshot-{PIN}",
                         str(ROOT / f"build/emacs-31-snapshot-{PIN}/Emacs.app")])
        self.env["GITHUB_WORKSPACE"] = str(ROOT)
        self.env["GITHUB_ENV"] = str(self.work / "ci-env")
        p = subprocess.run(["bash", "-eu", "-c", run_block("Load Emacs source lock")],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        values = dict(line.split("=", 1) for line in (self.work / "ci-env").read_text().splitlines())
        self.assertEqual(values, {
            "EMACS_SOURCE_LABEL": f"31-snapshot-{PIN}",
            "EMACS_SOURCE_DIR": f"emacs-31-snapshot-{PIN}",
            "EMACS_ARTIFACT": f"Emacs-31-snapshot-{PIN}.tar.xz",
            "EMACS_RELEASE_TAG": f"v31-snapshot-{PIN}"})
        self.assertIn('emacs_prepare_source "$GITHUB_WORKSPACE/$EMACS_SOURCE_DIR"', run_block("Build Emacs"))
        self.assertNotIn("30.2", CI)
        self.assertNotIn("30.2", LOCAL)
        self.assertIn('tag_name: ${{ env.EMACS_RELEASE_TAG }}', CI)
        self.assertIn('files: ${{ env.EMACS_SOURCE_DIR }}/${{ env.EMACS_ARTIFACT }}', CI)
        self.assertIn('git tag -f "$EMACS_RELEASE_TAG"', run_block("Update release tag"))

    def test_fixed_fetch_and_detached_checkout(self):
        self.shell('emacs_prepare_source src')
        trace = self.trace()
        self.assertIn(f"fetch --depth=1 origin {PIN}\n", trace)
        self.assertIn(f"checkout --detach {PIN}\n", trace)
        for moving in ("master", "refs/heads", "refs/tags", "FETCH_HEAD"):
            self.assertNotIn(moving, trace)

    def test_failed_fetch_stops_before_checkout(self):
        self.env["FAIL_FETCH"] = "1"
        self.shell('emacs_prepare_source src', ok=False)
        self.assertNotIn("checkout", self.trace())

    def test_matching_source_reused_without_fetch(self):
        self.fixture()
        self.shell('emacs_prepare_source src')
        self.assertNotIn("fetch", self.trace())

    def test_wrong_head_rejected_without_modification(self):
        self.fixture()
        self.env["FAKE_HEAD"] = "0" * 40
        self.shell('emacs_prepare_source src', ok=False)
        self.assertNotIn("fetch", self.trace())
        self.assertNotIn("checkout", self.trace())

    def test_wrong_origin_rejected(self):
        self.fixture()
        self.env["FAKE_ORIGIN"] = "https://example.invalid/not-emacs.git"
        self.shell('emacs_prepare_source src', ok=False)
        self.assertNotIn("fetch", self.trace())

    def test_surrounding_ebuild_git_never_used(self):
        (self.work / ".git").mkdir()
        (self.work / "src").mkdir()
        self.shell('emacs_prepare_source src', ok=False)
        self.assertEqual(self.trace(), "")

    def test_missing_output_allowed(self):
        self.shell('emacs_check_output Emacs.app')

    def test_unmarked_old_output_rejected_and_preserved(self):
        app = self.work / "Emacs.app/Contents/MacOS"
        app.mkdir(parents=True)
        (app / "Emacs").write_text("old-output")
        self.shell('emacs_check_output Emacs.app', ok=False)
        self.assertEqual((app / "Emacs").read_text(), "old-output")

    def test_matching_output_marker_roundtrip(self):
        self.shell('emacs_mark_output Emacs.app; emacs_check_output Emacs.app')
        marker = (self.work / "Emacs.app/Contents/Resources/ebuild-source.txt").read_text()
        self.assertEqual(marker, f"repository={ORIGIN}\nrevision={PIN}\nlabel=31-snapshot-{PIN}\n")
        self.assertEqual(self.trace(), "")  # Never uses ebuild HEAD for metadata.

    def test_wrong_output_revision_rejected(self):
        self.shell('emacs_mark_output Emacs.app')
        marker = self.work / "Emacs.app/Contents/Resources/ebuild-source.txt"
        marker.write_text(marker.read_text().replace(PIN, "0" * 40))
        self.shell('emacs_check_output Emacs.app', ok=False)

    def test_cache_checks_precede_local_output_skip(self):
        stage = LOCAL.split("stage_emacs() {", 1)[1].split("  # Patch dir", 1)[0]
        self.assertLess(stage.index('emacs_check_output "$OUT"'), stage.index('skip "Emacs'))
        self.assertLess(stage.index('emacs_validate_source "$src"'), stage.index('skip "Emacs'))
        self.assertIn('emacs_prepare_source "$src"', stage)
        self.assertIn('emacs_mark_output "$OUT"', LOCAL)
        self.assertIn('emacs_mark_output Emacs.app', run_block("Build Emacs"))

    def test_full_sha_cannot_be_overridden_by_environment(self):
        self.env["EMACS_SOURCE_REVISION"] = "master"
        p = self.shell('printf "%s" "$EMACS_SOURCE_REVISION"')
        self.assertEqual(p.stdout, PIN)
        self.shell('EMACS_SOURCE_REVISION=master', ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
