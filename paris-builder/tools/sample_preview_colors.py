"""Sample the brightest and most common colours of a preview, to check values.

"Does the glazing read as white?" is otherwise a judgement made on a small image, and
this project has already spent several rounds on judgements like that.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--top', type=int, default=12)
    args = parser.parse_args()

    image = Image.open(args.image).convert('RGB')
    pixels = list(image.getdata())
    counts = Counter(pixels)
    print('%s  %dx%d  %d distinct colours' % (args.image.name, image.width, image.height, len(counts)))
    total = len(pixels)
    print('\nmost common colours:')
    for colour, count in counts.most_common(args.top):
        print('  rgb%-16s %7d  %5.1f%%  luminance=%3d' % (str(colour), count, 100.0 * count / total,
                                                          round(0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2])))
    lum = sorted(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels)
    print('\nluminance percentiles: p05=%.0f p25=%.0f p50=%.0f p75=%.0f p95=%.0f' % (
        lum[int(0.05 * total)], lum[int(0.25 * total)], lum[int(0.50 * total)],
        lum[int(0.75 * total)], lum[int(0.95 * total)]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
