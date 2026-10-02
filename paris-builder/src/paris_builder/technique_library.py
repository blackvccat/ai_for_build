"""One addressable index of every technique and detail the project owns.

Three libraries hold the project's detail vocabulary — library-v1 (45 families, 135
recipe variants, 43 annotated windows), library-v2 (770 extracted details) and
library-v3 (8 audited reference techniques) — yet the generator and the planning agent
could only ever see the eight v3 entries. A plan therefore had source code and three
scalars to work with, and no way to NAME a technique it wanted.

This module gives every entry a stable id, a semantic label and a readable path, so a
framework plan, a facade plan or a generator repair can point at a concrete technique
instead of guessing which source function to edit.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / 'knowledge/library-v1'
V2 = ROOT / 'knowledge/library-v2/details'
V3 = ROOT / 'knowledge/library-v3/reference-techniques'
V4 = ROOT / 'knowledge/library-v4/atlas-techniques'

#: The 45 family labels are authored in Chinese in catalog.json; they are the semantic
#: bridge between "what the operator asked for" and "which detail implements it".
LAYERS = ('technique', 'recipe', 'window', 'detail', 'family')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _rel(path):
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def _v2_entry(folder):
    parts = folder.name.split('-')
    return {'id': 'v2:' + folder.name, 'layer': 'detail',
            'source': parts[0] if parts else '', 'category': parts[1] if len(parts) > 1 else '',
            'path': _rel(folder / 'detail.schem'),
            'exists': (folder / 'detail.schem').is_file()}


def _v3_entry(folder):
    record = folder / 'record.json'
    row = {'id': 'v3:' + folder.name, 'layer': 'technique', 'path': _rel(folder / 'detail.schem'),
           'exists': (folder / 'detail.schem').is_file()}
    if record.is_file():
        raw = _read(record)
        row.update(source=raw.get('source'), role='audited reference technique',
                   bbox=raw.get('source_bbox_xyz_half_open'))
    return row


def _v4_entry(folder):
    record = folder / 'record.json'
    row = {'id': 'v4:' + folder.name, 'layer': 'technique', 'path': _rel(folder / 'detail.schem'),
           'exists': (folder / 'detail.schem').is_file()}
    if record.is_file():
        raw = _read(record)
        row.update(source=raw.get('source'), role='atlas technique',
                   bbox=raw.get('source_bbox_xyz_half_open'),
                   sha256=raw.get('schematic_sha256'),
                   compatible_vanilla=raw.get('compatible_vanilla'),
                   outside=raw.get('outside'))
    return row


#: `catalogue()` walks three library trees and resolves a relative path per entry - about
#: 233k `Path.relative_to`/`stat` calls. `path_of` defaults to it and `load_detail` calls
#: `path_of`, so one atlas assembly rebuilt the whole catalogue 220 times and spent 167 of
#: its 200 seconds there. The libraries are static files, so cache it per process and let
#: a caller that has just written into a library ask for a refresh.
_CATALOGUE_CACHE = {}


def catalogue(refresh=False):
    """Every addressable entry, grouped by library, with counts."""
    if not refresh and 'value' in _CATALOGUE_CACHE:
        return _CATALOGUE_CACHE['value']
    value = _build_catalogue()
    _CATALOGUE_CACHE['value'] = value
    return value


def _build_catalogue():
    catalog = _read(V1 / 'catalog.json') if (V1 / 'catalog.json').is_file() else {}
    families = [{'id': 'v1:family:' + name, 'layer': 'family', 'label': label}
                for name, label in sorted((catalog.get('families') or {}).items())]
    recipes = []
    for recipe in catalog.get('recipes') or []:
        ident = str(recipe.get('component_id') or recipe.get('family'))
        folder = V1 / 'recipes' / ident
        recipes.append({'id': 'v1:recipe:' + ident, 'layer': 'recipe',
                        'family': recipe.get('family'), 'variant': recipe.get('variant'),
                        'states': len(recipe.get('evidence') or []),
                        'path': _rel(folder / 'component.schem'),
                        'exists': (folder / 'component.schem').is_file(),
                        'annotation': recipe.get('annotation')})
    windows = []
    for window in catalog.get('windows') or []:
        ident = str(window.get('component_id'))
        folder = V1 / 'windows' / ident
        windows.append({'id': 'v1:window:' + ident, 'layer': 'window',
                        'family': window.get('family'), 'bbox': window.get('crop_bbox_xyz'),
                        'view': window.get('intended_view'), 'lod': window.get('lod'),
                        'path': _rel(folder / 'component.schem'),
                        'exists': (folder / 'component.schem').is_file()})
    details = [_v2_entry(folder) for folder in sorted(V2.iterdir()) if folder.is_dir()] \
        if V2.is_dir() else []
    techniques = [_v3_entry(folder) for folder in sorted(V3.iterdir()) if folder.is_dir()] \
        if V3.is_dir() else []
    techniques += [_v4_entry(folder) for folder in sorted(V4.iterdir()) if folder.is_dir()] \
        if V4.is_dir() else []
    entries = families + recipes + windows + details + techniques
    return {'version': 1, 'root': _rel(ROOT), 'layers': list(LAYERS), 'entries': entries,
            'counts': {'family': len(families), 'recipe': len(recipes), 'window': len(windows),
                       'detail': len(details), 'technique': len(techniques)}}


def path_of(ident, rows=None):
    """The readable file behind an id, or None when the id is unknown."""
    rows = catalogue()['entries'] if rows is None else rows
    for row in rows:
        if row['id'] == ident:
            return row.get('path')
    return None


def cards(limit_per_layer=None):
    """A compact catalogue for a planning prompt: id + label + shape, one line each."""
    data = catalogue()
    labels = {row['id']: row.get('label') for row in data['entries'] if row['layer'] == 'family'}
    lines = []
    for layer in LAYERS:
        group = [row for row in data['entries'] if row['layer'] == layer]
        if limit_per_layer:
            group = group[:limit_per_layer]
        for row in group:
            if layer == 'family':
                lines.append('%s = %s' % (row['id'], row.get('label')))
            elif layer == 'recipe':
                lines.append('%s = family %s / variant %s' % (row['id'], row.get('family'),
                                                             row.get('variant')))
            elif layer == 'window':
                lines.append('%s = window %s bbox %s' % (row['id'], row.get('family'),
                                                         row.get('bbox')))
            elif layer == 'detail':
                lines.append('%s = %s part of %s' % (row['id'], row.get('category'),
                                                     row.get('source')))
            else:
                lines.append('%s = %s' % (row['id'], row.get('role') or 'audited technique'))
    return lines


def brief():
    """The catalogue at the size a planning prompt can afford.

    Every family label (the semantic bridge between a request and a detail), the id shape
    of each library, and the counts. Any single row is retrievable by id, so the agent can
    name a technique without carrying 1018 rows in context.
    """
    data = catalogue()
    families = [row for row in data['entries'] if row['layer'] == 'family']
    heads = '、'.join('%s=%s' % (row['id'].split(':')[-1], row.get('label')) for row in families)
    return '\n'.join([
        '手法族（%d）: %s' % (len(families), heads),
        '可引用 id: v1:family:<name>｜v1:recipe:<component_id>｜v1:window:<component_id>'
        '｜v2:<source>-<category>-<nn>｜v3:<technique>',
        '条目数: ' + json.dumps(data['counts'], ensure_ascii=False),
    ])


def load_detail(ident, rows=None):
    """Read one library entry as a schematic, so its blocks can be placed."""
    path = path_of(ident, rows)
    if not path:
        raise KeyError('unknown technique id: ' + str(ident))
    from .schematic import load_schematic
    return load_schematic(ROOT / path)


def size_of(ident, rows=None):
    read = load_detail(ident, rows)
    height, depth, width = read.volume.shape
    return {'width': width, 'height': height, 'depth': depth}


def _is_air_state(value):
    """Air is a block identity; the word 'stairs' also contains 'air'."""
    return str(value).split('[', 1)[0] in ('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air')


def stamp(scene, ident, x, y, z, turns=0):
    """Write a library entry into a scene at (x, y, z), states preserved.

    The libraries store blocks WITH their states — stair facings, wall and pane
    connections, slab halves — precisely because the paste environment forbids block
    updates, so states are copied verbatim and only rotated. This is the call that lets a
    plan or a generator repair actually USE a technique instead of re-implementing one.
    """
    from .architecture import transform_state
    read = load_detail(ident)
    volume = read.volume
    # A loaded schematic maps STATE -> id in `palette` and carries the reverse lookup in
    # `id_to_state`; a built Scene keeps a plain id -> state list. Use whichever the object
    # provides, and skip air through the schematic's own air_ids.
    states = getattr(read, 'id_to_state', None) or read.palette
    air_values = getattr(read, 'air_ids', None)
    air_ids = set(air_values if air_values is not None else [])
    height, depth, width = volume.shape
    placed = 0
    for dy in range(height):
        for dz in range(depth):
            for dx in range(width):
                index = int(volume[dy, dz, dx])
                if index in air_ids:
                    continue
                if isinstance(states, dict):
                    value = states.get(index, states.get(str(index)))
                else:
                    value = states[index]
                if value is None or _is_air_state(value):
                    continue
                written = str(value)
                written = transform_state(written, turns=turns) if turns else written
                scene.put(x + dx, y + dy, z + dz, written, 'library:' + ident)
                placed += 1
    return placed


def registry():
    """The id-stamp registry a generator repair expects to find by that name.

    A live repair reported `technique_library_stamp_dispatch: not_applicable` with the
    reason "No technique_library id-stamp registry exists in this module set", because it
    looked for a registry and found only functions. This returns exactly that: every
    addressable id mapped to its entry, plus the two call names that do the placement.
    """
    table = {row['id']: row for row in catalogue()['entries']}
    table['__place__'] = 'technique_library.stamp(scene, id, x, y, z, turns=0)'
    table['__size__'] = 'technique_library.size_of(id)'
    return table


def _state_at(read, x, y, z):
    """The exported state at a coordinate, or None outside the volume.

    A loaded schematic maps STATE -> id in `palette` and carries the reverse lookup in
    `id_to_state`; accept either shape, exactly as `stamp` does.
    """
    volume = read.volume
    height, depth, width = volume.shape
    if not (0 <= y < height and 0 <= z < depth and 0 <= x < width):
        return None
    states = getattr(read, 'id_to_state', None) or read.palette
    index = int(volume[y, z, x])
    if isinstance(states, dict):
        return states.get(index, states.get(str(index)))
    return states[index]


def verify_stamp_audit(read, audit, rows=None, *, allow_overwrites=False, allowed_overwrites=None):
    """Check a manifest's library-stamp claims against the exported geometry.

    `stamp()` writes through `scene.put`, and a Scene's ownership map does not survive
    export to `.schem`, so nothing downstream could tell a real dispatch from a claim.
    A live generator repair did exactly that: it imported `registry()`, stored
    `len(...)` in a local it never used, and declared
    `technique_library_stamp_dispatch: active` while the exported building contained no
    library block at all.

    Every claim is checked against the final exported states. Explicit clips are
    reported separately from unexplained loss. A later stamp may cover cells only
    when allow_overwrites is set AND a reasoned role pair (optionally bounded to an
    xyz region) is listed in allowed_overwrites. Fully lost pieces still fail. Derived
    rows also reproduce their transformations from the original source. The existing
    generic stamp contract rotates states in place; atlas uses pre-rotated pieces.
    """
    from .architecture import transform_state
    from hashlib import sha256
    known = {row['id']: row for row in (catalogue()['entries'] if rows is None else rows)}
    checked = []
    claims = []
    loaded = {}
    # A derived artifact cannot certify its own provenance. Reproduce its declared
    # operations from the original, unchanged library source before comparing stamps.
    derived_rows = {ident: row for ident, row in known.items() if 'provenance' in row}
    verifier = None
    if derived_rows or any(row.get('source_evidence') for row in known.values()):
        from .atlas_assembly import Assembler
        verifier = Assembler(None, derived=derived_rows)
    for entry in audit or []:
        if not isinstance(entry, dict):
            checked.append({'id': None, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'stamp entry is not an object'})
            claims.append({})
            continue
        ident = entry.get('id')
        if ident not in known:
            checked.append({'id': ident, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'unknown library id'})
            claims.append({})
            continue
        try:
            if ident not in loaded:
                if ident in derived_rows:
                    loaded[ident], _ = verifier._load_verified(ident)
                elif known[ident].get('source_evidence'):
                    loaded[ident], evidence = verifier._load_verified(ident)
                    if evidence != known[ident]['source_evidence']:
                        raise ValueError('original source evidence changed after stamp')
                elif str(ident).startswith(('derived:', 'probe:')):
                    raise ValueError('derived entry lacks original-source provenance')
                else:
                    loaded[ident] = load_detail(ident, list(known.values()))
                expected_hash = known[ident].get('sha256')
                if expected_hash and sha256(loaded[ident].path.read_bytes()).hexdigest() != expected_hash:
                    raise ValueError('library entry hash changed')
            library = loaded[ident]
            x, y, z = (int(entry.get(axis, 0)) for axis in ('x', 'y', 'z'))
            turns = int(entry.get('turns', 0) or 0)
            clip = entry.get('clip')
            if clip is not None and (len(clip) != 4 or any(type(v) is not int for v in clip)
                                     or clip[0] > clip[2] or clip[1] > clip[3]):
                raise ValueError('invalid stamp clip')
        except Exception as error:                                  # noqa: BLE001
            checked.append({'id': ident, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'unreadable library entry: %s' % error})
            claims.append({})
            continue
        states = getattr(library, 'id_to_state', None) or library.palette
        air_values = getattr(library, 'air_ids', None)
        air_ids = set(air_values if air_values is not None else [])
        height, depth, width = library.volume.shape
        total = clipped = unauthorized_clip = 0
        cells = {}
        for dy in range(height):
            for dz in range(depth):
                for dx in range(width):
                    index = int(library.volume[dy, dz, dx])
                    if index in air_ids:
                        continue
                    if isinstance(states, dict):
                        value = states.get(index, states.get(str(index)))
                    else:
                        value = states[index]
                    if value is None or _is_air_state(value):
                        continue
                    total += 1
                    expected = transform_state(str(value), turns=turns) if turns else str(value)
                    coordinate = (x + dx, y + dy, z + dz)
                    if clip is not None and not (clip[0] <= coordinate[0] <= clip[2]
                                                 and clip[1] <= coordinate[2] <= clip[3]):
                        clipped += 1
                        continue
                    if _state_at(read, *coordinate) is None:
                        clipped += 1
                        if not entry.get('allow_scene_clip'):
                            unauthorized_clip += 1
                        continue
                    cells[coordinate] = expected
        checked.append({'id': ident, 'anchor': [x, y, z], 'turns': turns, 'cells': total,
                        'role': entry.get('role'), 'placed_cells': len(cells), 'clipped': clipped,
                        'unauthorized_clip': unauthorized_clip, 'matched': 0})
        claims.append(cells)

    def authorized(before, after, coordinate):
        if not allow_overwrites or not before.get('role') or not after.get('role'):
            return False
        for rule in allowed_overwrites or []:
            if not isinstance(rule, dict) or not str(rule.get('reason') or '').strip():
                continue
            if rule.get('from_role') != before['role'] or rule.get('to_role') != after['role']:
                continue
            bounds = rule.get('bbox_xyz_half_open')
            if bounds is not None and (len(bounds) != 6 or any(type(v) is not int for v in bounds)
                                       or not all(bounds[i] <= coordinate[i] < bounds[i + 3]
                                                  for i in range(3))):
                continue
            return True
        return False

    last_writer = {}
    for index, cells in enumerate(claims):
        for coordinate, expected in cells.items():
            last_writer[coordinate] = (index, expected)
    for index, (row, cells) in enumerate(zip(checked, claims)):
        if 'status' in row:  # invalid claims already failed above
            continue
        matched = overwritten = approved = unexplained = 0
        samples = []
        for coordinate, expected in cells.items():
            actual = _state_at(read, *coordinate)
            if actual == expected:
                matched += 1
                continue
            later_index, later_state = last_writer[coordinate]
            if later_index > index and actual == later_state:
                overwritten += 1
                permitted = authorized(row, checked[later_index], coordinate)
                approved += int(permitted)
                explanation = 'authorized later stamp' if permitted else 'unapproved later stamp'
            else:
                unexplained += 1
                explanation = 'export differs from all declared surviving stamps'
            if len(samples) < 10:
                samples.append({'xyz': list(coordinate), 'expected': expected,
                                'actual': actual, 'reason': explanation})
        row.update(matched=matched, overwritten_by_later_stamp=overwritten,
                   authorized_overwritten=approved, unexplained=unexplained,
                   fully_lost=bool(cells) and matched == 0, mismatch_samples=samples)
        row['status'] = ('PASS' if cells and matched > 0 and not row['unauthorized_clip']
                         and matched + approved == len(cells) else 'FAIL')
    return {'status': 'PASS' if checked and all(row['status'] == 'PASS' for row in checked) else 'FAIL',
            'stamps': checked, 'declared': len(checked),
            'matched_cells': sum(row['matched'] for row in checked),
            'clipped_cells': sum(row.get('clipped', 0) for row in checked),
            'authorized_overwritten_cells': sum(row.get('authorized_overwritten', 0) for row in checked),
            'unexplained_cells': sum(row.get('unexplained', 0) for row in checked),
            'fully_lost_stamps': sum(bool(row.get('fully_lost')) for row in checked),
            'overwrite_policy': list(allowed_overwrites or []) if allow_overwrites else [],
            'game_acceptance': 'NOT_RUN'}


if __name__ == '__main__':
    data = catalogue()
    print(json.dumps(data['counts'], ensure_ascii=False))
    for line in cards()[:6]:
        print(' ', line)
