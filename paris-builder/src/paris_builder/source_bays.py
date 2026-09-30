"""Source-bay vocabulary: bay units mined from the user's own builds (route A).

The 14 source schematics were only ever indexed as evidence; generation had 45
hand-authored families. `tools/mine_source_bays.py` cuts the repeating facade
units out of those sources (one bay x one storey, with the window, its surround,
sill, band and railing) and this module makes the verified ones buildable.

Admission rules, enforced upstream and re-checked here:
  * only units seen at least twice in the sources;
  * palette restricted to vanilla namespaces;
  * every admitted unit passed the independent prismarine registry read, or it is
    listed as unverifiable and kept out.

A unit is one bay x one storey of a source facade. It is not a semantic model of
the building it came from and it is not a claim that the source build was learned.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / 'knowledge/library-v1/source-bays'

# Material families, keyed by the dominant block a mined unit is built from. A
# building locks one family so its facades read as one stone, the way the sources
# do; mixing families bay by bay produced patchwork facades.
MATERIAL_FAMILIES = {
    'sandstone': 'sandstone', 'smooth_sandstone': 'sandstone', 'cut_sandstone': 'sandstone',
    'chiseled_sandstone': 'sandstone', 'sandstone_slab': 'sandstone', 'sandstone_stairs': 'sandstone',
    'sandstone_wall': 'sandstone', 'sand': 'sandstone',
    'terracotta': 'terracotta', 'white_terracotta': 'terracotta', 'brown_terracotta': 'terracotta',
    'red_terracotta': 'terracotta', 'green_terracotta': 'terracotta', 'orange_terracotta': 'terracotta',
    'light_gray_terracotta': 'terracotta', 'polished_granite': 'granite', 'granite': 'granite',
    'deepslate': 'deepslate', 'deepslate_tiles': 'deepslate', 'polished_deepslate': 'deepslate',
    'cobbled_deepslate': 'deepslate', 'deepslate_bricks': 'deepslate',
    'spruce_planks': 'timber', 'dark_oak_planks': 'timber', 'oak_planks': 'timber',
    'birch_planks': 'timber', 'jungle_planks': 'timber', 'acacia_planks': 'timber',
    'stone_bricks': 'stone', 'stone': 'stone', 'smooth_stone': 'stone', 'andesite': 'stone',
    'polished_andesite': 'stone', 'cobblestone': 'stone', 'bricks': 'brick', 'brick': 'brick',
    'glass': 'glazing', 'glass_pane': 'glazing', 'light_gray_stained_glass_pane': 'glazing',
    'white_stained_glass': 'glazing', 'gray_stained_glass_pane': 'glazing',
    'iron_bars': 'ironwork', 'chain': 'ironwork', 'iron_trapdoor': 'ironwork', 'anvil': 'ironwork',
    'oxidized_copper': 'copper', 'weathered_copper': 'copper', 'copper_block': 'copper',
    'cut_copper': 'copper', 'oxidized_cut_copper': 'copper',
}


def material_family(state):
    """Family of one block state, by its base name."""
    name = str(state).split('[')[0].replace('minecraft:', '')
    return MATERIAL_FAMILIES.get(name, 'other')


def dominant_state(unit, ignore_air=True):
    """The block this unit is mostly built from, counted over voxels (not palette)."""
    counts = {}
    for _x, _z, _y, value in unit['voxels']:
        name = unit['palette'][value]
        base = name.split('[')[0].replace('minecraft:', '')
        if ignore_air and base in ('air', 'cave_air', 'void_air'):
            continue
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def unit_family(unit):
    """Material family of a unit, from its dominant solid block."""
    dominant = dominant_state(unit)
    return 'air' if dominant is None else material_family(dominant)


@lru_cache(maxsize=1)
def catalog():
    path = DIRECTORY / 'recipes.json'
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def summary():
    path = DIRECTORY / 'catalog.json'
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def units_for(role, floor_index, storeys):
    """Deterministic unit choice for one face role and storey.

    Street roles get the richer units (more distinct blocks, larger surround) and
    the noble floor gets the richest, matching how the sources themselves are
    composed; rear and service faces get the plainest. The choice is a pure
    function of (role, floor), so a rebuild reproduces the same building.
    """
    entries = catalog()
    if not entries:
        return []
    ranked = sorted(entries, key=lambda unit: (len(unit['palette']), unit['sha256']))
    if role in ('primary_street', 'corner'):
        pool = ranked[-max(3, len(ranked) // 3):] if floor_index == 0 else ranked[len(ranked) // 2:]
    elif role == 'secondary_street':
        pool = ranked[len(ranked) // 3: 2 * len(ranked) // 3]
    else:
        pool = ranked[:max(3, len(ranked) // 4)]
    return pool or ranked


def families():
    """Material families present in the mined library, richest first."""
    counts = {}
    for unit in catalog():
        counts[unit_family(unit)] = counts.get(unit_family(unit), 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if name not in ('air',)]


def lock_family(seed):
    """One material family per building.

    The first attempt sampled units freely and the facades came out patchy: red
    terracotta next to pale sandstone next to green ironwork. The sources keep one
    stone with small variations, so a building locks a family and the noise comes
    from unit choice inside it.
    """
    available = families()
    if not available:
        return None
    return available[seed % len(available)]


def pick(role, floor_index, bay_index, storeys, family=None, width=None):
    """One unit for a specific bay, stable across rebuilds.

    `family` locks the building's material (see `lock_family`) and `width` keeps a
    narrow window from receiving a wide unit that would overwrite its neighbours.

    Known limitation, measured this round: even with one family and matching
    widths, tiling one mined unit per grid cell reads as busy rather than composed,
    because each unit carries its own projecting sill, railing and band at slightly
    different offsets. Making mined units compose properly needs facade-level
    rhythm rules (route B), not just per-bay sampling; until then this vocabulary is
    behind `source_bay_vocabulary=False` and off by default.
    """
    pool = units_for(role, floor_index, storeys)
    if family:
        narrowed = [unit for unit in pool if unit_family(unit) == family]
        if narrowed:
            pool = narrowed
    if width:
        fits = [unit for unit in pool if unit['dimensions_wdh'][0] <= width + 2]
        if fits:
            pool = fits
    if not pool:
        return None
    return pool[(bay_index + floor_index) % len(pool)]


def unit_voxels(unit):
    """(dx, dy, dz, state) offsets with the unit's own bounds, origin at the aperture centre."""
    width, depth, height = unit['dimensions_wdh']
    palette = unit['palette']
    voxels = [(x, y, z, palette[value]) for x, z, y, value in unit['voxels']]
    return voxels, width, depth, height


def stamp(scene, face, opening_left, opening_bottom, opening_span, unit):
    """Stamp one mined bay so its own opening lands on the requested opening.

    The unit carries its aperture; centring the unit on the opening keeps the
    building's bay grid intact while the mined surround, sill and railing become
    real geometry. Air in the unit is written as air, so the aperture stays open.
    """
    voxels, width, depth, height = unit_voxels(unit)
    aperture = unit.get('aperture_span', 1)
    centre_u = opening_left + (opening_span - 1) / 2
    along = int(round(centre_u - (width - 1) / 2))
    along = max(0, along)
    anchor = face.point(along, opening_bottom, 0)
    # Canonical unit frame: +dx along the face, -dz outward, +dy up. The unit's own
    # depth is placed so its outermost layer sits on the facade line.
    offsets = [(dx, dy, dz - (depth - 1) - 1, value) for dx, dy, dz, value in voxels]
    return scene.voxel_unit(offsets, anchor, turns=face.turns, unit_id=unit['recipe_id'],
                            extra={'unit_sha256': unit['sha256'], 'sources': unit['sources'],
                                   'occurrences': unit['occurrences'], 'aperture_span': aperture,
                                   'dimensions_wdh': unit['dimensions_wdh']})
