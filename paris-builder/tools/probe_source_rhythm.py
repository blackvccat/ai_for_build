"""Feasibility probe for mining facade assemblies out of the 14 source builds.

Read-only. Answers one question: do the sources contain a regular, repeating
window-bay rhythm that can be cut out and promoted into reusable recipes, or are
they irregular one-offs? Prints detected bay rhythm and opening statistics.
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.schematic import load_schematic  # noqa: E402

GLASS = ('glass', 'pane', 'stained_glass')
OPENING = ('air',)


def base(state):
    return state.split('[')[0].replace('minecraft:', '')


def scan(path):
    src = load_schematic(path)
    states = np.array(src.id_to_state)[src.volume]          # (y, z, x)
    names = np.array([s.split('[')[0].replace('minecraft:', '') for s in src.id_to_state])[src.volume]
    solid = ~np.isin(names, ('air', 'cave_air', 'void_air'))
    # A window cell = a non-solid aperture with solid material 2 cells away on both
    # sides along the facade direction. Shifts are padded with False so shapes match.
    aperture = ~solid
    left = np.zeros_like(solid); left[:, :, 2:] = solid[:, :, :-2]
    right = np.zeros_like(solid); right[:, :, :-2] = solid[:, :, 2:]
    inner = aperture & left & right
    columns = inner.any(axis=0)                             # (z, x) has an aperture somewhere
    rows_with = columns.any(axis=1)
    zs = np.nonzero(rows_with)[0]
    print('%s  dims(y,z,x)=%s' % (path.name, src.volume.shape))
    print('   aperture columns: %d of %d   active z rows: %d' % (columns.sum(), columns.size, len(zs)))
    if len(zs) == 0:
        return
    per_row = []
    for z in zs:
        xs = np.nonzero(columns[z])[0]
        if len(xs) < 3:
            continue
        groups, start = [], xs[0]
        for a, b in zip(xs, xs[1:]):
            if b - a > 1:
                groups.append((start, a))
                start = b
        groups.append((start, xs[-1]))
        per_row.append((z, [g[1] - g[0] + 1 for g in groups],
                        [g2[0] - g1[0] for g1, g2 in zip(groups, groups[1:])]))
    spans = Counter(s for _, w, _ in per_row for s in w)
    gaps = Counter(g for _, _, gs in per_row for g in gs)
    print('   aperture widths (top 6): %s' % spans.most_common(6))
    print('   centre-to-centre gaps   : %s' % gaps.most_common(6))
    print('   rows with openings      : %d' % len(per_row))


def main():
    targets = sys.argv[1:]
    paths = ([Path(t) for t in targets] if targets else
             sorted((ROOT.parent / '巴黎建筑素材').glob('*.schem')))
    for path in paths:
        if path.is_file():
            scan(path)
            print()


if __name__ == '__main__':
    main()
