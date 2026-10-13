[![MacOS Build for GNU Emacs](https://github.com/nohzafk/ebuild/actions/workflows/build.yml/badge.svg)](https://github.com/nohzafk/ebuild/actions/workflows/build.yml)

This repository targets the pinned GNU Emacs 31.1 release source for macOS
with static linking and emacs-plus patches. Based on the work of upstream [ebuild](https://github.com/RadioNoiseE/ebuild)

Builds are triggered manually via workflow dispatch.

## Source lock and migration status

`scripts/emacs-source.lock` is the single source of truth for local and CI builds:

- Repository: `https://github.com/emacs-mirror/emacs.git`
- Commit: `a360712c9d272d950d8d8255ef74570f7e90b7d9`
- Release: `emacs-31.1` (the upstream annotated tag points at this commit)
- Label: `31-snapshot-a360712c9d272d950d8d8255ef74570f7e90b7d9`

The shared helper fetches only this full commit SHA into a detached Git checkout.
It does not follow `master`, an Emacs 31 branch, or the release tag itself: the
SHA is pinned so a moved or deleted upstream tag cannot change what is built.
Each checkout has its own `.git`, so Emacs build metadata comes from Emacs, not
this ebuild repository. The commit is the Emacs 31.1 release commit, though it
is fetched from Git rather than from the GNU release tarball.

The UI patches have been migrated to this exact revision and are vendored in
`patches/` with a fixed order and provenance in `patches/ui-patches.lock`
(`scripts/emacs-patches.sh` verifies each SHA-256 and applies them with
`patch -F0`). Both build paths now use `scripts/emacs-configure.sh` to request
Cocoa xwidgets and explicitly disable native Elisp compilation. All other
configure options and dependency versions are unchanged apart from dropping
the now-unrecognised `--with-gmp`. Configure detects XWIDGETS, MODULES,
TREE_SITTER, WEBP, native image APIs, GNUTLS, LIBXML2, GMP and ZLIB, and
reports no native Lisp compiler. A full Emacs build from this revision has
also been produced, signed, and started with a real configuration, but the
feature list below describes requested capabilities rather than a per-package
functional guarantee.

Source and default output directories include the full SHA. Existing source
caches must have their own `.git`, the locked HEAD, and the expected origin.
Existing output must have matching `Contents/Resources/ebuild-source.txt`
source provenance, `Contents/Resources/ebuild-patches.txt` patch provenance,
and `Contents/Resources/ebuild-configure.txt` requested configure arguments
before it can be reused. The configure marker records CFLAGS, PKG_CONFIG,
all explicit options, and the local prefix when supplied. A same-source,
same-patch app with different requested arguments (or no configure marker)
is rejected and preserved. This is not a full build-recipe fingerprint:
dependency bytes, inherited environment, compiler/SDK versions, and
configure's detected results are not covered.
The source marker records only the revision, so the patch marker records a
digest of the exact ordered patch set
(and its upstream provenance); a same-source app built from a different patch
set is therefore rejected instead of silently reused. A mismatch (including an
unmarked old app passed via `OUT`) stops with an error; nothing is deleted
automatically. Tracked source changes from these patches are allowed. These
checks identify the source and the patch set; they do not certify compile or
GUI behaviour.
Old `emacs-30.2` and `build/Emacs.app` caches are left untouched and are not used
by default.

CI publishes the artifact under the snapshot label but tags and titles the
release after the Emacs release it contains: asset
`Emacs-31-snapshot-<full-SHA>.tar.xz`, release tag `emacs-31.1`, release title
`Emacs 31.1`. The directory, artifact and provenance label stay keyed to the
exact revision because they are cache keys. The app bundle remains `Emacs.app`.

Run the focused offline checks (no downloads or build stages):

```bash
python3 tests/test_source_pin.py
python3 tests/test_ui_patches.py
python3 tests/test_configure_policy.py
```

`tests/test_ui_patches.py` is offline by default. To also apply the whole
fixed patch set at `-F0` against the pinned target files (downloaded into a
scratch directory, never vendored), point it at that directory:

```bash
EBUILD_UI_TARGETS=/path/to/pristine/checkout python3 tests/test_ui_patches.py
```

No package manager is used during the build process, as all external
dependencies are fetched from upstream and compiled from source. A
statically linked Emacs is produced (except the system components),
making link time optimization possible.

## Patches Applied

The UI patch set is vendored under `patches/` and applied in the fixed order
listed in `patches/ui-patches.lock`. Every patch is verified by SHA-256 and
applied with `patch -F0` (no fuzz) by `scripts/emacs-patches.sh`, both locally
and in CI. Provenance is the emacs-plus commit
`6489a284d333119a05c9b0c2175bedf68250d160`. The local xwidget patches, their
motivation and their design are explained in
[docs/xwidget-patches.md](docs/xwidget-patches.md).

- **system-appearance** - Adds the `ns-system-appearance-change-functions` hook and
  dark/light (`dark aqua`) appearance detection. Rebased to this revision: the
  pinned source inserted "Sleep event notification" methods where the upstream
  patch expected its insertion points, so the two affected hunks are re-anchored
  (the added code is unchanged).
- **round-undecorated-frame** - Enables rounded corners on undecorated frames
  (the Emacs 31 variant that also preserves window geometry when toggling).
- **fix-ns-x-colors** - Refreshes `x-colors` at NS window-system init so the full
  color list (~800) is available, not the headless-dump subset (~62).
- **fix-ns-scroll-crash** - Fixes bug#81585: a bus error in `memmove`
  (`copyRect:to:`) when the header line is toggled off while
  `pixel-scroll-precision-mode` leaves a partially visible line, plus the
  header-line overpaint that remains without the `ns_scroll_run` part.
- **no-frame-refocus-cocoa** (local) - Stops `delete-frame` from forcing the
  Cocoa key window onto another Emacs frame. Rebased to this revision: only the
  forced `ns_make_frame_key_window` fallback block is removed; the most-recently
  used frame selection and `do_switch_frame` are kept.
- **native-xwidget** (local) - Adds a `native` xwidget type on macOS (NS only):
  `make-xwidget` takes, as ARGUMENTS, a user pointer to an `NSView` that a
  dynamic module created, and redisplay places, clips and hides that view as it
  does a WebKit one. A hidden native view's container gets the `hidden`
  property, so the view receives `viewDidHide`/`viewDidUnhide`; a WebKit view is
  still moved off-screen. The per-window container now clips to its bounds for
  both types: AppKit stopped clipping subviews by default for programs linked
  against macOS 14 or later, so a widget cut by a window edge drew past it. The
  `xwidget-webkit-*` functions signal an error for a native widget. GTK and
  PGTK builds are unchanged.
- **ns-xwidget-scroll** (local) - Moves xwidget views when `ns_scroll_run`
  scrolls a window by copying rows, as `x_scroll_run` does on X. Without it a
  view stays where it was drawn while its glyph moves, one line's height off
  per line scrolled, under one-line, wheel, pixel-precision and page
  scrolling, until a full `redraw-frame`. It selects a view by the widget's
  whole rectangle, so a widget clipped to nothing or in a row partly outside
  the text area moves with its row too. NS only; touches only `src/nsterm.m`.

The obsolete emacs-28 **fix-window-role** patch is no longer applied: this
revision already returns `NSAccessibilityWindowRole`, so the patch would fail
forward and would reverse an upstream fix.

## Features

The recipe requests:

- GNU MP Bignum Library
- GnuTLS
- Tree-sitter
- libxml2
- WebP
- zlib
- Native Image API
- Dynamic modules support
- Cocoa xwidgets using the system WebKit framework

Native Elisp compilation is explicitly disabled with
`--without-native-compilation`. No GCC/libgccjit dependency is added.
The Cocoa `--with-xwidgets` path uses the macOS SDK and system WebKit;
it does not require GTK, WebKitGTK, libsoup, or a bundled browser engine.
Actual WebKit linking and loopback/WASM/WebGL behaviour still need validation.

## Local build

`scripts/build.sh` mirrors the CI workflow but installs every dependency into a local prefix (`build/prefix/`) instead of `/usr/local`, so it does not touch the system or your Homebrew install.

```bash
./scripts/build.sh                # output: build/emacs-31-snapshot-<full-SHA>/Emacs.app
./scripts/build.sh emacs          # rebuild only Emacs (deps already done)
PREFIX=/tmp/foo ./scripts/build.sh
```

Dependencies remain resumable via sentinels in the prefix. Emacs source and
output reuse also require the source-identity checks above. After a transient
failure, rerun; after a provenance mismatch, choose a fresh `WORK` or `OUT` path.

## Installation

After downloading and extracting the artifact, remove the quarantine attribute:

```bash
xattr -cr Emacs.app
```

Then move to `/Applications` or wherever you prefer.

## macOS Terminfo

ncurses is built with `--with-terminfo-dirs=/usr/share/terminfo:/usr/local/share/terminfo`
so that `emacs -nw` and `emacsclient -t` can find macOS's system terminfo
database at `/usr/share/terminfo`. Without this, the compiled-in search path
only includes `/usr/local/share/terminfo` (the install prefix), which does not
exist on end-user machines and causes "Cannot open terminfo database file"
errors in terminal mode.
