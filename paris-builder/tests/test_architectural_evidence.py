"""Readable evidence must retain coordinates, real air cells and honest scopes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.architectural_evidence import compare_plan, review_description, text_evidence
from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure


def fixture():
    # Air deliberately has a nonzero palette id, as in real exports.
    palette = ['minecraft:sandstone', 'minecraft:air', 'minecraft:glass',
               'minecraft:oak_trapdoor[half=top]', 'minecraft:deepslate_tiles']
    report = {'version': 2, 'status': 'measured', 'source': {'path': 'fixture.schem', 'sha256': 'a'*64,
               'voxel_state_hash': 'b'*64}, 'limitations': ['fixture sample, not visual acceptance'],
              'footprint': {'bounds_xz': [6,6,13,15], 'width': 8, 'depth': 10,
                            'north_east_cut_cells': 3, 'diagonal_xz': [[10,6],[11,7],[12,8],[13,9]],
                            'supported_pattern': True, 'pattern': 'north_east_chamfer'},
              'supported_geometry': {'supports_ne_corner_sampling': True},
              'floors_y': [1,5,9], 'palette': palette, 'surface_maps': {}, 'storeys': [], 'courses': [],
              'roof_section': {'last_floor_y': 9, 'samples': [{'axis': 'x', 'heights_y': [13,13]}]},
              'roof_slices': [{'axis':'x', 'fixed_coordinate':10, 'start':6, 'end':7,
                               'start_y':9, 'end_y':13, 'legend':{'.':'air','R':'roof','G':'glass'},
                               'rows':[{'y':13,'cells':'RR'}, {'y':12,'cells':'.R'},
                                       {'y':11,'cells':'G.'}, {'y':10,'cells':'..'}, {'y':9,'cells':'WW'}]}]}
    for face in ('street_north','street_east','chamfer','party_west','party_south'):
        report['surface_maps'][face] = {'coordinates_xz':[[6,6],[7,6]], 'start_y':2,
            'inward_step_xz':[0,1], 'depths':[-3,-2,-1,0,1,2,3],
            'palette_ids_y_axis_depth': [[[1,1,1,0,1,1,1], [1,0,1,1,2,1,1]],
                                        [[1,1,1,3,1,1,1], [1,1,1,2,1,1,1]],
                                        [[1,1,1,0,1,1,1], [1,1,1,0,1,1,1]],
                                        [[1,1,1,0,1,1,1], [1,1,1,0,1,1,1]],
                                        [[1,1,1,0,1,1,1], [1,1,1,0,1,1,1]],
                                        [[1,1,1,0,1,1,1], [1,1,1,0,1,1,1]],
                                        [[1,1,1,0,1,1,1], [1,1,1,0,1,1,1]]]}
    for index, y_range in enumerate(([2,4],[6,8])):
        report['storeys'].append({'storey':index,'y_range':y_range, 'faces':{
            face:{'opening_count':0, 'sampled_transmissive_groups_count':0,'openings':[]}
            for face in report['surface_maps']}})
    return report


class ArchitecturalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = fixture()
        self.plan = {'form':'corner_house','width':8,'depth':10,'storeys':2,'chamfer':3,'bay_pitch':6}

    def checks(self, plan=None, report=None):
        result = compare_plan(plan or self.plan, report or self.report)
        return {item['id']:item for item in result['checks']}

    def test_readable_material_grid_preserves_nonzero_air_and_coordinates(self):
        result = text_evidence(self.report, storey=0, include_roof=False)
        self.assertIn('north=-z; east=+x', result)
        self.assertIn('FACE chamfer | north-east diagonal', result)
        self.assertIn('0:6,6 1:7,6', result)
        self.assertIn('y=002 | #.', result)
        self.assertIn('y=003 | FG', result)
        self.assertIn('y=002 | -1', result)  # Real recess, independently of the skin air.
        self.assertIn('y=002 | .2', result)  # Outward occupancy does not overwrite the material grid.
        self.assertNotIn('palette_ids_y_axis_depth', result)
        self.assertNotIn('y=006 |', result)
        self.assertIn('a'*64, result)
        self.assertIn('b'*64, result)

    def test_roof_slice_keeps_actual_voids_and_nonroof_material(self):
        result = text_evidence(self.report, include_roof=True)
        self.assertIn('x slice @z=10; x=6..7 (west -> east)', result)
        self.assertIn('y=012 | .R', result)
        self.assertIn('y=011 | G.', result)
        self.assertIn('y=010 | ..', result)
        self.assertIn('no ridge, slope break or run/rise is inferred', result)
        legacy = copy.deepcopy(self.report)
        del legacy['roof_slices']
        self.assertIn('UNMEASURED: no per-y voxel slices', text_evidence(legacy))
        self.assertNotIn('y=013 | RR', text_evidence(legacy))

    def test_exact_supported_comparisons_fail_when_actual_measurement_changes(self):
        checks = self.checks()
        for name in ('width','depth','storeys','chamfer','party_west.sampled_transmissive_groups'):
            self.assertEqual(checks[name]['status'], 'pass')
            self.assertTrue(checks[name]['coordinates'])
        changed = copy.deepcopy(self.report)
        changed['footprint']['width'] = 7
        changed['footprint']['north_east_cut_cells'] = 2
        group = {'endpoints_xz':[[6,8],[6,8]],'y_range':[2,3], 'depth_counts':{'1':2}}
        face = changed['storeys'][0]['faces']['party_west']
        face.update(sampled_transmissive_groups_count=1, opening_count=1, openings=[group])
        checks = self.checks(report=changed)
        self.assertEqual(checks['width']['status'], 'fail')
        self.assertEqual(checks['chamfer']['status'], 'fail')
        leak = checks['party_west.sampled_transmissive_groups']
        self.assertEqual((leak['actual'],leak['expected'],leak['status']), (1,0,'fail'))
        self.assertEqual(leak['coordinates']['groups'][0]['openings'][0]['endpoints_xz'], [[6,8],[6,8]])

    def test_plan_pitch_never_invents_window_counts_or_roof_and_course_roles(self):
        checks = self.checks()
        for name in ('window_schedule','roof_profile','course_roles'):
            self.assertEqual(checks[name]['status'], 'unsupported')
            self.assertEqual(checks[name]['scope'], 'unscoped')
            self.assertIsNone(checks[name]['expected'])
        self.assertEqual(checks['form_orientation']['status'], 'unsupported')
        plan = {**self.plan,'bay_pitch':2,'roof_height':6}
        checks = self.checks(plan=plan)
        self.assertEqual(checks['window_schedule']['expected'], None)
        self.assertEqual(checks['roof_profile']['status'], 'unsupported')
        self.assertEqual(checks['roof_profile']['expected'], {'roof_height':6})

    def test_masonry_gap_keeps_coordinates_without_promoting_coverage_to_a_role(self):
        self.report['courses'] = [
            {'y':2, 'sampled_path_coverage_complete':False, 'stone_path_connection':{'connected':True},
             'faces':{'street_north':{'sample_count':2,'covered_cells':1,'longest_run':1,'gaps':[[1,1]],
                      'stone_path_connection':{'connected':True,'status':'measured'}}}},
            {'y':7,'faces':{},'stone_path_connection':{'connected':False}}]
        result = text_evidence(self.report, storey=0, include_roof=False)
        self.assertIn('"endpoints_xz":[[7,6],[7,6]]', result)
        self.assertIn('"sampled_path_coverage_complete":false,"stone_connected":true', result)
        self.assertNotIn('"y":7', result)
        course = self.checks()['course_roles']
        self.assertEqual(course['status'], 'unsupported')
        self.assertEqual(course['actual'][0]['faces']['street_north']['gaps'][0]['endpoints_xz'], [[7,6],[7,6]])

    def test_other_forms_cannot_inherit_corner_party_south_or_chamfer_assumptions(self):
        checks = self.checks(plan={**self.plan,'form':'street_house'})
        self.assertTrue(all(item['status'] == 'unsupported' for item in checks.values()))
        self.assertIsNone(checks['party_south.sampled_transmissive_groups']['expected'])
        checks = self.checks(plan={key:value for key,value in self.plan.items() if key != 'chamfer'})
        self.assertEqual(checks['chamfer']['status'], 'unsupported')
        unsupported = copy.deepcopy(self.report)
        unsupported['footprint']['supported_pattern'] = False
        checks = self.checks(report=unsupported)
        self.assertEqual(checks['chamfer']['status'], 'unsupported')
        self.assertEqual(checks['width']['status'], 'unsupported')

    def test_unmeasured_report_and_absent_storey_never_substitute_a_pass(self):
        report = {'status':'unmeasured','reason':'no supported foundation','source':self.report['source']}
        self.assertTrue(all(item['status']=='unsupported' for item in self.checks(report=report).values()))
        self.assertIn('no supported foundation', text_evidence(report))
        result = text_evidence(self.report, storey=99, include_roof=False)
        self.assertIn('requested storey is absent', result)
        self.assertNotIn('y=002 |', result)

    def test_payload_is_serializable_hash_bound_and_does_not_mutate_inputs(self):
        previous = copy.deepcopy(self.report)
        result = review_description(self.plan, self.report, storey=0)
        json.dumps(result)
        self.assertEqual(result['source'], self.report['source'])
        self.assertEqual(result['comparison']['source'], self.report['source'])
        self.assertEqual(self.report, previous)
        self.assertNotIn('overall_pass', result['comparison'])
        self.assertNotIn('game_acceptance', result['comparison'])

    def test_export_mutations_reach_text_and_comparison_without_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'candidate.schem'
            palette = ['minecraft:sandstone', 'minecraft:air', 'minecraft:glass',
                       'minecraft:spruce_planks', 'minecraft:deepslate_tiles']
            volume = np.full((16,16,16), 1, dtype=np.int32)
            volume[0,2:12,2:10] = 0
            for z in range(2,12):
                for x in range(2,10):
                    if 9-x+z-2 < 3:
                        volume[0,z,x] = 1
            for y in (1,5,9):
                volume[y,2:12,2:10] = np.where(volume[0,2:12,2:10] == 0, 3, 1)
            volume[1:10,2,2:7] = 0
            volume[1:10,5:12,9] = 0
            volume[1:10,2:12,2] = 0
            volume[1:10,11,2:10] = 0
            # A roof shell with a measured empty attic cell at y=11.
            volume[13,2:12,2:10] = 4
            write_schematic(path, volume, palette)
            before = measure(path)
            before_text = text_evidence(before, storey=0)
            self.assertIn('y=011 | ........', before_text)
            self.assertEqual(self.checks(report=before)['party_west.sampled_transmissive_groups']['status'], 'pass')
            volume[2:4,7,2] = 2
            write_schematic(path, volume, palette)
            after = measure(path)
            after_text = text_evidence(after, storey=0)
            self.assertIn('G', after_text.split('FACE party_west', 1)[1].split('FACE party_south', 1)[0])
            leak = self.checks(report=after)['party_west.sampled_transmissive_groups']
            self.assertEqual(leak['status'], 'fail')
            self.assertGreater(leak['actual'], 0)
            self.assertNotEqual(before['source']['sha256'], after['source']['sha256'])


if __name__ == '__main__':
    unittest.main()
