"""Independent export mutations must change the scoped code verdicts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.architectural_conformance import measure, pending, plan_hash, validate
from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure as measure_section


class ArchitecturalConformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'candidate.schem'
        self.palette = ['minecraft:air', 'minecraft:sandstone', 'minecraft:spruce_planks',
                        'minecraft:glass', 'minecraft:deepslate_tiles',
                        'minecraft:sandstone_slab[type=top,waterlogged=false]',
                        'minecraft:white_wool', 'minecraft:glass_pane[north=false,east=true,south=false,west=true,waterlogged=false]']
        self.v = np.zeros((20,16,14),dtype=np.int32)
        self.v[0,2:12,2:10] = 1
        for z in range(2,12):
            for x in range(2,10):
                if 9-x+z-2 < 3:
                    self.v[0,z,x] = 0
        for y in (1,5,9):
            self.v[y,2:12,2:10] = np.where(self.v[0,2:12,2:10],2,0)
        self.v[1:10,2:4,2:7] = 1
        self.v[1:10,5:12,8:10] = 1
        self.v[1:10,2:12,2] = 1
        self.v[1:10,11,2:10] = 1
        for x,z in [(6,2),(7,3),(8,4),(9,5)]:
            self.v[1:10,z,x] = 1
        for low in (2,6):
            self.v[low:low+3,2,4:6] = 0
            self.v[low:low+3,3,4:6] = 3
            self.v[low:low+3,7:9,9] = 0
            self.v[low:low+3,7:9,8] = 3
            self.v[low:low+3,3,7] = 0
            self.v[low:low+3,4,6] = 3
            self.v[low:low+3,4,8] = 0
            self.v[low:low+3,5,7] = 3
        for x,rise in enumerate([1,3,4,4,4,4,3,1],start=2):
            self.v[9+rise,2:12,x] = 4
        self.plan = {'form':'corner_house','scheme':'fixture','width':8,'depth':10,'storeys':2,'chamfer':3}

    def report(self, plan=None, **kwargs):
        write_schematic(self.path,self.v,self.palette)
        return measure(self.path,plan or self.plan,**kwargs)

    @staticmethod
    def check(report, ident):
        return next(c for c in report['checks'] if c['id'] == ident)

    def opening_spec(self, **extras):
        plan = deepcopy(self.plan)
        plan['conformance_spec'] = {'openings':[{'id':'north-0','face':'street_north','storey':0,
                                               'axis_indices':[1,2],'y_range':[2,4],**extras}]}
        return plan

    def test_existing_scalar_contract_measures_only_named_predicates(self):
        r = self.report()
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(self.check(r,'corner/chamfer_geometry')['status'],'pass')
        self.assertEqual(self.check(r,'topology/party_west_opaque')['status'],'pass')
        self.assertNotIn('junctions',{c['id'] for c in r['checks']})
        self.assertIn('architectural course role schedule',r['unscoped_requirements'])
        self.assertEqual(pending(r),[])
        self.assertEqual(validate(r,self.path,self.plan),r)

    def test_chamfer_not_roof_cascade(self):
        plan = {**self.plan,'detail_profile':'reference_haussmann'}
        r = self.report(plan)
        self.assertIn(self.check(r,'roof/mansard_profile')['status'],('fail','unsupported'))
        self.assertEqual(self.check(r,'corner/chamfer_geometry')['status'],'pass')
        self.v[0,7,5] = 0
        r = self.report(plan)
        cut = self.check(r,'corner/chamfer_geometry')
        self.assertEqual(cut['status'],'fail')
        self.assertIn('supported footprint=False',cut['observation'])

    def test_party_wall_hole_is_located_not_hidden_by_opening_components(self):
        self.v[5,7,2] = 0  # plate row: old group-only sampling skipped it
        r = self.report()
        check = self.check(r,'topology/party_west_opaque')
        self.assertEqual(check['status'],'fail')
        self.assertIn([2,5,7],check['coordinates']['violations_xyz'])

    def test_unknown_party_model_is_pending_not_guessed_opaque(self):
        self.v[4,7,2] = 6
        r = self.report()
        check = self.check(r,'topology/party_west_opaque')
        self.assertEqual(check['status'],'unsupported')
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(check['coordinates']['unsupported_cells'][0]['state'],'minecraft:white_wool')

    def test_opening_position_and_recession_follow_export(self):
        plan = self.opening_spec(depth_range_steps=[1,1],glazing_connected=True)
        r = self.report(plan)
        for suffix in ('position','depth','glazing_connectivity'):
            self.assertEqual(self.check(r,'spec/opening/north-0/'+suffix)['status'],'pass')
        self.v[2:5,2,4:6] = 3
        r = self.report(plan)
        self.assertEqual(self.check(r,'spec/opening/north-0/depth')['status'],'fail')
        self.assertIn('observed ray steps [0]',self.check(r,'spec/opening/north-0/depth')['observation'])
        self.assertEqual(self.check(r,'openings/street_north/storey-0/recessed_glazing')['status'],'fail')
        self.v[2:5,2,4:6] = 1
        r = self.report(plan)
        self.assertEqual(self.check(r,'spec/opening/north-0/position')['status'],'fail')
        self.assertEqual(self.check(r,'openings/street_north/storey-0/visible_glazing')['status'],'fail')

    def test_partial_glazing_does_not_claim_full_model_contact(self):
        plan = self.opening_spec(glazing_connected=True)
        self.v[2:5,3,4:6] = 7
        r = self.report(plan)
        check = self.check(r,'spec/opening/north-0/glazing_connectivity')
        self.assertEqual(check['status'],'unsupported')
        self.assertTrue(check['coordinates']['partial_model_xyz'])

    def test_explicit_storey_alignment_and_floor_schedule(self):
        plan = deepcopy(self.plan)
        plan['conformance_spec'] = {'floors_y':[1,5,9], 'aligned_storeys':[{'face':'street_north','storeys':[0,1]}]}
        r = self.report(plan)
        self.assertEqual(self.check(r,'spec/alignment/0')['status'],'pass')
        self.v[6:9,2:4,4:6] = 1
        self.v[6:9,2,5:7] = 0
        self.v[6:9,3,5:7] = 3
        r = self.report(plan)
        self.assertEqual(self.check(r,'spec/alignment/0')['status'],'fail')
        self.assertEqual(self.check(r,'floors/heights')['status'],'pass')
        plan['conformance_spec']['floors_y'] = [1,6,9]
        self.assertEqual(self.check(self.report(plan),'floors/heights')['status'],'fail')

    def test_course_projected_coverage_cannot_fake_connectivity(self):
        self.v[4,0:2,:] = 0
        for x in range(3,7):
            self.v[4,1 if x%2 else 0,x] = 1
        plan = deepcopy(self.plan)
        plan['conformance_spec'] = {'courses':[{'id':'north-band','y':4,'faces':['street_north']}]}
        r = self.report(plan)
        check = self.check(r,'spec/course/north-band')
        self.assertEqual(check['actual']['street_north']['gaps'],[])
        self.assertEqual(check['status'],'fail')
        self.assertFalse(check['actual']['street_north']['connected'])
        self.v[4,1,3:7] = 1
        self.assertEqual(self.check(self.report(plan),'spec/course/north-band')['status'],'pass')

    def test_supported_full_cube_contact_fails_exact_state_or_adjacency(self):
        plan = deepcopy(self.plan)
        plan['conformance_spec'] = {'contacts':[{'id':'masonry','a_xyz':[2,3,7],'b_xyz':[2,4,7],
                                               'a_state':'minecraft:sandstone','b_state':'minecraft:sandstone'}]}
        self.assertEqual(self.check(self.report(plan),'spec/contact/masonry')['status'],'pass')
        self.v[4,7,2] = 2
        self.assertEqual(self.check(self.report(plan),'spec/contact/masonry')['status'],'fail')
        contact = plan['conformance_spec']['contacts'][0]
        contact['b_state'] = self.palette[5]
        self.assertEqual(self.check(self.report(plan),'spec/contact/masonry')['status'],'unsupported')

    def test_unknown_explicit_spec_obligation_cannot_pass(self):
        plan = {**self.plan,'conformance_spec':{'lintel_shape':'arch'}}
        r = self.report(plan)
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(self.check(r,'spec/lintel_shape')['status'],'unsupported')
        self.assertTrue(self.check(r,'spec/lintel_shape')['required'])
        plan['conformance_spec'] = []
        self.assertEqual(self.check(self.report(plan),'spec/schema')['status'],'unsupported')

    def test_hash_binding_stale_section_and_forged_report(self):
        r = self.report()
        section = measure_section(self.path)
        self.assertEqual(r['plan_sha256'],plan_hash({**self.plan,'_stage':'facades'}))
        with self.assertRaisesRegex(ValueError,'plan hash changed'):
            validate(r,self.path,{**self.plan,'width':9})
        with self.assertRaisesRegex(ValueError,'stage changed'):
            validate(r,self.path,self.plan,stage='frameworks')
        forged = deepcopy(r)
        forged['checks'][0]['observation'] = 'forged passing evidence'
        with self.assertRaisesRegex(ValueError,'independently recomputed'):
            validate(forged,self.path,self.plan)
        self.v[4,7,2] = 0
        write_schematic(self.path,self.v,self.palette)
        with self.assertRaisesRegex(ValueError,'export hash changed'):
            validate(r,self.path,self.plan)
        with self.assertRaisesRegex(ValueError,'stale'):
            measure(self.path,self.plan,section)

    def test_framework_stage_does_not_invent_dressing_obligations(self):
        r = self.report(stage='frameworks')
        self.assertEqual(r['stage'],'frameworks')
        self.assertFalse(any(c['id'].startswith('spec/course') for c in r['checks']))
        self.assertEqual(validate(r,self.path,self.plan,stage='frameworks'),r)


if __name__ == '__main__':
    unittest.main()
