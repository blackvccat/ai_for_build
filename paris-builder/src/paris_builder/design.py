"""Assemble one house: structure + facade + technique, in that order.

The three layers are separate databases (`house.py`, `facade.py`, `technique.py`) and
this module is the only place that knows about all three. That separation is the point:
the same facade scheme must work on any form, which is what makes it a *style* rather
than one building's appearance.

Assembly order matters and is what the city layer got wrong at first:

  1. structure raises the walls, floor plates and roof;
  2. facade composes openings and cuts them into the wall — into the wall, never into
     the street, because the street wall has to be thick enough to contain its own
     reveal or each later write erases the one before it;
  3. technique dresses what is now there: surrounds, bands, rails, shopfronts.

Nothing here is used by the recorded PAR-002 delivery, so that package keeps
reproducing byte for byte.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from . import facade as facade_layer
from . import house as structure_layer
from . import technique as technique_layer
from .architecture import Scene, planar_connection
from .house import (Level, Structure, Wall, PRIMARY, SECONDARY, COURTYARD, PANE_BACKING,
                    PARTY, BLIND, FLOOR_PLATE, PLINTH, ROOF, ROOF_DORMER, ROOF_RIDGE,
                    STONE, STONE_COURSE, STONE_DRESSING, WINDOW_PANE, WALL_DEPTH)

#: Facade schemes that suit each form. This is a default, not a constraint: any scheme
#: can be asked for on any form, and the orthogonality test does exactly that.
DEFAULT_SCHEME = {
    'street_house': 'haussmann_apartment',
    'corner_house': 'haussmann_apartment',
    'street_row': 'haussmann_apartment',
    'apartment_block': 'haussmann_apartment',
    'court_palace': 'palace_front',
    'civic_hall': 'civic_colonnade',
    'slope_terrace': 'shop_terrace',
}

#: The block a door faces, by the wall's outward normal. A door's `facing` must point
#: out of the building or it renders inside out.
FACING = {(0, -1): 'north', (0, 1): 'south', (-1, 0): 'west', (1, 0): 'east'}

#: Which techniques each refinement tier is allowed to apply. Geometry is never gated by
#: the tier — a tier is how much of the design is built out, not how much building
#: exists — so tier 1 already carries the crown that makes the silhouette read.
TECHNIQUES_BY_TIER = {
    0: (),
    1: ('cornice', 'window_surround'),
    2: ('cornice', 'window_surround', 'string_course', 'door_leaf', 'shopfront'),
    3: ('cornice', 'window_surround', 'string_course', 'door_leaf', 'shopfront',
        'guard_rail', 'rustication', 'quoins', 'pilaster', 'cresting'),
}


@dataclass
class HousePlan:
    """A complete, reproducible house design: the three layers plus their seeds."""
    form: str
    scheme: str
    width: int
    depth: int
    storeys: int
    seed: int
    structure_seed: int = 0
    bay_pitch: int | None = None
    entrance_fraction: float | None = None
    roof_height: int | None = None
    detail_profile: str | None = None
    #: Pan coupé: how many cells of the corner are cut back. This is geometry the operator
    #: can ask for and the planning model should be able to choose, so it is a first-class
    #: field instead of a constant buried inside one profile implementation.
    chamfer: int | None = None

    def describe(self) -> dict:
        result = {'form': self.form, 'facade': self.scheme, 'width': self.width,
                  'depth': self.depth, 'storeys': self.storeys, 'seed': self.seed}
        result.update({k: getattr(self, k) for k in ('bay_pitch', 'entrance_fraction', 'roof_height',
                                                     'detail_profile', 'chamfer')
                       if getattr(self, k) is not None})
        return result


def _scene_for(structure: Structure, margin: int = 8) -> Scene:
    """A scene big enough for the form, its roof and its chimneys."""
    wid = max(x for x, _z in structure.footprint) + margin
    dep = max(z for _x, z in structure.footprint) + margin
    scenes_dep = dep + 2
    height = structure.top + 10
    return Scene(wid + 2, height, scenes_dep + 2)


def _raise_walls(scene: Scene, structure: Structure, roof_height=None) -> None:
    """The structure layer's own work: walls, floor plates, roof."""
    for wall in structure.walls:
        for u in range(wall.length):
            for d in range(wall.depth + 1):
                x, _y, z = wall.point(u, 0, d)
                for y in range(1, wall.height + 1):
                    # Faint coursing only: a strong course colour competes with the
                    # windows and the elevation stops reading as a facade.
                    scene.put(x, y, z, STONE_COURSE if y % 6 == 0 else STONE, 'wall')
    for level in structure.levels:
        for (x, z) in structure.footprint:
            if scene.volume[level.y, z, x] == 0:
                scene.put(x, level.y, z, FLOOR_PLATE, 'plate')
    _roof(scene, structure, roof_height)


def _roof(scene: Scene, structure: Structure, roof_height=None) -> None:
    """A mansard over the built footprint, with dormers and chimneys.

    The number of courses is a proportion, not a taste: on the reference the roof takes
    about a seventh of the whole elevation, which on a 47-block house is six to seven
    cells. A four-course roof reads as a lid and the building loses its Paris profile.
    """
    cells = structure.footprint
    x0 = min(x for x, _z in cells)
    x1 = max(x for x, _z in cells)
    z0 = min(z for _x, z in cells)
    z1 = max(z for _x, z in cells)
    top = structure.top
    width = x1 - x0
    depth = z1 - z0
    # A mansard is a *two-stage* profile: a steep lower slope carrying the dormers, a
    # knee, then a shallow slope covering the ridge. It is also *shorter in plan* than a
    # stepped pyramid — the lower slope is steep precisely so the roof does not have to
    # walk a long way in — and a roof that eats half the wall area stops being a roof and
    # becomes the building, which is what the first renders of this design showed.
    lower = 3
    upper = (roof_height - lower) if roof_height is not None else 2
    for step in range(lower):
        inset = step
        for (x, z) in cells:
            if x0 + inset <= x <= x1 - inset and z0 + inset <= z <= z1 - inset:
                scene.put(x, top + 1 + step, z, ROOF, 'roof')
    for step in range(upper):
        inset = 3 + step if roof_height is None else min(3 + min(step, 1), max(1, min(width, depth) // 2 - 1))
        for (x, z) in cells:
            if x0 + inset <= x <= x1 - inset and z0 + inset <= z <= z1 - inset:
                scene.put(x, top + 1 + lower + step, z, ROOF, 'roof')
    if structure.form == 'street_house':
        # The shared side walls rise above the roof to separate adjacent plots.
        for x in (x0, x1):
            for z in range(z0, z1 + 1):
                scene.put(x, top + 2, z, STONE_DRESSING, 'party-parapet')
                scene.put(x, top + 3, z, STONE_DRESSING, 'party-parapet')
    # Ridge: the flat top of the upper slope, one course of darker slate.
    for (x, z) in cells:
        inset = 3 + upper if roof_height is None else min(5, max(1, min(width, depth) // 2 - 1))
        if x0 + inset <= x <= x1 - inset and z0 + inset <= z <= z1 - inset:
            scene.put(x, top + lower + upper, z, ROOF_RIDGE, 'roof-ridge')
    # Dormers sit in the lower slope, where they can be seen from the street, and each
    # one is a lit window: a mansard without glazed dormers is a roof with bumps on it.
    # The reference puts one over almost every bay, with a dressed head.
    span = max(3, width // 5)
    for x in range(x0 + 1, x1 - 1, span):
        for dx in (0, 1):
            xx = x + dx
            if xx >= x1 or xx <= x0:
                continue
            for z, inward in ((z0 + 2, 1), (z1 - 2, -1)):
                for step in (1, 2):
                    scene.put(xx, top + step, z, ROOF_DORMER, 'dormer')
                    scene.put(xx, top + step, z + inward, WINDOW_PANE, 'dormer-glass')
                scene.put(xx, top + 3, z, STONE_DRESSING, 'dormer-head')
    # Chimneys rise out of the ridge as slim flues: one cell square with a slightly wider
    # cap, which is what the reference stacks are. A two-by-three block of stone is a
    # tower, and the first axonometric render of this design had exactly that. They are
    # kept short as well — a chimney taller than the roof it stands on dominates the
    # silhouette and the building stops reading as a Paris house.
    positions = [x0 + int(width * f) for f in (0.18, 0.42, 0.66, 0.86)]
    for cx in positions:
        if not (x0 + 1 < cx < x1 - 1):
            continue
        for y in range(top + 2, top + 5):
            for z in (z0 + 4, z1 - 5):
                scene.put(cx, y, z, STONE_COURSE, 'chimney')
        for z in range(z0 + 3, z0 + 6):
            scene.put(cx, top + 5, z, STONE_DRESSING, 'chimney-cap')
        for z in range(z1 - 6, z1 - 2):
            scene.put(cx, top + 5, z, STONE_DRESSING, 'chimney-cap')


def _cut_opening(scene: Scene, wall: Wall, opening) -> None:
    """Cut one opening into the wall and glaze it one cell in.

    The glazing sits at `d = 1`, not at `d = 0`. That single cell of recess is what makes
    a window read as a window from the street: it gives the opening a jamb and a soffit
    that catch different light from the wall face. A pane flush with the wall face is a
    flat panel, which is how the first generated elevations looked.

    The cell in front of the pane is opened only over the glazed area, so the wall face
    is still solid stone around the opening and the recess has sides.
    """
    for u in range(opening.u, opening.u + opening.width):
        if not 0 <= u < wall.length:
            continue
        for y in range(opening.y, opening.y + opening.height):
            x, _yy, z = wall.point(u, y, 0)
            scene.put(x, y, z, 'minecraft:air', 'opening')
            if opening.kind == 'door':
                continue
            gx, _gy, gz = wall.point(u, y, 1)
            scene.put(gx, y, gz, planar_connection(WINDOW_PANE, wall.normal), 'glazing')
            for d in range(2, wall.depth + 1):
                bx, by, bz = wall.point(u, y, d)
                scene.put(bx, by, bz, PANE_BACKING, 'reveal')


def build(plan: HousePlan, scene: Optional[Scene] = None, tier: int = 3) -> tuple:
    """Build one house from a plan. Returns (scene, manifest).

    `tier` is the refinement level the brief requires, and it gates the technique layer
    rather than the geometry:

      1. massing and openings only — the skeleton, plus the crown that makes the
         silhouette read;
      2. adds the framing of every opening and the storey lines, so the elevation can be
         judged as a composition;
      3. adds the surface dressing and the roof furniture — the delivered level.

    Geometry is never gated by the tier. A tier is how much of the design is *built out*,
    not how much of the building exists, and gating geometry on a tier is the mistake
    that once hid the crown and cornice from the framework review.
    """
    if plan.detail_profile == 'reference_haussmann':
        from .haussmann_reference import build as build_reference
        if scene is not None:
            raise ValueError('Reference profile builds a single independent plot')
        return build_reference(plan, tier)
    structure, context = structure_layer.build(plan.form, plan.width, plan.depth,
                                               plan.storeys, plan.seed)
    x0, x1, z0, z1, rng, roof_style = context
    rng = random.Random(plan.seed * 7919 + plan.storeys)
    spec = facade_layer.scheme(plan.scheme)
    if plan.bay_pitch is not None:
        spec = replace(spec, pitch=(plan.bay_pitch,))
    if plan.entrance_fraction is not None:
        spec = replace(spec, entrance_fraction=plan.entrance_fraction)
    wanted = TECHNIQUES_BY_TIER.get(tier)
    if wanted is None:
        raise KeyError('unknown tier %r; known: %s' % (tier, sorted(TECHNIQUES_BY_TIER)))
    scene = scene if scene is not None else _scene_for(structure)
    _raise_walls(scene, structure, plan.roof_height)

    used: List[dict] = []
    wall_reports: List[dict] = []
    for wall in structure.walls:
        # A form may carry more than one section — a terrace stepped down a hill has one
        # per segment — so each wall composes only the storeys it actually rises to.
        # Handing every wall the whole level list cuts doors and windows above the roof.
        levels = wall.levels if wall.levels is not None else [
            l for l in structure.levels if l.y + l.height <= wall.height + 1]
        if not levels:
            levels = structure.levels[:1]
        openings = facade_layer.compose(wall, levels, spec, rng, wall.role)
        report = {'name': wall.name, 'role': wall.role, 'length': wall.length}
        report.update(facade_layer.rhythm_report(openings, wall.length))
        if not openings:
            wall_reports.append(report)
            continue
        for opening in openings:
            _cut_opening(scene, wall, opening)
        if tier == 0:
            wall_reports.append(report)
            continue
        # --- technique layer: dress what is now there ---
        # Order matters between techniques as well as within one: `window_surround`
        # would otherwise write a sill row straight through a shopfront's glazing, and
        # the shop would vanish from the street plane. So the technique that owns an
        # element goes first, and the generic surround only frames plain windows.
        for opening in openings:
            if opening.kind == 'shop':
                if tier >= 2 and 'shopfront' in wanted:
                    used.append(technique_layer.shopfront(scene, wall, opening).__dict__)
                else:
                    used.append(technique_layer.window_surround(scene, wall, opening).__dict__)
            elif opening.kind == 'door':
                if tier >= 2 and 'door_leaf' in wanted:
                    facing = FACING[tuple(wall.normal)]
                    used.append(technique_layer.door_leaf(scene, wall, opening, facing).__dict__)
                else:
                    used.append(technique_layer.window_surround(scene, wall, opening).__dict__)
            else:
                used.append(technique_layer.window_surround(scene, wall, opening).__dict__)
            if opening.level in spec.rails and opening.kind == 'window' \
                    and 'guard_rail' in wanted:
                used.append(technique_layer.guard_rail(scene, wall, opening).__dict__)
            elif (structure.form == 'street_house' and wall.name == 'rear'
                  and opening.kind == 'window' and 'guard_rail' in wanted):
                used.append(technique_layer.guard_rail(scene, wall, opening).__dict__)
        if 'string_course' in wanted:
            for level in levels:
                if level.name in spec.string_courses:
                    used.append(technique_layer.string_course(scene, wall, level.y).__dict__)
        if wall.role == PRIMARY:
            # Rustication stops above the shopfronts, or it would paint over them.
            if 'rustication' in wanted:
                shop_top = max((o.y + o.height for o in openings if o.kind == 'shop'),
                               default=0)
                ground = levels[0]
                low = max(1, shop_top if shop_top else 1)
                high = ground.y + ground.height - 1
                if high >= low:
                    used.append(technique_layer.rustication(scene, wall, low, high).__dict__)
            if 'quoins' in wanted:
                used.append(technique_layer.quoins(scene, wall, 1, wall.height).__dict__)
            if 'pilaster' in wanted and openings:
                first = min(o.u for o in openings)
                last = max(o.u + o.width for o in openings)
                used.append(technique_layer.pilaster(scene, wall, max(0, first - 2),
                                                     1, wall.height).__dict__)
                used.append(technique_layer.pilaster(scene, wall, min(wall.length - 1, last + 1),
                                                     1, wall.height).__dict__)
            # The crown is part of the silhouette, so it is built from tier 1 up.
            used.append(technique_layer.cornice(scene, wall, wall.height).__dict__)
            if 'cresting' in wanted:
                used.append(technique_layer.cresting(scene, wall, wall.height + 4).__dict__)
        wall_reports.append(report)

    totals: Dict[str, int] = {}
    by_wall: Dict[str, Dict[str, int]] = {}
    for entry in used:
        totals[entry['name']] = totals.get(entry['name'], 0) + entry['count']
        wall_uses = by_wall.setdefault(entry['wall'], {})
        wall_uses[entry['name']] = wall_uses.get(entry['name'], 0) + entry['count']
    manifest = {
        'plan': plan.describe(),
        'structure': structure.report(),
        'facade_scheme': spec.name,
        'walls': wall_reports,
        'techniques': totals,
        'techniques_by_wall': by_wall,
        'technique_calls': len(used),
        'cells': int((scene.volume != 0).sum()),
        'scheme_expects': list(technique_layer.SCHEME_TECHNIQUES.get(spec.name, ())),
        'scene_whd': [scene.volume.shape[2], scene.volume.shape[0], scene.volume.shape[1]],
        'note': 'Three layers: structure form, facade scheme, block technique. '
                'Techniques take their surface as an argument, so they apply to any form.',
    }
    return scene, manifest


def plan_for(form: str, seed: int = 1900, scheme: Optional[str] = None,
             width: Optional[int] = None, depth: Optional[int] = None,
             storeys: Optional[int] = None, bay_pitch=None, entrance_fraction=None, roof_height=None, detail_profile=None, chamfer=None) -> HousePlan:
    """A sensible plan for a form, with measured defaults.

    Defaults come from the measured sources: frontage 8..14 and depth 20..35 is the
    ordinary Paris plot, which is what the reference street wall is made of.
    """
    if bay_pitch is not None and (type(bay_pitch) is not int or not 4 <= bay_pitch <= 8):
        raise ValueError('bay_pitch must be 4..8')
    if roof_height is not None and (type(roof_height) is not int or not 5 <= roof_height <= 9):
        raise ValueError('roof_height must be 5..9')
    if entrance_fraction is not None and not 0 <= entrance_fraction <= 1:
        raise ValueError('entrance_fraction must be 0..1')
    if detail_profile not in (None, 'reference_haussmann'):
        raise ValueError('Unknown detail profile')
    if detail_profile and (form not in ('street_house', 'corner_house')
                           or not width or not depth or width < 23 or depth < 24):
        raise ValueError('Reference Haussmann needs one street_house or corner_house, width >=23, depth >=24')
    rng = random.Random(seed)
    if width is None or depth is None:
        if form == 'slope_terrace':
            # Wider than a single plot: a slope terrace is several houses stepping down,
            # and each step needs enough frontage to hold a shop and an entrance.
            width = rng.randint(22, 34)
            depth = rng.randint(20, 32)
        elif form == 'street_row':
            # A street wall: a run of plots, which is what the reference elevation is.
            width = rng.randint(40, 60)
            depth = rng.randint(22, 30)
        elif form == 'corner_house':
            # A corner plot carries two street frontages, so it is wider than a single
            # plot in a run: each street needs its own shop base and bay rhythm.
            width = rng.randint(20, 30)
            depth = rng.randint(20, 30)
        elif form == 'street_house':
            # Frontages measured in the sources run 8..14 for a single narrow plot, but
            # the reference street wall is made of houses with two to three bays; a
            # one-bay house cannot carry both the shop and the entrance, which is what
            # the reference street front always has.
            width = rng.randint(10, 18)
            depth = rng.randint(20, 35)
        elif form == 'court_palace':
            width = rng.randint(24, 34)
            depth = rng.randint(24, 34)
        elif form == 'civic_hall':
            width = rng.randint(34, 48)
            depth = rng.randint(20, 30)
        else:
            width = rng.randint(16, 24)
            depth = rng.randint(18, 28)
    if storeys is None:
        storeys = rng.choice([5, 6, 6, 7])
    if chamfer is not None and (type(chamfer) is not int or not 0 <= chamfer <= 6):
        raise ValueError('chamfer must be 0..6')
    return HousePlan(form=form, scheme=scheme or DEFAULT_SCHEME[form], width=width,
                     depth=depth, storeys=storeys, seed=seed, bay_pitch=bay_pitch,
                     entrance_fraction=entrance_fraction, roof_height=roof_height,
                     detail_profile=detail_profile, chamfer=chamfer)


def matrix(forms: Optional[List[str]] = None, schemes: Optional[List[str]] = None,
           seed: int = 1900) -> List[dict]:
    """Build every (form, scheme) pair and report what each produced.

    This is the orthogonality check the separation exists for: a technique database is
    only orthogonal if its techniques work on every form, so the test builds all pairs
    and fails if any one of them drops an element or produces an empty elevation.
    """
    forms = forms or sorted(structure_layer.FORMS)
    schemes = schemes or sorted(facade_layer.SCHEMES)
    rows = []
    for form in forms:
        for name in schemes:
            plan = plan_for(form, seed=seed, scheme=name)
            scene, manifest = build(plan)
            face = next((w for w in manifest['walls'] if w['role'] == PRIMARY), None)
            rows.append({
                'form': form, 'scheme': name, 'openings': sum(w['openings'] for w in manifest['walls']),
                'street_openings': face['openings'] if face else 0,
                'street_bays': face['bay_groups'] if face else 0,
                'techniques': manifest['techniques'],
                'technique_count': len(manifest['techniques']),
                'cells': int((scene.volume != 0).sum()),
            })
    return rows
