#!/usr/bin/env python3
"""Offline tests for the fixed Emacs UI patch set.

No Emacs source, no downloads and no build stages are needed.  These tests
pin the ordered patch set, its provenance, the strict -F0 application and the
idempotent/rejecting behaviour of scripts/emacs-patches.sh, and the local/CI
wiring.

An optional integration test (enabled by EBUILD_UI_TARGETS, a scratch
directory holding the pinned target files src/, lisp/term/) applies the real
fixed patch set at -F0.  The target source is never vendored into this
repository.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/emacs-patches.sh"
LOCK = ROOT / "patches/ui-patches.lock"
LOCAL = (ROOT / "scripts/build.sh").read_text()
CI = (ROOT / ".github/workflows/build.yml").read_text()
PROVENANCE = ("d12frosted/homebrew-emacs-plus@"
              "6489a284d333119a05c9b0c2175bedf68250d160")

# The exact fixed order.  Changing it is a deliberate, reviewable act.
ORDER = [
    "emacs-31/system-appearance.patch",
    "emacs-31/round-undecorated-frame.patch",
    "emacs-31/fix-ns-x-colors.patch",
    "no-frame-refocus-cocoa.patch",
    "emacs-31/fix-ns-scroll-crash.patch",
    "emacs-31/native-xwidget.patch",
    "emacs-31/ns-xwidget-scroll.patch",
    "emacs-31/ns-child-frame-resize.patch",
]

# SHA-256 of the audited/derived patch bytes.
EXPECTED_SHA = {
    "emacs-31/round-undecorated-frame.patch":
        "c9430a1ead81e313b3d2877ff6f8044fb29441eecc7cc42000515d7c8ec6380f",
    "emacs-31/fix-ns-x-colors.patch":
        "9e5d3e26a8d388d3a000b697d582769645ca93ad597b4113744deba4b89a8b9e",
    "emacs-31/fix-ns-scroll-crash.patch":
        "3250bf6e45cdcb3f4cbc0ace2d2d3200464331cbfb34613980554e31ec45fe6c",
}

ROLE_PATCH = "fix-window-role"


def lock_entries():
    entries = []
    for line in LOCK.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sha, path = line.split()
        entries.append((sha, path))
    return entries


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_block(name):
    pattern = (rf"      - name: {re.escape(name)}\n        run: \|\n"
               rf"((?:          .*\n|\n)+)")
    match = re.search(pattern, CI)
    if not match:
        raise AssertionError(f"Missing workflow run block: {name}")
    return "\n".join(line[10:] for line in match[1].splitlines())


class PatchLockTests(unittest.TestCase):
    def test_fixed_order_is_exact(self):
        self.assertEqual([p for _, p in lock_entries()], ORDER)

    def test_provenance_recorded(self):
        self.assertIn(PROVENANCE, LOCK.read_text())

    def test_every_patch_exists_and_matches_locked_sha256(self):
        for sha, rel in lock_entries():
            path = LOCK.parent / rel
            self.assertTrue(path.is_file(), f"missing {rel}")
            self.assertEqual(sha256(path), sha, f"sha mismatch for {rel}")

    def test_golden_emacs_plus_shas(self):
        # The untouced upstream patches must stay byte-identical to the audit.
        for rel, sha in EXPECTED_SHA.items():
            self.assertEqual(sha256(LOCK.parent / rel), sha, rel)

    def test_obsolete_role_patch_absent(self):
        # No lock entry selects it, and no such patch file is vendored.
        entries = [rel for _, rel in lock_entries()]
        self.assertEqual([r for r in entries if ROLE_PATCH in r], [])
        self.assertEqual(list(LOCK.parent.rglob(f"{ROLE_PATCH}*")), [])
        self.assertEqual(list(LOCK.parent.rglob("*window-role*")), [])

    def test_no_patch_touches_the_accessibility_role(self):
        # The upstream source already returns NSAccessibilityWindowRole; no
        # vendored patch may add or reverse it.
        for _, rel in lock_entries():
            body = (LOCK.parent / rel).read_text()
            self.assertNotIn("NSAccessibilityTextFieldRole", body, rel)
            self.assertNotIn("NSAccessibilityWindowRole", body, rel)

    def test_intended_effects_present_in_patches(self):
        body = {rel: (LOCK.parent / rel).read_text() for _, rel in lock_entries()}
        app = body["emacs-31/system-appearance.patch"]
        self.assertIn("ns_appearance_dark_aqua", app)
        self.assertIn("ns-system-appearance-change-functions", app)
        self.assertIn("systemAppearanceDidChange", app)
        rnd = body["emacs-31/round-undecorated-frame.patch"]
        self.assertIn("undecorated-round", rnd)
        self.assertIn("FRAME_UNDECORATED_ROUND", rnd)
        col = body["emacs-31/fix-ns-x-colors.patch"]
        self.assertIn("(setq x-colors (ns-list-colors))", col)
        foc = body["no-frame-refocus-cocoa.patch"]
        removed = [l for l in foc.splitlines()
                   if l.startswith("-") and "ns_make_frame_key_window" in l]
        added = [l for l in foc.splitlines()
                 if l.startswith("+") and "ns_make_frame_key_window" in l]
        self.assertEqual(len(removed), 1, foc)
        self.assertEqual(added, [], foc)
        self.assertFalse(any("do_switch_frame" in line or "get_mru_frame" in line
                             for line in foc.splitlines()
                             if line.startswith("-") and not line.startswith("---")))
        scr = body["emacs-31/fix-ns-scroll-crash.patch"]
        self.assertIn("bug#81585", scr)
        self.assertIn("if (dest.y < 0)", scr)
        nat = body["emacs-31/native-xwidget.patch"]
        self.assertIn('DEFSYM (Qnative, "native")', nat)
        self.assertIn("XUSER_PTR (arguments)->p", nat)
        self.assertIn("xv->xvWindow.hidden = YES", nat)
        self.assertIn("xv->xvWindow.clipsToBounds = YES", nat)
        # The type is NS-only: its acceptance sits inside NS_IMPL_COCOA, and
        # the WebKit hide (moving the container away) is kept.
        self.assertIn("+#ifdef NS_IMPL_COCOA\n+  void *native_view = NULL;", nat)
        self.assertIn("setFrameOrigin:NSMakePoint(10000, 10000)", nat)
        touched = {l[len("+++ b/"):] for l in nat.splitlines()
                   if l.startswith("+++ b/")}
        self.assertEqual(touched, {"src/xwidget.c", "src/nsxwidget.m",
                                   "src/nsxwidget.h"})
        scl = body["emacs-31/ns-xwidget-scroll.patch"]
        # ns_scroll_run walks the frame's xwidget views, skips a killed
        # xwidget's stale view, and moves each by the run's displacement.
        self.assertIn("+#ifdef HAVE_XWIDGETS", scl)
        self.assertIn("isKindOfClass: [XvWindow class]", scl)
        self.assertIn("!XWIDGETP (xv->model)", scl)
        self.assertIn("xv->y += run->desired_y - run->current_y;", scl)
        self.assertIn("nsxwidget_move_view (xv,", scl)
        hunks = [l for l in scl.splitlines() if l.startswith("@@ ")]
        self.assertEqual(len(hunks), 1, hunks)
        self.assertTrue(hunks[0].endswith(
            "@@ ns_scroll_run (struct window *w, struct run *run)"), hunks)
        touched = {l[len("+++ b/"):] for l in scl.splitlines()
                   if l.startswith("+++ b/")}
        self.assertEqual(touched, {"src/nsterm.m"})
        cfr = body["emacs-31/ns-child-frame-resize.patch"]
        # Two-step grow of a chrome-less child frame, held view and layer,
        # a cancellable step 2, and a clear window for child frames only.
        self.assertIn("ns_child_frame_grow", cfr)
        self.assertIn("childGrowHold", cfr)
        self.assertIn("cancelPreviousPerformRequestsWithTarget", cfr)
        self.assertIn("afterDelay:0.02", cfr)
        self.assertIn("ns_update_window_opacity", cfr)
        self.assertIn("if (!FRAME_PARENT_FRAME (f))", cfr)
        for debug in ("NSLog", "DBG", "EMACS_NS_RESIZE_MODE"):
            self.assertNotIn(debug, cfr)
        touched = {l[len("+++ b/"):] for l in cfr.splitlines()
                   if l.startswith("+++ b/")}
        self.assertEqual(touched, {"src/nsterm.m", "src/nsterm.h",
                                   "src/nsfns.m"})


class HelperTests(unittest.TestCase):
    """Exercise scripts/emacs-patches.sh against generated fixtures."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pdir = self.tmp / "patches"
        self.pdir.mkdir()
        self.lock = self.pdir / "ui-patches.lock"
        self.tree = self.tmp / "tree"
        (self.tree / "src").mkdir(parents=True)
        (self.tree / "src/foo.txt").write_text("line one\nline two\nline three\n")

    def make_patch(self, rel, body):
        pf = self.pdir / rel
        pf.write_text(body)
        return pf

    def write_lock(self, entries):
        self.lock.write_text("".join(f"{sha}\t{rel}\n" for sha, rel in entries))

    def good_patch(self, rel="a.patch"):
        return self.make_patch(rel, (
            "--- a/src/foo.txt\n"
            "+++ b/src/foo.txt\n"
            "@@ -1,3 +1,4 @@\n"
            " line one\n"
            " line two\n"
            "+line inserted\n"
            " line three\n"))

    def run_helper(self, code, ok=True):
        env = dict(os.environ)
        env["EMACS_PATCH_LOCK"] = str(self.lock)
        env["EMACS_PATCH_PROVENANCE"] = "test-set"
        p = subprocess.run(
            ["bash", "-eu", "-o", "pipefail", "-c",
             f'source "{HELPER}"\n' + code],
            cwd=self.tmp, env=env, text=True, capture_output=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def test_apply_then_rerun_is_idempotent(self):
        pf = self.good_patch()
        self.write_lock([(sha256(pf), "a.patch")])
        self.run_helper('emacs_apply_patches tree')
        applied = (self.tree / "src/foo.txt").read_text()
        self.assertIn("line inserted", applied)
        second = self.run_helper('emacs_apply_patches tree')
        self.assertIn("already applied", second.stdout)
        self.assertEqual((self.tree / "src/foo.txt").read_text(), applied)

    def test_sha_mismatch_rejected_without_write(self):
        pf = self.good_patch()
        self.write_lock([("0" * 64, "a.patch")])
        # Sanity: the correct entry is fine.
        self.write_lock([(sha256(pf), "a.patch")])
        self.write_lock([("0" * 64, "a.patch")])
        self.run_helper('emacs_apply_patches tree', ok=False)
        self.assertNotIn("line inserted", (self.tree / "src/foo.txt").read_text())

    def test_broken_patch_aborts_before_any_write(self):
        # Patch 1 is valid; patch 2 cannot apply.  Nothing must be written.
        good = self.good_patch("a.patch")
        bad = self.make_patch("b.patch", (
            "--- a/src/foo.txt\n"
            "+++ b/src/foo.txt\n"
            "@@ -1,3 +1,4 @@\n"
            " line one\n"
            " THIS CONTEXT DOES NOT EXIST\n"
            "+line inserted\n"
            " line three\n"))
        self.write_lock([(sha256(good), "a.patch"), (sha256(bad), "b.patch")])
        self.run_helper('emacs_apply_patches tree', ok=False)
        self.assertEqual((self.tree / "src/foo.txt").read_text(),
                         "line one\nline two\nline three\n")
        self.assertEqual(list((self.tree / "src").glob("*.rej")), [])

    def test_partially_applied_tree_rejected(self):
        pf = self.good_patch()
        self.write_lock([(sha256(pf), "a.patch")])
        self.run_helper('emacs_apply_patches tree')
        # Corrupt the applied result so neither forward nor reverse -F0 matches.
        f = self.tree / "src/foo.txt"
        f.write_text(f.read_text().replace("line inserted", "line altered"))
        self.run_helper('emacs_apply_patches tree', ok=False)

    def test_state_change_after_precheck_is_rejected(self):
        pf = self.good_patch()
        self.write_lock([(sha256(pf), "a.patch")])
        result = self.run_helper('''
emacs_patch_state() {
  if [ -f checked-once ]; then
    echo broken
  else
    touch checked-once
    echo pending
  fi
}
emacs_apply_patches tree
''', ok=False)
        self.assertNotIn("already applied", result.stdout)
        self.assertEqual((self.tree / "src/foo.txt").read_text(),
                         "line one\nline two\nline three\n")

    def test_missing_lock_entry_file_rejected(self):
        pf = self.good_patch()
        self.write_lock([(sha256(pf), "a.patch")])
        pf.unlink()
        self.run_helper('emacs_apply_patches tree', ok=False)


class OutputMarkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pdir = self.tmp / "patches"
        self.pdir.mkdir()
        self.lock = self.pdir / "ui-patches.lock"
        pf = self.pdir / "a.patch"
        pf.write_text("--- a/x\n+++ b/x\n")
        self.lock.write_text(f"{sha256(pf)}\ta.patch\n")

    def run_helper(self, code, ok=True):
        env = dict(os.environ)
        env["EMACS_PATCH_LOCK"] = str(self.lock)
        env["EMACS_PATCH_PROVENANCE"] = "test-set"
        p = subprocess.run(
            ["bash", "-eu", "-o", "pipefail", "-c",
             f'source "{HELPER}"\n' + code],
            cwd=self.tmp, env=env, text=True, capture_output=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def test_missing_output_allowed(self):
        self.run_helper('emacs_check_patches Emacs.app')

    def test_roundtrip_and_wrong_provenance_rejected(self):
        self.run_helper('emacs_mark_patches Emacs.app')
        self.run_helper('emacs_check_patches Emacs.app')
        marker = self.tmp / "Emacs.app/Contents/Resources/ebuild-patches.txt"
        self.assertIn("patchset=", marker.read_text())
        marker.write_text("patchset=deadbeef\nprovenance=test-set\n")
        self.run_helper('emacs_check_patches Emacs.app', ok=False)

    def test_unmarked_output_rejected_and_preserved(self):
        (self.tmp / "Emacs.app/Contents/MacOS").mkdir(parents=True)
        binary = self.tmp / "Emacs.app/Contents/MacOS/Emacs"
        binary.write_text("old-output")
        self.run_helper('emacs_check_patches Emacs.app', ok=False)
        self.assertEqual(binary.read_text(), "old-output")


class WiringTests(unittest.TestCase):
    def test_local_and_ci_source_shared_helper(self):
        self.assertIn('source "$REPO_ROOT/scripts/emacs-patches.sh"', LOCAL)
        self.assertIn('emacs_apply_patches "$src"', LOCAL)
        build = run_block("Build Emacs")
        self.assertIn('source "$GITHUB_WORKSPACE/scripts/emacs-patches.sh"', build)
        self.assertIn('emacs_apply_patches "$GITHUB_WORKSPACE/$EMACS_SOURCE_DIR"',
                      build)

    def test_both_write_patch_provenance_marker(self):
        self.assertIn('emacs_mark_patches "$OUT"', LOCAL)
        self.assertIn("emacs_mark_patches Emacs.app", run_block("Build Emacs"))

    def test_no_network_or_wildcard_patch_selection(self):
        build = run_block("Build Emacs")
        for forbidden in ("fix-window-role", "raw.githubusercontent.com",
                          "system-appearance.patch", "round-undecorated-frame.patch",
                          "fix-ns-x-colors.patch", "patch -p1 <"):
            self.assertNotIn(forbidden, build)
        for forbidden in ("$WORK/patches", "*.patch", "fix-window-role",
                          "raw.githubusercontent.com"):
            self.assertNotIn(forbidden, LOCAL)

    def test_strict_f0_used_by_helper(self):
        body = HELPER.read_text()
        self.assertIn("-F0", body)
        self.assertIn("--dry-run", body)
        self.assertIn("-N --dry-run", body)  # forward: no prompts, no -R guessing
        self.assertIn("-p1 -F0 -N -R --dry-run", body)
        self.assertNotIn("--fuzz", body)


TARGETS = os.environ.get("EBUILD_UI_TARGETS")


@unittest.skipUnless(TARGETS and Path(TARGETS).is_dir(),
                     "set EBUILD_UI_TARGETS to a scratch dir of pinned target files")
class RealTargetIntegrationTests(unittest.TestCase):
    """Apply the real fixed patch set at -F0 to the pinned target files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tree = self.tmp / "tree"
        shutil.copytree(Path(TARGETS), self.tree,
                        ignore=shutil.ignore_patterns("*.orig", "*.rej"))

    def run_helper(self, code, ok=True):
        p = subprocess.run(
            ["bash", "-eu", "-o", "pipefail", "-c",
             f'source "{HELPER}"\n' + code],
            cwd=self.tmp, env=dict(os.environ), text=True, capture_output=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def test_combined_application_is_exact_f0(self):
        self.run_helper('emacs_apply_patches tree')
        ns = (self.tree / "src/nsterm.m").read_text()
        fc = (self.tree / "src/frame.c").read_text()
        nwin = (self.tree / "lisp/term/ns-win.el").read_text()
        # Intended effects.
        self.assertIn("ns_appearance_dark_aqua", ns)
        self.assertIn("systemAppearanceDidChange", ns)
        self.assertIn("undecorated_round", (self.tree / "src/frame.h").read_text())
        self.assertIn("(setq x-colors (ns-list-colors))", nwin)
        self.assertNotIn("ns_make_frame_key_window", fc)
        self.assertIn("do_switch_frame (frame1, 0, 1, Qnil)", fc)
        self.assertIn("if (dest.y < 0)", ns)
        self.assertIn('DEFSYM (Qnative, "native")',
                      (self.tree / "src/xwidget.c").read_text())
        self.assertIn("xv->y += run->desired_y - run->current_y;", ns)
        # Upstream accessibility role is left untouched.
        self.assertIn("return NSAccessibilityWindowRole;", ns)
        self.assertNotIn("NSAccessibilityTextFieldRole", ns)
        self.assertEqual(list(self.tree.rglob("*.rej")), [])
        # Reruns accept the already-applied set.
        again = self.run_helper('emacs_apply_patches tree')
        self.assertNotIn("FAILED", again.stdout + again.stderr)

    def test_partial_tree_rejected(self):
        self.run_helper('emacs_apply_patches tree')
        ns = self.tree / "src/nsterm.m"
        ns.write_text(ns.read_text().replace(
            "ns_appearance_dark_aqua", "ns_appearance_dark_aqua_typo"))
        self.run_helper('emacs_apply_patches tree', ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
