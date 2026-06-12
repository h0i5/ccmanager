#!/usr/bin/env fontforge -script
"""
Build ClaudeLogo.ttf — single-glyph font containing the Claude sunburst
logomark at private-use codepoint U+E900.

Usage:
    fontforge -script tools/build_font.py

Input:  assets/claude.svg   (simple-icons Claude logomark, viewBox 0 0 24 24)
Output: assets/ClaudeLogo.ttf

Install after generating:
    cp assets/ClaudeLogo.ttf ~/.local/share/fonts/ && fc-cache -f
"""

import fontforge
import os

HERE    = os.path.dirname(os.path.abspath(__file__))
SVG_IN  = os.path.join(HERE, "..", "assets", "claude.svg")
TTF_OUT = os.path.join(HERE, "..", "assets", "ClaudeLogo.ttf")

EM          = 1000   # units per em
CODEPOINT   = 0xE900 # private use area — won't collide with any real font

f = fontforge.font()
f.fontname   = "ClaudeLogo"
f.familyname = "ClaudeLogo"
f.fullname   = "ClaudeLogo"
f.encoding   = "UnicodeBMP"
f.em         = EM

g = f.createChar(CODEPOINT, "claudelogo")
g.importOutlines(SVG_IN)

# simple-icons SVG: viewBox="0 0 24 24", Y-down.
# FontForge imports SVG with an automatic Y-flip + scale to em, so the glyph
# should land roughly right.  We center it horizontally and sit it on baseline.
g.removeOverlap()
g.simplify()
g.canonicalContours()
g.canonicalStart()

# Tight bounding box after import
bb = g.boundingBox()   # (xmin, ymin, xmax, ymax)
glyph_w = bb[2] - bb[0]
glyph_h = bb[3] - bb[1]

# Scale to 70% of em HEIGHT — keeps the logo legible regardless of aspect ratio
bb = g.boundingBox()
glyph_w = bb[2] - bb[0]
glyph_h = bb[3] - bb[1]

if glyph_h > 0:
    scale = (EM * 0.70) / glyph_h
    g.transform((scale, 0, 0, scale, 0, 0))

# Re-read bb post-scale
bb = g.boundingBox()
glyph_w = bb[2] - bb[0]

# Sit on baseline, center horizontally, advance width = glyph width + 200 margin
MARGIN = 100
shift_y = -bb[1]
shift_x = -bb[0] + MARGIN
g.transform((1, 0, 0, 1, shift_x, shift_y))

g.width = int(glyph_w + MARGIN * 2)

f.generate(TTF_OUT)
print(f"Generated {TTF_OUT}")
