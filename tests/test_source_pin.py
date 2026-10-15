#!/usr/bin/env python3
"""Offline source-lock checks. No build stages, source downloads, or dependencies."""
import os
from pathlib import Path
import re
import shutil
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
    def test_lock_names_the_upstream_release(self):
        lock = (ROOT / "scripts/emacs-source.lock").read_text()
        self.assertIn('readonly EMACS_SOURCE_RELEASE_TAG="emacs-31.1"', lock)
        self.assertIn('readonly EMACS_BUILD_NUMBER="3"', lock)
        self.assertIn(f'readonly EMACS_SOURCE_REVISION="{PIN}"', lock)
        self.assertNotIn("This is a development snapshot", lock)
        self.assertNotIn("not an official", lock)
        self.assertIn("release", lock)

    def test_release_name_reaches_the_release_step(self):
        self.assertIn('name: ${{ env.EMACS_RELEASE_NAME }}', CI)
        self.assertIn('"EMACS_RELEASE_NAME=$EMACS_RELEASE_NAME"', run_block("Load Emacs source lock"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.env = dict(os.environ)
        # A BASH_ENV file (the user's shell environment) is sourced by every
        # bash below and can put a real git ahead of the fake one on PATH.
        self.env.pop("BASH_ENV", None)
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
  ls-remote) exit "${FAKE_LS_REMOTE:-2}" ;;
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
            "EMACS_ARTIFACT": "Emacs-31.1-bendmacs.3.tar.xz",
            "EMACS_RELEASE_TAG": "emacs-31.1-bendmacs.3",
            "EMACS_RELEASE_NAME": "Emacs 31.1, bendmacs build 3"})
        self.assertIn('emacs_prepare_source "$GITHUB_WORKSPACE/$EMACS_SOURCE_DIR"', run_block("Build Emacs"))
        self.assertNotIn("30.2", CI)
        self.assertNotIn("30.2", LOCAL)
        self.assertIn('tag_name: ${{ env.EMACS_RELEASE_TAG }}', CI)
        self.assertIn('          files: |\n'
                      '            ${{ env.EMACS_SOURCE_DIR }}/${{ env.EMACS_ARTIFACT }}\n'
                      '            ${{ env.EMACS_SOURCE_DIR }}/${{ env.EMACS_ARTIFACT }}.sha256\n', CI)
        self.assertIn('shasum -a 256 "$EMACS_ARTIFACT" > "$EMACS_ARTIFACT.sha256"',
                      run_block("Build Emacs"))

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
        self.assertEqual(self.trace(), "")  # Never uses this repository's HEAD for metadata.

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

    def test_release_names_follow_the_build_number(self):
        p = self.shell('printf "%s\\n" "$EMACS_RELEASE_TAG" "$EMACS_RELEASE_NAME" '
                       '"$EMACS_ARTIFACT" "$EMACS_RELEASE_VERSION"')
        self.assertEqual(p.stdout.splitlines(), [
            "emacs-31.1-bendmacs.3", "Emacs 31.1, bendmacs build 3",
            "Emacs-31.1-bendmacs.3.tar.xz", "31.1"])

    def lock_variant(self, old, new):
        """A copy of the helper beside a lock with OLD replaced by NEW."""
        scripts = self.work / "variant"
        scripts.mkdir()
        (scripts / "emacs-source.sh").write_text(HELPER.read_text())
        lock = (ROOT / "scripts/emacs-source.lock").read_text()
        self.assertIn(old, lock)
        (scripts / "emacs-source.lock").write_text(lock.replace(old, new))
        self.env["HELPER"] = str(scripts / "emacs-source.sh")

    def test_bad_build_number_rejected(self):
        for bad in ("0", "02", "3a", ""):
            with self.subTest(bad=bad):
                self.lock_variant('EMACS_BUILD_NUMBER="3"', f'EMACS_BUILD_NUMBER="{bad}"')
                self.shell('true', ok=False)
                shutil.rmtree(self.work / "variant")

    def test_next_build_number_names_a_new_release(self):
        self.lock_variant('EMACS_BUILD_NUMBER="3"', 'EMACS_BUILD_NUMBER="4"')
        p = self.shell('printf "%s\\n" "$EMACS_RELEASE_TAG" "$EMACS_ARTIFACT"')
        self.assertEqual(p.stdout.splitlines(),
                         ["emacs-31.1-bendmacs.4", "Emacs-31.1-bendmacs.4.tar.xz"])

    def test_free_release_tag_accepted(self):
        self.env["FAKE_LS_REMOTE"] = "2"
        self.shell('emacs_check_release_tag_free repo')
        self.assertIn("ls-remote --exit-code --tags origin refs/tags/emacs-31.1-bendmacs.3\n",
                      self.trace())

    def test_existing_release_tag_refused(self):
        self.env["FAKE_LS_REMOTE"] = "0"
        p = self.shell('emacs_check_release_tag_free repo', ok=False)
        self.assertIn("bump EMACS_BUILD_NUMBER", p.stderr)

    def test_unreadable_origin_is_not_a_free_tag(self):
        self.env["FAKE_LS_REMOTE"] = "128"
        p = self.shell('emacs_check_release_tag_free repo', ok=False)
        self.assertIn("exit 128", p.stderr)

    def test_ci_never_moves_a_tag(self):
        self.assertNotIn("git tag", CI)
        self.assertNotIn("git push", CI)
        self.assertNotIn("--force", CI)
        self.assertIn("target_commitish: ${{ github.sha }}", CI)
        self.assertIn("fail_on_unmatched_files: true", CI)
        self.assertIn("make_latest: true", CI)

    def test_tag_checked_before_the_build_and_before_the_release(self):
        build = CI.split("\n  build:\n", 1)[1]
        order = ["      - name: Load Emacs source lock",
                 "      - name: Refuse an existing release tag",
                 "      - name: Build Emacs",
                 "      - name: Write release notes",
                 "      - name: Recheck the release tag",
                 "      - name: Release Emacs"]
        positions = [build.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        for name in ("Refuse an existing release tag", "Recheck the release tag"):
            self.assertIn('emacs_check_release_tag_free "$GITHUB_WORKSPACE"', run_block(name))

    def test_tests_gate_the_build(self):
        self.assertIn("on:\n  push:\n  pull_request:\n  workflow_dispatch:\n", CI)
        jobs = CI.split("\njobs:\n", 1)[1]
        self.assertTrue(jobs.startswith("  tests:\n"), jobs[:40])
        build = jobs.split("\n  build:\n", 1)[1]
        self.assertTrue(build.startswith("    needs: tests\n"
                                         "    if: github.event_name == 'workflow_dispatch'\n"),
                        build[:120])
        self.assertIn("env -u BASH_ENV python3", run_block("Offline tests"))
        self.assertIn("tests/test_*.py", run_block("Offline tests"))
        fetch = run_block("Fetch the pinned source")
        self.assertIn('emacs_prepare_source "$RUNNER_TEMP/$EMACS_SOURCE_DIR"', fetch)
        self.assertIn("archive HEAD src lisp/term", fetch)
        apply = run_block("Apply the patch set to the pinned source")
        self.assertIn('EBUILD_UI_TARGETS="$RUNNER_TEMP/ui-targets"', apply)
        self.assertIn("tests/test_ui_patches.py", apply)
        self.assertLess(apply.index("test -f"), apply.index("EBUILD_UI_TARGETS="))

    def release_workspace(self):
        """A workspace with this repository's scripts and patches and a bundle."""
        ws = self.work / "ws"
        ws.mkdir()
        (ws / "scripts").symlink_to(ROOT / "scripts")
        (ws / "patches").symlink_to(ROOT / "patches")
        src = ws / f"emacs-31-snapshot-{PIN}"
        src.mkdir()
        self.env["GITHUB_WORKSPACE"] = str(ws)
        subprocess.run(["bash", "-eu", "-c",
                        'source "$GITHUB_WORKSPACE/scripts/emacs-source.sh"\n'
                        'source "$GITHUB_WORKSPACE/scripts/emacs-patches.sh"\n'
                        f'cd "{src}"\nemacs_mark_output Emacs.app\nemacs_mark_patches Emacs.app'],
                       env=self.env, check=True)
        return src

    def test_release_notes_describe_the_bundle(self):
        src = self.release_workspace()
        p = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", run_block("Write release notes")],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        notes = (src / "release-notes.md").read_text()
        marker = (src / "Emacs.app/Contents/Resources/ebuild-patches.txt").read_text()
        digest = marker.split("patchset=", 1)[1].split("\n", 1)[0]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertTrue(notes.startswith("Emacs 31.1 for macOS on Apple silicon: "
                                         "build 3 of bendmacs-emacs.\n"), notes)
        self.assertIn(f"`{PIN}`", notes)
        self.assertIn(f"`patchset={digest}`", notes)
        lock = (ROOT / "patches/ui-patches.lock").read_text().splitlines()
        patches = [line.split("\t")[1] for line in lock if line and not line.startswith("#")]
        listed = re.findall(r"^  - `(.+)`$", notes, re.M)
        self.assertEqual(listed, patches)
        self.assertEqual(len(listed), 8)
        self.assertIn("`shasum -a 256 -c Emacs-31.1-bendmacs.3.tar.xz.sha256`", notes)

    def test_release_notes_refuse_a_bundle_from_another_patch_set(self):
        src = self.release_workspace()
        marker = src / "Emacs.app/Contents/Resources/ebuild-patches.txt"
        marker.write_text(marker.read_text().replace("patchset=", "patchset=0"))
        p = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", run_block("Write release notes")],
                           env=self.env, text=True, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((src / "release-notes.md").exists())

    def test_full_sha_cannot_be_overridden_by_environment(self):
        self.env["EMACS_SOURCE_REVISION"] = "master"
        p = self.shell('printf "%s" "$EMACS_SOURCE_REVISION"')
        self.assertEqual(p.stdout, PIN)
        self.shell('EMACS_SOURCE_REVISION=master', ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
