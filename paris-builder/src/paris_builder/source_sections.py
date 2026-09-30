"""Source-section vocabulary: whole facade strips mined from the user's builds.

Route A's first pass cut single bays and they did not compose: tiled per grid cell
the facades read as busy, because no single bay carries a facade's rhythm. This
module carries the next size up — one storey of a source facade, several bays wide,
with its own bay spacing, piers, sill band and railing line — which is what a
facade can actually be assembled from.

Classification comes from measuring the library's own shape, not from taste
(`tools/mine_source_sections.py`):

  * `strip`  — wide (11..16), shallow (depth <= 4), 2..4 bays: tiles along a facade.
  * `corner` — 3 wide: a wall return, used at ends and corners.
  * `feature`— deep and dense: a set piece for an entrance bay.

A section is a fragment of a source facade. It is not a semantic model of the
building it came from, and using it is not evidence that the source was learned.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / 'knowledge/library-v1/source-sections'


@lru_cache(maxsize=1)
def sections():
    path = DIRECTORY / 'sections.json'
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def summary():
    path = DIRECTORY / 'catalog.json'
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def by_kind(kind):
    return [section for section in sections() if section.get('kind') == kind]


def material_family(section):
    """Dominant material of a section, from its own palette usage."""
    counts = {}
    for _x, _z, _y, value in section['voxels']:
        name = section['palette'][value].split('[')[0].replace('minecraft:', '')
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return 'air'
    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    from .source_bays import material_family as family_of
    return family_of('minecraft:' + dominant)


def pick_strip(floor_index, bay_offset, family=None, min_width=11):
    """One strip for a storey, stable across rebuilds.

    Prefers the requested material family so a building keeps one stone; falls back
    to any strip of the right shape rather than refusing to build.
    """
    pool = [s for s in by_kind('strip') if s['dimensions_wdh'][0] >= min_width]
    if not pool:
        return None
    if family:
        preferred = [s for s in pool if material_family(s) == family]
        if preferred:
            pool = preferred
    if not pool:
        return None
    return pool[(bay_offset + floor_index) % len(pool)]


def stamp_strip(scene, face, start_u, y, strip):
    """Stamp a section along a face at one storey.

    The section's local +x runs along the face and its -z faces outward, matching
    the component convention; air in the section is written as air so its windows
    stay open and its piers project relative to the wall behind.
    """
    width, depth, height = strip['dimensions_wdh']
    palette = strip['palette']
    anchor = face.point(start_u, y, 0)
    # Put the outermost layer of the section on the facade line.
    offsets = [(x, yy, z - (depth - 1) - 1, palette[value]) for x, z, yy, value in strip['voxels']]
    return scene.voxel_unit(offsets, anchor, turns=face.turns, unit_id=strip['recipe_id'],
                            extra={'unit_sha256': strip['sha256'], 'kind': strip['kind'],
                                   'source': strip['source'], 'source_bboxes': strip['source_bboxes'][:2],
                                   'occurrences': strip['occurrences'],
                                   'dimensions_wdh': strip['dimensions_wdh'], 'bays': strip['bays']})
