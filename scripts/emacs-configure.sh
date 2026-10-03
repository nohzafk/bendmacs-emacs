#!/usr/bin/env bash
# Shared Emacs configure arguments. Sourcing this file runs no build stage.
readonly EMACS_CONFIGURE_CFLAGS='-O2 -g0 -flto=thin'
readonly EMACS_CONFIGURE_PKG_CONFIG='pkgconf -static'
readonly -a EMACS_CONFIGURE_OPTIONS=(
  --disable-gc-mark-trace
  --without-all
  --without-native-compilation
  --with-compress-install
  --with-file-notification=kqueue
  --with-gnutls
  --with-modules
  --with-native-image-api
  --with-ns
  --with-xwidgets
  --with-small-ja-dic
  --with-threads
  --with-toolkit-scroll-bars
  --with-tree-sitter
  --with-webp
  --with-xml2
  --with-zlib
)

# PREFIX is explicit locally; CI keeps configure's default /usr/local.
# One argument per line preserves argument boundaries (including spaces).
emacs_configure_arguments() {
  printf '%s\n' "CFLAGS=$EMACS_CONFIGURE_CFLAGS" \
    "PKG_CONFIG=$EMACS_CONFIGURE_PKG_CONFIG"
  if [[ -n "${1:-}" ]]; then printf '%s\n' "--prefix=$1"; fi
  printf '%s\n' "${EMACS_CONFIGURE_OPTIONS[@]}"
}

emacs_configure() {
  local -a args=("CFLAGS=$EMACS_CONFIGURE_CFLAGS"
                "PKG_CONFIG=$EMACS_CONFIGURE_PKG_CONFIG")
  if [[ -n "${1:-}" ]]; then args+=("--prefix=$1"); fi
  ./configure "${args[@]}" "${EMACS_CONFIGURE_OPTIONS[@]}"
}

# This marker certifies requested arguments, not configure's detected results,
# dependency bytes, compiler/SDK identity, or inherited build environment.
emacs_check_configuration() {
  local out="$1" prefix="${2:-}"
  local marker="$out/Contents/Resources/ebuild-configure.txt"
  if [[ ! -e "$out" && ! -L "$out" ]]; then return 0; fi
  if [[ ! -f "$marker" || -L "$marker" ]]; then
    echo "Emacs configuration/cache mismatch: $out has no configure marker; use a fresh OUT path (nothing was deleted)." >&2
    return 1
  fi
  if [[ "$(cat "$marker")" != "$(emacs_configure_arguments "$prefix")" ]]; then
    echo "Emacs configuration/cache mismatch: $out has different requested arguments; use a fresh OUT path (nothing was deleted)." >&2
    return 1
  fi
}

emacs_mark_configuration() {
  local out="$1" prefix="${2:-}"
  mkdir -p "$out/Contents/Resources" || return 1
  emacs_configure_arguments "$prefix" > "$out/Contents/Resources/ebuild-configure.txt"
}
