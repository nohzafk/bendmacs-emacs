[![MacOS Build for GNU Emacs](https://github.com/nohzafk/bendmacs-emacs/actions/workflows/build.yml/badge.svg)](https://github.com/nohzafk/bendmacs-emacs/actions/workflows/build.yml)

# bendmacs-emacs

This repository builds the `Emacs.app` that bendmacs runs on: GNU Emacs
31.1 for macOS on Apple silicon, built from the release commit (pinned by
its full SHA, not by tag), with its dependencies linked statically, the
emacs-plus UI patches, and two local patches to Emacs's xwidget support.

bendmacs draws parts of its interface inside Emacs buffers with views that
are not text: a WebKit page, or a view that a dynamic module draws with the
GPU. Stock Emacs places, clips and hides only WebKit views, and on macOS it
leaves every xwidget view behind when a window scrolls by copying rows.
The two local patches add a `native` xwidget type whose `NSView` a dynamic
module supplies, and make xwidget views follow scrolling as they do on X.
Why each patch is shaped the way it is, and what it leaves alone, is in
[docs/xwidget-patches.md](docs/xwidget-patches.md).

## What a release contains

A release is one build of the pinned source with one patch set, configure
arguments and set of dependency versions. Its tag names the Emacs version
and this repository's build number, and never moves:

| | |
|---|---|
| Tag | `emacs-31.1-bendmacs.3` |
| Title | Emacs 31.1, bendmacs build 3 |
| Asset | `Emacs-31.1-bendmacs.3.tar.xz`, a tarball holding `Emacs.app` |
| Digest | `Emacs-31.1-bendmacs.3.tar.xz.sha256`, beside the asset |

The build number is `EMACS_BUILD_NUMBER` in `scripts/emacs-source.lock`.
Bump it by hand whenever the patch set, the configure arguments or a
dependency changes; a commit that changes only documentation or tests
does not need a new release. The build job refuses to start when the tag
for its number already exists on GitHub, so a changed build cannot replace
a published one under the same name, and a pin of a tag and its digest
keeps meaning one set of bytes.

The release notes list the source revision, the digest of the patch set,
and the patches in the order they were applied, so what a build contains
can be read without downloading it.

Releases made before this scheme are kept as they were. `emacs-31.1`
(asset `Emacs-31-snapshot-a360712c9d272d950d8d8255ef74570f7e90b7d9.tar.xz`,
no digest file) was built from the patch set below without the two xwidget
patches (`patchset=321c4e22…`); `v30.2` is the last Emacs 30 build.

### Verify and install

Download the asset and its digest, and check one against the other:

```bash
curl -fLO https://github.com/nohzafk/bendmacs-emacs/releases/download/emacs-31.1-bendmacs.3/Emacs-31.1-bendmacs.3.tar.xz
```

```bash
curl -fLO https://github.com/nohzafk/bendmacs-emacs/releases/download/emacs-31.1-bendmacs.3/Emacs-31.1-bendmacs.3.tar.xz.sha256
```

```bash
shasum -a 256 -c Emacs-31.1-bendmacs.3.tar.xz.sha256
```

```bash
tar -xJf Emacs-31.1-bendmacs.3.tar.xz
```

The bundle carries three provenance markers in `Emacs.app/Contents/Resources/`:

- `ebuild-source.txt`: the source repository, the full revision and the
  label the build directories are keyed by.
- `ebuild-patches.txt`: `patchset=`, a SHA-256 over the ordered list of
  patches (each one's digest and path), and the emacs-plus commit the
  upstream patches come from.
  It matches the digest in the release notes.
- `ebuild-configure.txt`: the configure arguments that were requested.

The bundle is signed ad hoc after the markers are written, so
`codesign --verify --deep --strict Emacs.app` checks that nothing in it
changed since. A browser download marks the files as quarantined; remove
only that attribute:

```bash
xattr -dr com.apple.quarantine Emacs.app
```

Not `xattr -cr`: codesign keeps the signatures of the bundle's non-Mach-O
files (the portable dump, a shell script) in extended attributes, and
clearing every attribute breaks the seal. For the same reason, copy the
bundle with Finder or `ditto` rather than a tool that drops extended
attributes:

```bash
ditto Emacs.app /Applications/Emacs.app
```

## The patch set

The patches are vendored under `patches/` and applied in the order
`patches/ui-patches.lock` lists them. `scripts/emacs-patches.sh` checks
each one against the SHA-256 in the lock, checks that every patch applies
before it writes anything, and applies them with `patch -F0`, so a patch
that no longer fits fails instead of being applied with fuzz. The local
build and CI run the same code. The upstream patches come from emacs-plus
at commit `6489a284d333119a05c9b0c2175bedf68250d160`.

- **system-appearance** - Adds the `ns-system-appearance-change-functions` hook and
  dark/light (`dark aqua`) appearance detection. Rebased to this revision: the
  pinned source inserted "Sleep event notification" methods where the upstream
  patch expected its insertion points, so the two affected hunks are re-anchored
  (the added code is unchanged).
- **round-undecorated-frame** - Enables rounded corners on undecorated frames
  (the Emacs 31 variant that also preserves window geometry when toggling).
- **fix-ns-x-colors** - Refreshes `x-colors` at NS window-system init so the full
  color list (~800) is available, not the headless-dump subset (~62).
- **no-frame-refocus-cocoa** (local) - Stops `delete-frame` from forcing the
  Cocoa key window onto another Emacs frame. Rebased to this revision: only the
  forced `ns_make_frame_key_window` fallback block is removed; the most-recently
  used frame selection and `do_switch_frame` are kept.
- **fix-ns-scroll-crash** - Fixes bug#81585: a bus error in `memmove`
  (`copyRect:to:`) when the header line is toggled off while
  `pixel-scroll-precision-mode` leaves a partially visible line, plus the
  header-line overpaint that remains without the `ns_scroll_run` part.
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
- **ns-child-frame-resize** (local) - Growing a chrome-less child frame
  (`undecorated` or `undecorated-round`) through one `setFrame:` shows the new
  area black for a display frame or more; AppKit presents the commits of the
  resize frame clipped to the old size. The patch grows the window first
  while the view holds its old frame and draws nothing, then applies the final
  frame 20 ms later and draws. Child-frame windows become non-opaque with a
  clear background for it; top-level and decorated frames are unchanged. NS
  only; touches `src/nsterm.m`, `src/nsterm.h` and `src/nsfns.m`.

  Titled windows do not show the band, so it cannot be reproduced with a
  normal frame. A child frame that holds a layer-backed view of its own, such
  as a `native` xwidget drawing with Metal, needs one more thing from that
  view: Emacs's views are flipped, so the layer's `contentsGravity` must be
  `kCAGravityBottomLeft` to stay pinned to the visual top while the frame
  grows. With `kCAGravityTopLeft` the old contents are drawn against the
  bottom edge and the whole view jumps down for a frame.

The obsolete emacs-28 **fix-window-role** patch is not applied: this
revision already returns `NSAccessibilityWindowRole`, so the patch would fail
forward and would reverse an upstream fix.

## Local build

`scripts/build.sh` runs the same stages as CI, but installs every
dependency into a local prefix (`build/prefix/`) instead of `/usr/local`, so
it does not touch the system or a Homebrew install.

```bash
./scripts/build.sh                # output: build/emacs-31-snapshot-<full-SHA>/Emacs.app
./scripts/build.sh emacs          # rebuild only Emacs (deps already done)
OUT="$PWD/build/try/Emacs.app" ./scripts/build.sh emacs
PREFIX=/tmp/foo ./scripts/build.sh
```

Each dependency leaves a sentinel in the prefix, so a rerun after a
failure resumes. An existing output is reused only when its three markers
match the source, the patch set and the configure arguments of this
checkout. When one differs, the build stops and deletes nothing: an app
built from another patch set is never overwritten. Set `OUT` to a new path
to build next to it; it must be absolute, because the Emacs stage copies
the app from inside the source directory. A local build is not a release and carries no build
number; only CI publishes.

## Tests

The tests are offline: they need no Emacs source, no download and no build
stage.

```bash
env -u BASH_ENV python3 tests/test_source_pin.py
env -u BASH_ENV python3 tests/test_ui_patches.py
env -u BASH_ENV python3 tests/test_configure_policy.py
env -u BASH_ENV python3 tests/test_bundle_sign.py
```

`BASH_ENV` is unset because every bash the tests start would source it,
and a shell environment can put a real `git` ahead of the tests' fake one.
`test_source_pin.py` also checks the release scheme: the names derived from
the build number, the refusal of an existing tag, and the release notes.

`tests/test_ui_patches.py` can also apply the whole patch set at `-F0` to
the real files of the pinned revision. Point `EBUILD_UI_TARGETS` at a
directory holding that revision's `src/` and `lisp/term/` (never vendored
here), for instance taken from a source checkout's own `HEAD`:

```bash
mkdir -p /tmp/ui-targets
git -C build/work/emacs-31-snapshot-<full-SHA> archive HEAD src lisp/term | tar -x -C /tmp/ui-targets
EBUILD_UI_TARGETS=/tmp/ui-targets env -u BASH_ENV python3 tests/test_ui_patches.py
```

CI runs all of this on every push and pull request: the `tests` job runs
the offline tests, fetches the pinned commit, and applies the patch set to
it. The `build` job runs only when dispatched by hand, and only after the
`tests` job passes on the same commit.

## Build configuration

The configure arguments, in `scripts/emacs-configure.sh`, request:

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
The tests here do not run the built Emacs, so they do not cover WebKit at
run time.

No package manager is used during the build: every dependency is fetched
from its upstream and compiled from source, and Emacs links them
statically (except the system frameworks), which makes link-time
optimization possible.

### Terminal mode

ncurses is built with `--with-terminfo-dirs=/usr/share/terminfo:/usr/local/share/terminfo`
so that `emacs -nw` and `emacsclient -t` can find macOS's system terminfo
database at `/usr/share/terminfo`. Without this, the compiled-in search path
only includes `/usr/local/share/terminfo` (the install prefix), which does not
exist on end-user machines and causes "Cannot open terminfo database file"
errors in terminal mode.

## Source lock

`scripts/emacs-source.lock` is the single source of truth for local and CI builds:

- Repository: `https://github.com/emacs-mirror/emacs.git`
- Commit: `a360712c9d272d950d8d8255ef74570f7e90b7d9`
- Release: `emacs-31.1` (the upstream annotated tag points at this commit)
- Label: `31-snapshot-a360712c9d272d950d8d8255ef74570f7e90b7d9`
- Build number: `2`

The shared helper fetches only this full commit SHA into a detached Git checkout.
It does not follow `master`, an Emacs 31 branch, or the release tag itself: the
SHA is pinned so a moved or deleted upstream tag cannot change what is built.
Each checkout has its own `.git`, so Emacs build metadata comes from Emacs, not
this repository. The commit is the Emacs 31.1 release commit, though it
is fetched from Git rather than from the GNU release tarball.

Both build paths use `scripts/emacs-configure.sh` to request Cocoa
xwidgets and explicitly disable native Elisp compilation. Configure
detects XWIDGETS, MODULES, TREE_SITTER, WEBP, native image APIs, GNUTLS,
LIBXML2, GMP and ZLIB, and reports no native Lisp compiler.

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

The source directory and its label stay keyed to the exact revision because
they are cache keys; the release tag and asset are named by version and
build number instead. The app bundle is always `Emacs.app`.

## Lineage

This repository was forked from
[RadioNoiseE/ebuild](https://github.com/RadioNoiseE/ebuild) and renamed
bendmacs-emacs, because the name collided with Gentoo's ebuild and said
nothing of what the repository now is. The bundle's marker files
(`ebuild-*.txt`) and the scripts' `EBUILD_*` variables keep the old name:
the markers are inside bundles already published, and the variables are
identifiers only.
