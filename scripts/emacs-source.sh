#!/usr/bin/env bash
# Shared source selection and source-only cache provenance; no build stages.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/emacs-source.lock"

if [[ ! "$EMACS_SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Emacs source lock must contain a full 40-character SHA" >&2
  exit 1
fi
readonly EMACS_SOURCE_LABEL="${EMACS_SOURCE_SERIES}-snapshot-${EMACS_SOURCE_REVISION}"
readonly EMACS_SOURCE_DIR="emacs-${EMACS_SOURCE_LABEL}"
readonly EMACS_ARTIFACT="Emacs-${EMACS_SOURCE_LABEL}.tar.xz"
readonly EMACS_RELEASE_TAG="v${EMACS_SOURCE_LABEL}"

emacs_source_error() {
  echo "Emacs source/cache mismatch: $*; use a fresh path (nothing was deleted)." >&2
  return 1
}

emacs_validate_source() {
  local src="$1" actual origin
  # Require a separate repository: never accept the surrounding ebuild .git.
  [[ -d "$src/.git" ]] || { emacs_source_error "$src has no own .git"; return 1; }
  actual="$(git -C "$src" rev-parse --verify HEAD)" || return 1
  [[ "$actual" == "$EMACS_SOURCE_REVISION" ]] || {
    emacs_source_error "$src HEAD is $actual, expected $EMACS_SOURCE_REVISION"; return 1;
  }
  origin="$(git -C "$src" remote get-url origin)" || return 1
  [[ "$origin" == "$EMACS_SOURCE_REPOSITORY" ]] || {
    emacs_source_error "$src origin is $origin"; return 1;
  }
  # Tracked modifications are allowed: the existing UI patches/configure tweak
  # modify this checkout. This check validates source identity, not build options.
}

emacs_prepare_source() {
  local src="$1"
  if [[ -e "$src" || -L "$src" ]]; then
    emacs_validate_source "$src"
    return
  fi
  mkdir -p "$src" || return 1
  git init "$src" || return 1
  git -C "$src" remote add origin "$EMACS_SOURCE_REPOSITORY" || return 1
  # Fetch only the immutable commit, never a branch/tag or a moving tip.
  git -C "$src" fetch --depth=1 origin "$EMACS_SOURCE_REVISION" || return 1
  git -C "$src" -c advice.detachedHead=false checkout --detach "$EMACS_SOURCE_REVISION" || return 1
  emacs_validate_source "$src"
}

emacs_source_metadata() {
  printf 'repository=%s\nrevision=%s\nlabel=%s\n' \
    "$EMACS_SOURCE_REPOSITORY" "$EMACS_SOURCE_REVISION" "$EMACS_SOURCE_LABEL"
}

emacs_check_output() {
  local out="$1" marker="$1/Contents/Resources/ebuild-source.txt"
  if [[ ! -e "$out" && ! -L "$out" ]]; then return 0; fi
  [[ -f "$marker" && ! -L "$marker" ]] || {
    emacs_source_error "$out has no source provenance marker"; return 1;
  }
  [[ "$(cat "$marker")" == "$(emacs_source_metadata)" ]] || {
    emacs_source_error "$out has different source provenance"; return 1;
  }
}

emacs_mark_output() {
  mkdir -p "$1/Contents/Resources"
  emacs_source_metadata > "$1/Contents/Resources/ebuild-source.txt"
}
