"""Independent export mutations must change the measured architectural evidence."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure, review_evidence
from paris_builder import atelier_workflow as a, workflow as w


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'candidate.schem'
        self.palette = ['minecraft:air', 'minecraft:sandstone', 'minecraft:spruce_planks',
                        'minecraft:glass', 'minecraft:deepslate_tiles',
                        'minecraft:sandstone_slab[type=top,waterlogged=false]']
        self.v = np.zeros((20,16,14),dtype=np.int32)
        self.v[0,2:12,2:10] = 1
        for z in range(2,12):
            for x in range(2,10):
                if 9-x+z-2 < 3: self.v[0,z,x] = 0
        for y in (1,5,9):
            self.v[y,2:12,2:10] = np.where(self.v[0,2:12,2:10],2,0)
        self.v[1:10,2,2:7] = 1
        self.v[1:10,3,2:7] = 1
        self.v[1:10,5:12,9] = 1
        self.v[1:10,2:12,2] = 1
        self.v[1:10,11,2:10] = 1
        self.v[2:5,2,4:6] = 0
        self.v[2:5,3,4:6] = 3
        self.v[6:9,2,4:6] = 0
        self.v[6:9,3,4:6] = 3
        self.v[5,1,3:7] = 5
        for x,rise in enumerate([1,3,4,4,4,4,3,1],start=2):
            self.v[9+rise,2:12,x] = 4

    def report(self):
        write_schematic(self.path,self.v,self.palette)
        return measure(self.path)

    def test_actual_footprint_floor_and_recess_without_manifest(self):
        r = self.report()
        self.assertEqual(r['footprint']['north_east_cut_cells'],3)
        self.assertEqual(r['floors_y'],[1,5,9])
        op=r['storeys'][0]['faces']['street_north']['openings'][0]
        self.assertEqual((op['width_cells'],op['height_cells']),(2,3))
        self.assertEqual(op['depth_counts'],{'1':6})
        self.assertEqual(r['storeys'][0]['faces']['party_west']['opening_count'],0)

    def test_flush_and_blocked_window_are_not_recessed(self):
        self.v[2:5,2,4:6] = 3
        r=self.report()
        self.assertEqual(r['storeys'][0]['faces']['street_north']['openings'][0]['depth_counts'],{'0':6})
        self.v[2:5,2,4:6] = 1
        self.assertEqual(self.report()['storeys'][0]['faces']['street_north']['opening_count'],0)

    def test_course_gap_and_roof_mutation_have_coordinate_evidence(self):
        r=self.report()
        course=next(c for c in r['courses'] if c['y']==5)
        longest=course['faces']['street_north']['longest_run']
        self.v[5,1,4]=0
        self.v[17,7,5]=4
        changed=self.report()
        course=next(c for c in changed['courses'] if c['y']==5)
        self.assertLess(course['faces']['street_north']['longest_run'],longest)
        self.assertEqual(changed['roof_column_map']['columns_z_x'][5][3]['top_y'],17)
        self.assertNotEqual(r['source']['sha256'],changed['source']['sha256'])

    def test_every_face_position_and_roof_column_is_persisted(self):
        r=self.report()
        self.assertEqual(set(r['surface_maps']),{'street_north','street_east','chamfer','party_west','party_south'})
        self.assertEqual(len(r['roof_column_map']['columns_z_x']),10)
        e=review_evidence(r,1)
        self.assertEqual([s['storey'] for s in e['storeys']],[1])
        self.assertEqual(e['surface_maps']['street_north']['start_y'],6)
        self.assertNotIn('horizontal_sections',e)

    def test_unrecognised_export_cannot_claim_measurement(self):
        self.v[:]=0
        r=self.report()
        self.assertEqual(r['status'],'unmeasured')
        self.assertIn('reason',r)

    def test_new_evidence_preserves_export_and_old_review_but_changes_binding(self):
        r=self.report()
        task=w.create_task(Path(self.temp.name)/'workflow.json', {'style':'test','use':'test',
            'scale_budget':{},'views':list(w.VIEWS),'minecraft_version':'1.21.11','data_version':4671},'fixture',{})
        task['stage']='facades'
        w.register_artifact(task,'schematic',self.path,'facade-1')
        old=w.bindings(task).copy()
        task['reviews'].append({'decision':'reject','artifact_hashes':old})
        a.ensure_section_evidence(task)
        self.assertNotEqual(w.bindings(task),old)
        self.assertEqual(task['reviews'][0]['artifact_hashes'],old)
        self.assertEqual(measure(self.path)['source']['sha256'],r['source']['sha256'])
        count=len(task['artifacts'])
        a.ensure_section_evidence(task)
        self.assertEqual(len(task['artifacts']),count)
        self.v[2,2,4]=1
        self.report()
        with self.assertRaisesRegex(ValueError,'Changed or missing'):
            a.ensure_section_evidence(task)


if __name__=='__main__': unittest.main()
