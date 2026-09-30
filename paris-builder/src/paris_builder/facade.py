"""Facade layer: how a street face is composed, independent of the house's form.

Why this file exists
--------------------
The user's distinction is the point of this module. A *form* is what a house is — one
house in a terrace, a detached block, a palace with wings. A *facade* is how its street
face is composed — the bay rhythm, where the windows sit, which storeys carry a balcony,
how the ground floor is run. Those are different things, and in a city they vary
independently: the same facade scheme appears on a corner block and on a terrace house,
and the same terrace house can be built with a different facade scheme.

So a scheme here is pure composition: it is handed a `Wall` and the storey list and it
decides where openings go. It never chooses blocks — that is `technique.py` — and it
never decides how deep the house is — that is `house.py`.

The schemes and the sources they answer to
------------------------------------------
==========================  ======================================================
`haussmann_apartment`       the reference street wall: pier-and-window bays, string
                            courses, iron rails at the body storeys, a shopfront ground
                            floor, a graded attic
`palace_front`              hôtel particulier: a centre advanced and crowned, tall
                            first-floor windows, rusticated ground floor
`civic_colonnade`           public building: a giant order over a rusticated base,
                            arched ground-floor openings
`plain_terrace`             the cheapest ordinary house: evenly spaced windows, no
                            bands, no rails — what most of a real street is made of
`shop_terrace`              ground floor of continuous shopfronts under a sign band
==========================  ======================================================
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

#: Bay pitch measured across the user's own street builds. The reference shows a stone
#: pier roughly as wide as the opening, which is a pitch of about twice the window.
BAY_PITCHES = (4, 5, 6)

#: Window width, in cells. Two cells on a four-to-six pitch gives the pier proportion
#: the reference shows; a three-cell window on the same pitch leaves no pier at all.
WINDOW_WIDTH = 2


@dataclass
class Opening:
    """One window or doorway, in wall coordinates."""
    u: int
    y: int
    width: int
    height: int
    level: str
    kind: str = 'window'      # window | shop | door | arch | dormer


@dataclass
class FacadeScheme:
    """A composition rule set. Applied to a wall and the storeys, returns openings.

    Every field is a decision the facade layer is allowed to make. Anything that would
    change what the building *is* (storey count, depth, courtyard) is not here.
    """
    name: str
    pitch: tuple = BAY_PITCHES
    window_width: int = WINDOW_WIDTH
    #: Which storeys carry a continuous string course under them.
    string_courses: tuple = ('body',)
    #: Which storeys carry the iron rail at the window foot.
    rails: tuple = ('body',)
    #: Ground floor treatment: 'shopfront', 'rusticated_arches', 'plain', 'portal'.
    ground: str = 'shopfront'
    #: How many bays the entrance takes.
    entrance_bays: int = 1
    entrance_fraction: float = 0.0
    #: Attic windows are shorter and set closer together.
    attic_short: bool = True
    #: A taller first floor with taller windows (the étage noble).
    noble_floor: bool = True
    #: Centre bay advanced and crowned, as a palace or civic front does.
    centre_feature: bool = False
    notes: str = ''


# --- the scheme database ---------------------------------------------------
SCHEMES: Dict[str, FacadeScheme] = {
    'haussmann_apartment': FacadeScheme(
        name='haussmann_apartment', ground='shopfront', rails=('body',),
        string_courses=('body',), noble_floor=True,
        notes='the reference street wall: pier-and-window bays, shopfront ground floor'),
    'palace_front': FacadeScheme(
        name='palace_front', pitch=(5, 6), ground='portal', rails=('entresol',),
        string_courses=('body',), noble_floor=True, centre_feature=True,
        notes='hôtel particulier: advanced crowned centre, tall first floor'),
    'civic_colonnade': FacadeScheme(
        name='civic_colonnade', pitch=(5, 6), ground='rusticated_arches', rails=(),
        string_courses=('body',), noble_floor=True, centre_feature=True,
        notes='public building: giant order over a rusticated base'),
    'plain_terrace': FacadeScheme(
        name='plain_terrace', ground='plain', rails=(), string_courses=(),
        noble_floor=False, attic_short=False,
        notes='the ordinary house: even windows, no bands, no rails'),
    'shop_terrace': FacadeScheme(
        name='shop_terrace', ground='shopfront', rails=('body',),
        string_courses=('body',), noble_floor=False,
        notes='continuous shopfronts under a sign band'),
}


def scheme(name: str) -> FacadeScheme:
    if name not in SCHEMES:
        raise KeyError('unknown facade scheme %r; known: %s' % (name, ', '.join(sorted(SCHEMES))))
    return SCHEMES[name]


def bay_centres(length: int, spec: FacadeScheme, rng) -> List[int]:
    """Where the windows sit along a wall of `length` cells.

    Two rules, both taken from the reference rather than from arithmetic convenience:

    * the rhythm comes from the *pitch*, not from spreading a handful of bays over the
      whole length — spreading is what leaves ten-cell blanks of stone between windows;
    * among the allowed pitches, take the one that fits the most bays, because a Paris
      plot is narrow and the sources never waste frontage on blank piers. Picking a
      pitch at random can leave a 14-cell house with a single window.
    """
    margin = 1
    usable = length - 2 * margin
    best = None
    for pitch in sorted(spec.pitch):
        count = max(1, usable // pitch)
        if best is None or count > best[0]:
            best = (count, pitch)
    count, pitch = best
    slack = usable - (count - 1) * pitch
    first = margin + slack // 2
    return [first + i * pitch for i in range(count)]


def compose(wall, levels, spec: FacadeScheme, rng, role: str = 'primary') -> List[Opening]:
    """Return the openings for one wall.

    A party wall never gets openings: it is shared with the neighbour, and the sources
    never punch a window into one. A courtyard face gets windows but no shopfront, since
    a shop cannot open into a light well.
    """
    if wall.role == 'party':
        return []
    if wall.role == 'blind':
        return []
    ground_shop = spec.ground in ('shopfront',) and wall.role == 'primary'
    ground_arches = spec.ground == 'rusticated_arches' and wall.role == 'primary'
    centres = bay_centres(wall.length, spec, rng)
    openings: List[Opening] = []
    half = spec.window_width // 2
    for index, centre in enumerate(centres):
        u = min(max(centre - half, 1), wall.length - spec.window_width - 1)
        for level in levels:
            if level.name == 'ground':
                # The entrance keeps a bay even when the rest of the ground floor is
                # shops: a Paris street front has a shop *and* a front door, and the
                # scheme lists the door as one of its techniques, so it must appear.
                if index == round((len(centres) - 1) * spec.entrance_fraction) and (wall.role == 'primary' and spec.entrance_bays
                                   or wall.name == 'rear' and wall.role == 'secondary'):
                    openings.append(Opening(u, level.y + 1, spec.window_width,
                                            max(2, level.height - 2), 'ground', 'door'))
                    continue
                if ground_shop:
                    openings.append(Opening(u, level.y + 1, spec.window_width,
                                            max(2, level.height - 2), 'ground', 'shop'))
                    continue
                if ground_arches:
                    openings.append(Opening(u, level.y + 1, spec.window_width,
                                            max(2, level.height - 2), 'ground', 'arch'))
                    continue
                openings.append(Opening(u, level.y + 1, spec.window_width,
                                        max(2, level.height - 2), 'ground', 'window'))
                continue
            height = max(2, level.height - 2)
            if level.name == 'body' and spec.noble_floor and index == len(centres) // 2:
                height = min(level.height - 1, height + 1)
            if level.name == 'attic' and spec.attic_short:
                height = max(2, height - 1)
            openings.append(Opening(u, level.y + 1, spec.window_width, height,
                                    level.name, 'window'))
    return openings


def rhythm_report(openings: List[Opening], length: int) -> dict:
    """Describe a composed facade in numbers, so claims about it can be checked."""
    columns = [False] * length
    for opening in openings:
        for u in range(opening.u, min(length, opening.u + opening.width)):
            columns[u] = True
    groups, start = [], None
    for index, occupied in enumerate(columns):
        if occupied and start is None:
            start = index
        elif not occupied and start is not None:
            groups.append((start, index - 1))
            start = None
    if start is not None:
        groups.append((start, length - 1))
    widths = [b - a + 1 for a, b in groups]
    piers = [groups[i + 1][0] - groups[i][1] - 1 for i in range(len(groups) - 1)]
    kinds = sorted({o.kind for o in openings})
    return {'openings': len(openings), 'bay_groups': len(groups), 'group_widths': widths,
            'pier_widths': piers,
            'by_kind': {k: sum(1 for o in openings if o.kind == k) for k in kinds}}


def catalogue() -> dict:
    return {
        'schemes': sorted(SCHEMES),
        'bay_pitches': list(BAY_PITCHES),
        'window_width': WINDOW_WIDTH,
        'separation': 'composition only: no block names, no massing',
    }
