#!/usr/bin/env python3
"""Offline tests. The configure executable below is a recorder, not Emacs."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/emacs-configure.sh'
LOCAL = (ROOT / 'scripts/build.sh').read_text()
CI = (ROOT / '.github/workflows/build.yml').read_text()
# Retained recipe options, excluding obsolete --with-gmp on the pinned 31.
OLD_OPTIONS = ['--disable-gc-mark-trace', '--without-all',
    '--with-compress-install', '--with-file-notification=kqueue',
    '--with-gnutls', '--with-modules', '--with-native-image-api', '--with-ns',
    '--with-small-ja-dic', '--with-threads', '--with-toolkit-scroll-bars',
    '--with-tree-sitter', '--with-webp', '--with-xml2', '--with-zlib']
ADDED = ['--without-native-compilation', '--with-xwidgets']

class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.env = dict(os.environ, HELPER=str(HELPER))
        # This script only records argv. No SDK/compiler/configure checks run.
        stub = self.work / 'configure'
        stub.write_text('#!' + os.sys.executable + '\nimport json,sys\n'
                        'open("argv.json","w").write(json.dumps(sys.argv[1:]))\n')
        stub.chmod(0o755)

    def shell(self, code, ok=True):
        p = subprocess.run(['bash', '-eu', '-o', 'pipefail', '-c',
            'source "$HELPER"\n' + code], cwd=self.work, env=self.env,
            text=True, capture_output=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def args(self, prefix=''):
        code = 'emacs_configure_arguments "$TEST_PREFIX"'
        self.env['TEST_PREFIX'] = prefix
        return self.shell(code).stdout.splitlines()

    def marker(self):
        return self.work / 'Emacs.app/Contents/Resources/ebuild-configure.txt'

    def test_only_two_approved_features_added(self):
        args = self.args()
        self.assertEqual(args[:2], ['CFLAGS=-O2 -g0 -flto=thin',
                                    'PKG_CONFIG=pkgconf -static'])
        self.assertEqual([x for x in args[2:] if x not in ADDED], OLD_OPTIONS)
        for flag in ADDED:
            self.assertEqual(args.count(flag), 1)
        self.assertNotIn('--with-native-compilation', ' '.join(args))
        self.assertFalse(any('gtk' in x or 'cairo' in x for x in args))

    def test_obsolete_gmp_option_is_absent(self):
        self.assertFalse(any(x == '--with-gmp' or x.startswith('--with-gmp=')
                             or x == '--without-gmp' for x in self.args()))

    def test_actual_argv_matches_marker_for_local_and_ci(self):
        for prefix in ['', '/tmp/a prefix with spaces']:
            self.env['TEST_PREFIX'] = prefix
            self.shell('emacs_configure "$TEST_PREFIX"')
            actual = json.loads((self.work / 'argv.json').read_text())
            self.assertEqual(actual, self.args(prefix))
            if prefix:
                self.assertIn('--prefix=' + prefix, actual)
            else:
                self.assertFalse(any(x.startswith('--prefix=') for x in actual))

    def test_environment_cannot_override_feature_policy(self):
        self.env['EMACS_CONFIGURE_CFLAGS'] = '-O0'
        self.env['EMACS_CONFIGURE_OPTIONS'] = '--with-native-compilation'
        self.test_only_two_approved_features_added()
        self.shell('EMACS_CONFIGURE_OPTIONS+=(--without-xwidgets)', ok=False)

    def test_missing_output_allowed(self):
        self.shell('emacs_check_configuration Emacs.app /prefix')
        self.assertFalse((self.work / 'Emacs.app').exists())

    def test_unmarked_output_rejected_without_delete(self):
        binary = self.work / 'Emacs.app/Contents/MacOS/Emacs'
        binary.parent.mkdir(parents=True)
        binary.write_text('old app')
        self.shell('emacs_check_configuration Emacs.app /prefix', ok=False)
        self.assertEqual(binary.read_text(), 'old app')

    def test_matching_output_roundtrip(self):
        self.shell('emacs_mark_configuration Emacs.app /prefix; '
                   'emacs_check_configuration Emacs.app /prefix')
        self.assertEqual(self.marker().read_text().splitlines(), self.args('/prefix'))
        self.assertFalse((self.work / 'argv.json').exists())

    def test_old_xwidget_or_native_policy_rejected(self):
        for before, after in [('--with-xwidgets', '--without-xwidgets'),
                              ('--without-native-compilation', '--with-native-compilation')]:
            self.shell('emacs_mark_configuration Emacs.app /prefix')
            self.marker().write_text(self.marker().read_text().replace(before, after))
            self.shell('emacs_check_configuration Emacs.app /prefix', ok=False)

    def test_changed_prefix_rejected(self):
        self.shell('emacs_mark_configuration Emacs.app /prefix')
        self.shell('emacs_check_configuration Emacs.app /other-prefix', ok=False)

    def test_changed_optimization_rejected(self):
        self.shell('emacs_mark_configuration Emacs.app /prefix')
        self.marker().write_text(self.marker().read_text().replace('-O2', '-O0'))
        self.shell('emacs_check_configuration Emacs.app /prefix', ok=False)

    def test_symlink_marker_rejected(self):
        self.shell('emacs_mark_configuration Emacs.app /prefix')
        target = self.work / 'saved.txt'
        self.marker().rename(target)
        self.marker().symlink_to(target)
        self.shell('emacs_check_configuration Emacs.app /prefix', ok=False)

    def test_local_and_ci_use_shared_configuration(self):
        self.assertIn('source "$REPO_ROOT/scripts/emacs-configure.sh"', LOCAL)
        self.assertIn('source "$GITHUB_WORKSPACE/scripts/emacs-configure.sh"', CI)
        stage = LOCAL.split('stage_emacs() {', 1)[1].split('\nfor s in', 1)[0]
        self.assertIn('emacs_configure "$PREFIX"', stage)
        self.assertNotIn('./configure ', stage)
        self.assertIn('emacs_mark_configuration "$OUT" "$PREFIX"', stage)
        ci_stage = CI.split('      - name: Build Emacs', 1)[1].split('      - name: Update release tag', 1)[0]
        self.assertIn('./autogen.sh && emacs_configure\n', ci_stage)
        self.assertIn('emacs_mark_configuration Emacs.app', ci_stage)
        self.assertNotIn('./configure ', ci_stage)
        for flag in OLD_OPTIONS + ADDED:
            self.assertNotIn(flag, stage)
            self.assertNotIn(flag, ci_stage)

    def test_cache_configuration_check_precedes_skip(self):
        stage = LOCAL.split('stage_emacs() {', 1)[1].split('  # Patch dir', 1)[0]
        check = stage.index('emacs_check_configuration "$OUT" "$PREFIX"')
        self.assertLess(check, stage.index('skip "Emacs'))
        self.assertLess(check, stage.index('emacs_prepare_source "$src"'))

if __name__ == '__main__':
    unittest.main(verbosity=2)
