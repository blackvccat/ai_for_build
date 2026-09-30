"""Structural diagnostics. Counts do not substitute for client physics checks."""
from collections import deque

import numpy as np

from .schematic import base_block


def inspect_geometry(schematic, decorative_doors=()):
    mask = schematic.nonair_mask()
    height, length, width = mask.shape
    unseen = mask.copy()
    components = []
    for y, z, x in zip(*np.nonzero(mask)):
        if not unseen[y, z, x]:
            continue
        queue = deque([(int(y), int(z), int(x))])
        unseen[y, z, x] = False
        size = 0
        while queue:
            yy, zz, xx = queue.popleft()
            size += 1
            for dy, dz, dx in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                ny, nz, nx = yy+dy, zz+dz, xx+dx
                if 0 <= ny < height and 0 <= nz < length and 0 <= nx < width and unseen[ny,nz,nx]:
                    unseen[ny,nz,nx] = False
                    queue.append((ny,nz,nx))
        components.append(size)
    door_issues = []
    door_count = 0
    decorative = {tuple(row['xyz']): row['state'] for row in decorative_doors}
    decorative_seen = 0
    for palette_id, state in enumerate(schematic.id_to_state):
        if not base_block(state).endswith('_door'):
            continue
        for y,z,x in zip(*np.where(schematic.volume == palette_id)):
            door_count += 1
            if decorative.get((int(x), int(y), int(z))) == state:
                decorative_seen += 1
                continue
            lower = 'half=lower' in state
            neighbor_y = y + (1 if lower else -1)
            expected = state.replace('half=lower', 'half=upper') if lower else state.replace('half=upper','half=lower')
            if not 0 <= neighbor_y < height or schematic.id_to_state[schematic.volume[neighbor_y,z,x]] != expected:
                door_issues.append([int(x),int(y),int(z)])
    occupied = int(mask.sum())
    missing_decorative = len(decorative) - decorative_seen
    return {'status': 'FAIL' if door_issues or missing_decorative else 'PASS',
            'declared_decorative_door_cells': decorative_seen,
            'missing_or_changed_decorative_cells': missing_decorative,
            'door_halves_checked': door_count, 'unmatched_door_halves': door_issues,
            'face_connected_components': len(components),
            'largest_component_fraction': max(components, default=0)/max(1,occupied),
            'component_sizes_descending': sorted(components, reverse=True)[:20],
            'note': '6-neighbour cell adjacency is diagnostic only; partial-model attachment and client updates require separate review.'}
