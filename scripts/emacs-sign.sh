#!/usr/bin/env bash
# Final resource sealing, after every bundle resource/provenance marker.
# Local ad-hoc signing only: no Developer ID, notarization or entitlements.
emacs_verify_bundle() {
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$1"
}
emacs_sign_bundle() {
  local app="$1" nested
  # MacOS/libexec also holds a portable dump and a shell script. They are
  # nested-code locations to codesign, so sign these files as well.
  for nested in "$app"/Contents/MacOS/bin/* "$app"/Contents/MacOS/libexec/*; do
    [[ -f "$nested" && ! -L "$nested" ]] || continue
    /usr/bin/codesign --force --sign - "$nested" || return 1
  done
  /usr/bin/codesign --force --sign - "$app" || return 1
  emacs_verify_bundle "$app"
}
