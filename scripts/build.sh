#!/usr/bin/env bash
# Local replica of .github/workflows/build.yml.
#
# Builds GNU Emacs 30.2 with the same patches and the same dependency tree
# as CI, but installs everything into a local prefix so it doesn't touch
# /usr/local or your Homebrew install.
#
#   ./scripts/build.sh                # build everything
#   ./scripts/build.sh emacs          # rebuild only Emacs (deps already done)
#   STAGES="m4 autoconf" ./scripts/build.sh
#   PREFIX=/tmp/foo ./scripts/build.sh
#
# Resume after a failure: rerun. Each dep has a sentinel file in $PREFIX;
# already-installed deps are skipped. Delete the sentinel (or $PREFIX) to
# force a rebuild.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$REPO_ROOT/build/prefix}"
WORK="${WORK:-$REPO_ROOT/build/work}"
OUT="${OUT:-$REPO_ROOT/build/Emacs.app}"
JOBS="${JOBS:-$(sysctl -n hw.ncpu)}"
EMACS_VER="30.2"

mkdir -p "$PREFIX" "$WORK"
export PATH="$PREFIX/bin:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export LDFLAGS="-L$PREFIX/lib ${LDFLAGS:-}"
export CPPFLAGS="-I$PREFIX/include ${CPPFLAGS:-}"

CURL_OPTS=(--fail --retry 5 --retry-delay 5 --location --silent --show-error)

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
skip() { printf '\033[0;33m--\033[0m  %s (already built)\n' "$*"; }

fetch() {
  local url="$1" out
  out="$(basename "$url")"
  if [[ -s "$WORK/$out" ]]; then return; fi
  ( cd "$WORK" && curl "${CURL_OPTS[@]}" -O "$url" )
}

extract() {
  local archive="$1" expect_dir="$2"
  if [[ -d "$WORK/$expect_dir" ]]; then return; fi
  case "$archive" in
    *.tar.xz)        ( cd "$WORK" && tar -Jxf "$archive" ) ;;
    *.tar.gz|*.tgz)  ( cd "$WORK" && tar -zxf "$archive" ) ;;
    *) echo "unknown archive: $archive" >&2; exit 1 ;;
  esac
}

# Build a configure-style autotools dependency.
#   build_dep <name> <sentinel> <url> <srcdir> [-- configure args...]
build_dep() {
  local name="$1" sentinel="$2" url="$3" srcdir="$4"; shift 4
  if [[ "${1:-}" == "--" ]]; then shift; fi
  if [[ -e "$PREFIX/$sentinel" ]]; then skip "$name"; return; fi
  log "$name"
  fetch "$url"
  extract "$(basename "$url")" "$srcdir"
  ( cd "$WORK/$srcdir" && ./configure --prefix="$PREFIX" "$@" && make -j"$JOBS" && make install )
}

# Selective stage runner: STAGES="m4 autoconf" ./build.sh runs only those.
# CLI args also act as a stage filter: ./build.sh emacs
ALL_STAGES=(
  m4 autoconf automake libtool pkgconf texinfo libiconv libunistring
  gettext ncurses zlib libwebp libxml2 gmp nettle libidn2 gnutls treesitter
  gzip emacs
)

if [[ $# -gt 0 ]]; then
  STAGES="$*"
fi
WANT="${STAGES:-${ALL_STAGES[*]}}"
should_run() {
  local s="$1"
  [[ " $WANT " == *" $s "* ]]
}

stage_m4()           { build_dep "GNU M4"            bin/m4               https://ftpmirror.gnu.org/gnu/m4/m4-1.4.21.tar.xz                                    m4-1.4.21; }
stage_autoconf()     { build_dep "GNU Autoconf"      bin/autoconf         https://ftpmirror.gnu.org/gnu/autoconf/autoconf-2.72.tar.xz                          autoconf-2.72; }
stage_automake()     { build_dep "GNU Automake"      bin/automake         https://ftpmirror.gnu.org/gnu/automake/automake-1.18.tar.xz                          automake-1.18; }
stage_libtool()      { build_dep "GNU Libtool"       bin/libtool          https://ftpmirror.gnu.org/gnu/libtool/libtool-2.5.4.tar.xz                           libtool-2.5.4 -- --disable-shared; }
stage_texinfo()      { build_dep "GNU Texinfo"       bin/makeinfo         https://ftpmirror.gnu.org/gnu/texinfo/texinfo-7.3.tar.xz                             texinfo-7.3; }
stage_libiconv()     { build_dep "GNU Libiconv"      lib/libiconv.a       https://ftpmirror.gnu.org/gnu/libiconv/libiconv-1.19.tar.gz                          libiconv-1.19   -- --disable-shared; }
stage_libunistring() { build_dep "GNU Libunistring"  lib/libunistring.a   https://ftpmirror.gnu.org/gnu/libunistring/libunistring-1.4.2.tar.xz                 libunistring-1.4.2 -- --disable-shared; }
stage_gettext()      { build_dep "GNU Gettext"       bin/msgfmt           https://ftpmirror.gnu.org/gnu/gettext/gettext-0.26.tar.xz                            gettext-0.26    -- --disable-shared; }
stage_libxml2()      { build_dep "Libxml2"           lib/libxml2.a        https://download.gnome.org/sources/libxml2/2.15/libxml2-2.15.2.tar.xz                libxml2-2.15.2  -- --disable-shared; }
stage_libwebp()      { build_dep "Libwebp"           lib/libwebp.a        https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-1.6.0.tar.gz libwebp-1.6.0 -- --disable-shared; }
stage_gmp()          { build_dep "GNU GMP"           lib/libgmp.a         https://ftpmirror.gnu.org/gnu/gmp/gmp-6.3.0.tar.xz                                   gmp-6.3.0       -- --disable-shared; }
stage_nettle()       { build_dep "Nettle"            lib/libnettle.a      https://ftpmirror.gnu.org/gnu/nettle/nettle-3.10.2.tar.gz                            nettle-3.10.2   -- --disable-shared; }
stage_libidn2()      { build_dep "Libidn2"           lib/libidn2.a        https://ftpmirror.gnu.org/gnu/libidn/libidn2-2.3.8.tar.gz                            libidn2-2.3.8   -- --disable-shared; }
stage_gnutls()       { build_dep "GnuTLS"            lib/libgnutls.a      https://www.gnupg.org/ftp/gcrypt/gnutls/v3.8/gnutls-3.8.12.tar.xz                    gnutls-3.8.12   -- --disable-shared --with-included-libtasn1 --without-p11-kit; }
stage_gzip()         { build_dep "GNU Gzip"          bin/gzip             https://ftpmirror.gnu.org/gnu/gzip/gzip-1.14.tar.xz                                  gzip-1.14; }

# Pkgconf: needs autogen.sh, plus pkg-config symlink.
stage_pkgconf() {
  if [[ -e "$PREFIX/bin/pkgconf" ]]; then skip "Pkgconf"; return; fi
  log "Pkgconf"
  fetch "https://github.com/pkgconf/pkgconf/archive/refs/tags/pkgconf-2.5.1.tar.gz"
  extract "pkgconf-2.5.1.tar.gz" "pkgconf-pkgconf-2.5.1"
  ( cd "$WORK/pkgconf-pkgconf-2.5.1"
    ./autogen.sh
    ./configure --prefix="$PREFIX" --disable-shared
    make -j"$JOBS"
    make install )
  ln -sf "$PREFIX/bin/pkgconf" "$PREFIX/bin/pkg-config"
}

# Ncurses: --with-terminfo-dirs so emacs -nw finds /usr/share/terminfo,
# plus a curses.h compatibility symlink.
stage_ncurses() {
  if [[ -e "$PREFIX/lib/libncursesw.a" ]]; then skip "Ncurses"; return; fi
  log "Ncurses"
  fetch "https://ftpmirror.gnu.org/gnu/ncurses/ncurses-6.6.tar.gz"
  extract "ncurses-6.6.tar.gz" "ncurses-6.6"
  ( cd "$WORK/ncurses-6.6"
    ./configure --prefix="$PREFIX" --disable-shared \
                --with-terminfo-dirs=/usr/share/terminfo:/usr/local/share/terminfo
    make -j"$JOBS"
    make install )
  ln -sf "$PREFIX/include/ncursesw/curses.h" "$PREFIX/include/ncurses.h"
}

# Zlib: uses its own configure script (no autotools), takes --static, --prefix.
stage_zlib() {
  if [[ -e "$PREFIX/lib/libz.a" ]]; then skip "Zlib"; return; fi
  log "Zlib"
  fetch "https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.xz"
  extract "zlib-1.3.2.tar.xz" "zlib-1.3.2"
  ( cd "$WORK/zlib-1.3.2"
    ./configure --static --prefix="$PREFIX"
    make -j"$JOBS"
    make install )
}

# tree-sitter: no autoconf; Makefile honors PREFIX. Delete dylibs to force
# static linkage in Emacs.
stage_treesitter() {
  if [[ -e "$PREFIX/lib/libtree-sitter.a" ]]; then skip "tree-sitter"; return; fi
  log "tree-sitter"
  fetch "https://github.com/tree-sitter/tree-sitter/archive/refs/tags/v0.25.10.tar.gz"
  extract "v0.25.10.tar.gz" "tree-sitter-0.25.10"
  ( cd "$WORK/tree-sitter-0.25.10"
    make -j"$JOBS" PREFIX="$PREFIX"
    make install PREFIX="$PREFIX" )
  find "$PREFIX/lib" -name 'libtree-sitter*.dylib' -delete
}

# Emacs: download tarball, apply emacs-plus + local patches, configure, build.
stage_emacs() {
  local src="$WORK/emacs-$EMACS_VER"
  if [[ -e "$OUT/Contents/MacOS/Emacs" ]]; then skip "Emacs"; return; fi
  log "Emacs $EMACS_VER"
  fetch "https://ftpmirror.gnu.org/gnu/emacs/emacs-$EMACS_VER.tar.xz"
  extract "emacs-$EMACS_VER.tar.xz" "emacs-$EMACS_VER"

  # Patch dir: cache patches outside the source tree so re-extraction (e.g.
  # after `rm -rf emacs-$EMACS_VER`) doesn't re-download them.
  local patchdir="$WORK/patches"
  mkdir -p "$patchdir"
  local patches=(
    "https://raw.githubusercontent.com/d12frosted/homebrew-emacs-plus/master/patches/emacs-28/fix-window-role.patch"
    "https://raw.githubusercontent.com/d12frosted/homebrew-emacs-plus/master/patches/emacs-30/system-appearance.patch"
    "https://raw.githubusercontent.com/d12frosted/homebrew-emacs-plus/master/patches/emacs-30/round-undecorated-frame.patch"
    "https://raw.githubusercontent.com/d12frosted/homebrew-emacs-plus/master/patches/emacs-30/fix-ns-x-colors.patch"
  )
  for url in "${patches[@]}"; do
    local f="$patchdir/$(basename "$url")"
    [[ -s "$f" ]] || curl "${CURL_OPTS[@]}" -o "$f" "$url"
  done

  # Apply patches idempotently: skip if already applied (rerunnable after
  # partial failures without `rm -rf` of the source).
  cd "$src"
  for f in "$patchdir"/*.patch "$REPO_ROOT/patches/no-frame-refocus-cocoa.patch"; do
    if patch -p1 --dry-run --silent < "$f" >/dev/null 2>&1; then
      patch -p1 < "$f"
    elif patch -p1 -R --dry-run --silent < "$f" >/dev/null 2>&1; then
      log "  already applied: $(basename "$f")"
    else
      echo "patch will not apply: $f" >&2
      exit 1
    fi
  done

  # Same configure.ac tweak as CI: force libncursesw on darwin.
  sed -i '' '/darwin/ s/lncurses/lncursesw/g' configure.ac

  if [[ ! -f configure ]]; then ./autogen.sh; fi
  ./configure CFLAGS='-O2 -g0 -flto=thin'      \
              PKG_CONFIG='pkgconf -static'     \
              --prefix="$PREFIX"               \
              --disable-gc-mark-trace          \
              --without-all                    \
              --with-compress-install          \
              --with-file-notification=kqueue  \
              --with-gmp                       \
              --with-gnutls                    \
              --with-modules                   \
              --with-native-image-api          \
              --with-ns                        \
              --with-small-ja-dic              \
              --with-threads                   \
              --with-toolkit-scroll-bars       \
              --with-tree-sitter               \
              --with-webp                      \
              --with-xml2                      \
              --with-zlib
  make -j"$JOBS"
  make install
  rm -rf "$OUT"
  ditto nextstep/Emacs.app "$OUT"
  log "Built: $OUT"
}

for s in "${ALL_STAGES[@]}"; do
  if should_run "$s"; then "stage_$s"; fi
done

log "Done. Emacs.app at: $OUT"
log "Test:  '$OUT/Contents/MacOS/Emacs' --version"
