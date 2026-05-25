[![MacOS Build for GNU Emacs](https://github.com/nohzafk/ebuild/actions/workflows/build.yml/badge.svg)](https://github.com/nohzafk/ebuild/actions/workflows/build.yml)

This repository builds GNU Emacs 30.2 for macOS with static linking and
emacs-plus patches. Base on the work of upstream [ebuild](https://github.com/RadioNoiseE/ebuild)

Builds are triggered manually via workflow dispatch.

No package manager is used during the build process, as all external
dependencies are fetched from upstream and compiled from source. A
statically linked Emacs is produced (except the system components),
making link time optimization possible.

## Patches Applied

The following patches from [emacs-plus](https://github.com/d12frosted/homebrew-emacs-plus) are applied:

- **fix-window-role** - Fixes accessibility window role for better screen reader support
- **system-appearance** - Adds `ns-system-appearance-change-functions` hook for dark/light mode detection
- **round-undecorated-frame** - Enables rounded corners on undecorated frames
- **fix-ns-x-colors** - Refreshes `x-colors` at NS window-system init so the full color list (~800) is available, not the headless-dump subset (~62)

A local patch in `patches/` is also applied:

- **no-frame-refocus-cocoa** - Stops `delete-frame` from yanking focus to another Emacs frame on macOS. Adapted from the emacs-plus emacs-28/29 patch; the equivalent block was refactored upstream in emacs-30 (`Fraise_frame` → `ns_make_frame_key_window`), so emacs-plus does not ship a 30 version.

## Features

Emacs is built with:

- GNU MP Bignum Library
- GnuTLS
- Tree-sitter
- libxml2
- WebP
- zlib
- Native Image API
- Dynamic modules support

> [!Note]
> Native compilation is not supported, since compiling libgccjit is
> considered too resource-intensive.

## Local build

`scripts/build.sh` mirrors the CI workflow but installs every dependency into a local prefix (`build/prefix/`) instead of `/usr/local`, so it does not touch the system or your Homebrew install.

```bash
./scripts/build.sh                # build everything; output in build/Emacs.app
./scripts/build.sh emacs          # rebuild only Emacs (deps already done)
PREFIX=/tmp/foo ./scripts/build.sh
```

The script is resumable — each stage has a sentinel file in the prefix and is skipped if already built. After a transient failure (e.g. flaky GNU mirror) just rerun.

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
