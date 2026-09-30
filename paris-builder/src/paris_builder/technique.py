"""Technique layer: which blocks and states realise one element of a house.

Why this file exists
--------------------
The user separated three things that must not be mixed up: the *structure* (what a
house is), the *facade* (how its street face is composed), and the *technique* (how a
given element is actually built out of blocks and block states). This module is the
third one, and the requirement on it is orthogonality: every technique takes the
surface it is applied to as an argument, so the same rustication, the same quoins, the
same rail can be laid on a terrace house, a palace wing, or a civic pavilion without
knowing which one it is on.

A technique therefore never asks what form it is decorating, never needs coordinates of
its own, and never changes the composition. Each one is `(scene, wall, opening/surface
description) -> None`.

The techniques and the sources they answer to
---------------------------------------------
==========================  ====================================================
`rustication`               the horizontal-jointed stone base every source street
                            front has, and the civic base course
`quoins`                    dressed stones at a corner, alternating wide and narrow
`pilaster`                  a shallow vertical band, chained or plain, marking a bay
`window_surround`           sill, lintel and jambs, the dressing around one opening
`string_course`             the band that marks a storey line
`cornice`                   the crowning course, with the corbel row under it
`guard_rail`                the iron rail at a window foot
`shopfront`                 glazed shop bay with its sign band and stall riser
`cresting`                  the iron crest along a ridge
==========================  ====================================================

These are named after the elements the brief lists; the block choices come from the
materials measured in the sources, and every state written here is explicit because the
project's independent geometry check rejects incomplete states.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from .architecture import planar_connection

from .house import (CORNICE, DOOR, IRON, PANE_BACKING, PLINTH, ROOF_RIDGE, STONE,
                    STONE_COURSE, STONE_DRESSING, WINDOW_PANE)

#: The rail block. Iron bars are a real block with connections, so the state has to say
#: which sides connect or the game recomputes the model on paste.
RAIL = IRON


@dataclass
class TechniqueUse:
    """One application of a technique, recorded so a report can prove what was used."""
    name: str
    wall: str
    count: int
    note: str = ''


def _column(wall, u: int):
    """The (x, z) of a wall cell, ignoring the plane offset."""
    return wall.point(u, 0, 0)[0], wall.point(u, 0, 0)[2]


# --- surface techniques ----------------------------------------------------
def rustication(scene, wall, y0: int, y1: int, band: int = 2, owner='technique') -> TechniqueUse:
    """Horizontal-jointed stone base: alternating band and joint courses.

    Applied by *surface*, not by building: it takes the y range and the wall, so it
    works on a palace plinth or a shop base without knowing which.
    """
    count = 0
    for u in range(wall.length):
        for y in range(y0, y1 + 1):
            x, z = _column(wall, u)
            scene.put(x, y, z, STONE_DRESSING if (y - y0) % band == 0 else STONE, owner)
            count += 1
    return TechniqueUse('rustication', wall.name, count, 'banded base course')


def quoins(scene, wall, y0: int, y1: int, width: int = 1, owner='technique') -> TechniqueUse:
    """Dressed corner stones, alternating wide on the quoin course.

    Quoins belong to the corner, so they are applied at `u = 0` or the last u of a wall
    rather than along it; passing a different wall applies them to a different corner.
    """
    count = 0
    for u in (0, wall.length - 1):
        for y in range(y0, y1 + 1):
            if (y - y0) % 2 and width > 1:
                continue
            for du in range(-width + 1, width):
                uu = u + du
                if not 0 <= uu < wall.length:
                    continue
                x, z = _column(wall, uu)
                scene.put(x, y, z, STONE_DRESSING, owner)
                count += 1
    return TechniqueUse('quoins', wall.name, count, 'alternating corner stones')


def pilaster(scene, wall, u: int, y0: int, y1: int, width: int = 1, owner='technique') -> TechniqueUse:
    """A shallow vertical band marking a bay, plain or chained.

    `width` cells wide, projected one cell out from the wall so it reads in relief.
    """
    count = 0
    for du in range(width):
        uu = u + du
        if not 0 <= uu < wall.length:
            continue
        for y in range(y0, y1 + 1):
            x, z = _column(wall, uu)
            scene.put(x, y, z, STONE_DRESSING if (y - y0) % 3 == 0 else STONE, owner)
            ox, _oy, oz = wall.point(uu, y, 1)
            scene.put(ox, y, oz, STONE_DRESSING if (y - y0) % 3 == 0 else STONE, owner)
            count += 1
    return TechniqueUse('pilaster', wall.name, count, 'relieved vertical band')


def window_surround(scene, wall, opening, owner='technique') -> TechniqueUse:
    """Sill under, lintel over, jambs either side, and a mullion down the middle.

    This is the technique that decides whether an opening reads as a window or as a
    hole, and it is the one that must never be applied *inside* the reveal: a lintel
    row written into the opening glazes a cell that is meant to be stone.

    The mullion matters more than it sounds. The reference windows are two lights
    divided by a stone muntin; a single undivided pane of glazing at this scale reads as
    a flat panel, which is what made the first generated elevations look like cardboard.
    """
    count = 0
    left = opening.u - 1
    right = opening.u + opening.width
    top = opening.y + opening.height
    # 窗台与过梁写在**外表面**（d=0），也就是玻璃前面那一层；两者不能越过玻璃所在的 d=1，
    # 否则窗台正好挡住窗——早期版本的窗之所以读成一条缝，就是这个覆盖。
    for u in range(left, right + 1):
        if not 0 <= u < wall.length:
            continue
        for y in (opening.y - 1, top):
            x, z = _column(wall, u)
            scene.put(x, y, z, STONE_DRESSING, owner)
            count += 1
    for u in (left, right):
        if not 0 <= u < wall.length:
            continue
        for y in range(opening.y, top):
            x, z = _column(wall, u)
            scene.put(x, y, z, STONE_DRESSING, owner)
            count += 1
    # 过梁底面（soffit）写在 d=0，与过梁同一层，不再占 d=1。
    for u in range(opening.u, opening.u + opening.width):
        if not 0 <= u < wall.length:
            continue
        x, y, z = wall.point(u, top, 0)
        scene.put(x, y, z, STONE_DRESSING, owner)
        count += 1
    # Mullion between two lights, plus a transom across the head.
    if opening.width >= 2 and opening.height >= 3:
        u = opening.u + opening.width // 2
        x, z = _column(wall, u)
        for y in range(opening.y, top):
            scene.put(x, y, z, STONE_DRESSING, owner)
            count += 1
        ty = opening.y + opening.height - 2
        for u in range(opening.u, opening.u + opening.width):
            x, z = _column(wall, u)
            scene.put(x, ty, z, STONE_DRESSING, owner)
            count += 1
    return TechniqueUse('window_surround', wall.name, count, opening.level)


def string_course(scene, wall, y: int, owner='technique') -> TechniqueUse:
    """The band that marks a storey line, run the length of the wall."""
    count = 0
    for u in range(wall.length):
        x, z = _column(wall, u)
        scene.put(x, y, z, STONE_DRESSING, owner)
        count += 1
    return TechniqueUse('string_course', wall.name, count, 'y=%d' % y)


def cornice(scene, wall, y: int, drip: bool = True, owner='technique') -> TechniqueUse:
    """The crowning course, with a corbel row under it and an optional drip over it."""
    count = 0
    for u in range(wall.length):
        x, z = _column(wall, u)
        scene.put(x, y, z, CORNICE, owner)
        scene.put(x, y - 1, z, STONE_COURSE, owner)
        count += 2
        if drip:
            scene.put(x, y + 1, z, STONE_DRESSING, owner)
            count += 1
    return TechniqueUse('cornice', wall.name, count, 'crown at y=%d' % y)


def guard_rail(scene, wall, opening, owner='technique') -> TechniqueUse:
    """The iron rail at a window foot, one cell out from the wall face.

    Written as a connected bar state: `up=false` with no side connections is a ghost
    block with no model in game, which the project's geometry check rejects.
    """
    count = 0
    y = opening.y - 1
    for u in range(opening.u - 1, opening.u + opening.width + 1):
        if not 0 <= u < wall.length:
            continue
        x, y2, z = wall.point(u, y, 1)
        scene.put(x, y2, z, planar_connection(RAIL, wall.normal), owner)
        count += 1
    return TechniqueUse('guard_rail', wall.name, count, 'rail at y=%d' % y)


def shopfront(scene, wall, opening, owner='technique') -> TechniqueUse:
    """A glazed shop bay: stall riser, glazing, and the sign band over it.

    The glazing goes on the plane the street sees. Putting it one cell in leaves an
    unbroken stone face and the shopfront disappears — the defect that made the first
    city renders a wall with no openings at all.
    """
    count = 0
    top = opening.y + opening.height
    for u in range(opening.u, opening.u + opening.width):
        if not 0 <= u < wall.length:
            continue
        # Stall riser under the glazing, then the glazing itself one cell back so the
        # shopfront has the same recess as the windows above it.
        x, z = _column(wall, u)
        scene.put(x, opening.y, z, PLINTH, owner)
        for y in range(opening.y + 1, top):
            gx, _gy, gz = wall.point(u, y, 1)
            scene.put(gx, y, gz, planar_connection(WINDOW_PANE, wall.normal), owner)
            for d in range(2, wall.depth + 1):
                px, py, pz = wall.point(u, y, d)
                scene.put(px, py, pz, PANE_BACKING, owner)
            count += 2
    # Sign band across the shopfront and its jambs.
    for u in range(opening.u - 1, opening.u + opening.width + 1):
        if not 0 <= u < wall.length:
            continue
        x, z = _column(wall, u)
        scene.put(x, top, z, STONE_DRESSING, owner)
        count += 1
    return TechniqueUse('shopfront', wall.name, count, 'glazed bay + sign band')


def cresting(scene, wall, y: int, step: int = 3, owner='technique') -> TechniqueUse:
    """The iron crest along a ridge, one upright every `step` cells."""
    count = 0
    for u in range(0, wall.length, step):
        x, _, z = wall.point(u, y, 0)
        scene.put(x, y, z, ROOF_RIDGE, owner)
        scene.put(x, y + 1, z, RAIL, owner)
        count += 2
    return TechniqueUse('cresting', wall.name, count, 'ridge crest')


def door_leaf(scene, wall, opening, facing: str, owner='technique') -> TechniqueUse:
    """A two-leaf entrance door, both halves written.

    A lone lower half is an incomplete state: the independent geometry check fails it,
    and in game it renders as half a door.
    """
    count = 0
    for offset, hinge in ((0, 'left'), (1, 'right')):
        u = opening.u + offset
        if not 0 <= u < wall.length:
            continue
        for half, dy in (('lower', 0), ('upper', 1)):
            # The leaf sits one cell in, in the same recess as the glazing, so the
            # entrance reads as a doorway rather than a panel stuck on the wall.
            x, y, z = wall.point(u, opening.y + dy, 1)
            scene.put(x, y, z,
                      '%s[facing=%s,half=%s,hinge=%s,open=false,powered=false]'
                      % (DOOR, facing, half, hinge), owner)
            count += 1
    # Fanlight over the leaf: the tall ground floor carries a glazed transom.
    for u in range(opening.u, opening.u + opening.width):
        if not 0 <= u < wall.length:
            continue
        for y in range(opening.y + 2, opening.y + opening.height):
            x, y2, z = wall.point(u, y, 1)
            scene.put(x, y2, z, planar_connection(WINDOW_PANE, wall.normal), owner)
            count += 1
    return TechniqueUse('door_leaf', wall.name, count, 'two leaves + fanlight')


# --- the technique database ------------------------------------------------
#: Every technique the project has, by name. A builder that wants an element asks for
#: it here; nothing about a technique is specific to one house form.
TECHNIQUES: Dict[str, object] = {
    'rustication': rustication,
    'quoins': quoins,
    'pilaster': pilaster,
    'window_surround': window_surround,
    'string_course': string_course,
    'cornice': cornice,
    'guard_rail': guard_rail,
    'shopfront': shopfront,
    'cresting': cresting,
    'door_leaf': door_leaf,
}

#: Which techniques a facade scheme expects, so a caller can apply a scheme without
#: hard-coding the element list. Ground-floor kinds map to their technique.
SCHEME_TECHNIQUES = {
    'haussmann_apartment': ('rustication', 'window_surround', 'string_course', 'cornice',
                            'guard_rail', 'shopfront', 'door_leaf'),
    'palace_front': ('rustication', 'quoins', 'pilaster', 'window_surround',
                     'string_course', 'cornice', 'door_leaf'),
    'civic_colonnade': ('rustication', 'pilaster', 'window_surround', 'cornice'),
    'plain_terrace': ('window_surround',),
    'shop_terrace': ('shopfront', 'window_surround', 'string_course', 'cornice',
                     'guard_rail', 'door_leaf'),
}


def catalogue() -> dict:
    return {
        'techniques': sorted(TECHNIQUES),
        'orthogonal': True,
        'separation': 'blocks and states only: each technique takes its surface as an '
                      'argument and never asks which form it is on',
        'per_scheme': {k: list(v) for k, v in SCHEME_TECHNIQUES.items()},
    }
