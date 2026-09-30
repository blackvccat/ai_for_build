import unittest
import numpy as np
from paris_builder.architecture import transform_state, transform_point, Scene, state
from paris_builder.components import FAMILIES,recipe
from paris_builder.production import propose, make_graph, build

class ArchitectureTests(unittest.TestCase):
    def test_directional_roundtrip_all_recipes(self):
        for family in FAMILIES:
            for variant in range(3):
                for *_,s in recipe(family,variant).voxels:
                    self.assertEqual(transform_state(s,4),s)
                    self.assertEqual(transform_state(transform_state(s,mirror=True),mirror=True),s)
                    r=s
                    for _ in range(4):r=transform_state(r,1)
                    self.assertEqual(r,s)

    def test_chirality_and_connections(self):
        s=state('sandstone_stairs',facing='north',half='top',shape='outer_left',waterlogged='false')
        self.assertIn('shape=outer_right',transform_state(s,mirror=True))
        self.assertIn('facing=east',transform_state(s,1))
        s=state('sandstone_wall',east='low',west='none',north='none',south='none',up='false',waterlogged='false')
        self.assertIn('south=low',transform_state(s,1))
        self.assertEqual(transform_point(2,3,4,1),(-4,3,2))

    def test_every_family_has_three_distinct_compositions(self):
        for family in FAMILIES:
            signatures={str(recipe(family,v).voxels) for v in range(3)}
            self.assertEqual(len(signatures),3,family)

    def test_collision_is_not_silently_overwritten_in_strict_mode(self):
        s=Scene(3,3,3);s.put(1,1,1,'minecraft:stone')
        self.assertFalse(s.put(1,1,1,'minecraft:glass',replace=False))
        self.assertEqual(len(s.collisions),1)
        self.assertEqual(s.palette[s.volume[1,1,1]],'minecraft:stone')

    def test_graph_has_real_court_and_diagonal(self):
        c=propose(6421);c['footprint_type']='open_court';g=make_graph(c)
        self.assertEqual(g.validate(),[])
        self.assertTrue(any(f.diagonal for f in g.faces))
        self.assertEqual(sum(f.courtyard for f in g.faces),3)
        mask=g.mask(c['width']+17,c['depth']+17)
        self.assertFalse(mask[8+c['depth']-3,8+c['width']//2])
        self.assertTrue(mask[12,15])
        for f in g.faces:
            self.assertEqual(f.point(0,7),(*f.start[:1],7,f.start[1]))
            self.assertEqual(f.point(f.length,7),(f.end[0],7,f.end[1]))

    def test_new_seed_changes_three_architectural_choices(self):
        cs=[propose(s) for s in [6101,6211,6317,6421,6521]]
        for i,c in enumerate(cs):
            self.assertEqual(c,propose(c['massing_seed']))
            for other in cs[:i]:self.assertGreaterEqual(sum(c[k]!=other[k] for k in c if k!='massing_seed'),3)

    def test_framework_and_detail_share_topology_not_voxels(self):
        c=propose(6317)
        bare,b=build(c,stage=0);detail,d=build(c,stage=3)
        self.assertEqual(b['face_graph'],d['face_graph'])
        self.assertGreater(len(d['component_ids']),0)
        self.assertEqual(b['component_ids'],[])
        self.assertTrue(all(o['visible_depth']>=3 for o in d['openings']))
        self.assertFalse(np.array_equal(bare.volume,detail.volume))

if __name__=='__main__':unittest.main()
