"""Structure layer: the massing of one Paris house, in five source forms.

Why this file exists
--------------------
The generator could produce exactly one form — a detached Haussmann apartment block —
which is why the user's own builds could not be reproduced: their sources include a
civic hall, a palace with wings, a corner block, a run of narrow street houses, and a
street built down a slope. Learning a *shape* means having shapes to learn from; this
module is the structure database, separate from facade decoration and from the block
techniques used to realise an element.

What belongs here
-----------------
Only the massing of one house: how wide and deep it is, how many storeys, where the
courtyard is, how the roofline steps, and how a neighbour shares a party wall. No
facade composition and no block choice: those are `facade.py` and `technique.py`.

The forms and the sources they answer to
----------------------------------------
======================  ==========================================================
`street_house`          a run of narrow houses sharing party walls (frontages
                        8..14, the ordinary Paris plot; the reference street wall)
`apartment_block`       a detached immeuble de rapport with four visible faces
`court_palace`          hôtel particulier: corps de logis, two wings, screen wall
`civic_hall`            a monumental public building: long front, central pavilion,
                        end pavilions, higher centre
`slope_terrace`         a street descending a hill, stepped in bays
======================  ==========================================================

All measurements are blocks and are taken from the user's own builds, measured in
`knowledge/city/measured_source_parcels.json`, not invented.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

# --- materials -------------------------------------------------------------
# A Paris street wall is one limestone family with a darker base, a slightly darker
# moulding tone, and light glazing. The palette lives here because the structure layer
# decides what a wall is made of; the facade layer only decides where openings go.
STONE = 'minecraft:smooth_sandstone'
STONE_COURSE = 'minecraft:sandstone'
STONE_DRESSING = 'minecraft:cut_sandstone'
CORNICE = 'minecraft:polished_diorite'
PLINTH = 'minecraft:polished_andesite'
ROOF = 'minecraft:deepslate_tiles'
ROOF_RIDGE = 'minecraft:polished_deepslate'
ROOF_DORMER = 'minecraft:light_gray_concrete'
IRON = 'minecraft:iron_bars[east=false,north=false,south=false,waterlogged=false,west=false]'
FLOOR_PLATE = 'minecraft:spruce_planks'
WINDOW_PANE = 'minecraft:white_stained_glass_pane[east=true,north=false,south=false,waterlogged=false,west=true]'
PANE_BACKING = 'minecraft:white_concrete'
DOOR = 'minecraft:dark_oak_door'

#: How thick the street wall is built before openings are cut into it. Openings are
#: decorated behind their face, so a one-cell wall makes every opening self-erasing.
WALL_DEPTH = 4

#: Outward normals, indexed so a form can name its faces without vectors.
NORTH = (0, -1)
SOUTH = (0, 1)
WEST = (-1, 0)
EAST = (1, 0)

#: Roles decide how much of the elevation the facade layer is allowed to decorate.
#: A party wall is shared with a neighbour, so it carries no openings at all.
PRIMARY = 'primary'      # the street front: full composition
SECONDARY = 'secondary'  # a visible return on a second street or a garden
COURTYARD = 'courtyard'  # inside the block: plainer
PARTY = 'party'          # shared with the neighbour: no openings
BLIND = 'blind'          # no openings, but still a visible wall


@dataclass
class Wall:
    """One straight wall: a run of `length` cells with a known outward direction.

    Coordinates are half-open: `u` runs 0..length-1 along the wall, and `d` runs 0 at
    the outer surface towards the inside of the building. `d` is what makes openings
    work: the street sees `d = 0`, and everything behind it is reveal.
    """
    name: str
    role: str
    ux: int          # x of u = 0
    uz: int          # z of u = 0
    step: tuple      # (dx, dz) for one step of u
    length: int
    height: int
    normal: tuple    # outward, one of the four constants above
    depth: int = WALL_DEPTH
    levels: Optional[List['Level']] = None

    def point(self, u: float, y: int, d: int = 0) -> tuple:
        """世界坐标 (x, y, z)。`d` 是**从墙体外表面往里的进深**，不是沿法向的位移。

        方向必须减：`normal` 指向室外，而 `d=0` 是墙的外表面、`d` 越大越往建筑内部。
        用 `+normal * d` 会让开口切到建筑外面去——实墙留在里面、凹进落在街上，
        于是街面的窗看起来是"从外表面一路通到内部"的竖条。这个符号错误害我改错过一次街面朝向。
        """
        return (int(round(self.ux + self.step[0] * u - self.normal[0] * d)), int(y),
                int(round(self.uz + self.step[1] * u - self.normal[1] * d)))

    def inner(self, u: float, y: int, d: int = 1) -> tuple:
        """墙体里侧第 `d` 格（`d=1` 就是紧贴外表面之后的那一格）。

        技法层需要区分"街面那一层"与"墙里面"：玻璃写在 `inner(u, y, 1)`，窗台/过梁写在
        `point(u, y, 0)`。以前两者都是 `point(u, y, 0)`，叠在同一格上互相覆盖。
        """
        return self.point(u, y, d)

    def surface(self, d: int = 0) -> List[tuple]:
        return [(*self.point(u, 0, d)[::2], ) for u in range(self.length)]

    def cells(self, d: int = 0):
        """Every (x, z) on plane `d` of this wall."""
        for u in range(self.length):
            x, _y, z = self.point(u, 0, d)
            yield x, z

    def bands(self, levels) -> Dict[str, int]:
        """Storey name -> the y of its floor, for the facade layer to compose on."""
        return {name: y for name, y, _h in levels}


@dataclass
class Level:
    """One storey of a house."""
    name: str
    y: int
    height: int


@dataclass
class Structure:
    """One house's massing, before any decoration.

    `walls` is what the facade layer iterates: the structure decides which faces exist
    and what role each one plays, and never how they are composed.
    """
    form: str
    wid: int
    dep: int
    top: int
    levels: List[Level]
    walls: List[Wall]
    footprint: List[tuple]
    courts: List[List[tuple]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def wall(self, name: str) -> Optional[Wall]:
        for wall in self.walls:
            if wall.name == name:
                return wall
        return None

    def street_walls(self) -> List[Wall]:
        return [w for w in self.walls if w.role == PRIMARY]

    def report(self) -> dict:
        return {
            'form': self.form, 'width': self.wid, 'depth': self.dep, 'top': self.top,
            'storeys': len(self.levels),
            'levels': [{'name': l.name, 'y': l.y, 'height': l.height} for l in self.levels],
            'walls': [{'name': w.name, 'role': w.role, 'length': w.length, 'height': w.height,
                       'depth': w.depth, 'normal': list(w.normal)} for w in self.walls],
            'roof_height': self.top - (self.levels[-1].y if self.levels else 0),
            'notes': self.notes,
            'extras': self.extras,
        }


# --- storey scheme ---------------------------------------------------------
#: The Parisian section, from the PLUi: a tall ground floor, sometimes an entresol,
#: 层高与窗高的关系是算过的，不是拍的：窗高 = 层高 − 2（窗台与过梁各占一格），
#: 而参考图的窗是 3–4 格高。所以层高取 5–6，窗才到 3–4 格；层高 3 会让窗只剩 1 格，
#: 整个立面读成一片细缝——那是实测到的结果。
STOREY_HEIGHTS = (5, 6)
GROUND_HEIGHTS = (6, 7)
ENTRESOL_HEIGHT = 3


def storeys(storey_count: int, rng, entresol: bool = False) -> List[Level]:
    """The vertical scheme: ground floor first, then body storeys, then the attic."""
    ground = rng.choice(GROUND_HEIGHTS)
    levels = [Level('ground', 1, ground)]
    y = 1 + ground
    if entresol:
        levels.append(Level('entresol', y, ENTRESOL_HEIGHT))
        y += ENTRESOL_HEIGHT
    # The top storey becomes the attic, so the body is one shorter than requested.
    body = max(1, storey_count - len(levels))
    for _ in range(body):
        height = rng.choice(STOREY_HEIGHTS)
        levels.append(Level('body', y, height))
        y += height
    if levels[-1].name == 'body':
        last = levels.pop()
        levels.append(Level('attic', last.y, rng.choice(STOREY_HEIGHTS)))
        y = levels[-1].y + levels[-1].height
    return levels, y


def _slab(scene, x0, x1, z0, z1, y0, y1, value, owner='structure'):
    """Fill a box, clipped to the scene, without raising on the edges."""
    height, depth, width = scene.volume.shape
    for y in range(max(0, y0), min(height, y1 + 1)):
        for z in range(max(0, z0), min(depth, z1 + 1)):
            for x in range(max(0, x0), min(width, x1 + 1)):
                scene.put(x, y, z, value, owner)


def _shell(scene, footprint, levels, top, thickness=1, role='wall'):
    """Raise the walls of a footprint to `top`, one cell thick."""
    for (x, z) in footprint:
        for y in range(1, top + 1):
            scene.put(x, y, z, STONE if y % 6 else STONE_COURSE, role)


def _plates(scene, footprint, levels, owner='plate'):
    for level in levels:
        for (x, z) in footprint:
            scene.put(x, level.y, z, FLOOR_PLATE, owner)


def _mansard(scene, x0, x1, z0, z1, top, rng, courses: int = 4):
    """A steep mansard over a rectangle, with dormers and chimneys.

    The roof is not decoration: on the reference it takes about a seventh of the whole
    elevation, and a two-course cap reads as a lid. The courses rise *and* pull in,
    which is what makes it a cone rather than a slab.
    """
    for step in range(courses):
        inset = step
        _slab(scene, x0 + inset, x1 - inset, z0 + inset, z1 - inset, top + 1 + step,
              top + 1 + step, ROOF, 'roof')
    _slab(scene, x0 + courses - 1, x1 - courses + 1, z0 + courses - 1, z1 - courses + 1,
          top + courses, top + courses, ROOF_RIDGE, 'roof-ridge')
    # Dormers on the lower slope, one per few bays: the reference has one per bay and
    # a mansard without them is a box with a lid.
    width = x1 - x0
    span = max(3, width // 4)
    for x in range(x0 + 1, x1 - 1, span):
        for dx in (0, 1):
            xx = x + dx
            if xx >= x1:
                continue
            scene.put(xx, top + 1, z0 + 2, ROOF_DORMER, 'dormer')
            scene.put(xx, top + 2, z0 + 1, ROOF_DORMER, 'dormer')
            scene.put(xx, top + 1, z1 - 2, ROOF_DORMER, 'dormer')
            scene.put(xx, top + 2, z1 - 1, ROOF_DORMER, 'dormer')
    # Chimneys rise out of the ridge, offset from the ends as the sources show.
    for x in (x0 + max(2, width // 3), x1 - max(2, width // 3)):
        if not (x0 < x < x1):
            continue
        _slab(scene, x, x, z0 + 4, z0 + 5, top + 2, top + 6, STONE_COURSE, 'chimney')
        _slab(scene, x, x, z0 + 3, z0 + 6, top + 7, top + 7, STONE_COURSE, 'chimney-cap')


def _flat_roof(scene, x0, x1, z0, z1, top, parapet: int = 1):
    _slab(scene, x0, x1, z0, z1, top, top, STONE_DRESSING, 'roof-deck')
    _slab(scene, x0, x1, z0, z1, top + parapet, top + parapet, CORNICE, 'parapet')


# --- the five forms --------------------------------------------------------
def street_house(wid: int, dep: int, storey_count: int, seed: int = 1900,
                 entresol: Optional[bool] = None, roof: str = 'mansard') -> tuple:
    """One house in a continuous street wall: party walls both sides, one street face.

    This is the ordinary Paris plot, and it is the form the reference street wall is
    made of. The two side walls are PARTY: they belong to the run, not to this house,
    so they carry no openings.
    """
    rng = random.Random(seed)
    if entresol is None:
        entresol = rng.random() < 0.5
    levels, top = storeys(storey_count, rng, entresol)
    x0, x1, z0 = 6, 6 + wid - 1, 6
    z1 = z0 + dep - 1
    walls = [
        # The street face is the north side; u increases eastwards along x.
        Wall('street', PRIMARY, x0, z0, (1, 0), wid, top, NORTH),
        Wall('party_west', PARTY, x0, z0, (0, 1), dep, top, WEST),
        Wall('party_east', PARTY, x1, z0, (0, 1), dep, top, EAST),
        Wall('rear', SECONDARY, x0, z1, (1, 0), wid, top, SOUTH),
    ]
    footprint = [(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)]
    structure = Structure('street_house', wid, dep, top, levels, walls, footprint,
                          notes=['party walls on both sides; street and courtyard elevations'])
    return structure, (x0, x1, z0, z1, rng, roof)


def apartment_block(wid: int, dep: int, storey_count: int, seed: int = 1900,
                    chamfer: int = 0, court: tuple = (0, 0)) -> tuple:
    """A detached immeuble de rapport: four visible faces, optionally chamfered.

    `court` is (width, depth) of an internal light well, which is what gives the deep
    Paris plot its second set of windows.
    """
    rng = random.Random(seed)
    levels, top = storeys(storey_count, rng, rng.random() < 0.4)
    x0, x1, z0 = 6, 6 + wid - 1, 6
    z1 = z0 + dep - 1
    walls = [
        Wall('street', PRIMARY, x0, z0, (1, 0), wid, top, NORTH),
        Wall('east', SECONDARY, x1, z0, (0, 1), dep, top, EAST),
        Wall('west', SECONDARY, x0, z0, (0, 1), dep, top, WEST),
        Wall('rear', SECONDARY, x0, z1, (1, 0), wid, top, SOUTH),
    ]
    footprint = [(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)]
    courts = []
    if court[0] >= 3 and court[1] >= 3:
        cx0 = x0 + max(2, (wid - court[0]) // 2)
        cz0 = z0 + max(2, (dep - court[1]) // 2)
        courts = [[(x, z) for x in range(cx0, cx0 + court[0]) for z in range(cz0, cz0 + court[1])]]
        inner = courts[0]
        for (x, z) in inner:
            footprint.remove((x, z))
        # The court's own faces are plain walls, not party walls.
        walls.extend([
            Wall('court_north', COURTYARD, cx0, cz0, (1, 0), court[0], top, SOUTH),
            Wall('court_south', COURTYARD, cx0, cz0 + court[1] - 1, (1, 0), court[0], top, NORTH),
            Wall('court_west', COURTYARD, cx0, cz0, (0, 1), court[1], top, EAST),
            Wall('court_east', COURTYARD, cx0 + court[0] - 1, cz0, (0, 1), court[1], top, WEST),
        ])
    structure = Structure('apartment_block', wid, dep, top, levels, walls, footprint,
                          courts, notes=['four visible faces', 'chamfer=%d' % chamfer])
    return structure, (x0, x1, z0, z1, rng, 'mansard')


def court_palace(wid: int, dep: int, storey_count: int, seed: int = 1900,
                 court: tuple = (14, 14), wing: int = 9) -> tuple:
    """A hôtel particulier: corps de logis at the back, two wings, screen to the street.

    The plan is a U around an entrance court, closed at the street by a lower screen
    wall with the gate in it. This is the source form with wings and a colonnade.
    """
    rng = random.Random(seed)
    levels, top = storeys(storey_count, rng, False)
    x0, x1, z0 = 6, 6 + wid - 1, 6
    z1 = z0 + dep - 1
    court_w = max(5, min(court[0], wid - 2 * wing))
    cx0 = x0 + (wid - court_w) // 2
    cz1 = z0 + max(4, dep - max(6, dep // 3))
    footprint = []
    # Screen wall across the street front, with the court behind it.
    for x in range(x0, x1 + 1):
        footprint.append((x, z0))
    # Two wings running back.
    for z in range(z0, z1 + 1):
        for x in list(range(x0, x0 + wing)) + list(range(x1 - wing + 1, x1 + 1)):
            footprint.append((x, z))
    # Corps de logis across the back.
    for x in range(x0, x1 + 1):
        for z in range(cz1, z1 + 1):
            footprint.append((x, z))
    footprint = sorted(set(footprint))
    walls = [
        # 街面（临街的院墙与大门）在 z_max 侧，与预览渲染器的 `front` 相机一致。
        Wall('screen', PRIMARY, x0, z0, (1, 0), wid, top, NORTH),
        Wall('wing_west', SECONDARY, x0, z0, (0, 1), dep, top, WEST),
        Wall('wing_east', SECONDARY, x1, z0, (0, 1), dep, top, EAST),
        Wall('corps_south', SECONDARY, x0, z1, (1, 0), wid, top, SOUTH),
        Wall('court_west', COURTYARD, x0 + wing - 1, z0 + 1, (0, 1), cz1 - z0 - 1, top, EAST),
        Wall('court_east', COURTYARD, x1 - wing + 1, z0 + 1, (0, 1), cz1 - z0 - 1, top, WEST),
        Wall('court_south', COURTYARD, x0 + wing, cz1, (1, 0), court_w - 1, top, NORTH),
    ]
    courts = [[(x, z) for x in range(x0 + wing, x1 - wing + 1)
               for z in range(z0 + 1, cz1)]]
    structure = Structure('court_palace', wid, dep, top, levels, walls, footprint, courts,
                          notes=['entry court, two wings, corps de logis'])
    return structure, (x0, x1, z0, z1, rng, 'mansard')


def civic_hall(wid: int, dep: int, storey_count: int, seed: int = 1900,
               pavilion: int = 9, end_pavilion: int = 7) -> tuple:
    """A monumental public building: long front, centre and end pavilions, higher centre.

    The centre pavilion rises above the wings and carries the tall windows, which is
    what makes a civic facade read differently from a terrace of houses.
    """
    rng = random.Random(seed)
    levels, top = storeys(storey_count, rng, False)
    x0, x1, z0 = 6, 6 + wid - 1, 6
    z1 = z0 + dep - 1
    centre_h = max(4, rng.choice(STOREY_HEIGHTS))
    walls = [
        Wall('street', PRIMARY, x0, z0, (1, 0), wid, top, NORTH),
        Wall('east', SECONDARY, x1, z0, (0, 1), dep, top, EAST),
        Wall('west', SECONDARY, x0, z0, (0, 1), dep, top, WEST),
        Wall('rear', SECONDARY, x0, z1, (1, 0), wid, top, SOUTH),
    ]
    footprint = [(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)]
    structure = Structure('civic_hall', wid, dep, top, levels, walls, footprint,
                          notes=['centre pavilion +%d high, end pavilions %d wide'
                                 % (centre_h, end_pavilion),
                                 'centre pavilion %d wide' % pavilion],
                          extras={'pavilion': pavilion, 'end_pavilion': end_pavilion,
                                  'centre_h': centre_h,
                                  'centre_x': x0 + (wid - pavilion) // 2})
    return structure, (x0, x1, z0, z1, rng, 'mansard')


def slope_terrace(wid: int, dep: int, storey_count: int, seed: int = 1900,
                  drop: int = 6, segments: int = 0) -> tuple:
    """A street running downhill: the terrace steps down in bays.

    The source slope build drops about six blocks over its length. The step is the whole
    point of the form — a slope terrace that records a drop and then builds one level
    slab is just a street house — so the frontage is split into segments and each one
    starts lower than the one before it.

    Segments are sized at about eight cells because that is the narrowest frontage that
    can still carry both a shop and an entrance; splitting a frontage into four-cell
    pieces gives every segment a door and no shopfront at all.
    """
    rng = random.Random(seed)
    x0, z0 = 6, 6
    z1 = z0 + dep - 1
    if segments <= 0:
        segments = max(2, min(4, round(wid / 9)))
    seg_w = max(6, wid // segments)
    walls: List[Wall] = []
    footprint = []
    all_levels = []
    top = 1
    x = x0
    for index in range(segments):
        width = seg_w if index < segments - 1 else max(3, x0 + wid - x)
        if width < 3:
            break
        seg_x1 = x + width - 1
        levels, seg_top = storeys(storey_count, rng, True)
        fall = (drop * index) // max(1, segments - 1)
        # Every segment carries the same section, shifted down by its place on the hill.
        levels = [Level(l.name, max(1, l.y - fall), l.height) for l in levels]
        seg_top = max(l.y + l.height for l in levels) - 1
        walls.append(Wall('street_%d' % index, PRIMARY, x, z0, (1, 0), width, seg_top, NORTH, levels=levels))
        walls.append(Wall('rear_%d' % index, BLIND, x, z1, (1, 0), width, seg_top, SOUTH, levels=levels))
        # The step between two segments is a real party wall, so it carries nothing.
        walls.append(Wall('step_%d' % index, PARTY, seg_x1, z0, (0, 1), dep, seg_top, EAST))
        if index == 0:
            walls.append(Wall('party_west', PARTY, x, z0, (0, 1), dep, seg_top, WEST))
        for xx in range(x, seg_x1 + 1):
            for zz in range(z0, z1 + 1):
                footprint.append((xx, zz))
        all_levels.extend(levels)
        top = max(top, seg_top)
        x = seg_x1 + 1
    footprint = sorted(set(footprint))
    structure = Structure('slope_terrace', wid, dep, top, all_levels, walls, footprint,
                          notes=['steps down %d blocks across %d of frontage in %d segments'
                                 % (drop, wid, segments)],
                          extras={'drop': drop, 'segments': segments})
    return structure, (x0, x - 1, z0, z1, rng, 'mansard')


def street_row(wid: int, dep: int, storey_count: int, seed: int = 1900,
               plot: int = 0, segments: int = 0) -> tuple:
    """A continuous street wall: several houses sharing party walls.

    This is the form the reference street wall actually is, and the reason comparing one
    detached house against it was misleading: a Paris street is not a row of separate
    buildings, it is one wall of neighbouring houses with a shared party wall between
    each pair and a different height, section and bay rhythm on every plot.

    Each plot is generated from its own derived seed, so the run is varied but entirely
    reproducible from the row's seed.
    """
    rng = random.Random(seed)
    x0, z0 = 6, 6
    z1 = z0 + dep - 1
    if segments <= 0:
        # Ordinary plot widths measured in the sources are 8..14, median about 11.
        segments = max(2, round(wid / 11.0))
    if plot <= 0:
        plot = max(8, wid // segments)
    walls: List[Wall] = []
    footprint = []
    all_levels: List[Level] = []
    top = 1
    x = x0
    index = 0
    plots = []
    while x < x0 + wid - 3:
        width = plot if x + plot <= x0 + wid else max(4, x0 + wid - x)
        if width < 4:
            break
        plot_seed = seed * 131 + index * 17
        plot_rng = random.Random(plot_seed)
        # Each plot gets its own section: the reference has houses of five, six and
        # seven storeys side by side, and that variation is most of what a street is.
        count = storey_count + plot_rng.choice([-1, 0, 0, 1])
        levels, seg_top = storeys(max(4, count), plot_rng, plot_rng.random() < 0.5)
        seg_x1 = x + width - 1
        walls.append(Wall('street_%d' % index, PRIMARY, x, z0, (1, 0), width, seg_top, NORTH, levels=levels))
        walls.append(Wall('rear_%d' % index, BLIND, x, z1, (1, 0), width, seg_top, SOUTH, levels=levels))
        # The party wall between two plots belongs to the run, not to either house.
        walls.append(Wall('party_%d' % index, PARTY, seg_x1, z0, (0, 1), dep, seg_top, EAST))
        for xx in range(x, seg_x1 + 1):
            for zz in range(z0, z1 + 1):
                footprint.append((xx, zz))
        all_levels.extend(levels)
        plots.append({'index': index, 'x0': x, 'x1': seg_x1, 'width': width,
                      'storeys': len(levels), 'top': seg_top})
        top = max(top, seg_top)
        x = seg_x1 + 1
        index += 1
    walls.append(Wall('party_west', PARTY, x0, z0, (0, 1), dep, top, WEST))
    footprint = sorted(set(footprint))
    structure = Structure('street_row', wid, dep, top, all_levels, walls, footprint,
                          notes=['%d plots sharing party walls' % len(plots),
                                 'plot widths %s' % [p['width'] for p in plots]],
                          extras={'plots': plots, 'plot_count': len(plots)})
    return structure, (x0, x - 1, z0, z1, rng, 'mansard')


def corner_house(wid: int, dep: int, storey_count: int, seed: int = 1900,
                 entresol: Optional[bool] = None, roof: str = 'mansard') -> tuple:
    """An immeuble d'angle: two adjacent street faces meeting at the corner.

    Street A runs along the north face and street B along the east face; the west and
    south faces belong to the neighbouring plots, so they are party walls and carry no
    openings at all. A continuous street wall cannot express this plot: its two street
    faces are opposite each other, not adjacent.
    """
    rng = random.Random(seed)
    if entresol is None:
        entresol = rng.random() < 0.5
    levels, top = storeys(storey_count, rng, entresol)
    x0, x1, z0 = 6, 6 + wid - 1, 6
    z1 = z0 + dep - 1
    walls = [
        Wall('street_north', PRIMARY, x0, z0, (1, 0), wid, top, NORTH),
        Wall('street_east', PRIMARY, x1, z0, (0, 1), dep, top, EAST),
        Wall('party_west', PARTY, x0, z0, (0, 1), dep, top, WEST),
        Wall('party_south', PARTY, x0, z1, (1, 0), wid, top, SOUTH),
    ]
    footprint = [(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)]
    structure = Structure('corner_house', wid, dep, top, levels, walls, footprint,
                          notes=['two adjacent street faces; the other two walls are party walls'])
    return structure, (x0, x1, z0, z1, rng, roof)


#: The structure database: name -> builder. Adding a form here is all the facade and
#: technique layers need in order to work on it, which is the point of the separation.
FORMS = {
    'street_house': street_house,
    'corner_house': corner_house,
    'street_row': street_row,
    'apartment_block': apartment_block,
    'court_palace': court_palace,
    'civic_hall': civic_hall,
    'slope_terrace': slope_terrace,
}


def build(form: str, wid: int, dep: int, storey_count: int, seed: int = 1900, **kwargs):
    """Build one structure by name, returning (structure, context).

    The context carries what the assembly needs but the structure does not model: the
    bounding box, the seeded RNG, and the roof style.
    """
    if form not in FORMS:
        raise KeyError('unknown form %r; known: %s' % (form, ', '.join(sorted(FORMS))))
    return FORMS[form](wid, dep, storey_count, seed, **kwargs)


def catalogue() -> dict:
    """What the structure database currently contains, for reports and tests."""
    return {
        'forms': sorted(FORMS),
        'measurements_from_sources': {
            'street_house_frontage': [8, 14],
            'street_house_depth': [20, 35],
            'slope_drop': 6,
            'source_storey_heights': [3, 4],
            'source_ground_heights': [5, 6],
        },
        'source': 'knowledge/city/measured_source_parcels.json (14 measured builds)',
        'separation': 'massing only; facade composition and block technique live elsewhere',
    }
