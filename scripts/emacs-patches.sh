#!/usr/bin/env bash
# Shared UI patch selection and application for the pinned Emacs 31 snapshot.
#
# scripts/build.sh (local) and .github/workflows/build.yml (CI) both source
# this file, so the fixed patch list, its provenance, and its strict
# application are identical.  The patch set is vendored in this repository
# (patches/); nothing is downloaded and no wildcard or $WORK cache is read.
#
# Application is deterministic and strict:
#   * every patch is verified against the SHA-256 in patches/ui-patches.lock;
#   * all patches are applied with `patch -F0` (no fuzz, no silent drift);
#   * every patch is pre-checked before anything is written, so a broken or
#     partially-applied tree fails without leaving a half-patched checkout;
#   * a patch that is already applied (reverse dry-run succeeds) is accepted
#     and skipped, which keeps local reruns idempotent.

EMACS_PATCH_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EMACS_PATCH_REPO_ROOT="$(dirname "$EMACS_PATCH_SCRIPT_DIR")"
EMACS_PATCH_LOCK="${EMACS_PATCH_LOCK:-$EMACS_PATCH_REPO_ROOT/patches/ui-patches.lock}"
EMACS_PATCH_ROOT="$(cd "$(dirname "$EMACS_PATCH_LOCK")" && pwd)"
EMACS_PATCH_PROVENANCE="${EMACS_PATCH_PROVENANCE:-d12frosted/homebrew-emacs-plus@6489a284d333119a05c9b0c2175bedf68250d160}"

emacs_patch_error() {
  echo "Emacs patch/cache mismatch: $*; use a fresh path (nothing was deleted)." >&2
  return 1
}

emacs_sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    sha256sum "$1" | cut -d' ' -f1
  fi
}

emacs_sha256_stream() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    sha256sum | cut -d' ' -f1
  fi
}

# Print "<sha256>\t<path>" for each non-comment lock entry, in file order.
emacs_patch_entries() {
  local line sha path
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    read -r sha path <<< "$line"
    if [ -z "$sha" ] || [ -z "$path" ]; then
      echo "Emacs patch lock: malformed line: $line" >&2
      return 1
    fi
    printf '%s\t%s\n' "$sha" "$path"
  done < "$EMACS_PATCH_LOCK"
}

# A stable digest of the ordered (sha256, path) list; pins the exact bytes of
# every patch in the fixed order.  Used as the output patch-provenance marker.
emacs_patches_digest() {
  emacs_patch_entries | emacs_sha256_stream
}

emacs_patches_metadata() {
  printf 'patchset=%s\nprovenance=%s\n' \
    "$(emacs_patches_digest)" "$EMACS_PATCH_PROVENANCE"
}

# Echo the state of one patch against SRC: pending | applied | broken.
# "-N --forward" makes both patch implementations ignore (rather than guess
# at or reverse) an already-applied patch and never prompt; a strict reverse
# dry-run then distinguishes "already applied" from a broken tree.
emacs_patch_state() {
  local src="$1" pf="$2"
  if ( cd "$src" && patch -p1 -F0 -N --dry-run --silent < "$pf" >/dev/null 2>&1 ); then
    echo pending
  elif ( cd "$src" && patch -p1 -F0 -N -R --dry-run --silent < "$pf" >/dev/null 2>&1 ); then
    echo applied
  else
    echo broken
  fi
}

# Apply the fixed patch set to SRC.  Fails without writing anything if any
# patch is missing, has the wrong SHA-256, or cannot be applied strictly.
emacs_apply_patches() {
  local src="$1"
  if [ ! -d "$src" ]; then
    emacs_patch_error "$src is not a directory"
    return 1
  fi
  if [ ! -f "$EMACS_PATCH_LOCK" ]; then
    emacs_patch_error "patch lock not found: $EMACS_PATCH_LOCK"
    return 1
  fi
  local entries_file
  entries_file="$(mktemp "${TMPDIR:-/tmp}/emacs-patches.XXXXXX")" || return 1
  if ! emacs_patch_entries > "$entries_file"; then
    rm -f "$entries_file"
    return 1
  fi
  if [ ! -s "$entries_file" ]; then
    rm -f "$entries_file"
    emacs_patch_error "patch lock is empty: $EMACS_PATCH_LOCK"
    return 1
  fi
  # Phase 1: verify bytes and pre-check every patch before writing anything.
  while IFS=$'\t' read -r sha path; do
    pf="$EMACS_PATCH_ROOT/$path"
    if [ ! -f "$pf" ]; then
      rm -f "$entries_file"
      emacs_patch_error "missing patch file: $pf"
      return 1
    fi
    actual="$(emacs_sha256_file "$pf")"
    if [ "$actual" != "$sha" ]; then
      rm -f "$entries_file"
      emacs_patch_error "SHA-256 mismatch for $path"
      return 1
    fi
    state="$(emacs_patch_state "$src" "$pf")"
    if [ "$state" = broken ]; then
      rm -f "$entries_file"
      emacs_patch_error "$path neither applies cleanly at -F0 nor is already applied"
      return 1
    fi
  done < "$entries_file"
  # Phase 2: apply only the pending patches, in lock order.
  while IFS=$'\t' read -r sha path; do
    pf="$EMACS_PATCH_ROOT/$path"
    state="$(emacs_patch_state "$src" "$pf")"
    if [ "$state" = pending ]; then
      if ! ( cd "$src" && patch -p1 -F0 -N --silent < "$pf" ); then
        rm -f "$entries_file"
        emacs_patch_error "failed to apply $path"
        return 1
      fi
    elif [ "$state" = applied ]; then
      echo "-- already applied: $path"
    else
      rm -f "$entries_file"
      emacs_patch_error "$path changed state after pre-check: $state"
      return 1
    fi
  done < "$entries_file"
  rm -f "$entries_file"
}

# Patch-provenance marker for a built app bundle.  The source marker records
# only the source revision; this one records the exact patch set that was
# applied, so a same-source output built from a different patch set is
# rejected instead of silently reused.
emacs_check_patches() {
  local out="$1" marker="$1/Contents/Resources/ebuild-patches.txt"
  if [ ! -e "$out" ] && [ ! -L "$out" ]; then return 0; fi
  if [ ! -f "$marker" ] || [ -L "$marker" ]; then
    emacs_patch_error "$out has no patch provenance marker"
    return 1
  fi
  if [ "$(cat "$marker")" != "$(emacs_patches_metadata)" ]; then
    emacs_patch_error "$out has different patch provenance"
    return 1
  fi
}

emacs_mark_patches() {
  mkdir -p "$1/Contents/Resources"
  emacs_patches_metadata > "$1/Contents/Resources/ebuild-patches.txt"
}
