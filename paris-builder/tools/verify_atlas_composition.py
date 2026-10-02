"""Measure composition features in an exported atlas schematic.

Composition is a target contract. Assembly rows only locate search boxes; no
anchor, role, declared audit result or generator parameter is counted as an
observed block. This receipt does not judge visual design quality or game state.

    python -X utf8 tools/verify_atlas_composition.py runs/ATLAS-PLAN-P2-v0.1
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.schematic import load_schematic  # noqa: E402


PASS, FAIL, UNSUPPORTED = 'measured_pass', 'measured_fail', 'unsupported'
AIR = {'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'}
DARK_CHEEKS = {'minecraft:deepslate_brick_wall', 'minecraft:cobbled_deepslate_wall',
               'minecraft:deepslate_tile_wall', 'minecraft:polished_deepslate_wall'}
LIGHT_CHEEKS = {'minecraft:andesite_wall', 'minecraft:diorite_wall',
                'minecraft:calcite', 'minecraft:bone_block', 'minecraft:quartz_block'}
ROOF_MINERALS = {
    'minecraft:andesite', 'minecraft:andesite_slab', 'minecraft:polished_andesite_slab',
    'minecraft:smooth_stone', 'minecraft:smooth_stone_slab', 'minecraft:tuff',
    'minecraft:blackstone', 'minecraft:polished_blackstone', 'minecraft:basalt',
    'minecraft:polished_basalt', 'minecraft:smooth_basalt', 'minecraft:deepslate',
    'minecraft:cobbled_deepslate', 'minecraft:deepslate_bricks',
    'minecraft:cracked_deepslate_bricks', 'minecraft:deepslate_tiles',
    'minecraft:polished_deepslate', 'minecraft:deepslate_coal_ore',
    'minecraft:gray_concrete', 'minecraft:gray_concrete_powder',
    'minecraft:light_gray_concrete_powder', 'minecraft:gray_wool',
    'minecraft:cyan_terracotta', 'minecraft:rooted_dirt',
}


def _base(state):
    return state.split('[', 1)[0]


def _box(row):
    low = [int(value) for value in row['anchor']]
    high = [low[i] + int(row['size_whd'][i]) for i in range(3)]
    return low + high


class Measurement:
    def __init__(self, read, rows):
        self.read, self.rows = read, rows
        self.volume = read.volume
        self.names = [_base(value) for value in read.id_to_state]
        self.air_ids = [i for i, name in enumerate(self.names) if name in AIR]

    def state(self, x, y, z):
        if not (0 <= x < self.read.width and 0 <= y < self.read.height
                and 0 <= z < self.read.length):
            return None
        return self.names[int(self.volume[y, z, x])]

    def rows_for(self, role, axis=None):
        result = [row for row in self.rows if row['role'] == role]
        return sorted(result, key=lambda row: row['anchor'][axis]) if axis is not None else result

    def points(self, box, names=None):
        x0, y0, z0, x1, y1, z1 = box
        x0, y0, z0 = max(0, x0), max(0, y0), max(0, z0)
        x1, y1, z1 = min(self.read.width, x1), min(self.read.height, y1), min(self.read.length, z1)
        if x0 >= x1 or y0 >= y1 or z0 >= z1:
            return []
        part = self.volume[y0:y1, z0:z1, x0:x1]
        ids = ([i for i, name in enumerate(self.names) if name in names]
               if names is not None else self.air_ids)
        mask = np.isin(part, ids)
        if names is None:
            mask = ~mask
        return [[int(x + x0), int(y + y0), int(z + z0)] for y, z, x in np.argwhere(mask)]


def _result(ident, title, status, criterion, evidence, limitation=None):
    result = {'id': ident, 'title': title, 'status': status,
              'criterion': criterion, 'evidence': evidence}
    if limitation:
        result['limitation'] = limitation
    return result


def _window_planes(measured, composition):
    evidence, good = [], True
    for side in ('north', 'west'):
        axis, normal = (0, 2) if side == 'north' else (2, 0)
        targets = composition['wings'][side]['bays']
        rows = measured.rows_for('bay-noble-' + side, axis)
        observations = []
        if len(rows) != len(targets):
            good = False
        for index, row in enumerate(rows):
            box = _box(row)
            # Use only the middle two window columns, excluding shared piers.
            box[axis] += 1
            box[axis + 3] = box[axis] + 2
            doors = measured.points(box, {'minecraft:iron_door'})
            front = min((point[normal] for point in doors), default=None)
            observations.append({'bay': index, 'search_bbox_xyz_half_open': box,
                                 'actual_door_cells': len(doors),
                                 'actual_front_normal_coordinate': front})
        ordinary = [row['actual_front_normal_coordinate'] for row, target in zip(observations, targets)
                    if target['projection'] == 0 and row['actual_front_normal_coordinate'] is not None]
        baseline = Counter(ordinary).most_common(1)[0][0] if ordinary else None
        for row, target in zip(observations, targets):
            row['target_projection'] = target['projection']
            row['actual_projection_from_recess'] = (baseline - row['actual_front_normal_coordinate']
                                                    if baseline is not None
                                                    and row['actual_front_normal_coordinate'] is not None else None)
            if row['actual_projection_from_recess'] != target['projection']:
                good = False
        evidence.append({'wing': side, 'actual_recess_window_plane': baseline,
                         'expected_bays': len(targets), 'located_bays': len(rows), 'bays': observations})
    return _result('wing_window_projection', '两翼窗面按构图分组进退', PASS if good else FAIL,
                   'In each wing, final iron-door window planes advance from the measured recess plane by the target projection.',
                   evidence, 'This measures window planes; it does not prove that the whole facade reads as a convincing pavilion.')


def _dormer_cheeks(measured, composition):
    evidence, good = [], True
    for side in ('north', 'west'):
        axis, normal = (0, 2) if side == 'north' else (2, 0)
        windows = measured.rows_for('bay-noble-' + side, axis)
        targets = composition['wings'][side]['bays']
        dormers = sorted(measured.rows_for('dormer-upper-' + side)
                         + measured.rows_for('dormer-pavilion-' + side),
                         key=lambda row: row['anchor'][axis])
        expected = [bay for bay in targets if bay['dormer_grade'] != 'none']
        if len(dormers) != len(expected) or len(windows) != len(targets):
            good = False
        for row, target in zip(dormers, expected):
            doors = measured.points(_box(row), {'minecraft:iron_door'})
            middle_y = row['anchor'][1] + 3
            probes = [point for point in doors if point[1] == middle_y]
            sample = []
            if probes:
                front = min(point[normal] for point in probes)
                cross = [point[axis] for point in probes if point[normal] == front]
                for at in (min(cross) - 1, max(cross) + 1):
                    xyz = [0, middle_y, 0]
                    xyz[axis], xyz[normal] = at, front
                    sample.append({'xyz': xyz, 'actual_block': measured.state(*xyz)})
            dark = sum(item['actual_block'] in DARK_CHEEKS for item in sample)
            light = sum(item['actual_block'] in LIGHT_CHEEKS for item in sample)
            measured_grade = 'pavilion' if dark == 2 and light == 0 else (
                'ordinary' if light > 0 else 'unresolved')
            aligned = False
            if probes and target['index'] < len(windows):
                wing_doors = measured.points(_box(windows[target['index']]), {'minecraft:iron_door'})
                if wing_doors:
                    aligned = (min(point[axis] for point in probes) == min(point[axis] for point in wing_doors)
                               and max(point[axis] for point in probes) == max(point[axis] for point in wing_doors))
            if measured_grade != target['dormer_grade'] or not aligned:
                good = False
            evidence.append({'wing': side, 'bay': target['index'], 'target_grade': target['dormer_grade'],
                             'actual_grade': measured_grade, 'actual_cheek_samples': sample,
                             'actual_dormer_aligned_to_window_columns': aligned})
    return _result('dormer_grade_echo', '深浅颊板呼应凸出开间并对窗轴', PASS if good else FAIL,
                   'Sample final flank blocks beside the upper window: pavilion flanks are dark walls; ordinary flanks include a lighter wall. Their actual window columns align with the noble window below.',
                   evidence, 'Ordinary source cheeks are light gray andesite rather than pure white. Only the sampled front flank course is measured.')


def _plants(measured, composition):
    evidence, good = [], True
    for side in ('north', 'west'):
        axis = 0 if side == 'north' else 2
        rows = measured.rows_for('plant-noble-' + side, axis)
        targets = [bay for bay in composition['wings'][side]['bays'] if bay['plant_accent']]
        bay_rows = measured.rows_for('bay-noble-' + side, axis)
        if len(rows) != len(targets):
            good = False
        for row, target in zip(rows, targets):
            box = _box(row)
            stems = measured.points(box, {'minecraft:attached_pumpkin_stem'})
            red_box = measured.points(box, {'minecraft:granite_wall'})
            yellow = measured.points(box, {'minecraft:hay_block'})
            shades = measured.points(box, {'minecraft:oak_trapdoor'})
            within_bay = False
            if target['index'] < len(bay_rows):
                noble = _box(bay_rows[target['index']])
                within_bay = bool(stems) and all(noble[axis] <= p[axis] < noble[axis + 3]
                                               and noble[1] <= p[1] < noble[4] for p in stems)
            intact = len(stems) == 2 and len(red_box) == 2 and len(yellow) == 2 and len(shades) == 2
            if not intact or not within_bay:
                good = False
            evidence.append({'wing': side, 'bay': target['index'], 'actual_stem_cells': stems,
                             'actual_red_box_cells': len(red_box), 'actual_yellow_backing_cells': len(yellow),
                             'actual_shade_cells': len(shades), 'actual_accent_within_noble_bay': within_bay})
    return _result('noble_source_accent_retention', '贵族层焦点开间保留完整源花箱', PASS if good else FAIL,
                   'Every target accent box contains two stems, two granite-wall planter cells, two hay backing cells and two source shade cells, located within the final noble bay.',
                   evidence, 'This proves the added noble-layer detail and its location; the broader visual dominance of that floor remains a visual-review question.')


def _chimneys(measured, composition):
    evidence, good = [], True
    for side in ('north', 'west'):
        axis = 0 if side == 'north' else 2
        rows = measured.rows_for('chimney-' + side, axis)
        targets = composition['wings'][side]['chimney_anchors']
        bay_rows = measured.rows_for('bay-noble-' + side, axis)
        if len(rows) != len(targets):
            good = False
        for row, target in zip(rows, targets):
            box = _box(row)
            mouths = measured.points(box, {'minecraft:flower_pot'})
            levels = {point[1] for point in mouths}
            offsets = sorted(point[axis] for point in mouths)
            contiguous = bool(offsets) and offsets == list(range(offsets[0], offsets[0] + len(offsets)))
            vertical = []
            for mouth in mouths:
                missing = [y for y in range(box[1], mouth[1])
                           if measured.state(mouth[0], y, mouth[2]) in AIR
                           or measured.state(mouth[0], y, mouth[2]) is None]
                vertical.append({'mouth_xyz': mouth, 'actual_air_gaps_below_mouth': missing})
            focus_aligned = False
            if mouths and target['bay'] < len(bay_rows):
                doors = measured.points(_box(bay_rows[target['bay']]), {'minecraft:iron_door'})
                if doors:
                    centre = (min(p[axis] for p in doors) + max(p[axis] for p in doors)) / 2
                    focus_aligned = abs((offsets[0] + offsets[-1]) / 2 - centre) <= 1
            if (len(mouths) != target['target_flues'] or len(levels) != 1 or not contiguous
                    or any(item['actual_air_gaps_below_mouth'] for item in vertical) or not focus_aligned):
                good = False
            evidence.append({'wing': side, 'target_focus_bay': target['bay'],
                             'expected_flues': target['target_flues'], 'actual_mouths': mouths,
                             'actual_contiguous_row': contiguous, 'actual_shafts': vertical,
                             'actual_cluster_aligned_to_focus_within_one_cell': focus_aligned})
    return _result('chimney_complete_focus_clusters', '焦点上方烟囱簇的五口与轴身完整存留', PASS if good else FAIL,
                   'Count final pot mouths, check their contiguous horizontal row and occupied shaft columns, and measure their alignment to the target focal window.',
                   evidence, 'These are source representations of flues; no functional chimney or interior smoke path is asserted.')


def _crown(measured, composition):
    rows = measured.rows_for('turret-finial')
    if not composition['corner']['finial'] or len(rows) != 1:
        status = UNSUPPORTED if not composition['corner']['finial'] else FAIL
        return [
            _result('corner_crown_above_ridge', '角亭冠饰最高点高于翼楼屋脊', status,
                    'Measure the final crown highest voxel and the actual wing ridge.', {'located_crowns': len(rows)}),
            _result('corner_crown_platform_contact', '冠饰平台与屋顶有实体接触', status,
                    'Measure structural contact immediately below the final crown platform.', {'located_crowns': len(rows)}),
        ]
    box = _box(rows[0])
    crown_points = measured.points(box)
    crown_top = max((point[1] for point in crown_points), default=None)
    exclude = [_box(row) for row in measured.rows if row['role'] in ('turret-finial', 'turret-cap')
               or row['role'].startswith(('dormer-', 'chimney-'))]

    def excluded(point):
        return any(all(other[i] <= point[i] < other[i + 3] for i in range(3)) for other in exclude)

    ridges = []
    for side in ('north', 'west'):
        points = set()
        for row in measured.rows_for('roof-' + side):
            points.update(tuple(point) for point in measured.points(_box(row), ROOF_MINERALS)
                          if not excluded(point))
        top = max((point[1] for point in points), default=None)
        ridges.append({'wing': side, 'actual_roof_surface_top_y': top,
                       'actual_top_samples_xyz': [list(point) for point in sorted(points)
                                                 if point[1] == top][:12]})
    roof_top = max((row['actual_roof_surface_top_y'] for row in ridges
                    if row['actual_roof_surface_top_y'] is not None), default=None)
    height_status = (UNSUPPORTED if roof_top is None else
                     PASS if crown_top is not None and crown_top > roof_top else FAIL)
    height = _result('corner_crown_above_ridge', '角亭冠饰最高点高于翼楼屋脊', height_status,
                     'Final crown highest occupied voxel must be higher than both measured roof surface maxima outside roof accessories.',
                     {'actual_crown_top_y': crown_top, 'actual_wing_roof_top_y': roof_top,
                      'actual_height_advantage': crown_top - roof_top if crown_top is not None and roof_top is not None else None,
                      'ridges': ridges}, 'The highest crown voxel may be a small ornament. Visual dominance and substantial tower height are not proved.')
    platform = measured.points([box[0], box[1], box[2], box[3], box[1] + 1, box[5]],
                               {'minecraft:andesite', 'minecraft:stone', 'minecraft:stone_bricks',
                                'minecraft:gravel', 'minecraft:andesite_slab',
                                'minecraft:stone_brick_slab', 'minecraft:polished_andesite_slab'})
    contacts = [point for point in platform
                if measured.state(point[0], point[1] - 1, point[2]) in ROOF_MINERALS]
    contact = _result('corner_crown_platform_contact', '冠饰平台与屋顶有实体接触',
                      PASS if platform and contacts else FAIL,
                      'At least one final platform voxel directly touches a mineral roof voxel below it; report the contact area.',
                      {'actual_platform_cells': len(platform), 'actual_roof_contact_cells': len(contacts),
                       'actual_contact_fraction': len(contacts) / len(platform) if platform else 0,
                       'actual_contact_samples_xyz': contacts[:20]},
                      'Voxel adjacency does not prove continuous support of each cantilever, slab-model contact or structural plausibility.')
    return [height, contact]


def verify(run_dir):
    run_dir = Path(run_dir).resolve()
    composition_path = run_dir / 'composition.json'
    assembly_path = run_dir / 'assembly.json'
    schematic_path = run_dir / 'ATLAS-HOUSE.schem'
    composition = json.loads(composition_path.read_text(encoding='utf-8'))
    assembly = json.loads(assembly_path.read_text(encoding='utf-8'))
    read = load_schematic(schematic_path)
    measured = Measurement(read, assembly['stamps'])
    predicates = [_window_planes(measured, composition), _dormer_cheeks(measured, composition),
                  _plants(measured, composition), _chimneys(measured, composition)]
    predicates.extend(_crown(measured, composition))
    predicates.extend([
        _result('noble_window_grade', '凸出开间窗套升级与主层视觉强弱', UNSUPPORTED,
                'Requires an independently classified enhanced-window variant and whole-facade visual review.',
                {}, 'Current construction supplies projection, wider piers and added plants; the window piece remains the same source variant.'),
        _result('firewall_roof_profile_and_white_gap', '端防火墙随实际屋坡且无白缺口', UNSUPPORTED,
                'Requires distinguishing source cornice and party-wall ownership plus block-model ray visibility.',
                {}, 'Palette voxels alone cannot distinguish valid pale cornice material from pale firewall exposure or detect thin-wall model apertures.'),
        _result('window_sandwich_visibility', '窗面三明治未被实芯遮堵', UNSUPPORTED,
                'Requires per-window model rays through frozen door leaves and depth layers.',
                {}, 'The measured presence of doors and glass does not establish exterior visibility through partial block models.'),
        _result('band_end_cleanup', '阳台带与檐口末端无碎片', UNSUPPORTED,
                'Requires complete band-end model geometry and a termination classification.',
                {}, 'Neighboring non-air voxels or source-piece retention do not prove finished architectural end caps.'),
        _result('composition_visual_quality', '整栋有主次且转角成为焦点', UNSUPPORTED,
                'Whole-building multi-view visual review followed by user game acceptance.',
                {}, 'No deterministic composition measurements transfer visual or game approval.'),
    ])
    counts = Counter(row['status'] for row in predicates)
    return {
        'schema_version': 1, 'run': run_dir.name,
        'status': 'MEASURED_FAIL' if counts[FAIL] else 'MEASURED_PARTIAL',
        'schematic': {'path': str(schematic_path), 'sha256': sha256(schematic_path.read_bytes()).hexdigest(),
                      'dimensions_whd': [read.width, read.height, read.length]},
        'inputs': {'composition_sha256': sha256(composition_path.read_bytes()).hexdigest(),
                   'assembly_locator_sha256': sha256(assembly_path.read_bytes()).hexdigest()},
        'method': 'Final exported schematic only for observations; composition for targets; assembly stamps for search-box location only.',
        'status_counts': {key: counts[key] for key in (PASS, FAIL, UNSUPPORTED)},
        'predicates': predicates, 'visual_acceptance': 'NOT_ESTABLISHED', 'game_acceptance': 'NOT_RUN',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    receipt = verify(args.run)
    path = args.out or args.run / 'geometry_receipt.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(path.resolve()), 'status': receipt['status'],
                      'status_counts': receipt['status_counts'],
                      'schematic_sha256': receipt['schematic']['sha256']}, ensure_ascii=False))
    if receipt['status_counts'][FAIL]:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
