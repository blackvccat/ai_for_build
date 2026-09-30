"""Regression tests for the city layer.

These encode the failures that cost the most time in this project, so they cannot come
back silently:

  * the first four city renders had a facade with *no visible windows*, because the
    street wall was one cell thick and every recessed write was overwritten by the next
    one. The test therefore checks the plane the street actually sees (`z = facade
    line`), not the parcel interior.
  * the fifth render put the glazing behind an unbroken stone face, so the elevation
    read as a solid wall with dark lines in it.
  * a lone door half is an incomplete block state and fails the project's independent
    geometry check.
"""
import unittest
from collections import Counter

from paris_builder.architecture import split_state
from paris_builder.city import (StreetCity, PANE_BACKING, REVEAL_DEPTH, SHOP_DEPTH,
                                WINDOW_PANE)

GLAZING = {WINDOW_PANE, 'minecraft:white_stained_glass_pane'}


def build(seed=1900, length=90, side='north'):
    city = StreetCity(seed, street_length=length)
    city.assemble()
    return city, [p for p in city.parcels if p.side == side]


def face_cells(city, parcel, depth):
    """The material on plane `depth` back from the street face of one parcel."""
    palette, volume = city.scene.palette, city.scene.volume
    z0 = city.facade_line(parcel)
    oz = city.outward(parcel)
    out = []
    for x in range(parcel.front_x, parcel.front_x + parcel.frontage):
        for y in range(1, parcel.top_y + 1):
            name, _ = split_state(palette[int(volume[y, z0 + oz * depth, x])])
            out.append(name)
    return out


class CityFacadeTests(unittest.TestCase):
    def test_street_wall_is_thick_enough_to_hold_its_openings(self):
        # The wall an opening is cut into must be deeper than the decorations placed
        # inside it, or each write destroys the previous one.
        self.assertGreater(REVEAL_DEPTH, 2)
        self.assertGreater(SHOP_DEPTH, REVEAL_DEPTH)

    def test_windows_are_present_on_the_plane_the_street_sees(self):
        city, parcels = build()
        house = max(parcels[:6], key=lambda p: p.frontage) if parcels else None
        self.assertIsNotNone(house)
        cells = face_cells(city, house, 0)
        glazing = sum(1 for name in cells if name in GLAZING)
        self.assertGreater(glazing, 0, 'no glazing on the street-facing plane at all')
        self.assertGreater(glazing / len(cells), 0.10,
                           'less than a tenth of the street face is glazing')

    def test_no_open_shaft_runs_through_the_building_at_street_level(self):
        # A window or shop backed by nothing is a hole, not an opening.
        city, parcels = build()
        for parcel in parcels[:6]:
            cells = face_cells(city, parcel, SHOP_DEPTH - 1)
            holes = sum(1 for name in cells if name == 'minecraft:air')
            self.assertEqual(holes, 0,
                             '%s has %d open cells %d deep behind its face' % (
                                 parcel.parcel_id, holes, SHOP_DEPTH - 1))

    def test_doors_are_written_as_both_halves(self):
        city, parcels = build()
        palette, volume = city.scene.palette, city.scene.volume
        halves = Counter()
        for parcel in parcels:
            z0 = city.facade_line(parcel)
            for y in range(1, parcel.top_y + 1):
                for x in range(parcel.front_x, parcel.front_x + parcel.frontage):
                    name, props = split_state(palette[int(volume[y, z0, x])])
                    if 'door' in name:
                        halves[props.get('half')] += 1
        self.assertEqual(halves['lower'], halves['upper'],
                         'door halves are unbalanced: %r' % dict(halves))
        self.assertGreater(halves['lower'], 0, 'no doors were written at all')

    def test_neighbours_share_a_party_wall_without_a_gap(self):
        city, parcels = build()
        ends = {p.front_x + p.frontage - 1 for p in parcels}
        starts = {p.front_x for p in parcels}
        touching = ends & {s - 1 for s in starts}
        self.assertGreaterEqual(len(touching), len(parcels) - 2,
                                'parcels do not form a continuous street wall')

    def test_roof_is_continuous_over_the_row(self):
        # Per-parcel roofs produced a sawtooth; the row carries one roof.
        city, parcels = build()
        palette, volume = city.scene.palette, city.scene.volume
        z0 = city.facade_line(parcels[0])
        oz = city.outward(parcels[0])
        xs = [x for p in parcels for x in range(p.front_x, p.front_x + p.frontage)]
        covered = 0
        for x in xs:
            top = max(p.top_y for p in parcels
                      if p.front_x <= x < p.front_x + p.frontage)
            for dz in range(1, 12):
                name, _ = split_state(palette[int(volume[top + 1, z0 + oz * dz, x])])
                if 'deepslate' in name:
                    covered += 1
                    break
        self.assertGreater(covered / len(xs), 0.9, 'the row roof has gaps: %.2f covered' % (covered / len(xs)))


if __name__ == '__main__':
    unittest.main()
