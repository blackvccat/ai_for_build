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


def catalogue():
    """Every addressable entry, grouped by library, with counts."""
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
    entries = families + recipes + windows + details + techniques
    return {'version': 1, 'root': _rel(ROOT), 'layers': list(LAYERS), 'entries': entries,
            'counts': {'family': len(families), 'recipe': len(recipes), 'window': len(windows),
                       'detail': len(details), 'technique': len(techniques)}}


def path_of(ident, rows=None):
    """The readable file behind an id, or None when the id is unknown."""
    rows = rows or catalogue()['entries']
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
    air_ids = set(getattr(read, 'air_ids', None) or [])
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
                if value is None or 'air' in str(value):
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


def verify_stamp_audit(read, audit, rows=None):
    """Check a manifest's library-stamp claims against the exported geometry.

    `stamp()` writes through `scene.put`, and a Scene's ownership map does not survive
    export to `.schem`, so nothing downstream could tell a real dispatch from a claim.
    A live generator repair did exactly that: it imported `registry()`, stored
    `len(...)` in a local it never used, and declared
    `technique_library_stamp_dispatch: active` while the exported building contained no
    library block at all.

    This re-reads the claim out of the artifact: for every declared stamp it loads the
    library entry again and compares its non-air cells, cell by cell, with what was
    actually exported. `matched` is the count that survived verbatim (a later wall or
    opening may legitimately overwrite part of a stamp), so the caller can decide how
    strict to be — an empty or wholly unmatched stamp is a claim with nothing behind it.
    """
    from .architecture import transform_state
    known = {row['id']: row for row in (rows or catalogue()['entries'])}
    checked = []
    for entry in audit or []:
        if not isinstance(entry, dict):
            checked.append({'id': None, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'stamp entry is not an object'})
            continue
        ident = entry.get('id')
        if ident not in known:
            checked.append({'id': ident, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'unknown library id'})
            continue
        try:
            library = load_detail(ident, list(known.values()))
        except Exception as error:                                  # noqa: BLE001
            checked.append({'id': ident, 'cells': 0, 'matched': 0, 'status': 'FAIL',
                            'reason': 'unreadable library entry: %s' % error})
            continue
        x, y, z = int(entry.get('x', 0)), int(entry.get('y', 0)), int(entry.get('z', 0))
        turns = int(entry.get('turns', 0) or 0)
        states = getattr(library, 'id_to_state', None) or library.palette
        air_ids = set(getattr(library, 'air_ids', None) or [])
        height, depth, width = library.volume.shape
        total = matched = 0
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
                    if value is None or 'air' in str(value):
                        continue
                    total += 1
                    expected = transform_state(str(value), turns=turns) if turns else str(value)
                    if _state_at(read, x + dx, y + dy, z + dz) == expected:
                        matched += 1
        checked.append({'id': ident, 'anchor': [x, y, z], 'turns': turns, 'cells': total,
                        'matched': matched,
                        'status': 'PASS' if total and matched == total else 'FAIL'})
    return {'status': 'PASS' if checked and all(row['status'] == 'PASS' for row in checked) else 'FAIL',
            'stamps': checked, 'declared': len(checked),
            'matched_cells': sum(row['matched'] for row in checked)}


if __name__ == '__main__':
    data = catalogue()
    print(json.dumps(data['counts'], ensure_ascii=False))
    for line in cards()[:6]:
        print(' ', line)
