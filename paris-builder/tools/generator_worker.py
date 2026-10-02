"""Trusted fresh-process adapter for task-local generator modules."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np
import paris_builder

ROOT = Path(__file__).resolve().parents[1]


def bind_library_resources(library, project_root=ROOT):
    """Use snapshot functions with the shared read-only knowledge files.

    Snapshot placement changes ``__file__`` and therefore the library's derived
    ROOT/V1/V2/V3 paths. Rebase knowledge paths (including index/catalog aliases)
    without changing the snapshot's source location or unrelated source paths.
    """
    source_root = library.ROOT
    for name, value in list(vars(library).items()):
        if not isinstance(value, Path):
            continue
        try:
            relative = value.relative_to(source_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == 'knowledge':
            setattr(library, name, project_root / relative)
    library.ROOT = project_root


def main():
    action, request_path, out = sys.argv[1:]
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    version = request['version']; output = Path(out)
    paris_builder.__path__.insert(0, version['path'])
    from paris_builder import technique_library
    bind_library_resources(technique_library)
    from paris_builder import design, haussmann_reference
    from paris_builder.exporter import write_schematic
    from paris_builder.operations import write_json
    haussmann_reference.ROOT = ROOT
    if action == 'validate':
        suite = unittest.TestSuite()
        patterns = ('test_design.py', 'test_haussmann_reference.py', 'test_architecture.py')
        if request['plan'].get('detail_profile') == 'atlas_street1':
            patterns += ('test_atlas_composition.py', 'test_atlas_stage_conformance.py')
        for pattern in patterns:
            suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=pattern))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        if not result.wasSuccessful(): raise ValueError('Generator regression tests failed')
    plan_keys = ('form', 'scheme', 'width', 'depth', 'storeys', 'seed', 'bay_pitch',
                 'entrance_fraction', 'roof_height', 'detail_profile', 'composition_profile')
    plan = design.plan_for(**{key: value for key, value in request['plan'].items() if key in plan_keys})
    if request['plan'].get('detail_profile') == 'atlas_street1':
        scene, manifest = design.build(plan, tier=request['tier'], work_dir=output / 'atlas-work')
        repeat, _ = design.build(plan, tier=request['tier'], work_dir=output / 'atlas-work-repeat')
    else:
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
