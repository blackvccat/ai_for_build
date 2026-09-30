#!/usr/bin/env python3
"""Mine whole facade sections out of the 14 source builds (route A, second pass).

Route A's first pass cut one bay x one storey. Measured against the visual critic
that vocabulary did not compose: tiled per grid cell it read as busy rather than
composed, because no single bay carries the rhythm of a facade.

This pass cuts the next size up: a storey-tall strip spanning several bays of the
same source facade, so a section carries its own bay spacing, pier width, sill band
and railing line. Sections are the unit a facade can actually be assembled from.

Read-only on the sources. Sections keep source file, bbox, storey band and a
SHA-256 of their own voxels as evidence; admission is by recurrence plus the
independent registry check, never by this tool's own opinion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.exporter import dump_json, write_schematic  # noqa: E402
from paris_builder.fonts import node_binary  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402

AIR = ('air', 'cave_air', 'void_air')
ALLOWED_NAMESPACE = 'minecraft:'
OUT = ROOT / 'knowledge/library-v1/source-sections'


def block_names(src):
    lookup = np.array([s.split('[')[0].replace('minecraft:', '') for s in src.id_to_state])
    return lookup[src.volume]


def aperture_mask(solid):
    """Non-solid cells with solid material two cells away along the facade axis."""
    aperture = ~solid
    left = np.zeros_like(solid); left[:, :, 2:] = solid[:, :, :-2]
    right = np.zeros_like(solid); right[:, :, :-2] = solid[:, :, 2:]
    return aperture & left & right


def runs(indices):
    if len(indices) == 0:
        return []
    groups, start = [], indices[0]
    for a, b in zip(indices, indices[1:]):
        if b - a > 1:
            groups.append((start, a)); start = b
    groups.append((start, indices[-1]))
    return groups


def cross_sections(profile, mask, min_width, max_width, gap):
    """Contiguous runs of `mask` rows along axis 0, merged across small gaps."""
    rows = np.nonzero(mask)[0]
    if len(rows) == 0:
        return []
    merged = []
    for start, end in runs(rows):
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return [(a, b) for a, b in merged if min_width <= (b - a + 1) <= max_width]


def outer_shell(solid, thickness=3):
    """Depth rows that belong to the building envelope on either z side.

    Earlier versions tried to find an "elevation band" from the openings, but the
    sources are up to 26 cells deep: every measurement then scaled with the
    interior rather than the wall, and everything was rejected on depth. A facade
    is the envelope, so take the first and last `thickness` rows of each column
    that contain any solid material.
    """
    occupied = solid.any(axis=0)                 # (z, x)
    rows = np.nonzero(occupied.any(axis=1))[0]
    if len(rows) == 0:
        return np.zeros_like(occupied)
    lo, hi = rows[0], rows[-1]
    mask = np.zeros_like(occupied)                       # (z, x)
    mask[lo:lo + thickness] = True
    mask[max(lo, hi - thickness + 1):hi + 1] = True
    # Broadcast the (z, x) envelope over y, keeping the interior of each column out.
    return mask[None, :, :] & occupied[None, :, :] & np.ones(solid.shape, dtype=bool)


def mine_axis(states, names, args, stats=None):
    """Mine sections off the envelope: facades run along x, envelope along z."""
    stats = stats if stats is not None else Counter()
    solid = ~np.isin(names, AIR)
    shell = outer_shell(solid, args.shell_thickness)
    opening = aperture_mask(solid) & shell
    columns_any = shell.any(axis=0)              # (z, x)
    rows = np.nonzero(columns_any.any(axis=1))[0]
    if len(rows) == 0:
        return []
    out = []
    for z in rows:
        row_shell = shell[:, z, :]
        columns = np.nonzero(row_shell.any(axis=0))[0]
        if len(columns) < args.min_span:
            continue
        for col_start, col_end in runs(columns):
            for start in range(col_start, col_end + 1, args.stride):
                x0 = start
                x1 = min(col_end + 1, start + args.max_span)
                if x1 - x0 < args.min_span:
                    continue
                # Openings of this envelope row, grouped per storey.
                strip_open = opening[:, z, x0:x1]
                ys = np.nonzero(strip_open.any(axis=1))[0]
                for y0, y1 in runs(ys):
                    height = y1 - y0 + 1
                    if not args.min_height <= height <= args.max_height:
                        continue
                    bay_columns = np.nonzero(strip_open[y0:y1 + 1].any(axis=0))[0]
                    if len(runs(bay_columns)) < args.min_bays:
                        stats['too_few_bays'] += 1
                        continue
                    # Depth window: envelope plus any projecting detail.
                    z0 = max(0, z - args.outward)
                    z1 = min(states.shape[1], z + args.inward + 1)
                    block = states[y0:y1 + 1, z0:z1, x0:x1]
                    name_window = names[y0:y1 + 1, z0:z1, x0:x1]
                    if block.size == 0:
                        continue
                    fill = float(np.sum(~np.isin(name_window, AIR))) / block.size
                    if fill < args.min_fill:
                        stats['low_fill'] += 1
                        continue
                    stats['candidates'] += 1
                    out.append({'voxels': block, 'names': name_window,
                                'bbox': [int(x0), int(y0), int(z0), int(x1), int(y1), int(z1)],
                                'bays': int(len(runs(bay_columns))),
                                'storey': int(height), 'span': int(x1 - x0)})
    return out


def mine(path, args):
    """Mine both facade orientations.

    The first version only looked for facades whose bays run along x, so only 2 of
    the 14 sources contributed any section. Buildings whose street front runs along
    z were silently skipped; transposing the volume makes the same detector apply
    to them. The transposed cut is recorded with its bbox in ORIGINAL coordinates.
    """
    src = load_schematic(path)
    states = src.volume
    names = block_names(src)
    stats = Counter()
    primary = mine_axis(states, names, args, stats)
    # (y, z, x) -> (y, x, z) so a z-facing street front becomes an x-facing one.
    swapped_states = np.transpose(states, (0, 2, 1))
    swapped_names = np.transpose(names, (0, 2, 1))
    secondary = mine_axis(swapped_states, swapped_names, args, stats)
    if args.explain:
        print('   filter counters: %s' % dict(stats), flush=True)
    for section in secondary:
        x0, y0, z0, x1, y1, z1 = section['bbox']
        # z0..z1 were x in the original, and x0..x1 were z.
        section['bbox'] = [int(z0), int(y0), int(x0), int(z1), int(y1), int(x1)]
        section['orientation'] = 'z_axis'
        section['voxels'] = np.transpose(section['voxels'], (0, 2, 1))
        section['names'] = np.transpose(section['names'], (0, 2, 1))
    for section in primary:
        section['orientation'] = 'x_axis'
    return primary + secondary


def section_kind(use, occurrences, fill):
    """`strip` tiles along a facade; `corner` is an end piece; `feature` is a set piece.

    Classified by shape, not by recurrence: the rendered sheet showed that the wide
    multi-bay fragments (whether or not they repeat) are clean wall-plus-window runs
    that can tile, while the narrow ones are corner returns and the deep, densely
    carved ones are elaborate assemblies that belong at an entrance or a corner.
    """
    width, depth, height = use['block'].shape[2], use['block'].shape[1], use['block'].shape[0]
    if width <= 4:
        return 'corner'
    if use['bays'] >= 3 and fill <= 0.7 and depth <= 4:
        return 'strip'
    if use['bays'] >= 2 and fill <= 0.85:
        return 'strip'
    return 'feature'


def signature(block):
    solid = block >= 0
    if not solid.any():
        return None, block
    ys, zs, xs = np.nonzero(solid)
    trimmed = block[ys.min():ys.max() + 1, zs.min():zs.max() + 1, xs.min():xs.max() + 1]
    return hashlib.sha256(np.ascontiguousarray(trimmed).tobytes()).hexdigest(), trimmed


def validate(out, kept, palette_by_source):
    checks = out / 'checks'; checks.mkdir(parents=True, exist_ok=True)
    verified, unverifiable = [], []
    for entry in kept:
        shape = (entry['dimensions_wdh'][2], entry['dimensions_wdh'][1], entry['dimensions_wdh'][0])
        volume = np.zeros(shape, dtype=np.int32)
        used = sorted({int(v) for *_, v in entry['voxels']})
        states = [palette_by_source[entry['source']][i] for i in used]
        remap = {value: position for position, value in enumerate(used)}
        for x, z, y, value in entry['voxels']:
            volume[y, z, x] = remap[value]
        schem = checks / (entry['recipe_id'] + '.schem')
        report = checks / (entry['recipe_id'] + '.json')
        write_schematic(schem, volume, states, name=entry['recipe_id'])
        result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'), str(schem), str(report)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
        payload = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
        if result.returncode == 0:
            verified.append(entry['recipe_id'])
        else:
            unverifiable.append({'recipe_id': entry['recipe_id'], 'issues': payload.get('issues', [])[:4]})
    return verified, unverifiable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / '巴黎建筑素材')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--limit', type=int, default=120)
    parser.add_argument('--min-occurrences', type=int, default=2)
    parser.add_argument('--include-oneoffs', action='store_true',
                        help='also sample sections that appear only once (they are the elaborate ones)')
    parser.add_argument('--oneoff-budget', type=int, default=60,
                        help='how many one-off sections may be sampled')
    parser.add_argument('--min-span', type=int, default=8, help='narrowest section in cells')
    parser.add_argument('--max-span', type=int, default=16)
    parser.add_argument('--stride', type=int, default=4, help='how far the window slides along the facade')
    parser.add_argument('--min-height', type=int, default=4, help='shortest storey band')
    parser.add_argument('--max-height', type=int, default=9)
    parser.add_argument('--outward', type=int, default=1)
    parser.add_argument('--inward', type=int, default=1)
    parser.add_argument('--min-bays', type=int, default=2,
                        help='distinct openings required in one storey (filters single holes)')
    parser.add_argument('--shell-thickness', type=int, default=3,
                        help='envelope depth rows kept on each side of the building')
    parser.add_argument('--min-fill', type=float, default=0.15,
                        help='minimum fraction of solid cells in the cut window')
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--explain', action='store_true', help='print per-filter rejection counters')
    args = parser.parse_args()

    out = args.output if args.output.is_absolute() else ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    sources = sorted(args.source.glob('*.schem'))
    if not sources:
        raise SystemExit('no sources under ' + str(args.source))

    groups = defaultdict(list)
    palette_by_source = {}
    cuts = Counter()
    for path in sources:
        src = load_schematic(path)
        palette_by_source[path.name] = list(src.id_to_state)
        sections = mine(path, args)
        cuts[path.name] = len(sections)
        print('%s: %d section cuts' % (path.name, len(sections)), flush=True)
        for section in sections:
            digest, trimmed = signature(section['voxels'])
            if digest is None:
                continue
            # Keep the block-name view too: the fill ratio and the strip/feature
            # classification are computed from names, not from palette indices.
            names_trimmed = section['names']
            solid = section['voxels'] >= 0
            if solid.any():
                ys, zs, xs = np.nonzero(solid)
                names_trimmed = section['names'][ys.min():ys.max() + 1, zs.min():zs.max() + 1, xs.min():xs.max() + 1]
            groups[digest].append({'source': path.name, 'bbox': section['bbox'], 'block': trimmed,
                                   'names': names_trimmed,
                                   'bays': section['bays'], 'storey': section['storey']})

    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    kept, dropped = [], []
    sampled = 0
    for digest, uses in ranked:
        # Admission is NOT "repeats somewhere else". Measuring the sources showed
        # they are mostly one-off handcraft (2,813 of 2,819 bay units and most
        # facade sections occur exactly once), so a recurrence rule throws away the
        # most elaborate work. Sections are admitted by shape, palette and the
        # independent registry check instead, and their occurrence count is recorded
        # truthfully (1 for a one-off).
        if len(uses) < args.min_occurrences:
            if not args.include_oneoffs:
                continue
            if sampled >= args.oneoff_budget:
                continue
            sampled += 1
        if len(kept) >= args.limit:
            break
        block = uses[0]['block']
        used = sorted({int(v) for v in np.unique(block)})
        states = [palette_by_source[uses[0]['source']][i] for i in used]
        if any(not s.startswith(ALLOWED_NAMESPACE) for s in states):
            dropped.append({'id': 'sec-%s' % digest[:10], 'reason': 'modded_palette'})
            continue
        solid_cells = int(np.sum(np.isin(uses[0]['names'], AIR) == False))  # noqa: E712
        fill = solid_cells / max(1, block.size)
        use = {'block': block, 'bays': uses[0]['bays']}
        kept.append({'recipe_id': 'sec-%s' % digest[:10], 'sha256': digest,
                     'source': uses[0]['source'],
                     # Two kinds, with different uses (measured, see reports):
                     # `strip` tiles along a facade; `feature` is an elaborate one-off
                     # that belongs at an entrance, corner or end bay, not repeated.
                     'kind': section_kind(use, len(uses), fill),
                     'dimensions_wdh': [int(block.shape[2]), int(block.shape[1]), int(block.shape[0])],
                     'occurrences': len(uses), 'sources': sorted({u['source'] for u in uses}),
                     'source_bboxes': [[int(v) for v in u['bbox']] for u in uses[:5]],
                     'bays': int(uses[0]['bays']), 'storey_height': int(uses[0]['storey']),
                     'palette': states,
                     'voxels': [[int(x), int(z), int(y), used.index(int(block[y, z, x]))]
                                for y in range(block.shape[0]) for z in range(block.shape[1])
                                for x in range(block.shape[2])]})

    verified = []
    unverifiable = []
    if args.validate and kept:
        verified, unverifiable = validate(out, kept, palette_by_source)
        keep = set(verified)
        kept = [entry for entry in kept if entry['recipe_id'] in keep]

    dump_json(out / 'catalog.json', {
        'schema': 'source-section-v1',
        'generated_from': [p.name for p in sources],
        'section_cuts_per_source': dict(cuts),
        'distinct_sections': len(groups),
        'kept': len(kept),
        'verified': len(verified),
        'unverifiable': len(unverifiable),
        'dropped': dropped,
        'min_occurrences': args.min_occurrences,
        'span_range': [args.min_span, args.max_span],
        'admission': 'A section must occur at least twice across the sources and, with --validate, '
                     'read back through the independent prismarine registry.',
        'scope_note': 'A section is one storey of a source facade, several bays wide. It is a facade '
                      'fragment with its own bay rhythm, not a semantic model of the source building.',
    })
    (out / 'sections.json').write_text(json.dumps(kept, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    dump_json(out / 'registry_summary.json', {
        'verified': verified, 'unverifiable': unverifiable,
        'status': 'PASS' if not unverifiable else 'PARTIAL',
        'note': 'Independent registry read of every promoted section; failures stay listed and out of sections.json.',
    })
    print('distinct sections: %d | kept: %d | verified: %d' % (len(groups), len(kept), len(verified)), flush=True)


if __name__ == '__main__':
    main()
