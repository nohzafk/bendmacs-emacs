#!/usr/bin/env python3
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SigningTests(unittest.TestCase):
 def test_local_signs_after_markers(self):
  t=(ROOT/'scripts/build.sh').read_text(); stage=t.split('stage_emacs() {',1)[1]
  self.assertGreater(stage.index('emacs_sign_bundle "$OUT"'),stage.index('emacs_mark_configuration "$OUT" "$PREFIX"'))
 def test_cached_app_is_verified_before_skip(self):
  t=(ROOT/'scripts/build.sh').read_text().split('stage_emacs() {',1)[1]
  self.assertLess(t.index('emacs_verify_bundle "$OUT"'),t.index('skip "Emacs'))
 def test_ci_signs_before_archive(self):
  t=(ROOT/'.github/workflows/build.yml').read_text().split('      - name: Build Emacs',1)[1]
  self.assertLess(t.index('emacs_mark_configuration Emacs.app'),t.index('emacs_sign_bundle Emacs.app'))
  self.assertLess(t.index('emacs_sign_bundle Emacs.app'),t.index('tar -Jcf'))
 def test_nested_files_and_strict_verification(self):
  t=(ROOT/'scripts/emacs-sign.sh').read_text()
  self.assertIn('Contents/MacOS/bin/*',t); self.assertIn('Contents/MacOS/libexec/*',t)
  self.assertIn('--verify --deep --strict',t)
  self.assertNotIn('--deep --sign',t)
if __name__=='__main__': unittest.main(verbosity=2)
