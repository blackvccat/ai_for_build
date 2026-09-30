"""Lossless, source-coordinate crops for understanding construction techniques.

Cleaning removes unused padding and palette entries. Decorative block states are
evidence: even unmatched door halves must not be rewritten without a semantic review.
"""
from collections import Counter
import numpy as np

from .architecture import split_state
from .schematic import AIR_BLOCKS, base_block


def state_grid(data):
    return np.asarray(data.id_to_state, dtype=object)[data.volume]


def crop(data, bounds):
    if len(bounds) != 6 or any(type(n) is not int for n in bounds):
        raise ValueError('bbox requires six integer xyz coordinates')
    x0, y0, z0, x1, y1, z1 = bounds
    if not (0 <= x0 < x1 <= data.width and 0 <= y0 < y1 <= data.height
            and 0 <= z0 < z1 <= data.length):
        raise ValueError('bbox outside source')
    raw = np.asarray(data.id_to_state, dtype=object)[data.volume[y0:y1, z0:z1, x0:x1]]
    occupied = ~np.isin(raw, list(AIR_BLOCKS))
    if not occupied.any():
        raise ValueError('empty crop')
    ys, zs, xs = np.nonzero(occupied)
    start = [int(xs.min()), int(ys.min()), int(zs.min())]
    end = [int(xs.max()) + 1, int(ys.max()) + 1, int(zs.max()) + 1]
    clean = raw[start[1]:end[1], start[2]:end[2], start[0]:end[0]].copy()
    offset = [x0 + start[0], y0 + start[1], z0 + start[2]]
    return raw, clean, offset, {
        'policy': 'PRESERVE_EVERY_RETAINED_SOURCE_STATE',
        'removed_air_padding_xyz': [[start[i], raw.shape[(2, 0, 1)[i]] - end[i]] for i in range(3)],
        'state_changes': [], 'changed_nonair_cells': 0,
        'palette_policy': 'compact used states; palette IDs are not semantic block identities',
        'door_policy': 'preserve source halves; record functional and crop-boundary questions separately',
    }


def encode(grid):
    palette, inverse = np.unique(grid, return_inverse=True)
    return inverse.reshape(grid.shape).astype(np.int32), palette.tolist()


def migrate_to_12111(grid, offset):
    """Explicit registry rename only; never infer decorative or connection states."""
    result = grid.copy()
    changes = []
    for y, z, x in np.ndindex(grid.shape):
        old = str(grid[y, z, x])
        if base_block(old) == 'minecraft:chain':
            new = old.replace('minecraft:chain', 'minecraft:iron_chain', 1)
            result[y, z, x] = new
            changes.append({'source_xyz': [offset[0]+x,offset[1]+y,offset[2]+z],
                'local_xyz':[x,y,z], 'before':old, 'after':new,
                'reason':'1.21.1 chain to 1.21.11 iron_chain; axis and waterlogged registry definitions identical'})
    return result, changes


def inventory(grid):
    exact = Counter(str(s) for s in grid.ravel() if base_block(str(s)) not in AIR_BLOCKS)
    families = Counter()
    for value, count in exact.items():
        families[base_block(value)] += count
    return {'nonair': sum(exact.values()), 'exact_states': dict(exact.most_common()),
            'base_blocks': dict(families.most_common()),
            'dimensions_whd': [grid.shape[2], grid.shape[0], grid.shape[1]]}


def state_context(data, grid, offset):
    """Locate states whose interpretation depends on source or adjacent context."""
    ox, oy, oz = offset
    issues = []
    h, d, w = grid.shape
    for y, z, x in np.ndindex(grid.shape):
        value = str(grid[y, z, x])
        name, props = split_state(value)
        if name.endswith('_door'):
            delta = 1 if props.get('half') == 'lower' else -1
            expected = value.replace('half=lower', 'half=upper') if delta == 1 else value.replace('half=upper', 'half=lower')
            sy = oy + y + delta
            source_neighbor = (data.id_to_state[int(data.volume[sy, oz + z, ox + x])]
                               if 0 <= sy < data.height else None)
            if not 0 <= y + delta < h or str(grid[y + delta, z, x]) != expected:
                issues.append({'kind': 'door_half_context', 'local_xyz': [x, y, z],
                    'source_xyz': [ox+x, oy+y, oz+z], 'state': value,
                    'source_neighbor': source_neighbor,
                    'cause': 'crop_boundary' if source_neighbor == expected else 'already_in_source',
                    'action': 'preserve; not certified as a functional door'})
        for side, (dx, dz) in {'north': (0,-1), 'south': (0,1), 'east': (1,0), 'west': (-1,0)}.items():
            if props.get(side) in ('true', 'low', 'tall') and not (0 <= x+dx < w and 0 <= z+dz < d):
                issues.append({'kind': 'connection_at_cut', 'local_xyz': [x,y,z], 'side': side,
                               'action': 'retain frozen connection; requires continuation or explicit end design'})
    return {'counts': dict(Counter(i['kind'] for i in issues)), 'items': issues,
            'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED', 'game_acceptance': 'NOT_RUN'}


def family_matches(families, exact_states, catalog):
    """Explain family compatibility with existing recipes; overlap is not quality."""
    blocks = {base_block(s) for s in exact_states}
    matches = []
    for family in families:
        examples = []
        for recipe in catalog['recipes']:
            if recipe.get('family') != family:
                continue
            states = {v[3] for v in recipe.get('voxels', [])}
            palette = {base_block(s) for s in states}
            examples.append({'id': 'v1:' + recipe['component_id'],
                             'shared_base_blocks': sorted(blocks & palette),
                             'shared_exact_states': sorted(set(exact_states) & states)})
        matches.append({'technique_id': 'technique:' + family,
                        'label': catalog['families'].get(family, family),
                        'basis': 'visually interpreted architectural role; source coordinates and states are measured',
                        'existing_recipes': examples,
                        'placement_status': 'REFERENCE_ONLY_REQUIRES_FIT_AND_STATE_TRANSFORM'})
    return matches
