"""City layer: streets and parcels that assemble into a Paris street wall.

The generator could only ever produce one detached apartment block of one form,
which is why whole source builds (continuous street walls, corner blocks, civic
buildings) could not be reproduced at all. This module adds the missing context
layer: it decides streets and parcels, then assembles each parcel's building so
that neighbours share party walls, exactly as the sources do.

Division of labour, matching the project's G3 separation:

  * this module  — where the street runs, how wide each parcel is, what stands
                   on it, and how neighbours meet (zero of the three below);
  * structure    — the massing of one parcel's building (storeys, depth, roof);
  * facade       — how the street face is composed (bays, bands, openings);
  * technique    — which blocks and states realise a given element.

Nothing here is used by the recorded PAR-002 delivery, so that package keeps
reproducing byte for byte.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .architecture import Scene, split_state, state, transform_state

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / 'knowledge/city/paris_1900_city_v0.1.json'

# Stones by role. A Paris street wall is a limestone family with a slightly darker
# base and a lighter attic; keeping the family narrow is what makes a run of
# neighbouring houses read as one street rather than a patchwork.
STONE = 'minecraft:smooth_sandstone'
WALL_COURSE = 'minecraft:cut_sandstone'
# Mouldings and course lines have to be visibly darker than the wall behind them, or
# the elevation turns into one striped mass and the windows disappear into the
# stripes — which is exactly what the first three city renders did. Same family,
# lower value: this is the contrast the sources themselves rely on.
STONE_COURSE = 'minecraft:sandstone'
STONE_DRESSING = 'minecraft:cut_sandstone'
CORNICE = 'minecraft:polished_diorite'
PLINTH = 'minecraft:polished_andesite'
ATTIC = 'minecraft:cut_sandstone'
# Window and shopfront glazing. In the standard reference the openings are the
# *brightest* large areas of the elevation — white sashes against limestone — and the
# wall's banding is nearly absent. White glazing is therefore not decoration: it is what
# makes the facade read as windows at all. One material, measured once: separate names
# for the same block made the facade report count every window twice.
WINDOW_PANE = 'minecraft:white_stained_glass_pane'
SHOP_GLASS = WINDOW_PANE
# What is seen *through* a window. Light, because the software preview composites glass
# over what is behind it: a grey back drops the glazing to mid-grey (measured luminance
# 103) and every window then reads as a hole rather than a window.
PANE_BACKING = 'minecraft:white_concrete'
# A Paris roof is a mid-tone slate, not black. Only the ridge course is dark, and
# that single line is what makes the roof silhouette readable from the street.
ROOF = 'minecraft:deepslate_tiles'
ROOF_RIDGE = 'minecraft:polished_deepslate'
ROOF_DORMER = 'minecraft:light_gray_concrete'
IRON = 'minecraft:iron_bars'
FLOOR_PLATE = 'minecraft:spruce_planks'
GLASS = 'minecraft:glass_pane'
# How many cells of wall an opening cuts through. Everything odd about the first city
# renders came from this being effectively one: an opening needs to be deeper than the
# decorations placed inside it, or each write overwrites the previous one.
REVEAL_DEPTH = 4
SHOP_DEPTH = 5


def spec():
    return json.loads(SPEC_PATH.read_text(encoding='utf-8'))


def ranges(key):
    return spec()['parcel'][key]


def _runs_of(flags):
    out, start = [], None
    for index, value in enumerate(flags):
        if value and start is None:
            start = index
        elif not value and start is not None:
            out.append((start, index - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def facade_report(city, side, min_glazing_share=0.10):
    """Score one row's street face, from the voxels rather than from a render.

    A render cannot tell "the windows are too dark" from "the windows were never
    written", and this project spent four iterations on that confusion. Everything here
    is read off the plane the street actually sees: `z = the parcel's facade line`.

    Each parcel is measured only up to its own cornice — scanning the row's tallest
    height would count the sky above a shorter neighbour as a hole in its wall.
    """
    parcels = [p for p in city.parcels if p.side == side]
    if not parcels:
        return {'side': side, 'verdict': 'FAIL', 'reason': 'no parcels'}
    palette, volume = city.scene.palette, city.scene.volume
    z0 = city.facade_line(parcels[0])
    height_of = {}
    for parcel in parcels:
        for x in range(parcel.front_x, parcel.front_x + parcel.frontage):
            height_of[x] = parcel.top_y
    top = max(height_of.values())
    left = min(height_of)
    right = max(height_of)
    counts = Counter()
    columns = []
    for x in range(left, right + 1):
        column_glazed = False
        for y in range(1, height_of[x] + 1):
            name, _ = split_state(palette[int(volume[y, z0, x])])
            counts[name] += 1
            column_glazed = column_glazed or name in (WINDOW_PANE, SHOP_GLASS)
        columns.append(column_glazed)
    cells = sum(counts.values())
    glazing = counts[WINDOW_PANE] + (counts[SHOP_GLASS] if SHOP_GLASS != WINDOW_PANE else 0)
    groups = _runs_of(columns)
    widths = [b - a + 1 for a, b in groups]
    piers = [groups[i + 1][0] - groups[i][1] - 1 for i in range(len(groups) - 1)]
    air = counts['minecraft:air']
    doors = sum(count for name, count in counts.items() if 'door' in name)
    share = glazing / cells if cells else 0.0
    passed = bool(glazing) and share >= min_glazing_share and air == 0
    return {
        'side': side, 'facade_plane_z': z0, 'parcels': len(parcels), 'cells': cells,
        'glazing_cells': glazing, 'glazing_share': share,
        'window_cells': counts[WINDOW_PANE] + (counts[SHOP_GLASS] if SHOP_GLASS != WINDOW_PANE else 0),
        'window_groups': len(groups), 'group_widths': widths, 'pier_widths': piers,
        'glazed_columns': int(sum(columns)), 'columns': len(columns),
        'door_cells': doors, 'open_cells': air,
        'min_glazing_share': min_glazing_share,
        'verdict': 'PASS' if passed else 'FAIL',
    }


@dataclass
class Parcel:
    """One plot: what the city layer hands to the structure layer."""
    parcel_id: str
    unit_no: int
    front_x: int
    frontage: int
    depth: int
    side: str
    role: str = 'street_wall'
    corner: bool = False
    storeys: int = 6
    shop_bays: int = 0
    entrance_bay: int = 1
    top_y: int = 0


@dataclass
class Building:
    parcel: Parcel
    parts: list = field(default_factory=list)


class StreetCity:
    """A street with two parcel rows, assembled into one shared Scene.

    One Scene (not one file per house) is the point: Paris street walls share party
    walls, so the wall between two neighbouring parcels belongs to the street, not to
    either house.
    """

    def __init__(self, seed: int, street_length: int = 210, street_width: int = 16,
                 sidewalk: int = 3):
        self.spec = spec()
        self.rng = random.Random(seed)
        self.seed = seed
        self.street_length = street_length
        self.street_width = street_width
        self.sidewalk = sidewalk
        # Extent: two parcel rows fronting the street, plus the street itself, plus
        # a margin of open ground so the preview camera has room.
        self.depth_rows = 30
        self.width = street_length + 20
        self.depth = self.street_width + 2 * (self.sidewalk + self.depth_rows) + 24
        self.height = 48
        self.scene = Scene(self.width, self.height, self.depth)
        # z of the north row's facade line and of the south row's facade line.
        self.north_face_z = (self.depth - self.street_width) // 2 + self.sidewalk
        self.south_face_z = self.north_face_z + self.street_width
        self.parcels: list[Parcel] = []
        self.buildings: list[Building] = []
        self.street_blocks: list[dict] = []

    # --- geometry helpers -------------------------------------------------
    def put(self, x, y, z, value, owner='city'):
        if 0 <= y < self.scene.volume.shape[0] and 0 <= z < self.scene.volume.shape[1] \
                and 0 <= x < self.scene.volume.shape[2]:
            self.scene.put(x, y, z, value, owner)
            return True
        return False

    def box(self, x0, y0, z0, x1, y1, z1, value, owner='city'):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                for x in range(x0, x1 + 1):
                    self.put(x, y, z, value, owner)

    def ground(self):
        """Pavement and roadway, so the street reads as a street."""
        x0, x1 = 4, self.width - 5
        self.box(x0, 0, 4, x1, 0, self.depth - 5, 'minecraft:smooth_stone', 'pavement')
        road_z0 = self.north_face_z + self.sidewalk
        road_z1 = road_z0 + self.street_width - 1
        self.box(x0, 0, road_z0, x1, 0, road_z1, 'minecraft:gray_concrete', 'road')
        # Kerbs and a sparse tree line, which is what makes a boulevard readable.
        for z in (road_z0 - 1, road_z1 + 1):
            for x in range(x0, x1 + 1):
                self.put(x, 0, z, 'minecraft:stone_bricks', 'kerb')
        for x in range(x0 + 6, x1 - 6, 26):
            for z in (road_z0 - 2, road_z1 + 2):
                self.put(x, 1, z, 'minecraft:oak_log[axis=y]', 'tree')
                self.put(x, 2, z, 'minecraft:oak_log[axis=y]', 'tree')
                self.box(x - 2, 3, z - 2, x + 2, 4, z + 2, 'minecraft:oak_leaves', 'tree')

    # --- parcels ----------------------------------------------------------
    def subdivide(self, side):
        """Cut one side of the street into parcels of the measured frontage range."""
        lo, hi = ranges('frontage_width')
        corner_lo, corner_hi = ranges('corner_frontage')
        x = 10
        limit = self.width - 10
        index = 0
        while x + lo < limit:
            corner = (side == 'north' and index == 0) or (side == 'south' and index == 0)
            if corner:
                frontage = self.rng.randint(corner_lo, corner_hi)
            else:
                frontage = self.rng.randint(lo, hi)
            if x + frontage >= limit:
                break
            depth = self.rng.randint(*ranges('depth'))
            storeys = self.rng.choice([6, 6, 6, 7, 7])
            parcel = Parcel(parcel_id='%s-%02d' % (side, index + 1), unit_no=index + 1,
                            front_x=x, frontage=frontage, depth=depth, side=side,
                            corner=corner, storeys=storeys)
            # Ground-floor run-in: a Paris street wall carries shops along most of
            # its length, with one bay given to the entrance. The bay count has to be
            # derived from the frontage at the same pitch the elevation uses, or the
            # shops stop lining up with the windows above them.
            parcel.entrance_bay = 0
            parcel.shop_bays = max(1, frontage // 4)
            self.parcels.append(parcel)
            x += frontage
            index += 1
        return index

    def facade_line(self, parcel):
        return self.north_face_z if parcel.side == 'north' else self.south_face_z

    def depth_direction(self, parcel):
        return -1 if parcel.side == 'north' else 1

    # --- structure layer: one parcel's massing ---------------------------
    def build_parcel(self, parcel: Parcel):
        parts = []
        z0 = self.facade_line(parcel)
        dz = self.depth_direction(parcel)
        x0, x1 = parcel.front_x, parcel.front_x + parcel.frontage - 1
        storey_h = self.rng.choice(self.spec['height']['storey_height'])
        ground_h = self.rng.choice(self.spec['height']['ground_floor_height'])
        entresol = self.rng.random() < 0.5
        levels = [('ground', 1, ground_h)]
        y = 1 + ground_h
        if entresol:
            levels.append(('entresol', y, 2))
            y += 2
        body = parcel.storeys - len(levels) + 1
        for index in range(max(2, body)):
            levels.append(('body', y, storey_h))
            y += storey_h
        top = y
        # Attic setback: the last level pulls back, as the sources show.
        attic_h = storey_h
        levels = levels[:-1] + [('attic', levels[-1][1], attic_h)]
        top = levels[-1][1] + attic_h
        parcel.storeys = len(levels)
        parcel.top_y = top
        # Walls: front face, party walls on both parcel edges, back face. The street
        # wall is built a full REVEAL_DEPTH thick *before* anything is cut into it:
        # with a one-cell wall, the recessed glazing lands one cell outside the wall
        # in the open street and the white backing block then overwrites it — which is
        # why the first four city renders showed a facade with no visible windows.
        side_walls = [x0, x1]
        for x in side_walls:
            for zz in range(0, parcel.depth + 1):
                z = z0 + dz * zz
                for yy in range(1, top + 1):
                    self.put(x, yy, z, STONE if yy % 7 else STONE_DRESSING, 'party')
        for x in range(x0, x1 + 1):
            for yy in range(1, top + 1):
                for d in range(REVEAL_DEPTH + 1):
                    # Faint coursing only: a strong course colour here competes with the
                    # windows and the elevation stops reading as a facade at all.
                    self.put(x, yy, z0 + dz * d, WALL_COURSE if yy % 6 == 0 else STONE, 'front-wall')
        # Back wall.
        back_z = z0 + dz * parcel.depth
        for x in range(x0, x1 + 1):
            for yy in range(1, top + 1):
                self.put(x, yy, back_z, STONE if yy % 3 else STONE_DRESSING, 'back')
        # Floor plates. The roof is *not* built here: one parcel cannot know where
        # its neighbours end, and per-parcel roofs were the sawtooth that ruined the
        # first two city renders. It is built once per row in continuous_roof().
        for _name, y0, _h in levels:
            for x in range(x0, x1 + 1):
                for zz in range(0, parcel.depth + 1):
                    self.put(x, y0, z0 + dz * zz, FLOOR_PLATE, 'plate')
        parts.append({'stage': 'massing', 'frontage': parcel.frontage, 'depth': parcel.depth,
                      'levels': [{'name': n, 'y': yv, 'h': h} for n, yv, h in levels],
                      'top_y': top, 'entresol': entresol})
        return levels, top

    def continuous_roof(self, side, tops):
        """One mansard for the whole row, stepped only at party walls.

        The sources are explicit about this: a street wall carries a single roof
        rhythm with party walls and chimneys breaking it, never one little roof per
        house. Each step is the roof profile of one parcel, cut at a common depth so
        neighbouring profiles line up; the chord between two different tops is
        closed by the party wall, which is what a real party wall does.
        """
        parcels = [p for p in self.parcels if p.side == side]
        if not parcels:
            return
        dz = self.depth_direction(parcels[0])
        z0 = self.facade_line(parcels[0])
        # Every roof on the row stops at the shallowest plot, so the profiles share
        # one back edge instead of stepping in and out.
        depth = min(p.depth for p in parcels) - 1
        for parcel in parcels:
            x0 = parcel.front_x
            x1 = parcel.front_x + parcel.frontage - 1
            _levels, top = tops[parcel.parcel_id]
            # The slope: it pulls back a course at a time, which is what makes a mansard
            # a steep cone rather than a flat cap. Four courses over a plot 20+ deep is
            # about the proportion the reference shows.
            for step in range(4):
                y = top + 1 + step
                inset = step
                for x in range(x0, x1 + 1):
                    for zz in range(2 + inset, depth - inset):
                        self.put(x, y, z0 + dz * zz, ROOF, 'roof')
            # Ridge course, one line of darker slate at the top of the slope: this is
            # what gives the roof its silhouette from the street.
            for x in range(x0, x1 + 1):
                for zz in range(5, depth - 4):
                    self.put(x, top + 4, z0 + dz * zz, ROOF_RIDGE, 'roof-ridge')
            # Dormers in the lower slope at the bay rhythm. A mansard without dormers is
            # a box with a lid, and the reference has one over almost every bay.
            bay = max(3, parcel.frontage // 3)
            for centre in range(x0 + 1, x1 - 2, bay):
                for x in range(centre, min(centre + 2, x1 + 1)):
                    for step in (1, 2):
                        self.put(x, top + step, z0 + dz * (2 - step), ROOF_DORMER, 'dormer')
                    self.put(x, top + 1, z0 + dz * 2, PANE_BACKING, 'dormer-glass')
                    self.put(x, top + 2, z0 + dz, PANE_BACKING, 'dormer-glass')
            # A chimney rising out of the ridge, offset from the party wall as the
            # sources show, so the roofline is never a bare line.
            stack = x0 + max(2, parcel.frontage // 2)
            for x in range(stack, min(stack + 2, x1 + 1)):
                for y in range(top + 3, top + 8):
                    for zz in (4, 5):
                        self.put(x, y, z0 + dz * zz, STONE_COURSE, 'chimney-stack')
                for zz in (3, 4, 5, 6):
                    self.put(x, top + 8, z0 + dz * zz, STONE_COURSE, 'chimney-cap')

    # --- facade layer: the street face -----------------------------------
    def outward(self, parcel):
        return -1 if parcel.side == 'north' else 1

    def cut_opening(self, x_left, y_lo, y_hi, z0, oz, depth, pane, jamb_depth=1, width=3):
        """Cut a window or shopfront into the street wall and glaze it.

        The write order is the whole lesson of the first four city renders:

          * the glazing goes on the plane the street actually sees (`z0`), or an
            unbroken stone face hides it and the window disappears;
          * it fills *every* cell of that plane, or the unglazed cells show the
            backing and the window reads as a grey patch instead of a white one;
          * the backing sits immediately behind the pane rather than several cells
            back, because a deep dark void reads as a hole, which is what made the
            fifth render look like a black grid.
        """
        for x in range(x_left, x_left + width):
            for y in range(y_lo, y_hi):
                for d in range(0, depth + 1):
                    self.put(x, y, z0 + oz * d, pane, 'glazing')
                for d in range(jamb_depth, depth + 1):
                    self.put(x, y, z0 + oz * d, PANE_BACKING, 'reveal')

    def build_facade(self, parcel: Parcel, levels, top):
        z0 = self.facade_line(parcel)
        oz = self.outward(parcel)
        x0 = parcel.front_x
        frontage = parcel.frontage
        # Bay rhythm. This is the single strongest signal of a Paris street wall: bays
        # on a regular pitch with a narrow stone pier between them. The reference shows
        # piers about half a window wide, so the opening is three cells and the pier
        # one to two — an earlier version used two-cell openings on an eleven-cell pitch
        # and the elevation read as a striped wall with slots in it.
        pitch = self.rng.choice([4, 5])
        win_w = 2
        number = max(1, (frontage - 2) // pitch)
        edge = frontage - 2 - (number - 1) * pitch
        first = x0 + 1 + edge // 2
        centres = [first + i * pitch for i in range(number)]
        openings = []
        # Ground floor first, so the decoration pass knows where the door is.
        ground_name, gy, gh = levels[0]
        door_x = x0 + 1
        for bi, centre in enumerate(centres):
            left = centre - win_w // 2
            is_entry = bi == 0
            if is_entry:
                # The entrance occupies two bays' worth of width in the sources: a
                # single window-wide door leaf reads as a shop, not a front door.
                door_x = left
                leaf_w = min(2, win_w)
                self.cut_opening(left, gy + 1, gy + gh, z0, oz, SHOP_DEPTH,
                                 PANE_BACKING, jamb_depth=3, width=leaf_w)
                for x in range(left - 1, left + leaf_w + 1):
                    self.put(x, gy + gh, z0, STONE_DRESSING, 'sign-band')
                facing = 'south' if parcel.side == 'north' else 'north'
                for offset, hinge in ((0, 'left'), (1, 'right')):
                    for half, dy in (('lower', 0), ('upper', 1)):
                        self.put(left + offset, gy + 1 + dy, z0,
                                 'minecraft:dark_oak_door[facing=%s,half=%s,hinge=%s,open=false,powered=false]'
                                 % (facing, half, hinge), 'door')
                # Fanlight over the leaf: the tall ground floor of the sources carries a
                # glazed transom, not extra door.
                for x in range(left, left + leaf_w):
                    for dy in range(3, gh):
                        self.put(x, gy + 1 + dy, z0, WINDOW_PANE, 'transom')
                continue
            # Shopfront: glazed flush with the face so it reads from the street, and
            # deep enough behind to hold its own shadow.
            self.cut_opening(left, gy + 1, gy + gh, z0, oz, SHOP_DEPTH, SHOP_GLASS,
                             jamb_depth=3, width=win_w)
            for x in range(left - 1, left + win_w + 1):
                self.put(x, gy + gh, z0, STONE_DRESSING, 'sign-band')
        # Upper storeys. The reference gives the openings most of the wall: tall windows
        # on a narrow pier, a sill under them and a tiny cornice over them, and almost
        # no continuous banding. Continuous string courses were the mistake that made
        # three city renders look like a striped mattress.
        for name, y0, height in levels[1:]:
            wh = max(3, height - 2)
            lo = y0 + 1
            for bi, centre in enumerate(centres):
                left = centre - win_w // 2
                self.cut_opening(left, lo, lo + wh, z0, oz, REVEAL_DEPTH, WINDOW_PANE,
                                 width=win_w)
                for x in range(left - 1, left + win_w + 1):
                    self.put(x, lo - 1, z0, STONE_DRESSING, 'sill')
                    self.put(x, lo + wh, z0, STONE_DRESSING, 'lintel')
                    self.put(x, lo + wh, z0 + oz, STONE_DRESSING, 'lintel-soffit')
                if name in ('body', 'attic'):
                    for x in range(left - 1, left + win_w + 1):
                        self.put(x, lo - 1, z0 + oz, IRON, 'guard-rail')
                openings.append({'unit': parcel.unit_no, 'centre': centre, 'level': name,
                                 'bottom': lo, 'height': wh, 'width': win_w})
        # Course lines between storeys tie the run together, as the sources do.
        for name, y0, _height in levels[1:]:
            for x in range(x0, x0 + frontage):
                self.put(x, y0, z0, STONE_DRESSING if (y0 % 7) else STONE, 'storey-line')
        # A narrow recessed joint at the party wall separates two houses that share
        # it: the sources never let neighbours read as one blank mass.
        for edge in (x0, x0 + frontage - 1):
            for y in range(2, top + 2):
                for dz in range(0, 2):
                    self.put(edge, y, z0 + oz * dz, 'minecraft:air' if dz else STONE_DRESSING, 'party-joint')
        for y in range(1, top + 2):
            self.put(x0, y, z0 + oz, STONE_DRESSING, 'party-joint')
            self.put(x0 + frontage - 1, y, z0 + oz, STONE_DRESSING, 'party-joint')
        # Plinth course, the run's cornice, and a drip above it.
        for x in range(x0, x0 + frontage):
            self.put(x, 1, z0, PLINTH, 'plinth')
            self.put(x, top, z0, CORNICE, 'cornice')
            self.put(x, top + 1, z0, STONE_DRESSING, 'cornice-drip')
        return openings, door_x

    def assemble(self):
        self.ground()
        for side in ('north', 'south'):
            self.subdivide(side)
        # One pass for massing, then one for street faces, then one continuous roof
        # per row: the facade pass needs every parcel to exist so doors, rails and
        # cornices land on finished walls, and the roof pass needs every parcel's top.
        tops = {}
        for parcel in self.parcels:
            levels, top = self.build_parcel(parcel)
            tops[parcel.parcel_id] = (levels, top)
        for parcel in self.parcels:
            levels, top = tops[parcel.parcel_id]
            openings, door_x = self.build_facade(parcel, levels, top)
            self.buildings.append(Building(parcel=parcel,
                                           parts=[{'parcel': asdict(parcel), 'openings': len(openings),
                                                   'door_x': door_x}]))
            self.street_blocks.append({'unit': parcel.unit_no, 'side': parcel.side,
                                       'frontage': parcel.frontage, 'depth': parcel.depth,
                                       'storeys': parcel.storeys, 'corner': parcel.corner,
                                       'openings': len(openings), 'top_y': top,
                                       'levels': [n for n, _y, _h in levels]})
        for side in ('north', 'south'):
            self.continuous_roof(side, tops)
        return self.scene

    def manifest(self):
        return {'city_spec': self.spec['spec_id'], 'seed': self.seed,
                'street_length': self.street_length, 'street_width': self.street_width,
                'sidewalk': self.sidewalk, 'parcels': len(self.parcels),
                'blocks': self.street_blocks,
                'frontage_total_north': sum(p.frontage for p in self.parcels if p.side == 'north'),
                'frontage_total_south': sum(p.frontage for p in self.parcels if p.side == 'south'),
                'note': 'City layer output: parcels and one shared street wall per side. '
                        'Structure, facade and technique layers are selected from these parcels.'}
