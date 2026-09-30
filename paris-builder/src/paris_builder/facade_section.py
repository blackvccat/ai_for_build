"""Voxel section evidence measured from exports, never from generator claims."""
from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np

from .schematic import AIR_BLOCKS, base_block, load_schematic


def runs(values):
    result = []
    start = None
    for i, value in enumerate(list(values) + [False]):
        if value and start is None:
            start = i
        elif not value and start is not None:
            result.append([start, i - 1])
            start = None
    return result


def measure(path):
    """Report integer voxel depths; slabs/stairs are not full-cube surfaces."""
    path = Path(path)
    s = load_schematic(path)
    names = [base_block(state) for state in s.id_to_state]
    def mask(predicate):
        return np.isin(s.volume, [i for i, name in enumerate(names) if predicate(name)])
    air = mask(lambda n: n in AIR_BLOCKS)
    stone = mask(lambda n: any(k in n for k in ('sandstone', 'stone_bricks', 'quartz')))
    full_stone = mask(lambda n: any(k in n for k in ('sandstone', 'stone_bricks', 'quartz'))
                      and not n.endswith(('_slab', '_stairs', '_wall')))
    wood = mask(lambda n: n.endswith('_planks'))
    glass = mask(lambda n: 'glass' in n)
    roof = mask(lambda n: 'deepslate' in n or 'blackstone' in n)
    report = {'version': 1, 'source': {'path': str(path.resolve()),
              'sha256': sha256(path.read_bytes()).hexdigest(), 'voxel_state_hash': s.voxel_state_hash()},
              'coordinates': 'local export [x,y,z]; north=-z, east=+x, west=-x, south=+z',
              'method': 'Foundation footprint, broad wood floor plates, masonry skins and roof-family voxels measured independently. No manifest coordinates or counts used.',
              'limitations': ['Voxel depths, not sub-block model dimensions; slabs/stairs occupy partial cells.',
                             'Material classifier supports the current sandstone/deepslate palette; unsupported materials are unmeasured.',
                             'Roof samples include all roof-family voxels, including chimney/crest spikes; compare multiple sections. Dormer interruptions remain visible.',
                             'Measurements establish geometry, not aesthetic or game acceptance.'],
              'status': 'unmeasured'}
    foundation = full_stone[0]
    z, x = np.where(foundation)
    if not len(x):
        report['reason'] = 'No supported foundation found at y=0.'
        return report
    x0, x1, z0, z1 = map(int, (x.min(), x.max(), z.min(), z.max()))
    area = int(foundation.sum())
    floors = np.flatnonzero(wood[:, z0:z1+1, x0:x1+1].sum(axis=(1, 2)) >= area * .45).tolist()
    if len(floors) < 2:
        report['reason'] = 'Cannot independently locate at least two broad floor plates.'
        return report
    # The NE cut is read from missing foundation cells, not the requested chamfer.
    cut = 0
    while x1 - cut >= x0 and not foundation[z0, x1 - cut]:
        cut += 1
    diagonal = [(x1 - cut + d, z0 + d) for d in range(cut + 1)] if cut else []
    paths = {
        'street_north': [(u, z0, 0, 1) for u in range(x0+1, x1-cut+1)],
        'street_east': [(x1, u, -1, 0) for u in range(z0+cut, z1)],
        'chamfer': [(u, v, -1, 1) for u, v in diagonal],
        'party_west': [(x0, u, 1, 0) for u in range(z0, z1+1)],
        'party_south': [(u, z1, 0, -1) for u in range(x0, x1+1)]}
    def at(m, u, y, v):
        return bool(m[y, v, u]) if 0 <= u < s.width and 0 <= v < s.length and 0 <= y < s.height else False
    def opening(u, y, v, dx, dz):
        # A solid skin blocks any glazing inside the building from becoming a window.
        for d in range(4):
            xx, zz = u + d*dx, v + d*dz
            if at(glass, xx, y, zz): return d, 'glazing'
            if not at(air, xx, y, zz): return None
        return 4, 'open_portal'
    report.update(status='measured', footprint={'bounds_xz': [x0, z0, x1, z1],
                  'width': x1-x0+1, 'depth': z1-z0+1, 'foundation_cells': area,
                  'north_east_cut_cells': cut, 'diagonal_xz': diagonal},
                  floors_y=floors, storeys=[], courses=[], surface_maps={})
    # Every sampled skin position retains its actual state and inward/outward ray.
    # The maps are persisted separately; review groups receive only relevant rows.
    for face, cells in paths.items():
        grid = []
        for yy in range(1, floors[-1]+2):
            line = []
            for u,v,dx,dz in cells:
                ray = []
                for d in range(-3,4):
                    xx, zz = u+d*dx, v+d*dz
                    ray.append(int(s.volume[yy,zz,xx]) if 0 <= xx < s.width and 0 <= zz < s.length else None)
                line.append(ray)
            grid.append(line)
        report['surface_maps'][face] = {'coordinates_xz': [c[:2] for c in cells],
            'inward_step_xz': list(cells[0][2:]) if cells else None,
            'start_y': 1, 'depths': list(range(-3,4)), 'palette_ids_y_axis_depth': grid}
    report['palette'] = s.id_to_state
    for i, (lo, hi) in enumerate(zip(floors, floors[1:])):
        row = {'storey': i, 'y_range': [lo+1, hi-1], 'faces': {}}
        for face, cells in paths.items():
            pixels = np.zeros((max(0, hi-lo-1), len(cells)), dtype=bool)
            depths = {}
            for iy, yy in enumerate(range(lo+1, hi)):
                for j, (u, v, dx, dz) in enumerate(cells):
                    sample = opening(u, yy, v, dx, dz)
                    if sample:
                        pixels[iy, j] = True
                        depths[iy, j] = sample
            openings = []
            for a, b in runs(pixels.any(axis=0)):
                yy = np.flatnonzero(pixels[:, a:b+1].any(axis=1)) + lo+1
                samples = [val for (iy, j), val in depths.items() if a <= j <= b]
                openings.append({'axis_indices': [a,b], 'endpoints_xz': [cells[a][:2], cells[b][:2]],
                    'centre_xz': [(cells[a][0]+cells[b][0])/2, (cells[a][1]+cells[b][1])/2],
                    'y_range': [int(yy.min()), int(yy.max())], 'width_cells': b-a+1,
                    'height_cells': int(yy.max()-yy.min()+1),
                    'depth_counts': dict(Counter(str(val[0]) for val in samples)),
                    'kinds': sorted(set(val[1] for val in samples)), 'sampled_cells': len(samples)})
            material_counts = Counter()
            for yy in range(lo+1,hi):
                for u,v,dx,dz in cells:
                    for d in range(-3,4):
                        xx,zz=u+d*dx,v+d*dz
                        if 0 <= xx < s.width and 0 <= zz < s.length:
                            state = s.id_to_state[int(s.volume[yy,zz,xx])]
                            if base_block(state) not in AIR_BLOCKS: material_counts[state] += 1
            row['faces'][face] = {'openings': openings, 'opening_count': len(openings),
                                  'surface_state_counts': dict(material_counts)}
        report['storeys'].append(row)
    for yy in range(1, floors[-1]+3):
        row = {'y': yy, 'faces': {}}
        for face in ('street_north', 'chamfer', 'street_east'):
            cells = paths[face]
            covered = [any(at(stone, u-d*dx, yy, v-d*dz) for d in (1,2,3))
                       for u,v,dx,dz in cells]
            segments = runs(covered)
            row['faces'][face] = {'sample_count': len(cells), 'covered_cells': sum(covered),
                                  'longest_run': max((b-a+1 for a,b in segments), default=0),
                                  'gaps': runs([not value for value in covered])}
        if any(v['covered_cells'] for v in row['faces'].values()):
            row['continuous_sampled_path'] = all(v['sample_count'] > 0 and not v['gaps'] for v in row['faces'].values())
            report['courses'].append(row)
    heights = np.full((s.length, s.width), -1, dtype=int)
    lowest = heights.copy()
    for yy in range(floors[-1], s.height):
        select = roof[yy]
        lowest[select & (lowest < 0)] = yy
        heights[select] = yy
    samples = []
    for axis, lo, hi, other_lo, other_hi in [('x',x0,x1,z0,z1), ('z',z0,z1,x0,x1)]:
        for fixed in sorted(set(other_lo + (other_hi-other_lo)*f//4 for f in (1,2,3))):
            values = [int(heights[fixed,u] if axis=='x' else heights[u,fixed]) for u in range(lo,hi+1)]
            samples.append({'axis': axis, 'fixed_coordinate': fixed, 'start': lo,
                            'heights_y': [None if v<0 else v for v in values],
                            'rises_from_last_floor': [None if v<0 else v-floors[-1] for v in values]})
    occupied = (~air)[floors[-1]+1:]
    roof_cells = roof[floors[-1]+1:]
    report['roof_section'] = {'last_floor_y': floors[-1], 'samples': samples,
                              'measured_roof_columns': int((heights>=0).sum()),
                              'roof_family_cells_above_floor': int(roof_cells.sum()),
                              'occupied_cells_above_floor': int(occupied.sum()),
                              'section_policy': 'Topmost roof-family voxel. Local spikes are not automatically a ridge or slope break.'}
    roof_columns = []
    for v in range(z0,z1+1):
        line = []
        for u in range(x0,x1+1):
            high = int(heights[v,u])
            line.append(None if high<0 else {'top_y': high, 'first_roof_y': int(lowest[v,u]),
                'air_cells_below_top': int(air[floors[-1]+1:high,v,u].sum()),
                'roof_cells_below_top': int(roof[floors[-1]+1:high,v,u].sum())})
        roof_columns.append(line)
    report['roof_column_map'] = {'start_xz': [x0,z0], 'columns_z_x': roof_columns,
        'instruction': 'Every footprint column, including dormers/chimneys. Air counts test attic space without assuming a hollow roof.'}
    report['horizontal_sections'] = []
    for yy in floors:
        report['horizontal_sections'].append({'y': yy, 'palette_ids_z_x':
            s.volume[yy,z0:z1+1,x0:x1+1].astype(int).tolist()})
    report['volume_state_counts'] = {s.id_to_state[int(i)]: int(n)
        for i,n in zip(*np.unique(s.volume,return_counts=True))}
    report['corner_alignment'] = {'method': 'Compare measured centre_xz and y_range across storeys/faces. Coordinates are not inferred from bay_pitch.',
                                  'diagonal_xz': diagonal}
    return report


def review_evidence(report, storey=None, include_roof=True):
    """Keep model inputs bounded while retaining position-level evidence on disk."""
    result = {k:v for k,v in report.items() if k not in
              ('surface_maps', 'roof_column_map', 'horizontal_sections', 'palette')}
    if storey is not None and report.get('status') == 'measured':
        row = next((r for r in report['storeys'] if r['storey'] == storey), None)
        result['storeys'] = [row] if row else []
        if row:
            lo,hi = row['y_range']
            result['surface_maps'] = {face: {**data, 'start_y': lo,
                'palette_ids_y_axis_depth': data['palette_ids_y_axis_depth'][lo-1:hi]}
                for face,data in report['surface_maps'].items()}
            result['palette'] = report['palette']
            result['courses'] = [r for r in report['courses'] if lo-1 <= r['y'] <= hi+1]
    if include_roof and report.get('roof_column_map'):
        columns = [c for line in report['roof_column_map']['columns_z_x'] for c in line if c]
        result['roof_section'] = {**report['roof_section'],
            'columns_with_air_below_top': sum(c['air_cells_below_top']>0 for c in columns),
            'columns_without_air_below_top': sum(c['air_cells_below_top']==0 for c in columns)}
    return result
