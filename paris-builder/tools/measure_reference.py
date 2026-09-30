"""Measure a reference elevation so the facade spec can be calibrated, not guessed.

The reference image is a render at a known blocks-per-pixel scale, so its bay pitch,
window-to-pier ratio and storey rhythm can be read off it as numbers. Doing this by eye
is how a facade ends up with an eleven-cell pitch and ten-cell blanks of stone.

The measurement is deliberately crude and honest: it looks for the window colour along
one horizontal line and reports the runs it finds. It is evidence for a parameter, not a
computer-vision pipeline.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def runs_of(flags):
    out, start = [], None
    for index, value in enumerate(flags):
        if value and start is None:
            start = index
        elif not value and start is not None:
            out.append((start, index - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--row', type=int, nargs='+', required=True,
                        help='image rows to scan (0 = top)')
    parser.add_argument('--blocks-per-pixel', type=float, default=None,
                        help='known scale of the render; omit to report pixels only')
    args = parser.parse_args()

    image = Image.open(args.image).convert('RGB')
    pixels = np.asarray(image).astype(int)
    print('%s  %dx%d' % (args.image.name, image.width, image.height))
    print('most common colours:')
    flat = Counter(map(tuple, pixels.reshape(-1, 3)))
    for colour, count in flat.most_common(6):
        print('   rgb%-16s %7d  %5.2f%%' % (str(colour), count, 100.0 * count / pixels.shape[0] / pixels.shape[1]))

    for row in args.row:
        if not 0 <= row < pixels.shape[0]:
            print('row %d out of range' % row)
            continue
        line = pixels[row]
        # A window is markedly lighter and less saturated than the stone around it.
        lum = 0.299 * line[:, 0] + 0.587 * line[:, 1] + 0.114 * line[:, 2]
        spread = line.max(axis=1) - line.min(axis=1)
        mask = (lum > np.percentile(lum, 75)) & (spread < 26)
        groups = runs_of(list(mask))
        widths = [b - a + 1 for a, b in groups]
        piers = [groups[i + 1][0] - groups[i][1] - 1 for i in range(len(groups) - 1)]
        pitches = [groups[i + 1][0] - groups[i][0] for i in range(len(groups) - 1)]
        print('\nrow %d: %d light runs' % (row, len(groups)))
        print('   window widths (px): %s' % widths[:20])
        print('   pier widths   (px): %s' % piers[:20])
        print('   pitch         (px): %s' % pitches[:20])
        if args.blocks_per_pixel:
            scale = args.blocks_per_pixel
            if widths:
                print('   window width (blocks): %.2f' % (sum(widths) / len(widths) * scale))
            if piers:
                print('   pier width   (blocks): %.2f' % (sum(piers) / len(piers) * scale))
            if pitches:
                print('   pitch        (blocks): %.2f' % (sum(pitches) / len(pitches) * scale))
    return


if __name__ == '__main__':
    raise SystemExit(main())
