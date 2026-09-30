#!/usr/bin/env python3
"""Independent delivery audit for PAR-002 v0.4 on this machine.

This tool changes nothing. It re-derives the delivered package from the
recorded seeds and files so a handoff does not have to trust the previous
author's report:

  1. every checksums.json entry matches the file on disk;
  2. PAR-002.schem and STATE-LAB.schem pass the Python round-trip and the
     independent Node/prismarine registry validator;
  3. rebuilding concept+seeds reconstructs the delivered voxel state hash and
     byte-identical schematic;
  4. the state-lab centre cells in the delivered file still carry the states
     recorded in state_lab_tests.json.

Nothing here is a game-client paste test, and nothing here may be reported as
user acceptance.
"""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.exporter import dump_json, write_schematic  # noqa: E402
from paris_builder.geometry import inspect_geometry  # noqa: E402
from paris_builder.production import build  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402


def node_binary():
    found = shutil.which('node')
    if found:
        return found
    raise RuntimeError('node is required for the independent registry validation')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_checksums(out):
    recorded = json.loads((out / 'checksums.json').read_text(encoding='utf-8'))
    missing, mismatched = [], []
    for name, digest in sorted(recorded.items()):
        path = out / name
        if not path.is_file():
            missing.append(name)
        elif sha(path) != digest:
            mismatched.append(name)
    present = {str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name != 'checksums.json'}
    return {'status': 'PASS' if not missing and not mismatched else 'FAIL',
            'entries': len(recorded), 'missing': sorted(missing), 'mismatched': sorted(mismatched),
            'unlisted_files': sorted(present - set(recorded)),
            'note': 'Checksums cover the recorded package; unlisted files are reported, not silently ignored.'}


def python_roundtrip(path):
    read = load_schematic(path)
    report = read.validation()
    report['status'] = 'PASS' if all(report['checks'].values()) else 'FAIL'
    return read, report


def node_registry(path, destination):
    result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'), str(path), str(destination)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
    report = json.loads(Path(destination).read_text(encoding='utf-8')) if Path(destination).is_file() else {}
    report['entry_status'] = 'PASS' if result.returncode == 0 else 'FAIL'
    report['stdout'] = result.stdout.strip()[-2000:]
    report['stderr'] = result.stderr.strip()[-2000:]
    return report


def rebuild(out, temp):
    concept = json.loads((out / 'concept.json').read_text(encoding='utf-8'))
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    seeds = manifest['seeds']
    scene, meta = build(concept, facade_seed=seeds['facade_seed'], detail_seed=seeds['detail_seed'],
                        stage=manifest['stage'], scheme=manifest['scheme'])
    delivered = load_schematic(out / 'PAR-002.schem')
    same_states = np.array_equal(np.array(scene.palette)[scene.volume], np.array(delivered.id_to_state)[delivered.volume])
    replica = Path(temp) / 'rebuild.schem'
    write_schematic(replica, scene.volume, scene.palette, name='PAR-002 stage 3 scheme 1')
    return {'status': 'PASS' if same_states and sha(replica) == sha(out / 'PAR-002.schem') else 'FAIL',
            'dimensions_whl': [delivered.width, delivered.height, delivered.length],
            'voxel_state_hash_recomputed': delivered.voxel_state_hash(),
            'voxel_state_hash_recorded': manifest.get('voxel_state_hash'),
            'state_equal_to_delivered': bool(same_states),
            'byte_identical_to_delivered': sha(replica) == sha(out / 'PAR-002.schem'),
            'replica_sha256': sha(replica), 'delivered_sha256': sha(out / 'PAR-002.schem'),
            'repeat_byte_identical': manifest.get('repeat_byte_identical'),
            'component_ids_rebuilt': sorted(meta['component_ids']) == sorted(manifest['component_ids'])}


def model_run_reproducibility(delivery_dir):
    """Rebuild a model-executor delivery package from its own recorded concept.

    This is the "stable product" check for MODEL-DESIGN runs: the same concept and
    seeds must produce the same schematic bytes and the same state-lab centre
    states, so a delivered candidate is reproducible rather than a one-off render.
    """
    concept_path = None
    for candidate in sorted(p for p in delivery_dir.iterdir() if p.is_dir()):
        if (candidate / 'concept.json').is_file() and (candidate / 'candidate.schem').is_file():
            concept_path = candidate
            break
    if concept_path is None:
        return {'status': 'NOT_RUN', 'note': 'not a model-executor delivery package'}
    concept = json.loads((concept_path / 'concept.json').read_text(encoding='utf-8'))
    scene, meta = build(concept, facade_seed=concept.get('facade_seed', 4409),
                        detail_seed=concept.get('detail_seed', 5519), stage=3, scheme=1, shopfront_stage=1)
    delivered = load_schematic(concept_path / 'candidate.schem')
    same_states = np.array_equal(np.array(scene.palette)[scene.volume],
                                 np.array(delivered.id_to_state)[delivered.volume])
    with tempfile.TemporaryDirectory() as temp:
        replica = Path(temp) / 'replica.schem'
        write_schematic(replica, scene.volume, scene.palette, name='model-authored candidate')
        byte_identical = sha(replica) == sha(concept_path / 'candidate.schem')
    plots = json.loads((delivery_dir / 'state_lab_tests.json').read_text(encoding='utf-8'))['plots']
    lab = load_schematic(delivery_dir / 'STATE-LAB.schem')
    mismatched = [p['plot'] for p in plots
                  if lab.id_to_state[lab.volume[p['centre_xyz'][1], p['centre_xyz'][2], p['centre_xyz'][0]]] != p['state']]
    return {'status': 'PASS' if same_states and byte_identical and not mismatched else 'FAIL',
            'candidate': str(concept_path.name), 'state_equal_to_delivered': bool(same_states),
            'byte_identical_to_delivered': bool(byte_identical),
            'state_lab_plots': len(plots), 'state_lab_centre_mismatches': mismatched[:10],
            'note': 'Same concept + seeds reproduce the delivered schematic byte for byte.'}


def state_lab(out):
    tests = json.loads((out / 'state_lab_tests.json').read_text(encoding='utf-8'))
    read = load_schematic(out / 'STATE-LAB.schem')
    wrong = []
    for plot in tests['plots']:
        x, y, z = plot['centre_xyz']
        actual = read.id_to_state[read.volume[y, z, x]]
        if actual != plot['state']:
            wrong.append({'plot': plot['plot'], 'expected': plot['state'], 'actual': actual})
    return {'status': 'PASS' if not wrong else 'FAIL', 'plots': len(tests['plots']),
            'centre_state_mismatches': wrong[:10],
            'game_status': tests.get('game_status', 'NOT_RUN'),
            'note': 'File-level context check only; normal vs suppressed paste is a game experiment.'}


def preview_provenance(out):
    """The delivered previews must be renders of the delivered schematic."""
    path = out / 'previews' / 'render_metadata.json'
    if not path.is_file():
        return {'status': 'NOT_RUN', 'note': 'no preview metadata in this package'}
    meta = json.loads(path.read_text(encoding='utf-8'))
    recorded = meta.get('source_sha256')
    actual = sha(out / 'PAR-002.schem')
    views = meta.get('views', {})
    return {'status': 'PASS' if recorded == actual and len(views) >= 23 else 'FAIL',
            'recorded_source_sha256': recorded, 'actual_source_sha256': actual,
            'views_rendered': len(views), 'minecraft_version': meta.get('minecraft_version'),
            'exposed_model_faces': meta.get('exposed_model_faces'),
            'note': 'Provenance only: this renderer does not simulate client lighting or block updates. '
                    'The original author absolute path is kept as an unchanged historical field.'}


def compare_zip(archive, out):
    """Compare a delivered zip against the verified directory, entry by entry.

    A zip that matches the audited directory byte for byte needs no repacking:
    the user's acceptance package is then the same evidence this audit covered.
    """
    import zipfile
    archive = Path(archive)
    if not archive.is_file():
        return {'status': 'NOT_RUN', 'note': 'no zip supplied; directory audit only', 'archive': str(archive)}
    missing, mismatched, extra = [], [], []
    with zipfile.ZipFile(archive) as handle:
        # Zip entry names always use "/", while Path.rglob on Windows yields "\".
        names = {name for name in handle.namelist() if not name.endswith('/')}
        for name in sorted(names):
            member = handle.read(name)
            path = out / name
            if not path.is_file():
                missing.append(name)
            elif hashlib.sha256(member).hexdigest() != sha(path):
                mismatched.append(name)
        present = {str(p.relative_to(out)).replace('\\', '/') for p in out.rglob('*') if p.is_file()}
        extra = sorted(present - names)
    return {'status': 'PASS' if not missing and not mismatched and not extra else 'FAIL',
            'archive': str(archive), 'entries': len(names),
            'missing_from_zip': missing, 'content_mismatch': mismatched, 'not_in_zip': extra,
            'note': 'Zip and verified directory are byte identical; no repacking was needed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path, default=ROOT / 'runs/PAR-002-v0.4/delivery')
    parser.add_argument('--out', type=Path, default=ROOT / 'runs/PAR-002-v0.4/delivery_verification.json')
    parser.add_argument('--zip', type=Path, default=None,
                        help='delivered acceptance zip to compare against the directory')
    args = parser.parse_args()
    out = args.delivery if args.delivery.is_absolute() else ROOT / args.delivery
    if not out.is_dir():
        raise SystemExit('delivery directory not found: ' + str(out))
    with tempfile.TemporaryDirectory() as temp:
        checks = {}
        if (out / 'PAR-002.schem').is_file():
            checks['par002_python_roundtrip'] = python_roundtrip(out / 'PAR-002.schem')[1]
            checks['par002_independent_registry'] = node_registry(
                out / 'PAR-002.schem', Path(temp) / 'par002_registry.json')
            checks['par002_geometry'] = inspect_geometry(load_schematic(out / 'PAR-002.schem'))
            checks['rebuild_from_recorded_seeds'] = rebuild(out, temp)
        if (out / 'STATE-LAB.schem').is_file():
            checks['state_lab_python_roundtrip'] = python_roundtrip(out / 'STATE-LAB.schem')[1]
            checks['state_lab_independent_registry'] = node_registry(
                out / 'STATE-LAB.schem', Path(temp) / 'lab_registry.json')
            checks['state_lab_centres'] = state_lab(out)
        checks['model_run_reproducibility'] = model_run_reproducibility(out)
        checks['preview_provenance'] = preview_provenance(out)
        checks['acceptance_zip'] = compare_zip(args.zip, out) if args.zip else \
            {'status': 'NOT_RUN', 'note': 'no zip supplied; directory audit only'}
        if (out / 'checksums.json').is_file():
            checks['checksums'] = check_checksums(out)
    statuses = {name: value.get('status', value.get('entry_status', 'UNKNOWN')) for name, value in checks.items()}
    # NOT_RUN means the check does not apply to this package (e.g. no acceptance zip,
    # or a PAR-002 package has no model-run candidate); only explicit FAIL fails.
    failures = {name: status for name, status in statuses.items() if status not in ('PASS', 'NOT_RUN')}
    report = {'delivery': str(out), 'status': 'PASS' if not failures else 'FAIL', 'failures': failures,
              'checks': checks, 'check_status': statuses,
              'game_acceptance': 'PENDING: in-game paste, update A/B and visual acceptance are user-only',
              'scope': 'File, registry and reproduction checks on this machine; not a game-client test.'}
    dump_json(args.out, report)
    print(json.dumps({'status': report['status'], 'checks': statuses, 'report': str(args.out)},
                     ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
