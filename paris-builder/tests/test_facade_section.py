"""Independent export mutations must change the measured architectural evidence."""
from pathlib import Path
import json
import tempfile
import unittest

import numpy as np

from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure, review_evidence, REPORT_VERSION
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

    def test_tangent_thin_door_leaves_require_real_recessed_glass(self):
        leaf = 'minecraft:iron_door[facing=east,half=lower,hinge=left,open=false,powered=false]'
        self.palette.append(leaf)
        self.v[2:5,3,4:6] = len(self.palette)-1
        self.v[2:5,4,4:6] = 3
        group = self.report()['storeys'][0]['faces']['street_north']['openings'][0]
        self.assertEqual(group['kinds'], ['glazing'])
        self.assertEqual(group['depth_counts'], {'2':6})
        self.v[2:5,4,4:6] = 1
        self.assertEqual(self.report()['storeys'][0]['faces']['street_north']['opening_count'],0)
        self.v[2:5,4:6,4:6] = 0
        self.assertEqual(self.report()['storeys'][0]['faces']['street_north']['opening_count'],0)

    def test_door_plane_across_ray_does_not_reveal_hidden_glass(self):
        self.palette.append('minecraft:iron_door[facing=north,half=lower,hinge=left,open=false,powered=false]')
        self.v[2:5,3,4:6] = len(self.palette)-1
        self.v[2:5,4,4:6] = 3
        self.assertEqual(self.report()['storeys'][0]['faces']['street_north']['opening_count'],0)

    def test_east_thin_window_uses_rotated_leaf_orientation(self):
        self.palette.append('minecraft:iron_door[facing=north,half=lower,hinge=left,open=false,powered=false]')
        self.v[2:5,6:8,9] = 0
        self.v[2:5,6:8,8] = len(self.palette)-1
        self.v[2:5,6:8,7] = 3
        group = self.report()['storeys'][0]['faces']['street_east']['openings'][0]
        self.assertEqual(group['depth_counts'], {'2':6})
        self.palette[-1] = self.palette[-1].replace('facing=north','facing=east')
        self.assertEqual(self.report()['storeys'][0]['faces']['street_east']['opening_count'],0)

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

    def test_global_summary_bounds_coordinates_but_storey_restores_exact_evidence(self):
        r = self.report()
        frozen = json.dumps(r)
        e = review_evidence(r)
        self.assertNotIn('sample_coordinates_xyz',e['storeys'][0]['faces']['street_north']['openings'][0])
        self.assertNotIn('stone_coordinates_xyz',e['courses'][0]['faces']['street_north']['stone_path_connection'])
        layer = review_evidence(r,0)
        self.assertIn('sample_coordinates_xyz',layer['storeys'][0]['faces']['street_north']['openings'][0])
        self.assertIn('stone_coordinates_xyz',layer['courses'][0]['faces']['street_north']['stone_path_connection'])
        self.assertEqual(json.dumps(r),frozen)

    def test_unrecognised_export_cannot_claim_measurement(self):
        self.v[:]=0
        r=self.report()
        self.assertEqual(r['status'],'unmeasured')
        self.assertIn('reason',r)

    def test_thick_floor_plate_is_one_band_with_no_empty_storey(self):
        self.v[2,2:12,2:10] = self.v[1,2:12,2:10]
        r = self.report()
        self.assertEqual(r['version'],REPORT_VERSION)
        self.assertEqual(r['floor_plate_bands_y'],[[1,2],[5,5],[9,9]])
        self.assertEqual(r['floors_y'],[2,5,9])
        self.assertEqual(len(r['storeys']),2)
        self.assertTrue(all(lo<=hi for lo,hi in (row['y_range'] for row in r['storeys'])))

    def test_separate_vertical_windows_keep_separate_coordinates(self):
        self.v[2:5,2:4,4:6] = 1
        for y in (2,4):
            self.v[y,2,4:6] = 0
            self.v[y,3,4:6] = 3
        face = self.report()['storeys'][0]['faces']['street_north']
        self.assertEqual(face['sampled_transmissive_groups_count'],2)
        self.assertEqual(face['opening_count'],2)
        self.assertEqual([o['y_range'] for o in face['openings']],[[2,2],[4,4]])
        self.assertEqual(face['openings'][1]['sample_coordinates_xyz'],[[4,4,2],[5,4,2]])

    def test_joinery_splits_transmissive_groups_without_claiming_bays(self):
        self.v[2:5,2,4:7] = 0
        self.v[2:5,3,4:7] = 3
        self.v[2:5,3,5] = 2
        r = self.report()
        face = r['storeys'][0]['faces']['street_north']
        self.assertEqual(face['sampled_transmissive_groups_count'],2)
        self.assertIn('not architectural bays',r['opening_group_semantics'])

    def test_projected_coverage_does_not_prove_connected_stone(self):
        self.v[4,0:2,:] = 0
        for x in range(3,7):
            self.v[4,1 if x%2 else 0,x] = 1
        row = next(c for c in self.report()['courses'] if c['y']==4)
        face = row['faces']['street_north']
        self.assertEqual((face['covered_cells'],face['longest_run'],face['gaps']),(4,4,[]))
        self.assertFalse(face['stone_path_connection']['connected'])
        self.assertEqual(face['stone_path_connection']['status'],'disconnected')
        self.assertFalse(row['continuous_sampled_path'])
        self.assertEqual(face['stone_path_connection']['stone_coordinates_xyz'],
                         [[3,4,1],[4,4,0],[5,4,1],[6,4,0]])

    def test_connected_stone_voxels_have_evidence_and_break_after_mutation(self):
        self.v[4,0:2,:] = 0
        self.v[4,1,3:7] = 1
        row = next(c for c in self.report()['courses'] if c['y']==4)
        face = row['faces']['street_north']
        self.assertTrue(face['stone_path_connection']['connected'])
        self.assertEqual(face['stone_path_connection']['connected_coordinates_xyz'],
                         [[3,4,1],[4,4,1],[5,4,1],[6,4,1]])
        self.v[4,1,4] = 0
        changed = next(c for c in self.report()['courses'] if c['y']==4)
        self.assertFalse(changed['faces']['street_north']['stone_path_connection']['connected'])

    def test_corner_connection_requires_real_diagonal_stair_step_bridges(self):
        self.v[4] = 0
        positions = ([(x,1) for x in range(3,7)] +
                     [(7,1),(8,2),(9,3),(10,4)] + [(10,z) for z in range(5,11)])
        for x,z in positions:
            self.v[4,z,x] = 1
        row = next(c for c in self.report()['courses'] if c['y']==4)
        self.assertTrue(row['sampled_path_coverage_complete'])
        self.assertFalse(row['continuous_sampled_path'])
        for x,z in [(7,2),(8,3),(9,4)]:
            self.v[4,z,x] = 1
        changed = next(c for c in self.report()['courses'] if c['y']==4)
        self.assertTrue(changed['continuous_sampled_path'])
        self.assertTrue(changed['stone_path_connection']['connected'])
        self.assertIn([8,4,3],changed['stone_path_connection']['connected_coordinates_xyz'])

    def test_rectangle_cannot_claim_three_face_corner_connection(self):
        self.v[0,2:12,2:10] = 1
        r = self.report()
        self.assertEqual(r['footprint']['pattern'],'rectangle')
        self.assertFalse(r['supported_geometry']['supports_ne_corner_sampling'])
        self.assertTrue(all(not c['continuous_sampled_path'] for c in r['courses']))
        self.assertTrue(all(c['stone_path_connection']['status']=='unsupported' for c in r['courses']))

    def test_unrelated_foundation_hole_does_not_claim_supported_chamfer(self):
        self.v[0,7,5] = 0
        r = self.report()
        self.assertEqual(r['footprint']['north_east_cut_cells'],3)
        self.assertFalse(r['footprint']['supported_pattern'])
        self.assertFalse(r['supported_geometry']['supports_ne_corner_sampling'])
        self.assertTrue(all(not c['continuous_sampled_path'] for c in r['courses']))

    def test_roof_slices_preserve_real_air_and_materials_without_profile_fill(self):
        # The centre x section is at z=6. Every marker is an actual exported cell.
        self.v[10,6,2:10] = 0
        self.v[10,6,3] = 1
        self.v[10,6,4] = 2
        self.v[10,6,5] = 3
        self.v[10,6,6] = 4
        r = self.report()
        section = next(t for t in r['roof_slices'] if t['axis']=='x' and t['fixed_coordinate']==6)
        row = next(t for t in section['rows'] if t['y']==10)
        self.assertEqual(row['cells'],'.SWGR...')
        self.assertEqual(section['rows'][0]['y'],19)
        self.assertEqual(section['rows'][-1]['y'],9)
        self.assertEqual(len(section['rows']),11)
        self.assertIn('roof_slices',review_evidence(r))
        json.dumps(r)  # The export evidence must survive actual workflow serialization.
        self.v[10,6,5] = 0
        changed = self.report()
        changed_slice = next(t for t in changed['roof_slices'] if t['axis']=='x' and t['fixed_coordinate']==6)
        self.assertEqual(next(t for t in changed_slice['rows'] if t['y']==10)['cells'],'.SW.R...')
        self.assertNotEqual(r['source']['sha256'],changed['source']['sha256'])

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
