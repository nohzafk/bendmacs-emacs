#!/usr/bin/env python3
"""Rename patched Rysana Mono faces to RysMono and restore isFixedPitch.

"Rysana" is a Reserved Font Name under the OFL, so a modified font must not
carry it. Every name record is rewritten from "Rysana" to "Rys" except the
copyright (0) and license (13, 14) records, which keep the original wording.
The patcher clears post.isFixedPitch; it is set back to 1.
"""
import sys

from fontTools.ttLib import TTFont

KEEP = (0, 13, 14)

for path in sys.argv[1:]:
    font = TTFont(path)
    for rec in font["name"].names:
        text = rec.toUnicode()
        if "Rysana" in text and rec.nameID not in KEEP:
            rec.string = text.replace("Rysana", "Rys")
    font["post"].isFixedPitch = 1
    font.save(path)
