#!/usr/bin/env python3
"""Bundled font checks. Offline, except the bundle check that needs a built app."""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = (ROOT / "scripts/emacs-font.lock").read_text()
SH = (ROOT / "scripts/emacs-font.sh").read_text()
LOCAL = (ROOT / "scripts/build.sh").read_text()
CI = (ROOT / ".github/workflows/build.yml").read_text()
FACES = ["Regular", "Italic", "Medium", "MediumItalic", "SemiBold", "SemiBoldItalic",
         "Bold", "BoldItalic", "ExtraBold", "ExtraBoldItalic"]
FAMILY = "RysMono Nerd Font Mono"


def lock_value(name):
    return re.search(rf'^readonly {name}="(.*)"$', LOCK, re.M)[1]


class FontLockTests(unittest.TestCase):
    def test_pins_are_full_sha256(self):
        for name in ("EMACS_FONT_SHA256", "EMACS_FONT_PATCHER_SHA256"):
            self.assertRegex(lock_value(name), r"^[0-9a-f]{64}$", name)

    def test_inputs_are_the_pinned_releases(self):
        self.assertEqual(lock_value("EMACS_FONT_VERSION"), "1.0.0")
        self.assertEqual(lock_value("EMACS_FONT_PATCHER_VERSION"), "3.5.1")
        self.assertIn("rysana-os/type/releases/download/v${EMACS_FONT_VERSION}/rysana-type.zip", LOCK)
        self.assertIn("ryanoasis/nerd-fonts/releases/download/v${EMACS_FONT_PATCHER_VERSION}/FontPatcher.zip", LOCK)

    def test_ten_faces(self):
        m = re.search(r"EMACS_FONT_FACES=\(\n(.*?)\n\)", SH, re.S)
        self.assertEqual(m[1].split(), FACES)

    def test_patch_flags(self):
        m = re.search(r"EMACS_FONT_PATCH_FLAGS=\(\n(.*?)\n\)", SH, re.S)
        self.assertEqual(m[1].split(), ["--complete", "--single-width-glyphs", "--careful",
                                        "--cell", "0:600:-300:1010", "--quiet", "--no-progressbars"])
        self.assertNotIn("--mono", m[1])

    def test_rename_keeps_license_records_and_sets_fixed_pitch(self):
        py = (ROOT / "scripts/emacs-font-rename.py").read_text()
        self.assertIn("KEEP = (0, 13, 14)", py)
        self.assertIn("isFixedPitch = 1", py)
        self.assertIn('"Rysana"', py)

    def test_hangul_is_removed_before_patching(self):
        py = (ROOT / "scripts/emacs-font-subset.py").read_text()
        for lo, hi in (("0x1100", "0x11FF"), ("0x3130", "0x318F"), ("0xA960", "0xA97F"),
                       ("0xAC00", "0xD7FF"), ("0xFFA0", "0xFFDF")):
            self.assertIn(f"({lo}, {hi})", py)
        prepare = SH.split("emacs_font_prepare() {", 1)[1]
        self.assertLess(prepare.index("emacs-font-subset.py"), prepare.index("font-patcher"))

    def test_build_number_was_bumped(self):
        # 5: the bundled font lost its Hangul.
        src = (ROOT / "scripts/emacs-source.lock").read_text()
        self.assertRegex(src, r'EMACS_BUILD_NUMBER="([5-9]|\d\d+)"')

    def test_installed_before_signing_locally(self):
        stage = LOCAL.split("stage_emacs() {", 1)[1]
        self.assertLess(stage.index("emacs_font_prepare"), stage.index("make -j"))
        self.assertLess(stage.index('emacs_mark_configuration "$OUT"'),
                        stage.index('emacs_font_install_bundle "$OUT"'))
        self.assertLess(stage.index('emacs_font_install_bundle "$OUT"'),
                        stage.index('emacs_sign_bundle "$OUT"'))

    def test_installed_before_signing_in_ci(self):
        build = CI.split("      - name: Build Emacs", 1)[1]
        self.assertLess(build.index("emacs_font_install_bundle Emacs.app"),
                        build.index("emacs_sign_bundle Emacs.app"))
        self.assertLess(build.index("emacs_sign_bundle Emacs.app"), build.index("tar -Jcf"))
        self.assertIn("scripts/emacs-font.sh", build)

    def test_ci_prepares_font_while_homebrew_is_present(self):
        self.assertLess(CI.index("name: Prepare the bundled font"), CI.index("name: Uninstall Homebrew"))
        self.assertIn("brew install fontforge", CI)

    def test_release_notes_name_the_font(self):
        notes = CI.split("name: Write release notes", 1)[1]
        for var in ("$EMACS_FONT_VERSION", "$EMACS_FONT_SHA256", "$EMACS_FONT_PATCHER_VERSION"):
            self.assertIn(var, notes)


@unittest.skipUnless(Path("/usr/libexec/PlistBuddy").exists(), "needs PlistBuddy (macOS)")
class InstallTests(unittest.TestCase):
    def test_install_places_fonts_and_plist_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            app = tmp / "Emacs.app"
            (app / "Contents/Resources").mkdir(parents=True)
            (app / "Contents/Info.plist").write_text(
                '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                '<key>CFBundleName</key><string>Emacs</string></dict></plist>')
            (tmp / "font/fonts").mkdir(parents=True)
            for f in FACES:
                (tmp / f"font/fonts/RysMono-{f}.ttf").write_bytes(b"x")
            (tmp / "font/OFL.txt").write_text("license")
            script = (f'source "{ROOT}/scripts/emacs-font.sh"\n'
                      f'emacs_font_install_bundle "{app}" "{tmp}/font"\n'
                      f'emacs_font_install_bundle "{app}" "{tmp}/font"\n'
                      f'emacs_font_check_bundle "{app}"')
            p = subprocess.run(["bash", "-eu", "-c", script], text=True, capture_output=True,
                               env={**os.environ, "BASH_ENV": ""})
            self.assertEqual(p.returncode, 0, p.stderr)
            fonts = sorted(x.name for x in (app / "Contents/Resources/Fonts").iterdir())
            self.assertEqual(fonts, sorted([f"RysMono-{f}.ttf" for f in FACES] + ["OFL.txt"]))


def built_app():
    found = sorted(glob.glob(str(ROOT / "build/*/Emacs.app/Contents/MacOS/Emacs")))
    env = os.environ.get("EBUILD_APP")
    if env:
        return Path(env)
    return Path(found[-1]).parents[2] if found else None


@unittest.skipUnless(built_app(), "no built Emacs.app (set EBUILD_APP or build one)")
class BuiltBundleTests(unittest.TestCase):
    """The system may have the family installed, so the files and the plist key
    are asserted first; the family list alone proves nothing."""

    def test_fonts_and_plist_key_are_in_the_bundle(self):
        app = built_app()
        fonts = app / "Contents/Resources/Fonts"
        for f in FACES:
            self.assertTrue((fonts / f"RysMono-{f}.ttf").is_file(), f)
        self.assertTrue((fonts / "OFL.txt").is_file())
        out = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Print :ATSApplicationFontsPath",
                              str(app / "Contents/Info.plist")], text=True, capture_output=True)
        self.assertEqual(out.stdout.strip(), "Fonts/")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)

    def test_emacs_lists_the_family(self):
        app = built_app()
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.txt"
            probe = Path(tmp) / "probe.el"
            probe.write_text(
                '(with-temp-file "%s" (insert (if (member "%s" (font-family-list)) "yes" "no")))\n'
                "(kill-emacs)\n" % (result, FAMILY))
            subprocess.run([str(app / "Contents/MacOS/Emacs"), "-Q", "-l", str(probe.resolve())],
                           timeout=120, capture_output=True)
            self.assertEqual(result.read_text(), "yes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
