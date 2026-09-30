"""Trusted fresh-process adapter for task-local generator modules."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np
import paris_builder

ROOT = Path(__file__).resolve().parents[1]


def main():
    action, request_path, out = sys.argv[1:]
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    version = request['version']; output = Path(out)
    paris_builder.__path__.insert(0, version['path'])
    from paris_builder import design, haussmann_reference
    from paris_builder.exporter import write_schematic
    from paris_builder.operations import write_json
    haussmann_reference.ROOT = ROOT
    if action == 'validate':
        suite = unittest.TestSuite()
        for pattern in ('test_design.py', 'test_haussmann_reference.py', 'test_architecture.py'):
            suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=pattern))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        if not result.wasSuccessful(): raise ValueError('Generator regression tests failed')
    plan_keys = ('form', 'scheme', 'width', 'depth', 'storeys', 'seed', 'bay_pitch',
                 'entrance_fraction', 'roof_height', 'detail_profile')
    plan = design.plan_for(**{key: value for key, value in request['plan'].items() if key in plan_keys})
    scene, manifest = design.build(plan, tier=request['tier'])
    repeat, _ = design.build(plan, tier=request['tier'])
    same = np.array_equal(np.array(scene.palette)[scene.volume], np.array(repeat.palette)[repeat.volume])
    if not same: raise ValueError('Patched generator is not deterministic')
    write_schematic(output / 'candidate.schem', scene.volume, scene.palette, name='Versioned generator')
    write_json(output / 'manifest.json', {**manifest, 'generator_version': version['id']})
    plots = None
    if action == 'state_lab':
        from paris_builder.executor import state_lab
        plots = state_lab(scene, output)
    write_json(output / 'worker-result.json', {'status': 'PASS', 'deterministic': bool(same),
        'generator_version': version['id'], 'plots': plots, 'tests': result.testsRun if action == 'validate' else None})


if __name__ == '__main__': main()
