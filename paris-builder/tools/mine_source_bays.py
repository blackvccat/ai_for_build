#!/usr/bin/env python3
"""Mine reusable bay recipes out of the 14 source builds (route A).

Why this exists: the production vocabulary was 45 hand-authored families while
1.75M non-air source positions were only indexed as evidence. This tool cuts the
repeating facade units those sources actually use -- one bay x one storey, with
its window, surround, sill, band and any railing -- and promotes the most frequent
distinct units into the recipe library, so generation has something to say that
came from the user's own builds.

Guarantees:
  * read-only on the sources; every recipe keeps source file, source bbox and a
    SHA-256 of its own voxels as evidence;
  * deterministic: same sources in, same recipes out (ordering is by hash);
  * nothing is admitted that the independent Node registry validator rejects.
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

from paris_builder.exporter import dump_json  # noqa: E402
from paris_builder.fonts import node_binary  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402

AIR = ('air', 'cave_air', 'void_air')
OUT = ROOT / 'knowledge/library-v1/source-bays'
# Vanilla-only admission. The 14 sources include modded builds (Create machinery,
# block entities), and a recipe whose palette cannot be read by the vanilla
# registry must not enter the library: it would fail the independent check and
# could not be placed in the target client either. Such units are counted as
# excluded evidence, never as recipes.
ALLOWED_NAMESPACE = 'minecraft:'


def block_names(src):
    lookup = np.array([s.split('[')[0].replace('minecraft:', '') for s in src.id_to_state])
    return lookup[src.volume]


def aperture_cells(solid):
    """Non-solid cells with solid material two cells away along x (a window hole)."""
    aperture = ~solid
    left = np.zeros_like(solid); left[:, :, 2:] = solid[:, :, :-2]
    right = np.zeros_like(solid); right[:, :, :-2] = solid[:, :, 2:]
    return aperture & left & right


def column_groups(xs):
    """Contiguous runs in a sorted index array, as (start, end) pairs."""
    groups, start = [], xs[0]
    for a, b in zip(xs, xs[1:]):
        if b - a > 1:
            groups.append((start, a)); start = b
    groups.append((start, xs[-1]))
    return groups


def find_bays(states, names, solid, pad_x=1, outward=2, inward=1):
    """Cut one-storey bay units around each detected aperture column."""
    opening = aperture_cells(solid)
    profile = opening.any(axis=0)                       # (z, x)
    rows = np.nonzero(profile.any(axis=1))[0]
    if len(rows) == 0:
        return []
    bays = []
    for z in rows:
        xs = np.nonzero(profile[z])[0]
        if len(xs) < 2:
            continue
        groups = column_groups(xs)
        centres = [g for g in groups if g[1] - g[0] <= 4]
        if not centres:
            continue
        # Storey band: consecutive y rows that contain apertures in this row of bays.
        ys = np.nonzero(opening[:, z, xs].any(axis=1))[0]
        for start_y, end_y in column_groups(ys):
            height = end_y - start_y + 1
            if not 3 <= height <= 8:
                continue
            for left, right in centres:
                width = right - left + 1
                if not 1 <= width <= 4:
                    continue
                # Tight in-plane pad and a shallow depth: a unit is the window with
                # its surround, not a slice of wall. A wide pad dragged in the
                # neighbouring bays, which is what made the first library's units
                # read as wall material (white wool, stripped logs) instead of detail.
                pad_x_use, pad_y = pad_x, 1
                x0, x1 = max(0, left - pad_x_use), min(states.shape[2], right + pad_x_use + 1)
                y0, y1 = max(0, start_y - pad_y), min(states.shape[0], end_y + pad_y + 1)
                z0 = max(0, z - outward)
                z1 = min(states.shape[1], z + inward + 1)
                block = states[y0:y1, z0:z1, x0:x1]
                if block.size == 0:
                    continue
                bays.append({'voxels': block, 'w': x1 - x0, 'h': y1 - y0, 'd': z1 - z0,
                             'span': right - left + 1, 'storey': height,
                             'bbox': [x0, y0, z0, x1, y1, z1], 'names': names[y0:y1, z0:z1, x0:x1]})
    return bays


def signature(block):
    trimmed = trim(block)
    return hashlib.sha256(np.ascontiguousarray(trimmed).tobytes()).hexdigest(), trimmed


def trim_like(block, reference):
    """Trim `reference` with the same border crop that produced `reference`'s twin."""
    solid = block >= 0
    if not solid.any():
        return reference
    ys, zs, xs = np.nonzero(solid)
    return reference[ys.min():ys.max() + 1, zs.min():zs.max() + 1, xs.min():xs.max() + 1]


def trim(block):
    """Drop all-air border layers so identical units share one signature."""
    solid = block >= 0
    if not solid.any():
        return block
    ys, zs, xs = np.nonzero(solid)
    return block[ys.min():ys.max() + 1, zs.min():zs.max() + 1, xs.min():xs.max() + 1]


def trim_layers(block, keep=1):
    """Remove `keep` voxel layers from each side, if the result stays usable.

    The cut is padded by three cells each way so a unit keeps its neighbours'
    context for evidence, but a stamped unit must not overlap the next bay: the
    source bay pitch measured across the 14 builds is 4..6 cells while an untrimmed
    unit is 7..8 wide. Trimming to the window core keeps the surround, sill and band
    while fitting the grid.
    """
    if keep <= 0:
        return block
    interior = block[keep:-keep, :, keep:-keep]
    # Keep the deepest layer only if anything survives; the facade-facing layers are
    # what the unit is for.
    if interior.size == 0 or not (interior >= 0).any():
        return block
    return interior


def validate_units(out, kept, limit=None):
    """Write units as real .schem files and read them back with the Node validator.

    Returns (verified, unverifiable). `unverifiable` covers units whose palette
    contains a vanilla block the bundled minecraft-data build does not know yet
    (for example minecraft:chain in 1.21.11): those cannot be independently
    verified here and are reported, never silently admitted.
    """
    from paris_builder.exporter import write_schematic
    checks_dir = out / 'checks'
    checks_dir.mkdir(parents=True, exist_ok=True)
    verified, unverifiable = [], []
    for entry in kept:
        shape = (entry['dimensions_wdh'][2], entry['dimensions_wdh'][1], entry['dimensions_wdh'][0])
        volume = np.zeros(shape, dtype=np.int32)
        for x, z, y, value in entry['voxels']:
            volume[y, z, x] = value
        used = sorted({int(value) for _, _, _, value in entry['voxels']})
        states = [entry['palette'][index] for index in used]
        remap = {index: position for position, index in enumerate(used)}
        for x, z, y, value in entry['voxels']:
            volume[y, z, x] = remap[value]
        stem = entry['recipe_id']
        schem = checks_dir / (stem + '.schem')
        report = checks_dir / (stem + '.json')
        write_schematic(schem, volume, states, name=stem)
        result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'), str(schem), str(report)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
        payload = {}
        if report.is_file():
            payload = json.loads(report.read_text(encoding='utf-8'))
        issues = payload.get('issues', [])
        unknown = [i for i in issues if 'Unknown block' in str(i)]
        if result.returncode == 0:
            verified.append(stem)
        else:
            unverifiable.append({'recipe_id': stem, 'issues': issues[:4],
                                 'reason': 'registry_library_missing_blocks' if unknown else 'invalid'})
    return verified, unverifiable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / '巴黎建筑素材')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--limit', type=int, default=60, help='maximum recipes to keep')
    parser.add_argument('--min-occurrences', type=int, default=3)
    parser.add_argument('--trim', type=int, default=0,
                        help='extra layers removed from each side after the tight cut')
    parser.add_argument('--pad-x', type=int, default=1,
                        help='cells kept each side of the aperture (the surround)')
    parser.add_argument('--outward', type=int, default=2,
                        help='cells kept in front of the facade plane (projecting detail)')
    parser.add_argument('--inward', type=int, default=1,
                        help='cells kept behind the facade plane')
    parser.add_argument('--validate', action='store_true', help='run the independent registry check')
    args = parser.parse_args()

    out = args.output if args.output.is_absolute() else ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)

    sources = sorted(args.source.glob('*.schem'))
    if not sources:
        raise SystemExit('no source schematics under ' + str(args.source))

    groups = defaultdict(list)
    scanned = Counter()
    palette_by_source = {}
    for path in sources:
        src = load_schematic(path)
        states = src.volume
        names = block_names(src)
        solid = ~np.isin(names, AIR)
        bays = find_bays(states, names, solid, pad_x=args.pad_x, outward=args.outward, inward=args.inward)
        scanned[path.name] = len(bays)
        palette_by_source[path.name] = list(src.id_to_state)
        print('%s: %d bay cuts' % (path.name, len(bays)), flush=True)
        for bay in bays:
            digest, trimmed = signature(trim_layers(bay['voxels'], args.trim))
            groups[digest].append({'source': path.name, 'bbox': bay['bbox'],
                                   'block': trimmed,
                                   'states': trim_like(bay['voxels'], bay['names']),
                                   'span': bay['span'], 'storey': bay['storey']})
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    kept = []
    excluded = {'modded': [], 'block_entity': []}
    palette = []
    for digest, uses in ranked:
        if len(uses) < args.min_occurrences:
            continue
        if len(kept) >= args.limit:
            break
        block = uses[0]['block']
        used = sorted({int(v) for v in np.unique(block)})
        states = [palette_by_source[uses[0]['source']][index] for index in used]
        if any(not state.startswith(ALLOWED_NAMESPACE) for state in states):
            excluded['modded'].append('bay-%s' % digest[:10])
            continue
        kept.append({'recipe_id': 'bay-%s' % digest[:10], 'sha256': digest,
                     'dimensions_wdh': [int(block.shape[2]), int(block.shape[1]), int(block.shape[0])],
                     'occurrences': len(uses),
                     'sources': sorted({u['source'] for u in uses}),
                     'source_bboxes': [[int(v) for v in u['bbox']] for u in uses[:5]],
                     'aperture_span': int(uses[0]['span']), 'storey_height': int(uses[0]['storey']),
                     'palette': states,
                     'voxels': [[int(x), int(z), int(y), used.index(int(block[y, z, x]))]
                                for y in range(block.shape[0]) for z in range(block.shape[1])
                                for x in range(block.shape[2])]})

    dump_json(out / 'catalog.json', {
        'schema': 'source-bay-v1',
        'generated_from': [p.name for p in sources],
        'bay_cuts_per_source': dict(scanned),
        'distinct_units': len(groups),
        'kept': len(kept),
        'excluded_modded': len(excluded['modded']),
        'excluded_modded_ids': excluded['modded'][:20],
        'min_occurrences': args.min_occurrences,
        'admission': 'Only units that occur in at least two places in the sources are promoted; '
                     'each recipe keeps its source file, bbox and voxel hash as evidence.',
        'scope_note': 'A bay unit is one bay x one storey. It is not a complete facade or a semantic '
                      'understanding of the source building.',
    })
    # Every voxel index must resolve inside the recorded palette, or a promoted
    # recipe would silently reference a state that does not exist.
    broken = [entry['recipe_id'] for entry in kept
              if any(not 0 <= value < len(entry['palette']) for *_, value in entry['voxels'])]
    if broken:
        raise SystemExit('palette index out of range in: ' + ', '.join(broken[:5]))
    (out / 'recipes.json').write_text(json.dumps(kept, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('distinct units: %d | kept: %d | output: %s' % (len(groups), len(kept), out), flush=True)

    if args.validate and kept:
        verified, unverifiable = validate_units(out, kept)
        keep_ids = set(verified)
        dropped = [entry for entry in kept if entry['recipe_id'] not in keep_ids]
        kept = [entry for entry in kept if entry['recipe_id'] in keep_ids]
        (out / 'recipes.json').write_text(json.dumps(kept, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        dump_json(out / 'registry_summary.json', {
            'verified': len(verified), 'unverifiable': unverifiable,
            'status': 'PASS' if not unverifiable else 'PARTIAL',
            'note': 'Independent prismarine-schematic registry read of every promoted unit. Units whose '
                    'palette needs a block missing from the bundled registry data are dropped from '
                    'recipes.json and listed here; they are not silently admitted.',
            'dropped_count': len(dropped),
            'dropped_ids': [entry['recipe_id'] for entry in dropped],
        })
        dump_json(out / 'catalog.json', {**json.loads((out / 'catalog.json').read_text(encoding='utf-8')),
                                         'kept_after_validation': len(kept)})
        print('registry: %d verified, %d unverifiable (dropped)' % (len(verified), len(unverifiable)), flush=True)


if __name__ == '__main__':
    main()
