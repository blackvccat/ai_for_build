"""atlas_street1 detail profile：plan_for 校验与 design.build 主链的件库组装接入。

集成测试在临时 work_dir 里真实组装最小体量（34×31，北 5 开间/西 4 开间），
skip_render 不走渲染子进程；Node 注册表校验（validate_vanilla）用 monkeypatch
跳过——它是逐件+整栋的子进程调用，约占整楼构建时长的大半，而它自身的严格性已由
tests/test_atlas_assembly.py 的 StrictVanillaTests 真跑覆盖，这里要测的是主链接入，
不是注册表。两次构建字节一致证明 plan 路径的确定性。
"""
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from paris_builder import atlas_street1, design
from paris_builder import atlas_assembly as atlas


class AtlasStreet1PlanForTests(unittest.TestCase):
    def test_legal_corner_house_plan(self):
        plan = design.plan_for('corner_house', seed=1901, width=46, depth=42,
                               detail_profile='atlas_street1')
        self.assertEqual(plan.detail_profile, 'atlas_street1')
        self.assertEqual(plan.form, 'corner_house')
        self.assertEqual(plan.composition_profile, 'grouped_pavilions')
        # 边界：最小体量 34×31 任意相位都放得下塔亭 + 5/4 开间。
        edge = design.plan_for('corner_house', seed=1900, width=34, depth=31,
                               detail_profile='atlas_street1', composition_profile='flat_baseline')
        self.assertEqual(edge.width, 34)

    def test_rejects_non_corner_form(self):
        with self.assertRaisesRegex(ValueError, 'corner_house'):
            design.plan_for('street_house', width=40, depth=36,
                            detail_profile='atlas_street1')

    def test_rejects_undersized_or_missing_dimensions(self):
        for kwargs in ({'width': 33, 'depth': 36}, {'width': 40, 'depth': 30},
                       {'width': None, 'depth': 36}, {'width': 40, 'depth': None}):
            with self.assertRaisesRegex(ValueError, 'width >= 38'):
                design.plan_for('corner_house', detail_profile='atlas_street1', **kwargs)

    def test_rejects_kit_owned_parameters(self):
        for name, value in (('storeys', 6), ('bay_pitch', 6), ('chamfer', 2),
                            ('roof_height', 7)):
            with self.assertRaisesRegex(ValueError, '件库自带层序与节距'):
                design.plan_for('corner_house', width=40, depth=36,
                                detail_profile='atlas_street1', **{name: value})

    def test_unknown_profile_still_rejected_and_reference_rules_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'Unknown detail profile'):
            design.plan_for('corner_house', width=40, depth=36, detail_profile='atlas_x')
        plan = design.plan_for('street_house', width=24, depth=30,
                               detail_profile='reference_haussmann', bay_pitch=6)
        self.assertEqual(plan.detail_profile, 'reference_haussmann')

    def test_composition_is_explicit_and_cannot_leak_into_other_profiles(self):
        with self.assertRaisesRegex(ValueError, 'composition_profile requires'):
            design.plan_for('street_house', composition_profile='grouped_pavilions')
        with self.assertRaisesRegex(ValueError, 'Unknown composition'):
            design.plan_for('corner_house', width=46, depth=42,
                            detail_profile='atlas_street1', composition_profile='unknown')
        baseline = design.plan_for('corner_house', width=34, depth=31,
                                   detail_profile='atlas_street1', composition_profile='flat_baseline')
        self.assertEqual(baseline.describe()['composition_profile'], 'flat_baseline')

    def test_grouped_piers_are_budgeted_before_a_plan_is_accepted(self):
        # This size fits the old flat kit but not its grouped, wider-pier counterpart.
        with self.assertRaisesRegex(ValueError, '放不下最小体量'):
            design.plan_for('corner_house', seed=1901, width=38, depth=36,
                            detail_profile='atlas_street1')


class BaysWithinTests(unittest.TestCase):
    def test_grouped_count_uses_real_phase_and_maximizes_within_budget(self):
        from paris_builder.atlas_composition import wing_extra_width
        from paris_builder.atlas_assembly import bay_positions
        for phase in range(4):
            for start, limit, minimum in ((10, 46, 5), (11, 42, 4)):
                count = atlas_street1.composition_bays_within(
                    start, limit, phase, minimum, 'grouped_pavilions')
                span = lambda n: bay_positions(start, n, atlas_street1.RHYTHM, phase)[-1] + 6 + wing_extra_width(n, phase=phase)
                self.assertLessEqual(span(count), limit)
                self.assertGreater(span(count + 1), limit)

    def test_maximal_bays_within_limit(self):
        # seed=1901 → phase=1：节距自 5 起循环。width=40 → xs[-1]=33+6=39 可，再进一间 44 不可。
        self.assertEqual(atlas_street1.bays_within(10, 40, 1, 5), 6)
        self.assertEqual(atlas_street1.bays_within(11, 36, 1, 4), 5)
        # 最小体量边界：phase=0 时 5 开间 xs[-1]=28 → 34 恰好，4 开间 zs[-1]=25 → 31 恰好。
        self.assertEqual(atlas_street1.bays_within(10, 34, 0, 5), 5)
        self.assertEqual(atlas_street1.bays_within(11, 31, 0, 4), 4)

    def test_limit_below_minimum_massing_raises(self):
        with self.assertRaisesRegex(ValueError, '放不下最小体量'):
            atlas_street1.bays_within(10, 33, 0, 5)


class BuildFromPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # work_dir 必须在项目树内：Assembler 的派生件按 ROOT 相对路径记账，
        # 系统临时目录会让 register_derived 的 relative_to(ROOT) 失败。
        cls.temp = tempfile.TemporaryDirectory(dir=atlas_street1.ROOT / 'runs')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work_a = Path(cls.temp.name) / 'a'
        cls.work_b = Path(cls.temp.name) / 'b'
        plan = design.plan_for('corner_house', seed=1900, width=34, depth=31,
                               detail_profile='atlas_street1', composition_profile='flat_baseline')
        cls.plan = plan
        # validate_vanilla 是 node 子进程校验，此处跳过（理由见模块 docstring）；
        # atlas_street1 与 atlas_assembly 各自持有一个全局引用，都要 patch。
        # 返回形状带 independent_read：write_report 会读 roundtrip_changed_voxels。
        registry = {'status': 'PASS', 'independent_read': {'roundtrip_changed_voxels': 0}}
        patches = (patch.object(atlas_street1, 'validate_vanilla', return_value=registry),
                   patch.object(atlas, 'validate_vanilla', return_value=registry))
        for patcher in patches:
            patcher.start()
        try:
            cls.scene, cls.manifest = design.build(plan, work_dir=cls.work_a)
            repeat_scene, repeat_manifest = design.build(plan, work_dir=cls.work_b)
        finally:
            for patcher in patches:
                patcher.stop()
        cls.repeat_manifest = repeat_manifest
        cls.first = (cls.work_a / 'ATLAS-HOUSE.schem').read_bytes()
        cls.second = (cls.work_b / 'ATLAS-HOUSE.schem').read_bytes()

    def test_validation_and_audit_pass(self):
        self.assertEqual(self.manifest['validation']['status'], 'PASS')
        self.assertEqual(self.manifest['atlas_audit']['status'], 'PASS')
        self.assertGreater(self.manifest['atlas_audit']['matched_cells'], 0)

    def test_two_builds_are_byte_identical(self):
        self.assertEqual(self.first, self.second)
        self.assertEqual(hashlib.sha256(self.first).hexdigest(),
                         self.manifest['schematic']['sha256'])

    def test_manifest_carries_plan_and_atelier_shaped_stamp_audit(self):
        self.assertEqual(self.manifest['plan'], self.plan.describe())
        declarations = self.manifest['stamp_audit']
        self.assertIsInstance(declarations, list)
        self.assertTrue(declarations)
        for entry in declarations:
            self.assertEqual(set(entry), {'id', 'x', 'y', 'z', 'turns', 'role',
                                          'clip', 'allow_scene_clip'})
        policy = self.manifest['stamp_audit_policy']
        self.assertIsInstance(policy, list)
        self.assertTrue(policy)
        for rule in policy:
            self.assertEqual(set(rule), {'from_role', 'to_role',
                                         'bbox_xyz_half_open', 'reason'})
        self.assertEqual(self.manifest['atlas_audit']['overwrite_policy'], policy)
        self.assertEqual(self.manifest['atlas_tier_semantics'], 'post_framework_complete_kit')

    def test_minimum_massing_bays_and_scene_size(self):
        self.assertEqual(self.manifest['scene']['width'], 34)
        self.assertEqual(self.manifest['scene']['depth'], 31)
        self.assertEqual(len(self.manifest['scene']['bays_north']), 5)
        self.assertEqual(len(self.manifest['scene']['bays_west']), 4)

    def test_work_dir_is_required(self):
        with self.assertRaisesRegex(ValueError, 'work_dir'):
            design.build(self.plan)

    def test_build_from_plan_rechecks_form_and_massing(self):
        bad_form = design.HousePlan(form='street_house', scheme='haussmann_apartment',
                                    width=40, depth=36, storeys=6, seed=1900,
                                    detail_profile='atlas_street1')
        with self.assertRaisesRegex(ValueError, 'corner_house'):
            atlas_street1.build_from_plan(bad_form, work_dir=self.work_a)
        too_small = design.HousePlan(form='corner_house', scheme='haussmann_apartment',
                                     width=30, depth=31, storeys=6, seed=1900,
                                     detail_profile='atlas_street1')
        with self.assertRaisesRegex(ValueError, '放不下最小体量'):
            atlas_street1.build_from_plan(too_small, work_dir=self.work_a)

    def test_design_build_rejects_foreign_scene_for_atlas(self):
        from paris_builder.architecture import Scene
        with self.assertRaisesRegex(ValueError, 'own scene'):
            design.build(self.plan, scene=Scene(40, 50, 40), work_dir=self.work_a)


if __name__ == '__main__':
    unittest.main()
