"""Voxel section evidence measured from exports, never from generator claims."""
from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np

from .schematic import AIR_BLOCKS, base_block, load_schematic
from .architecture import split_state


REPORT_VERSION = 3


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


def connected_components(points):
    """Four-neighbour components in a sampled plane, preserving actual cells."""
    remaining = set(points)
    result = []
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        component, pending = {first}, [first]
        while pending:
            a, b = pending.pop()
            for neighbour in ((a-1, b), (a+1, b), (a, b-1), (a, b+1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    pending.append(neighbour)
        result.append(component)
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
    report = {'version': REPORT_VERSION, 'source': {'path': str(path.resolve()),
              'sha256': sha256(path.read_bytes()).hexdigest(), 'voxel_state_hash': s.voxel_state_hash()},
              'coordinates': 'local export [x,y,z]; north=-z, east=+x, west=-x, south=+z',
              'method': 'Foundation footprint, broad wood floor plates, masonry skins and roof-family voxels measured independently. No manifest coordinates or counts used.',
              'limitations': ['Voxel depths, not sub-block model dimensions; slabs/stairs occupy partial cells.',
                             'Material classifier supports the current sandstone/deepslate palette; unsupported materials are unmeasured.',
                             'Roof samples include all roof-family voxels, including chimney/crest spikes; compare multiple sections. Dormer interruptions remain visible.',
                             'Face roles assume the fixed north-east street-corner layout; export voxels cannot identify streets or party-wall obligations.',
                             'A chamfer depth step changes both x and z, so it is not the same physical distance as an orthogonal face depth step.',
                             'Broad wood plates are floor proxies, not proof of functional storeys; adjacent plate layers are one band.',
                             'Opening groups are connected sampled transmissive cells, not architectural bays. Joinery can split one opening into multiple groups.',
                             'A closed iron-door leaf parallel to an orthogonal centre ray is a thin side leaf, not a solid skin. Glass must still be present behind it; other door orientations and diagonal rays remain blocking.',
                             'Course coverage is a projection only. Connected stone paths establish face-adjacent occupied voxels, not slab/stair model-surface contact.',
                             'Roof slices show actual classified cells; highest-voxel profiles do not prove slope breaks or connected usable attic volume.',
                             'Measurements establish geometry, not aesthetic or game acceptance.'],
              'status': 'unmeasured'}
    foundation = full_stone[0]
    z, x = np.where(foundation)
    if not len(x):
        report['reason'] = 'No supported foundation found at y=0.'
        return report
    x0, x1, z0, z1 = map(int, (x.min(), x.max(), z.min(), z.max()))
    area = int(foundation.sum())
    floor_bands = runs(wood[:, z0:z1+1, x0:x1+1].sum(axis=(1, 2)) >= area * .45)
    # Use each band's top surface; consecutive board layers are one plate.
    floors = [hi for lo, hi in floor_bands]
    if len(floors) < 2:
        report['reason'] = 'Cannot independently locate at least two broad floor plates.'
        return report
    # The NE cut is read from missing foundation cells, not the requested chamfer.
    cut = 0
    while x1 - cut >= x0 and not foundation[z0, x1 - cut]:
        cut += 1
    zz, xx = np.mgrid[z0:z1+1, x0:x1+1]
    expected_foundation = x1 - xx + zz - z0 >= cut
    supported_pattern = bool(np.array_equal(foundation[z0:z1+1, x0:x1+1], expected_foundation))
    pattern = ('north_east_chamfer' if cut else 'rectangle') if supported_pattern else 'unsupported'
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
        thin_leaf_seen = False
        for d in range(4):
            xx, zz = u + d*dx, v + d*dz
            if at(glass, xx, y, zz): return d, 'glazing'
            if 0 <= xx < s.width and 0 <= zz < s.length and 0 <= y < s.height:
                name, props = split_state(s.id_to_state[int(s.volume[y, zz, xx])])
                # Closed door models occupy a thin plane at the cell edge. The
                # centre ray can pass a tangent leaf, as in the source thin-window
                # method; the leaf itself never counts as glazing or an air portal.
                tangent = (dx == 0 and dz != 0 and props.get('facing') in ('east', 'west') or
                           dz == 0 and dx != 0 and props.get('facing') in ('north', 'south'))
                if name == 'minecraft:iron_door' and props.get('open') == 'false' and tangent:
                    thin_leaf_seen = True
                    continue
            if not at(air, xx, y, zz): return None
        return None if thin_leaf_seen else (4, 'open_portal')
    report.update(status='measured', footprint={'bounds_xz': [x0, z0, x1, z1],
                  'width': x1-x0+1, 'depth': z1-z0+1, 'foundation_cells': area,
                  'north_east_cut_cells': cut, 'diagonal_xz': diagonal,
                  'supported_pattern': supported_pattern, 'pattern': pattern},
                  supported_geometry={'supports_ne_corner_sampling': supported_pattern and cut > 0,
                      'footprint_pattern': pattern,
                      'face_role_basis': 'Fixed NE layout assumption; export geometry does not identify street/party roles'},
                  floors_y=floors, floor_plate_bands_y=floor_bands,
                  floor_detection='Top surfaces of broad wood plate bands; proxy storeys are intervals between these surfaces.',
                  opening_group_semantics='Four-neighbour connected sampled transmissive cells, not architectural bays or complete apertures.',
                  storeys=[], courses=[], surface_maps={})
    # Every sampled skin position retains its actual state and inward/outward ray.
    # The maps are persisted separately; review groups receive only relevant rows.
    for face, cells in paths.items():
        grid = []
        for yy in range(1, min(s.height, floors[-1]+2)):
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
            for component in connected_components((int(iy),int(j)) for iy,j in zip(*np.where(pixels))):
                positions = sorted(component)
                a, b = min(j for iy,j in positions), max(j for iy,j in positions)
                ys = [lo+1+iy for iy,j in positions]
                samples = [depths[iy,j] for iy,j in positions]
                openings.append({'axis_indices': [a,b], 'endpoints_xz': [cells[a][:2], cells[b][:2]],
                    'centre_xz': [(cells[a][0]+cells[b][0])/2, (cells[a][1]+cells[b][1])/2],
                    'y_range': [min(ys), max(ys)], 'width_cells': b-a+1,
                    'height_cells': max(ys)-min(ys)+1,
                    'depth_counts': dict(Counter(str(val[0]) for val in samples)),
                    'kinds': sorted(set(val[1] for val in samples)), 'sampled_cells': len(samples),
                    'sample_coordinates_xyz': [[cells[j][0], lo+1+iy, cells[j][1]] for iy,j in positions]})
            material_counts = Counter()
            for yy in range(lo+1,hi):
                for u,v,dx,dz in cells:
                    for d in range(-3,4):
                        xx,zz=u+d*dx,v+d*dz
                        if 0 <= xx < s.width and 0 <= zz < s.length:
                            state = s.id_to_state[int(s.volume[yy,zz,xx])]
                            if base_block(state) not in AIR_BLOCKS: material_counts[state] += 1
            row['faces'][face] = {'openings': openings, 'opening_count': len(openings),
                                  'sampled_transmissive_groups_count': len(openings),
                                  'surface_state_counts': dict(material_counts)}
        report['storeys'].append(row)

    def stone_connection(cells, yy, diagonal_face=False):
        samples = [{(u-d*dx, v-d*dz) for d in (1,2,3)
                    if at(stone, u-d*dx, yy, v-d*dz)} for u,v,dx,dz in cells]
        vertices = set().union(*samples) if samples else set()
        if diagonal_face and cells:
            # Diagonal rays omit alternating lattice cells. Include actual stone
            # in the same outward strip, so a stair-step bridge can be verified.
            tangent_lo = min(u+v for u,v,dx,dz in cells)
            tangent_hi = max(u+v for u,v,dx,dz in cells)
            boundary = cells[0][0] - cells[0][1]
            for v in range(max(0,z0-3), min(s.length,z1+1)):
                for u in range(max(0,x0), min(s.width,x1+4)):
                    if (tangent_lo <= u+v <= tangent_hi and
                            1 <= u-v-boundary <= 6 and at(stone,u,yy,v)):
                        vertices.add((u,v))
        components = connected_components(vertices)
        connected = next((c for c in components if samples and all(c & sample for sample in samples)), None)
        status = ('not_applicable' if not samples else 'uncovered' if not all(samples)
                  else 'connected' if connected else 'disconnected')
        return samples, vertices, {'status': status, 'connected': bool(connected) if samples else None,
            'method': 'One face-adjacent stone-voxel component must intersect every outward sample ray.',
            'component_count': len(components),
            'stone_coordinates_xyz': [[u,yy,v] for u,v in sorted(vertices)],
            'connected_coordinates_xyz': [[u,yy,v] for u,v in sorted(connected or ())]}

    for yy in range(1, floors[-1]+3):
        row = {'y': yy, 'faces': {}}
        all_samples, all_vertices = [], set()
        for face in ('street_north', 'chamfer', 'street_east'):
            cells = paths[face]
            samples, vertices, connection = stone_connection(cells, yy, face == 'chamfer')
            all_samples.extend(samples)
            all_vertices.update(vertices)
            covered = [bool(sample) for sample in samples]
            segments = runs(covered)
            row['faces'][face] = {'sample_count': len(cells), 'covered_cells': sum(covered),
                                  'longest_run': max((b-a+1 for a,b in segments), default=0),
                                  'gaps': runs([not value for value in covered]),
                                  'stone_path_connection': connection}
        if any(v['covered_cells'] for v in row['faces'].values()):
            row['sampled_path_coverage_complete'] = all(v['sample_count'] > 0 and not v['gaps'] for v in row['faces'].values())
            supported = supported_pattern and cut > 0 and all(paths[f] for f in row['faces'])
            connected = next((c for c in connected_components(all_vertices)
                              if all_samples and all(c & sample for sample in all_samples)), None) if supported else None
            # The legacy continuity flag can no longer grant continuity from a
            # projection alone. Preserve that old measurement under its literal name.
            row['continuous_sampled_path'] = bool(connected)
            row['continuous_sampled_path_basis'] = 'Verified face-adjacent stone voxels across the three sampled NE faces; coverage alone is insufficient.'
            row['stone_path_connection'] = {'status': 'unsupported' if not supported else
                'connected' if connected else 'disconnected',
                'connected': bool(connected) if supported else None,
                'method': 'One face-adjacent stone-voxel component must intersect every ray on all three NE faces.',
                'connected_coordinates_xyz': [[u,yy,v] for u,v in sorted(connected or ())]}
            report['courses'].append(row)
    heights = np.full((s.length, s.width), -1, dtype=int)
    lowest = heights.copy()
    for yy in range(floors[-1], s.height):
        select = roof[yy]
        lowest[select & (lowest < 0)] = yy
        heights[select] = yy
    samples = []
    slices = []
    symbols = np.full(len(names), 'O', dtype='<U1')
    for index, name in enumerate(names):
        if name in AIR_BLOCKS: symbols[index] = '.'
        elif 'deepslate' in name or 'blackstone' in name: symbols[index] = 'R'
        elif any(k in name for k in ('sandstone', 'stone_bricks', 'quartz')): symbols[index] = 'S'
        elif name.endswith('_planks'): symbols[index] = 'W'
        elif 'glass' in name: symbols[index] = 'G'
    legend = {'.':'air', 'R':'roof', 'S':'stone', 'W':'wood', 'G':'glass', 'O':'other'}
    for axis, lo, hi, other_lo, other_hi in [('x',x0,x1,z0,z1), ('z',z0,z1,x0,x1)]:
        for fixed in sorted(set(other_lo + (other_hi-other_lo)*f//4 for f in (1,2,3))):
            values = [int(heights[fixed,u] if axis=='x' else heights[u,fixed]) for u in range(lo,hi+1)]
            samples.append({'axis': axis, 'fixed_coordinate': fixed, 'start': lo,
                            'heights_y': [None if v<0 else v for v in values],
                            'rises_from_last_floor': [None if v<0 else v-floors[-1] for v in values]})
            slices.append({'axis': axis, 'fixed_coordinate': fixed, 'start': lo, 'end': hi,
                'start_y': floors[-1], 'end_y': s.height-1, 'y_order': 'descending', 'legend': legend,
                'rows': [{'y': yy, 'cells': ''.join(symbols[s.volume[yy,fixed,lo:hi+1] if axis=='x'
                    else s.volume[yy,lo:hi+1,fixed]])} for yy in range(s.height-1,floors[-1]-1,-1)]})
    report['roof_slices'] = slices
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
    if storey is None:
        # Full voxel coordinates remain in the hash-bound report. Global review
        # needs located groups and connection results; individual floor review
        # below restores the relevant coordinates and material rays.
        def compact_connection(value):
            return {k:v for k,v in value.items() if k not in
                    ('stone_coordinates_xyz', 'connected_coordinates_xyz')}
        if 'storeys' in report:
            result['storeys'] = [{**row, 'faces': {face: {**data, 'openings': [
                {k:v for k,v in opening.items() if k != 'sample_coordinates_xyz'}
                for opening in data['openings']]} for face,data in row['faces'].items()}}
                for row in report['storeys']]
        if 'courses' in report:
            result['courses'] = [{**row,
                'stone_path_connection': compact_connection(row.get('stone_path_connection', {})),
                'faces': {face: {**data, 'stone_path_connection': compact_connection(
                    data.get('stone_path_connection', {}))} for face,data in row['faces'].items()}}
                for row in report['courses']]
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
