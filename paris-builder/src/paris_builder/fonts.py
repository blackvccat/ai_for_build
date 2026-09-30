"""Cross-platform font and Node resolution for the rendering and packaging tools.

Font safety probe
-----------------
On some Windows hosts the TrueType backend of the installed Pillow build dies
with an access violation (0xC0000005) the moment a glyph is rendered, even for
plain Arial text; the failure is a hard process crash, so `try/except` cannot
catch it. The CJK system fonts (`msyh.ttc`, `msyhbd.ttc`, `simhei.ttf`,
`simsun.ttc`, `Deng.ttf`) are avoided for the same reason.

`load_font` therefore probes TrueType in a throwaway subprocess exactly once
per process: rendering succeeds there or the tools fall back to Pillow's built-in
bitmap font, which is always safe. These labels are ASCII/Latin only; the
Chinese documentation lives in the Markdown deliverables and needs no font.

Node policy
-----------
`node` is required for the independent prismarine registry validation. It is
resolved from PATH and a missing Node is reported as an actionable error.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import sys

# Latin-capable, and the only files considered. Order is preference, not proof.
LATIN_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)

# Kept visible so nobody "improves" the fallback order without reading the probe.
UNSAFE_CJK_FILENAMES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf")

# This probe mirrors _render's real usage: the same sizes, several fonts from one
# file, and one draw. On this host's Pillow build a second TrueType size can hard
# crash inside FreeType, so a single-size probe is not sufficient evidence.
PROBE_SIZES = (22, 12, 18)
PROBE = ("import sys\n"
         "from PIL import Image, ImageDraw, ImageFont\n"
         "sizes = [int(x) for x in sys.argv[2].split(',')]\n"
         "canvas = Image.new('RGB', (320, 160), 'white')\n"
         "draw = ImageDraw.Draw(canvas)\n"
         "for index, size in enumerate(sizes):\n"
         "    font = ImageFont.truetype(sys.argv[1], size)\n"
         "    box = font.getbbox('north / front')\n"
         "    if not box or box[2] - box[0] <= 0:\n"
         "        raise SystemExit('empty true type glyph box at size %d' % size)\n"
         "    draw.text((8, 8 + index * 30), 'north / front', font=font, fill=(36, 46, 53))\n")


def _probe(candidate: str) -> bool:
    """True only if a subprocess can load and render this font at the used sizes."""
    try:
        result = subprocess.run([sys.executable, '-c', PROBE, candidate,
                                 ','.join(str(size) for size in PROBE_SIZES)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=90)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


@lru_cache(maxsize=1)
def resolved_font_path():
    """First candidate that exists AND renders in a probe subprocess, else None."""
    for candidate in LATIN_FONT_CANDIDATES:
        if Path(candidate).is_file() and _probe(candidate):
            return candidate
    return None


@lru_cache(maxsize=64)
def load_font(size: int):
    """Usable font at `size`; the built-in bitmap font is the safe fallback."""
    from PIL import ImageFont
    path = resolved_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


@lru_cache(maxsize=1)
def font_report() -> dict:
    path = resolved_font_path()
    return {"resolved": path,
            "fallback": "Pillow built-in bitmap font (measured size only; TrueType probe failed)" if path is None else None,
            "truetype_probe": "isolated subprocess render test per process",
            "cjk_system_fonts_skipped": list(UNSAFE_CJK_FILENAMES),
            "reason": "Windows TrueType rendering can hard-crash the process; labels here are Latin only."}


def node_binary() -> str:
    """Absolute path to Node, or an actionable error naming the requirement."""
    found = shutil.which("node")
    if found:
        return found
    raise RuntimeError("Node.js is required for the independent prismarine registry validation "
                       "(tools/validate_schematic.cjs); install Node or put it on PATH")
