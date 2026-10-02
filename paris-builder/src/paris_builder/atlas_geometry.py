"""Robust measurement of an exported building, separating form from attached volume.

Every earlier attempt to judge this project's geometry failed the same way: a raw
per-column reading mixed the thing being judged with the things standing on it. The
facade-section report sampled the topmost roof-family voxel per column, so a chimney
became a "slope spike", a dormer became a "null column", and a live run spent its repair
rounds chasing a measurement artefact instead of the real defect.

That matters again here. The Paris roof rule is that the roof must fit under a
45-degree line drawn from the eave, so at horizontal distance ``d`` from the eave the
roof may rise at most ``d``. Measured naively on `ATLAS-FRAME-PROBE-v5` the profile shows
single-step rises of 9, 10 and 17 cells and looks like a violation at d=13..15 - but
those steps are the dormer rows and the chimneys, not the roof plane.

Two wrong ways to separate them, both tried here first:

* a local window (percentile inside a 7x7 box) assumes the roof is locally flat. This
  roof climbs 17 cells across the footprint, so every column lands above its neighbours'
  low percentile and the *whole roof* is reported as attached volume - 197 cells in one
  "chimney".
* the per-distance median still breaks, because the dormer row covers about half of a
  band, which moves the median.

What works is the roof's own symmetry: a roof is a function of distance from the eave.
So every column is banded by its distance to the nearest footprint edge, and each band
reports a low percentile (the plane) alongside the median and high (the attached volume
standing in it). Attached volumes are then whatever sits clearly above the plane, listed
with their footprints instead of being averaged into the slope.

Nothing here decides pass or fail. It reports numbers a predicate can be written on.
"""
import numpy as np

from .schematic import AIR_BLOCKS, base_block

#: Roof-family classifier for the current atlas palette. Named explicitly so an
#: unsupported material is reported as unmeasured rather than silently counted as roof.
ROOF_TOKENS = ('deepslate', 'blackstone', 'basalt', 'slate')
#: Percentile of a distance band that estimates the plane. Dormers cover roughly half a
#: band and chimneys are narrow, so a low percentile passes under both.
PLANE_PERCENTILE = 20
#: A column is attached volume when it stands at least this far above the plane.
ATTACHED_MIN_RISE = 3


def names_of(read):
    """Map palette index -> base block name for a loaded schematic."""
    states = getattr(read, 'id_to_state', None) or read.palette
    if isinstance(states, dict):
        return {int(k): base_block(v) for k, v in states.items()}
    return {i: base_block(v) for i, v in enumerate(states)}


def masks(read, names=None):
    """Boolean masks for solid, roof family and glass, plus an unmeasured flag."""
    names = names or names_of(read)
    volume = read.volume
    air_ids = [i for i, n in names.items() if n in AIR_BLOCKS]
    roof_ids = [i for i, n in names.items() if any(t in n for t in ROOF_TOKENS)]
    glass_ids = [i for i, n in names.items() if 'glass' in n]
    solid = ~np.isin(volume, air_ids) if air_ids else np.ones(volume.shape, dtype=bool)
    roof = np.isin(volume, roof_ids) if roof_ids else np.zeros(volume.shape, dtype=bool)
    glass = np.isin(volume, glass_ids) if glass_ids else np.zeros(volume.shape, dtype=bool)
    return {'solid': solid, 'roof': roof, 'glass': glass,
            'air_ids': air_ids, 'roof_ids': roof_ids, 'glass_ids': glass_ids,
            'unmeasured': not roof_ids}


def column_tops(mask):
    """Topmost set y per (z, x) column, or -1 where the column is empty."""
    tops = np.full(mask.shape[1:], -1, dtype=int)
    for y in range(mask.shape[0]):
        tops[mask[y]] = y
    return tops


def footprint_bounds(solid_tops):
    zs, xs = np.where(solid_tops >= 0)
    if not len(zs):
        return None
    return [int(xs.min()), int(zs.min()), int(xs.max()), int(zs.max())]


def edge_distance(bounds, shape):
    """Chebyshev distance of every cell to the nearest footprint edge.

    A roof is a function of distance from the eave, so this is the natural coordinate to
    band by. Cells outside the footprint get -1 so they can never occupy a band.
    """
    x0, z0, x1, z1 = bounds
    depth, width = shape
    grid = np.full((depth, width), -1, dtype=int)
    for z in range(max(0, z0), min(depth, z1 + 1)):
        for x in range(max(0, x0), min(width, x1 + 1)):
            grid[z, x] = min(z - z0, z1 - z, x - x0, x1 - x)
    return grid


#: Minimum columns a distance band needs before its percentile is trusted. At the innermost
#: band of a square hip there may be a single column, and a percentile of one sample IS
#: that sample - so a chimney standing on the crown would be adopted as the roof plane.
#: Bands thinner than this are interpolated from their neighbours instead.
PLANE_MIN_SAMPLES = 4


def band_statistics(tops, distance_grid, occupied, *, percentile=PLANE_PERCENTILE,
                    min_samples=PLANE_MIN_SAMPLES):
    """Per-distance low/median/high of the occupied tops, and the resolved plane.

    A band with fewer than ``min_samples`` columns reports its statistics but flags
    ``trusted: False``, and the plane is interpolated across it from the nearest trusted
    bands on either side. A crown of one or two columns is common on a hip roof, so this
    is the difference between measuring the roof and measuring the chimney.
    """
    max_d = int(distance_grid.max()) if distance_grid.size else 0
    bands = []
    for d in range(max_d + 1):
        values = tops[occupied & (distance_grid == d)]
        if not values.size:
            bands.append({'distance': d, 'samples': 0, 'low': None, 'median': None,
                          'high': None, 'trusted': False})
            continue
        trusted = int(values.size) >= min_samples
        bands.append({'distance': d, 'samples': int(values.size),
                      'low': int(np.percentile(values, percentile)) if trusted else None,
                      'median': int(np.median(values)),
                      'high': int(values.max()), 'trusted': trusted})

    trusted = [row for row in bands if row['trusted']]
    if not trusted:
        # Nothing is trustworthy; fall back to the median so callers still get numbers,
        # but say so rather than presenting them as a measurement.
        for row in bands:
            if row['median'] is not None:
                row['low'] = row['median']
        trusted = [row for row in bands if row['low'] is not None]
    lookup = {row['distance']: row['low'] for row in trusted}
    plane = np.full(tops.shape, -1, dtype=int)
    inside = distance_grid >= 0
    if lookup:
        known = sorted(lookup)
        for d in range(max_d + 1):
            if d in lookup:
                continue
            nearest = min(known, key=lambda k: (abs(k - d), k))
            lookup[d] = lookup[nearest]
    for d, value in lookup.items():
        if value is not None:
            plane[inside & (distance_grid == d)] = value
    plane[~occupied] = -1
    return bands, plane


def roof_plane(read, *, names=None, percentile=PLANE_PERCENTILE,
               attached_min_rise=ATTACHED_MIN_RISE):
    """Measure the roof plane and the attached volumes standing on it."""
    names = names or names_of(read)
    m = masks(read, names)
    if m['unmeasured']:
        return {'status': 'UNMEASURED', 'reason': 'no roof-family material in the palette',
                'roof_tokens': list(ROOF_TOKENS)}
    tops = column_tops(m['roof'])
    occupied = tops >= 0
    if not occupied.any():
        return {'status': 'UNMEASURED', 'reason': 'no roof-family voxel found'}

    solid_tops = column_tops(m['solid'])
    bounds = footprint_bounds(solid_tops)
    if bounds is None:
        return {'status': 'UNMEASURED', 'reason': 'no solid voxel found'}
    x0, z0, x1, z1 = bounds
    # Roof columns can sit outside the solid footprint only by measurement error.
    roof_occupied = occupied.copy()
    bands, plane = band_statistics(tops, edge_distance(bounds, tops.shape), roof_occupied,
                                   percentile=percentile)
    above = np.where(roof_occupied & (plane >= 0), tops - plane, 0)
    attached = roof_occupied & (above >= attached_min_rise)

    return {
        'status': 'MEASURED',
        'method': 'roof plane = %dth percentile of roof-family column tops per band of '
                  'Chebyshev distance to the nearest footprint edge; attached volume = '
                  'columns standing >=%d above that plane'
                  % (percentile, attached_min_rise),
        'bounds_xz': bounds,
        'footprint_wd': [x1 - x0 + 1, z1 - z0 + 1],
        'plane_top': plane.tolist(),
        'raw_top': tops.tolist(),
        'attached_mask': attached.tolist(),
        'bands': bands,
        'attached_clusters': _clusters(attached, tops, plane, bounds),
        'attached_cells': int(attached.sum()),
        'roof_cells': int(roof_occupied.sum()),
        'max_raw_top_y': int(tops[roof_occupied].max()),
        'max_plane_top_y': int(plane[plane >= 0].max()),
        'min_plane_top_y': int(plane[plane >= 0].min()),
    }


def _clusters(mask, tops, plane, bounds):
    """Connected footprints of attached volume, in footprint-local coordinates."""
    x0, z0 = bounds[0], bounds[1]
    height, width = mask.shape
    seen = np.zeros_like(mask)
    out = []
    for z in range(height):
        for x in range(width):
            if not mask[z, x] or seen[z, x]:
                continue
            stack, cells = [(z, x)], []
            seen[z, x] = True
            while stack:
                cz, cx = stack.pop()
                cells.append((cz, cx))
                for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nz, nx = cz + dz, cx + dx
                    if 0 <= nz < height and 0 <= nx < width and mask[nz, nx] and not seen[nz, nx]:
                        seen[nz, nx] = True
                        stack.append((nz, nx))
            rises = [int(tops[cz, cx] - plane[cz, cx]) for cz, cx in cells if plane[cz, cx] >= 0]
            out.append({'cells': len(cells),
                        'z_range': [min(c[0] for c in cells) - z0, max(c[0] for c in cells) - z0],
                        'x_range': [min(c[1] for c in cells) - x0, max(c[1] for c in cells) - x0],
                        'max_rise': max(rises) if rises else 0,
                        'top_y': int(max(tops[cz, cx] for cz, cx in cells))})
    out.sort(key=lambda row: (-row['cells'], -row['max_rise']))
    return out


#: Wing of a corner plan: the face it addresses and how distance runs across it.
FACES = {
    'north': ('z', +1), 'south': ('z', -1),
    'west': ('x', +1), 'east': ('x', -1),
}


def eave_profile(report, face, *, span=None, limit=None, percentile=PLANE_PERCENTILE):
    """Roof-plane height as a function of distance inward from one eave.

    A corner plan is L-shaped: two wings whose roofs meet at the turret. Banding by
    distance to the bounding box therefore mixes both roofs - walking north to south
    across the full width climbs the north wing and then stays high across the west
    wing, which reads as a flat crown that is not there. So callers pass the ``span``
    transverse to this face (one wing only) and a ``limit`` on how far inward to walk
    (the wing depth), which is the only way this profile means anything.

    Per distance it reports a low percentile (the plane), the median and the maximum.
    The gap between low and high is the attached volume standing in that band.
    """
    if report.get('status') != 'MEASURED':
        return None
    if face not in FACES:
        raise ValueError('unknown face: ' + str(face))
    raw = np.array(report['raw_top'])
    x0, z0, x1, z1 = report['bounds_xz']
    axis, direction = FACES[face]
    if axis == 'z':
        coords = list(range(z0, z1 + 1)) if direction > 0 else list(range(z1, z0 - 1, -1))
        lo, hi = (x0, x1) if span is None else span
    else:
        coords = list(range(x0, x1 + 1)) if direction > 0 else list(range(x1, x0 - 1, -1))
        lo, hi = (z0, z1) if span is None else span
    if limit is not None:
        coords = coords[:limit]
    outline = []
    for d, coord in enumerate(coords):
        values = []
        for other in range(lo, hi + 1):
            z, x = (coord, other) if axis == 'z' else (other, coord)
            if not (0 <= z < raw.shape[0] and 0 <= x < raw.shape[1]):
                continue
            if raw[z, x] >= 0:
                values.append(int(raw[z, x]))
        if not values:
            outline.append({'distance': d, 'plane_y': None, 'median_y': None,
                            'low_y': None, 'high_y': None, 'samples': 0})
            continue
        outline.append({
            'distance': d,
            'plane_y': int(np.percentile(values, percentile)),
            'median_y': int(np.median(values)),
            'low_y': int(min(values)),
            'high_y': int(max(values)),
            'samples': len(values)})
    # Drop the leading distances before the roof starts, so distance 0 is the eave.
    first = next((i for i, row in enumerate(outline) if row['plane_y'] is not None), None)
    if first is None:
        return {'face': face, 'span': [lo, hi], 'profile': []}
    trimmed = []
    for row in outline[first:]:
        trimmed.append({**row, 'distance': row['distance'] - first})
    return {'face': face, 'span': [lo, hi], 'eave_distance_offset': first,
            'profile': trimmed}


def slope_segments(profile, *, key='plane_y', min_run=2, break_delta=0.25):
    """Split a plane profile into constant-slope runs.

    A mansard is defined by two regimes - a steep lower flank and a shallow upper
    flank - so the useful output is the segment list, not the raw heights.
    """
    rows = profile.get('profile', profile) if isinstance(profile, dict) else profile
    points = [(row['distance'], row[key]) for row in (rows or [])
              if isinstance(row, dict) and row.get(key) is not None]
    if len(points) < 3:
        return []
    segments, start = [], 0
    for i in range(1, len(points) - 1):
        d0, y0 = points[start]
        d1, y1 = points[i]
        d2, y2 = points[i + 1]
        before = (y1 - y0) / max(1, d1 - d0)
        after = (y2 - y1) / max(1, d2 - d1)
        if abs(after - before) >= break_delta and (i - start) >= min_run:
            segment = _segment(points[start:i + 1])
            if segment:
                segments.append(segment)
            start = i
    segment = _segment(points[start:])
    if segment:
        segments.append(segment)
    return segments


def _segment(points):
    if len(points) < 2:
        return None
    d0, y0 = points[0]
    d1, y1 = points[-1]
    run, rise = d1 - d0, y1 - y0
    return {'distance': [d0, d1], 'y': [y0, y1], 'run': run, 'rise': rise,
            'rise_per_run': round(rise / run, 3) if run else None}


def forty_five_degree(profile, *, key='plane_y'):
    """Paris roof rule: at distance d from the eave the roof may rise at most d."""
    rows = profile.get('profile', profile) if isinstance(profile, dict) else profile
    rows = [row for row in (rows or []) if isinstance(row, dict) and row.get(key) is not None]
    if len(rows) < 2:
        return {'status': 'UNMEASURED', 'reason': 'profile too short'}
    base_distance, base = rows[0]['distance'], rows[0][key]
    worst, violations = None, []
    for row in rows:
        d = row['distance'] - base_distance
        if d <= 0:
            continue
        rise = row[key] - base
        margin = d - rise
        if worst is None or margin < worst['margin']:
            worst = {'distance': d, 'rise': rise, 'margin': margin, 'plane_y': row[key]}
        if rise > d:
            violations.append({'distance': d, 'rise': rise, 'over_by': rise - d})
    return {'status': 'FAIL' if violations else 'PASS',
            'eave_y': base, 'ridge_y': max(row[key] for row in rows),
            'roof_height': max(row[key] for row in rows) - base,
            'tightest': worst, 'violations': violations[:8],
            'violation_count': len(violations)}
