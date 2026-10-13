#!/usr/bin/env bash
# Shared source selection and source-only cache provenance; no build stages.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/emacs-source.lock"

if [[ ! "$EMACS_SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Emacs source lock must contain a full 40-character SHA" >&2
  exit 1
fi
if [[ ! "$EMACS_SOURCE_RELEASE_TAG" =~ ^emacs-[0-9]+\.[0-9]+$ ]]; then
  echo "Emacs source lock: release tag must be emacs-<major>.<minor>" >&2
  exit 1
fi
if [[ ! "$EMACS_BUILD_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
  echo "Emacs source lock: build number must be a positive integer" >&2
  exit 1
fi
# Directory and provenance label stay keyed to the exact revision: they are
# cache keys, and changing them would invalidate existing outputs.
readonly EMACS_SOURCE_LABEL="${EMACS_SOURCE_SERIES}-snapshot-${EMACS_SOURCE_REVISION}"
readonly EMACS_SOURCE_DIR="emacs-${EMACS_SOURCE_LABEL}"
# The published release names the upstream release it contains and this
# repository's build of it: tag emacs-31.1-bendmacs.2, asset
# Emacs-31.1-bendmacs.2.tar.xz. A changed build gets a new number, never the
# old name, so a pinned tag and digest keep meaning one set of bytes.
readonly EMACS_RELEASE_VERSION="${EMACS_SOURCE_RELEASE_TAG#emacs-}"
readonly EMACS_RELEASE_TAG="${EMACS_SOURCE_RELEASE_TAG}-bendmacs.${EMACS_BUILD_NUMBER}"
readonly EMACS_RELEASE_NAME="${EMACS_SOURCE_RELEASE_NAME}, bendmacs build ${EMACS_BUILD_NUMBER}"
readonly EMACS_ARTIFACT="Emacs-${EMACS_RELEASE_VERSION}-bendmacs.${EMACS_BUILD_NUMBER}.tar.xz"

emacs_source_error() {
  echo "Emacs source/cache mismatch: $*; use a fresh path (nothing was deleted)." >&2
  return 1
}

emacs_validate_source() {
  local src="$1" actual origin
  # Require a separate repository: never accept the surrounding bendmacs-emacs .git.
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

# Succeed only when REPO's origin has no tag named EMACS_RELEASE_TAG. A
# published release is never moved or overwritten, so a build whose tag
# exists stops here; `git ls-remote --exit-code` answers 2 for "no such
# ref", and any other failure is an error, not a free tag.
emacs_check_release_tag_free() {
  local repo="$1" status=0
  git -C "$repo" ls-remote --exit-code --tags origin "refs/tags/$EMACS_RELEASE_TAG" \
    >/dev/null || status=$?
  case "$status" in
    2) return 0 ;;
    0) echo "Release tag $EMACS_RELEASE_TAG already exists on origin; bump EMACS_BUILD_NUMBER in scripts/emacs-source.lock (nothing was moved)." >&2
       return 1 ;;
    *) echo "Could not list origin's tags (git ls-remote exit $status)." >&2
       return 1 ;;
  esac
}
