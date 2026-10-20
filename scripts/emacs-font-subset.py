#!/usr/bin/env python3
"""Drop the Hangul glyphs from Rysana Mono faces, in place.

Emacs never draws Hangul with the mono font: bendmacs assigns the `hangul'
script to its CJK family with set-fontset-font. The ranges below are the
ones `char-script-table' gives the `hangul' script in Emacs 31.1, so exactly
what that assignment takes away is removed, and nothing Emacs could still
reach. They are 11,223 of the font's 29,383 glyphs and a quarter of each file.

Every other codepoint, OpenType feature, name record and the hinting are
kept. Run before the Nerd Fonts patcher, so the patcher works on the smaller
font; the rename that follows covers the OFL's modified-version rule.
"""
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

HANGUL = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3130, 0x318F),  # Hangul Compatibility Jamo
    (0xA960, 0xA97F),  # Hangul Jamo Extended-A
    (0xAC00, 0xD7FF),  # Hangul Syllables, Hangul Jamo Extended-B
    (0xFFA0, 0xFFDF),  # Halfwidth Hangul
)


def is_hangul(cp):
    return any(lo <= cp <= hi for lo, hi in HANGUL)


options = subset.Options()
options.layout_features = ["*"]
options.name_IDs = ["*"]
options.name_languages = ["*"]
options.name_legacy = True
options.notdef_glyph = True
options.notdef_outline = True
options.glyph_names = True
options.legacy_kern = True
options.symbol_cmap = True
options.legacy_cmap = True
options.passthrough_tables = True
options.drop_tables = []

for path in sys.argv[1:]:
    font = TTFont(path)
    keep = [cp for cp in font.getBestCmap() if not is_hangul(cp)]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=keep)
    subsetter.subset(font)
    left = [cp for cp in font.getBestCmap() if is_hangul(cp)]
    if left:
        sys.exit(f"{path}: {len(left)} Hangul codepoints survived the subset")
    font.save(path)
