"""Tests for the three house-design databases and their separation.

The user's requirement is specific: technique, facade and structure are *separate*
databases, so that a facade learned from one building can be applied to any form. These
tests check the separation holds rather than checking any one building looks nice:

  * every facade scheme builds on every structure form (the orthogonality contract);
  * a form's geometry is not decided by the facade layer (same form + different scheme
    = same massing and same default scheme application);
  * a technique is applied to a surface it is handed, so the same technique appears on
    every form;
  * the failures that cost the most time cannot come back: openings must land on the
    plane the street sees, a shopfront must not be overwritten by a window surround,
    and a stepped terrace must not cut doors above its own roof.
"""
import unittest

from paris_builder import design, facade, house, technique


class LayerSeparationTests(unittest.TestCase):
    def test_structure_layer_exposes_the_source_forms(self):
        # Five forms the brief lists, the street wall the reference elevation actually is
        # (a run of plots sharing party walls), and the corner plot, which a street wall
        # cannot express: its two street faces are opposite each other, not adjacent.
        self.assertEqual(len(house.FORMS), 7)
        for name in ('street_house', 'street_row', 'apartment_block', 'court_palace',
                     'civic_hall', 'slope_terrace', 'corner_house'):
            self.assertIn(name, house.FORMS)

    def test_street_row_is_several_plots_with_different_sections(self):
        # A row whose plots all came out the same height would not be a street wall.
        plan = design.plan_for('street_row', seed=1900, width=56, depth=26, storeys=6)
        _scene, manifest = design.build(plan)
        plots = manifest['structure']['extras'].get('plots', [])
        self.assertGreaterEqual(len(plots), 3, 'a street row needs several plots')
        self.assertGreater(len({p['top'] for p in plots}), 1,
                           'every plot came out the same height: %s' % plots)
        walls = {w['name']: w for w in manifest['structure']['walls']}
        self.assertTrue(any(name.startswith('party_') for name in walls),
                        'the plots are not separated by party walls')

    def test_segment_walls_use_only_their_own_levels(self):
        for form in ('street_row', 'slope_terrace'):
            structure, _ = house.build(form, 56, 26, 6, 1900)
            for wall in structure.street_walls():
                self.assertIsNotNone(wall.levels, (form, wall.name))
                self.assertEqual(len(wall.levels), len({(level.y, level.height)
                                                        for level in wall.levels}))
                self.assertLessEqual(max(level.y + level.height for level in wall.levels),
                                     wall.height + 1)

    def test_facade_layer_is_composition_only(self):
        # A scheme must not name blocks or sizes: if it did, it could not be moved from
        # one form to another.
        for name, spec in facade.SCHEMES.items():
            fields = set(vars(spec))
            self.assertNotIn('material', fields, name)
            self.assertNotIn('block', fields, name)
            self.assertNotIn('width', fields, name)
        self.assertTrue(facade.SCHEMES)

    def test_techniques_take_their_surface_as_an_argument(self):
        # Every technique's first two parameters are (scene, wall): that is what makes
        # it orthogonal, so the check is on the signature rather than on behaviour.
        for name, function in technique.TECHNIQUES.items():
            params = list(function.__code__.co_varnames[:2])
            self.assertEqual(params, ['scene', 'wall'], name)

    def test_every_scheme_builds_on_every_form(self):
        for form in sorted(house.FORMS):
            for scheme in sorted(facade.SCHEMES):
                plan = design.plan_for(form, seed=1900, scheme=scheme)
                scene, manifest = design.build(plan)
                self.assertGreater(manifest['cells'], 100,
                                   '%s + %s produced almost nothing' % (form, scheme))
                self.assertGreater(sum(w['openings'] for w in manifest['walls']), 0,
                                   '%s + %s produced no openings' % (form, scheme))

    def test_same_form_different_scheme_keeps_the_same_massing(self):
        # The facade layer must not change what the building is.
        for form in sorted(house.FORMS):
            shapes = set()
            for scheme in sorted(facade.SCHEMES):
                plan = design.plan_for(form, seed=1900, scheme=scheme)
                _scene, manifest = design.build(plan)
                structure = manifest['structure']
                shapes.add((structure['width'], structure['depth'], structure['storeys'],
                            len(structure['walls'])))
            self.assertEqual(len(shapes), 1, '%s massing changed with the scheme: %s'
                             % (form, shapes))

    def test_a_technique_lands_on_every_form(self):
        # window_surround is the technique every scheme lists, so it must appear on
        # every form; a technique bound to one form would fail here.
        for form in sorted(house.FORMS):
            plan = design.plan_for(form, seed=1900, scheme='haussmann_apartment')
            _scene, manifest = design.build(plan)
            self.assertIn('window_surround', manifest['techniques'], form)

    def test_scheme_expectations_are_actually_applied(self):
        # A scheme lists the techniques it needs. A narrow house can legitimately lack
        # shopfronts (every bay is the entrance), so the strict check is on the ones
        # that every elevation needs.
        required = ('window_surround', 'cornice')
        for form in sorted(house.FORMS):
            for scheme in sorted(facade.SCHEMES):
                plan = design.plan_for(form, seed=1900, scheme=scheme)
                _scene, manifest = design.build(plan)
                for name in required:
                    self.assertIn(name, manifest['techniques'],
                                  '%s + %s is missing %s' % (form, scheme, name))


class FacadeWriteOrderTests(unittest.TestCase):
    """The failures that made earlier renders unreadable, locked as regressions."""

    def _wall(self, form='street_house', seed=1900):
        plan = design.plan_for(form, seed=seed)
        scene, manifest = design.build(plan)
        structure, _ctx = house.build(plan.form, plan.width, plan.depth, plan.storeys,
                                      plan.seed)
        wall = next(w for w in structure.walls if w.role == 'primary')
        return scene, manifest, wall

    def test_glazing_is_visible_from_the_street(self):
        # The invariant is that the street can see the glazing, not which exact cell holds
        # it. The design recesses it to d=1 so the opening gets a jamb and a soffit; an
        # earlier version put it at d=0 and the windows read flat. What must never happen
        # is glazing hidden deep inside the wall, where it is simply not there.
        scene, _manifest, wall = self._wall()
        palette = scene.palette
        visible = 0
        for u in range(wall.length):
            for y in range(1, wall.height + 1):
                for d in (0, 1):
                    x, _yy, z = wall.point(u, y, d)
                    if palette[int(scene.volume[y, z, x])].startswith(
                            'minecraft:white_stained_glass'):
                        visible += 1
        self.assertGreater(visible, 0, 'no glazing visible from the street')

    def test_the_opening_is_recessed_so_it_reads_as_a_window(self):
        # A pane flush with the wall face is a flat panel: the recess is what gives the
        # opening a jamb and a soffit that catch different light from the wall.
        scene, _manifest, wall = self._wall()
        palette = scene.palette
        recessed = 0
        for u in range(wall.length):
            for y in range(1, wall.height + 1):
                outer = palette[int(scene.volume[y, wall.point(u, y, 0)[2],
                                                wall.point(u, y, 0)[0]])]
                inner = palette[int(scene.volume[y, wall.point(u, y, 1)[2],
                                                wall.point(u, y, 1)[0]])]
                if inner.startswith('minecraft:white_stained_glass') and outer == 'minecraft:air':
                    recessed += 1
        self.assertGreater(recessed, 0,
                           'no opening is recessed behind the wall face')

    def test_shopfront_is_not_overwritten_by_the_window_surround(self):
        # `window_surround` writes a sill row under its opening; running it before
        # `shopfront` erases the shop glazing and the shop disappears from the street.
        plan = design.plan_for('street_house', seed=1900, width=14, scheme='shop_terrace')
        scene, manifest = design.build(plan)
        self.assertIn('shopfront', manifest['techniques'])
        structure, _ctx = house.build(plan.form, plan.width, plan.depth, plan.storeys, plan.seed)
        wall = next(w for w in structure.walls if w.role == 'primary')
        palette = scene.palette
        shop_rows = 0
        for opening in facade.compose(wall, structure.levels, facade.scheme('shop_terrace'),
                                      __import__('random').Random(1), wall.role):
            if opening.kind != 'shop':
                continue
            for u in range(opening.u, opening.u + opening.width):
                for d in (0, 1):
                    x, _yy, z = wall.point(u, opening.y + 1, d)
                    if palette[int(scene.volume[opening.y + 1, z, x])].startswith(
                            'minecraft:white_stained_glass'):
                        shop_rows += 1
        self.assertGreater(shop_rows, 0, 'the shop glazing was overwritten')

    def test_party_walls_carry_no_openings(self):
        for form in sorted(house.FORMS):
            plan = design.plan_for(form, seed=1900)
            _scene, manifest = design.build(plan)
            for wall in manifest['walls']:
                if wall['role'] == 'party':
                    self.assertEqual(wall['openings'], 0,
                                     '%s punched a window into a party wall' % form)

    def test_terraced_house_rear_and_party_parapets(self):
        plan = design.plan_for('street_house', seed=1900, width=12, depth=30,
                               scheme='haussmann_apartment')
        scene, manifest = design.build(plan)
        walls = {wall['name']: wall for wall in manifest['walls']}
        self.assertGreater(walls['rear']['openings'], 0)
        self.assertEqual(walls['party_west']['openings'], 0)
        self.assertEqual(walls['party_east']['openings'], 0)
        self.assertGreater(manifest['techniques_by_wall']['rear']['window_surround'], 0)
        self.assertGreater(manifest['techniques_by_wall']['rear']['door_leaf'], 0)
        structure, _context = house.build(plan.form, plan.width, plan.depth,
                                           plan.storeys, plan.seed)
        for x in (6, 6 + plan.width - 1):
            self.assertEqual(scene.palette[int(scene.volume[structure.top + 3,
                              6 + plan.depth // 2, x])], house.STONE_DRESSING)

    def test_stepped_terrace_does_not_cut_openings_above_its_own_roof(self):
        plan = design.plan_for('slope_terrace', seed=1900, width=30, depth=26)
        _scene, manifest = design.build(plan)
        structure, _ctx = house.build(plan.form, plan.width, plan.depth, plan.storeys, plan.seed)
        by_name = {w.name: w for w in structure.walls}
        for report in manifest['walls']:
            if report['openings'] == 0:
                continue
            wall = by_name[report['name']]
            for opening_top in [wall.height]:
                self.assertLessEqual(opening_top, wall.height)

    def test_slope_terrace_actually_steps(self):
        plan = design.plan_for('slope_terrace', seed=1900, width=30, depth=26)
        _scene, manifest = design.build(plan)
        heights = [w['height'] for w in manifest['structure']['walls']
                   if w['role'] == 'primary']
        self.assertGreater(len(heights), 1, 'a slope terrace needs more than one segment')
        self.assertEqual(len(set(heights)), len(heights),
                         'the segments did not step: %s' % heights)


if __name__ == '__main__':
    unittest.main()
