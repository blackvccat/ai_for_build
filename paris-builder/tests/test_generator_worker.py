"""Fresh worker must keep snapshot code and read the shared technique libraries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from paris_builder import technique_library, generator_repair as repair
from paris_builder.architecture import Scene
from paris_builder.exporter import write_schematic
from paris_builder.schematic import load_schematic


ROOT = Path(__file__).resolve().parents[1]
DETAIL_ID = 'v3:s3-window-bay'
FIXTURE_DESIGN = '''from pathlib import Path
from paris_builder.architecture import Scene
from paris_builder import technique_library as library

def plan_for(**values):
    return values

def build(plan, tier):
    detail = library.load_detail('v3:s3-window-bay')
    height, depth, width = detail.volume.shape
    scene = Scene(width, height, depth)
    placed = library.stamp(scene, 'v3:s3-window-bay', 0, 0, 0)
    return scene, {'placed': placed, 'design_source': str(Path(__file__).resolve()),
        'loaded_detail_hash': detail.voxel_state_hash(),
        'library_source': str(Path(library.__file__).resolve()),
        'library_root': str(library.ROOT), 'library_paths': [str(library.V1), str(library.V2), str(library.V3)],
        'library_counts': library.catalogue()['counts']}
'''


class GeneratorWorkerTests(unittest.TestCase):
    def test_atlas_snapshot_uses_patched_frame_and_preserves_composition_workdirs(self):
        """Fresh process executes the active atlas module, not the live fallback."""
        frame_source = ROOT / 'src/paris_builder/atlas_street1_frame.py'
        original_hash = hashlib.sha256(frame_source.read_bytes()).hexdigest()
        base = repair.sources({})
        self.assertIn('atlas_street1_frame.py', base)
        self.assertIn('atlas_composition.py', base)
        with tempfile.TemporaryDirectory(dir=ROOT / 'runs') as temporary:
            folder = Path(temporary)
            version = repair.create_version(folder, base, [{
                'file': 'atlas_street1_frame.py', 'before': "PLINTH = 'minecraft:stone'",
                'after': "PLINTH = 'minecraft:granite'",
            }], 'Offline worker snapshot fixture; no architectural acceptance')
            output = folder / 'worker'
            result = repair.worker(version, 'validate', {
                'form': 'corner_house', 'scheme': 'haussmann_apartment',
                'width': 46, 'depth': 42, 'seed': 1901, 'detail_profile': 'atlas_street1',
                'composition_profile': 'flat_baseline',
            }, 0, output)
            self.assertEqual(result['status'], 'PASS', result.get('log'))
            self.assertTrue(result['deterministic'])
            self.assertGreater(result['tests'], 40)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['composition']['mode'], 'flat_baseline')
            self.assertEqual(manifest['atlas_tier_semantics'], 'bare_massing')
            self.assertEqual(manifest['materials']['plinth'], 'minecraft:granite')
            self.assertEqual(manifest['stamp_audit'], [])
            self.assertIn('minecraft:granite', load_schematic(output / 'candidate.schem').id_to_state)
            self.assertTrue((output / 'atlas-work/frame.json').is_file())
            self.assertTrue((output / 'atlas-work-repeat/frame.json').is_file())
        self.assertEqual(original_hash, hashlib.sha256(frame_source.read_bytes()).hexdigest())

    def test_snapshot_and_legacy_workers_read_shared_library_without_changing_sources(self):
        detail = technique_library.load_detail(DETAIL_ID)
        library_source = ROOT / 'src/paris_builder/technique_library.py'
        shared_hash = hashlib.sha256(library_source.read_bytes()).hexdigest()
        expected_paths = [str(technique_library.V1), str(technique_library.V2), str(technique_library.V3)]
        expected_counts = technique_library.catalogue()['counts']
        with tempfile.TemporaryDirectory() as temporary:
            height, depth, width = detail.volume.shape
            expected_scene = Scene(width, height, depth)
            technique_library.stamp(expected_scene, DETAIL_ID, 0, 0, 0)
            expected_file = Path(temporary) / 'expected.schem'
            write_schematic(expected_file, expected_scene.volume, expected_scene.palette)
            expected_stamp_hash = load_schematic(expected_file).voxel_state_hash()
            for snapshot_library in (True, False):
                with self.subTest(snapshot_library=snapshot_library):
                    folder = Path(temporary) / ('snapshot' if snapshot_library else 'legacy')
                    version = folder / 'generator'
                    version.mkdir(parents=True)
                    (version / 'design.py').write_text(FIXTURE_DESIGN, encoding='utf-8')
                    if snapshot_library:
                        (version / 'technique_library.py').write_bytes(library_source.read_bytes())
                    before = {path.name: path.read_bytes() for path in version.iterdir()}
                    output = folder / 'output'
                    output.mkdir()
                    request = folder / 'request.json'
                    request.write_text(json.dumps({'version': {'id': 'fixture-version', 'path': str(version)},
                                                   'plan': {}, 'tier': 3}), encoding='utf-8')
                    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONUTF8': '1'}
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/generator_worker.py'),
                                             'build', str(request), str(output)],
                                            cwd=ROOT, env=env, capture_output=True, text=True,
                                            encoding='utf-8', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
                    self.assertEqual(manifest['design_source'], str((version / 'design.py').resolve()))
                    expected_source = version / 'technique_library.py' if snapshot_library else library_source
                    self.assertEqual(manifest['library_source'], str(expected_source.resolve()))
                    self.assertEqual(manifest['library_root'], str(ROOT))
                    self.assertEqual(manifest['library_paths'], expected_paths)
                    self.assertEqual(manifest['library_counts'], expected_counts)
                    self.assertEqual(manifest['loaded_detail_hash'], detail.voxel_state_hash())
                    self.assertGreater(manifest['placed'], 0)
                    self.assertEqual(load_schematic(output / 'candidate.schem').voxel_state_hash(), expected_stamp_hash)
                    self.assertEqual(before, {path.name: path.read_bytes() for path in version.iterdir() if path.is_file()})
                    receipt = json.loads((output / 'worker-result.json').read_text(encoding='utf-8'))
                    self.assertTrue(receipt['deterministic'])
        self.assertEqual(shared_hash, hashlib.sha256(library_source.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
