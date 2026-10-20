#!/usr/bin/env bash
# Bundled font: Rysana Mono without its Hangul, patched with Nerd Fonts glyphs,
# renamed RysMono,
# loaded app-locally. Sourced by scripts/build.sh and the release workflow, so
# both run the same code. Pins are in scripts/emacs-font.lock.
#
#   emacs_font_prepare DIR       download, verify, patch and rename into DIR
#   emacs_font_install_bundle APP DIR   copy into APP; run before emacs_sign_bundle
#
# Needs `fontforge` on PATH (override with EMACS_FONT_FONTFORGE), plus curl,
# unzip and python3 with venv. The ttf files under DIR/src are subset in place:
# a rerun unzips them afresh first.
_EMACS_FONT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_EMACS_FONT_DIR/emacs-font.lock"

# The ten faces the config can reach: body, bold and the weights between,
# each with its italic.
readonly EMACS_FONT_FACES=(
  Regular Italic Medium MediumItalic SemiBold SemiBoldItalic
  Bold BoldItalic ExtraBold ExtraBoldItalic
)
# --single-width-glyphs, not --mono: --mono would also squash the font's own
#   two-cell glyphs (fractions, arrows) into one cell.
# --cell 0:600:-300:1010 fixes the cell: left to itself the patcher guesses it
#   from the font's advances (with Hangul, the most common was 1200) and icons
#   can come out two cells wide. 600 is the Latin advance; -300 and 1010 are the font's
#   descent and ascent.
# --careful keeps Rysana's own powerline glyphs.
readonly EMACS_FONT_PATCH_FLAGS=(
  --complete --single-width-glyphs --careful --cell 0:600:-300:1010
  --quiet --no-progressbars
)
readonly EMACS_FONT_FAMILY="RysMono Nerd Font Mono"
readonly EMACS_FONT_PLIST_KEY="ATSApplicationFontsPath"
readonly EMACS_FONT_PLIST_VALUE="Fonts/"

emacs_font_fetch() { # URL SHA256 OUT
  [[ -f "$3" ]] || curl --fail --retry 5 --retry-delay 5 --location --silent --show-error -o "$3" "$1" || return 1
  local got
  got="$(shasum -a 256 "$3" | cut -d' ' -f1)"
  if [[ "$got" != "$2" ]]; then
    echo "Bundled font: $1 has SHA-256 $got, expected $2" >&2
    return 1
  fi
}

emacs_font_prepare() {
  local dir="$1" fontforge="${EMACS_FONT_FONTFORGE:-fontforge}" face out
  command -v "$fontforge" >/dev/null || { echo "Bundled font: fontforge not found (set EMACS_FONT_FONTFORGE)" >&2; return 1; }
  rm -rf "$dir/fonts" "$dir/src" "$dir/patcher"
  mkdir -p "$dir/fonts" "$dir/src" "$dir/patcher" || return 1
  emacs_font_fetch "$EMACS_FONT_URL" "$EMACS_FONT_SHA256" "$dir/rysana-type.zip" || return 1
  emacs_font_fetch "$EMACS_FONT_PATCHER_URL" "$EMACS_FONT_PATCHER_SHA256" "$dir/FontPatcher.zip" || return 1
  unzip -q -o "$dir/rysana-type.zip" -d "$dir/src" || return 1
  unzip -q -o "$dir/FontPatcher.zip" -d "$dir/patcher" || return 1
  python3 -m venv "$dir/venv" || return 1
  "$dir/venv/bin/pip" install --quiet "fonttools==$EMACS_FONT_FONTTOOLS_VERSION" || return 1
  # Hangul goes before patching, so the patcher works on the smaller font.
  local src=()
  for face in "${EMACS_FONT_FACES[@]}"; do
    src+=("$dir/src/rysana-type/ttf/RysanaMono-$face.ttf")
  done
  "$dir/venv/bin/python" "$_EMACS_FONT_DIR/emacs-font-subset.py" "${src[@]}" || return 1
  for face in "${EMACS_FONT_FACES[@]}"; do
    "$fontforge" -quiet -script "$dir/patcher/font-patcher" "${EMACS_FONT_PATCH_FLAGS[@]}" \
      --outputdir "$dir/fonts" "$dir/src/rysana-type/ttf/RysanaMono-$face.ttf" >&2 || return 1
  done
  "$dir/venv/bin/python" "$_EMACS_FONT_DIR/emacs-font-rename.py" "$dir"/fonts/*.ttf || return 1
  for face in "${EMACS_FONT_FACES[@]}"; do
    out="$dir/fonts/RysMono-$face.ttf"
    # The patcher names its output <Family>NerdFontMono-<Style>.ttf.
    mv "$dir/fonts/RysanaMonoNerdFontMono-$face.ttf" "$out" || return 1
  done
  cp "$dir/src/rysana-type/LICENSE.txt" "$dir/OFL.txt" || return 1
}

emacs_font_install_bundle() {
  local app="$1" dir="$2" fonts="$1/Contents/Resources/Fonts" plist="$1/Contents/Info.plist"
  rm -rf "$fonts" && mkdir -p "$fonts" || return 1
  cp "$dir"/fonts/RysMono-*.ttf "$fonts/" || return 1
  cp "$dir/OFL.txt" "$fonts/OFL.txt" || return 1
  /usr/libexec/PlistBuddy -c "Delete :$EMACS_FONT_PLIST_KEY" "$plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :$EMACS_FONT_PLIST_KEY string $EMACS_FONT_PLIST_VALUE" "$plist"
}

# A reused app must already carry the fonts; it is never edited after signing.
emacs_font_check_bundle() {
  local app="$1" face
  for face in "${EMACS_FONT_FACES[@]}"; do
    [[ -f "$app/Contents/Resources/Fonts/RysMono-$face.ttf" ]] || {
      echo "Bundled font: $app lacks RysMono-$face.ttf; it predates the bundled font. Remove it and rebuild." >&2
      return 1
    }
  done
  [[ "$(/usr/libexec/PlistBuddy -c "Print :$EMACS_FONT_PLIST_KEY" "$app/Contents/Info.plist" 2>/dev/null)" == "$EMACS_FONT_PLIST_VALUE" ]] || {
    echo "Bundled font: $app Info.plist lacks $EMACS_FONT_PLIST_KEY; remove it and rebuild." >&2
    return 1
  }
}
