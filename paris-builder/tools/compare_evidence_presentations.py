"""Paired live JSON/ASCII comprehension trials on one frozen schematic.

This measures objective evidence reading only, never architectural acceptance.
All truth values are recomputed from exported voxel states independently of the
facade_section report. Credentials are obtained from local Windows DPAPI only.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.architectural_evidence import text_evidence
from paris_builder.facade_section import measure, review_evidence
from paris_builder.local_credentials import load_key
from paris_builder.providers import MultimodalClient, ProviderError
from paris_builder.schematic import AIR_BLOCKS, base_block, load_schematic


VIEWS = ('front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back')
DEFAULT_CANDIDATE = ROOT / 'runs/ATELIER-A9B3C7EE/revision-59/facades/facade-1/candidate.schem'
LIMITATIONS = [
    'One fixed building, one sampled storey, 18 correlated objective questions and few paired trials; no population-level superiority claim.',
    'Temperature zero does not guarantee provider determinism; calls share the same model name but the remote deployment can change.',
    'Both arms include identical seven images and the same plan. JSON roof_slices already contain material character rows; this comparison is the complete evidence presentation, not a pure JSON-versus-ASCII encoding experiment.',
    'Ground truth uses the supported material-family classifier and four-step rays; it measures sampled cells, not complete window semantics or partial block-model light transmission.',
    'Questions target factual extraction. Accuracy does not prove mansard/style compliance, aesthetic quality, workflow approval or user-only game acceptance.',
    'Saved source/image hashes prove byte identity; the model receives the same client JPEG conversions, not original PNG byte streams.',
]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _groups(points):
    """Independent breadth-first count in a sampled y/index plane."""
    remaining = set(points)
    total = 0
    while remaining:
        total += 1
        queue = deque([remaining.pop()])
        while queue:
            y, index = queue.popleft()
            for point in ((y-1,index),(y+1,index),(y,index-1),(y,index+1)):
                if point in remaining:
                    remaining.remove(point)
                    queue.append(point)
    return total


def independent_questions(schematic, storey):
    scene = load_schematic(schematic)
    names = [base_block(value) for value in scene.id_to_state]
    def state(x,y,z):
        return names[int(scene.volume[y,z,x])] if 0 <= x < scene.width and 0 <= y < scene.height and 0 <= z < scene.length else None
    foundation = [(x,z) for z in range(scene.length) for x in range(scene.width)
                  if (name := state(x,0,z)) and any(token in name for token in ('sandstone','stone_bricks','quartz'))
                  and not name.endswith(('_slab','_stairs','_wall'))]
    if not foundation:
        raise ValueError('No supported independent foundation')
    xs,zs = zip(*foundation)
    x0,x1,z0,z1 = min(xs),max(xs),min(zs),max(zs)
    footprint = set(foundation)
    cut = 0
    while (x1-cut,z0) not in footprint and x1-cut >= x0:
        cut += 1
    selected_y = [y for y in range(scene.height)
                  if sum(state(x,y,z).endswith('_planks') for z in range(z0,z1+1) for x in range(x0,x1+1)) >= len(foundation)*.45]
    floors = [y for y in selected_y if y+1 not in selected_y]
    if not 0 <= storey < len(floors)-1:
        raise ValueError('Independent requested floor interval absent')
    lo,hi = floors[storey]+1,floors[storey+1]-1
    middle_y = (lo+hi)//2
    paths = {
        'street_north':[(x,z0,0,1) for x in range(x0+1,x1-cut+1)],
        'street_east':[(x1,z,-1,0) for z in range(z0+cut,z1)],
        'chamfer':[(x1-cut+d,z0+d,-1,1) for d in range(cut+1)],
        'party_west':[(x0,z,1,0) for z in range(z0,z1+1)],
        'party_south':[(x,z1,0,-1) for x in range(x0,x1+1)]}
    def opening(cell,y):
        x,z,dx,dz = cell
        for depth in range(4):
            name = state(x+depth*dx,y,z+depth*dz)
            if name and 'glass' in name:
                return depth,'glass'
            if name not in AIR_BLOCKS:
                return None
        return 4,'portal'
    observed = {}
    for face,path in paths.items():
        rays = {(y,i):sample for y in range(lo,hi+1) for i,cell in enumerate(path)
                if (sample := opening(cell,y)) is not None}
        observed[face] = {'count':_groups(rays),
                         'glass_depth_counts':dict(sorted(Counter(str(depth) for depth,kind in rays.values() if kind == 'glass').items())),
                         'glass_depths':sorted(set(depth for depth,kind in rays.values() if kind == 'glass')),
                         'row_glass_indices':[i for i,cell in enumerate(path)
                                              if (sample := opening(cell,middle_y)) and sample[1]=='glass']}
    # Slice positions reproduce the sampling policy from independently read bounds.
    fixed_z = z0+(z1-z0)//4
    fixed_x = x0+(x1-x0)//4
    last_floor = floors[-1]
    roof = lambda name: bool(name and ('deepslate' in name or 'blackstone' in name))
    x_row_y = last_floor+1
    z_row_y = min(last_floor+3,scene.height-1)
    x_row = [state(x,x_row_y,fixed_z) for x in range(x0,x1+1)]
    z_row = [state(fixed_x,z_row_y,z) for z in range(z0,z1+1)]
    roof_y = [y for y in range(last_floor,scene.height) for x in range(x0,x1+1) if roof(state(x,y,fixed_z))]
    questions = []
    def add(identifier,prompt,expected,coordinates):
        questions.append({'id':identifier,'prompt':prompt,'expected':expected,'coordinates':coordinates})
    add('Q01','What is the fixed z coordinate of the street_north sampled skin? Return one integer.',z0,{'face':'street_north'})
    add('Q02','What is the fixed x coordinate of the street_east sampled skin? Return one integer.',x1,{'face':'street_east'})
    add('Q03','Return the first and last [x,z] coordinates of the north-east chamfer sampling path as [[x,z],[x,z]], in sampling order.',
        [list(paths['chamfer'][0][:2]),list(paths['chamfer'][-1][:2])],{'face':'chamfer'})
    for index,face in enumerate(paths,4):
        add(f'Q{index:02d}',f'For storey {storey} (y={lo}..{hi}), how many four-neighbour connected sampled transmissive groups are on {face}? Count groups, not architectural windows or bays. Return an integer.',
            observed[face]['count'],{'face':face,'storey':storey,'y_range':[lo,hi]})
    add('Q09',f'For street_north in storey {storey}, count glass-reaching sample cells by inward ray depth, excluding portal rays. Return an object mapping depth string to integer cell count.',
        observed['street_north']['glass_depth_counts'],{'face':'street_north','y_range':[lo,hi]})
    for identifier,face in (('Q10','street_east'),('Q11','chamfer')):
        add(identifier,f'For {face} in storey {storey}, return the sorted unique inward ray depths at which glass is reached. Exclude portal rays. Return an integer array.',
            observed[face]['glass_depths'],{'face':face,'y_range':[lo,hi]})
    for identifier,face in (('Q12','street_north'),('Q13','street_east'),('Q14','chamfer')):
        add(identifier,f'At y={middle_y} on {face}, return all zero-based sample-column indices whose inward ray reaches glass before an opaque block (depth 0..3). Return a sorted integer array.',
            observed[face]['row_glass_indices'],{'face':face,'y':middle_y})
    add('Q15',f'On the actual x roof slice at z={fixed_z}, y={x_row_y}, x={x0}..{x1}, how many cells are air? Return an integer; do not fill from top heights.',
        sum(name in AIR_BLOCKS for name in x_row),{'axis':'x','fixed_z':fixed_z,'y':x_row_y,'x_range':[x0,x1]})
    add('Q16',f'On that actual x roof slice at z={fixed_z}, y={x_row_y}, x={x0}..{x1}, how many cells are roof-family R (deepslate/blackstone)? Return an integer.',
        sum(roof(name) for name in x_row),{'axis':'x','fixed_z':fixed_z,'y':x_row_y,'x_range':[x0,x1]})
    add('Q17',f'On the x roof slice at z={fixed_z}, x={x0}..{x1}, what is the highest y containing any roof-family R cell at/above last_floor_y? Include spikes if present. Return an integer, or null if none.',
        max(roof_y) if roof_y else None,{'axis':'x','fixed_z':fixed_z,'x_range':[x0,x1]})
    add('Q18',f'On the actual z roof slice at x={fixed_x}, y={z_row_y}, z={z0}..{z1}, how many cells are air? Return an integer.',
        sum(name in AIR_BLOCKS for name in z_row),{'axis':'z','fixed_x':fixed_x,'y':z_row_y,'z_range':[z0,z1]})
    return questions,{'bounds_xz':[x0,z0,x1,z1], 'cut':cut,'floors_y':floors,'storey_y_range':[lo,hi],
                      'paths':{face:[list(cell[:2]) for cell in path] for face,path in paths.items()},
                      'observed':observed,'voxel_state_hash':scene.voxel_state_hash()}


def freeze(args):
    original = args.schematic.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    plan_source = args.plan.resolve() if args.plan else original.parent/'worker-input.json'
    plan_data = json.loads(plan_source.read_text(encoding='utf-8'))
    plan = plan_data.get('plan',plan_data)
    image_dir = args.images.resolve() if args.images else original.parent/'previews'
    metadata = json.loads((image_dir/'render_metadata.json').read_text(encoding='utf-8'))
    original_hash = digest(original)
    if metadata.get('source_sha256') != original_hash:
        raise ValueError('Image render metadata does not match the frozen schematic hash')
    candidate = out/'candidate.schem'
    if candidate.exists() and digest(candidate) != original_hash:
        raise ValueError('Output already contains a different frozen schematic; use a new --out')
    if not candidate.exists():
        shutil.copy2(original,candidate)
    images = []
    image_manifest = []
    (out/'images').mkdir(exist_ok=True)
    for view in VIEWS:
        source = image_dir/(view+'.png')
        target = out/'images'/(view+'.png')
        source_hash = digest(source)
        if target.exists() and digest(target) != source_hash:
            raise ValueError('Output has a different frozen view: '+view)
        if not target.exists():
            shutil.copy2(source,target)
        images.append(target)
        image_manifest.append({'view':view,'path':str(target),'sha256':source_hash,'original_path':str(source)})
    report = measure(candidate)
    if report.get('status') != 'measured' or report['source']['sha256'] != original_hash:
        raise ValueError('Measured report is unavailable or hash mismatch')
    questions,verification = independent_questions(candidate,args.storey)
    if report['source']['voxel_state_hash'] != verification['voxel_state_hash'] or report['footprint']['bounds_xz'] != verification['bounds_xz'] or report['floors_y'] != verification['floors_y']:
        raise ValueError('Independent report/source geometry mismatch')
    scope = next(row for row in report['storeys'] if row['storey']==args.storey)
    for face,observed in verification['observed'].items():
        if scope['faces'][face]['sampled_transmissive_groups_count'] != observed['count']:
            raise ValueError('Independent sampled group mismatch: '+face)
        if [list(point) for point in report['surface_maps'][face]['coordinates_xz']] != verification['paths'][face]:
            raise ValueError('Independent sampled path mismatch: '+face)
    dump(out/'plan.json',plan)
    dump(out/'report_v2.json',report)
    dump(out/'ground_truth.json',{'method':'Independent schematic state lookup, foundation bounds, broad wood plate bands, breadth-first sampled group counts and actual roof slice cells. No manifest geometry used.',
                                'source_sha256':original_hash,'questions':questions,'verification':verification})
    raw = review_evidence(report,storey=args.storey,include_roof=True)
    dump(out/'json_evidence.json',raw)
    characters = text_evidence(report,storey=args.storey,include_roof=True)
    (out/'character_evidence.txt').write_text(characters,encoding='utf-8')
    dump(out/'render_metadata.json',metadata)
    manifest = {'original_schematic':str(original),'schematic':str(candidate),'source_sha256':original_hash,
                'voxel_state_hash':report['source']['voxel_state_hash'],'report_sha256':digest(out/'report_v2.json'),
                'plan_sha256':digest(out/'plan.json'),'images':image_manifest,'views':list(VIEWS)}
    dump(out/'freeze_manifest.json',manifest)
    public_questions = [{key:value for key,value in question.items() if key != 'expected'} for question in questions]
    shared = ('This is an objective exported-voxel evidence reading task, not a style, aesthetic or acceptance review. '
              'Face names use a fixed NE-corner sampling convention; do not infer real street use from material alone. '
              'Use only supplied evidence; do not infer window counts from bay_pitch. '
              'Return exactly one JSON object {"responses":{"Q01":value,...,"Q18":value}}. '
              'Include all IDs exactly once and no other keys. Answer numbers as integers, indices/depth sets as sorted arrays, '
              'and coordinate pairs as arrays. Use null for an unavailable answer; do not add explanations. '
              'Questions include sampled transmissive groups, not semantic windows. Air must be identified by state name, not palette ID 0.\n'
              'SAME DESIGN PLAN:\n'+json.dumps(plan,ensure_ascii=False)+'\nSAME QUESTIONS:\n'+json.dumps(public_questions,ensure_ascii=False)+'\nEVIDENCE:\n')
    prompts = {'json':shared+json.dumps(raw,ensure_ascii=False,separators=(',',':')),
               'characters':shared+characters}
    for arm,prompt in prompts.items():
        (out/(arm+'_prompt.txt')).write_text(prompt,encoding='utf-8')
    return out,images,manifest,questions,prompts


def assert_frozen(out,manifest):
    for field,path in (('source_sha256',manifest['schematic']),('source_sha256',manifest['original_schematic']),
                       ('report_sha256',out/'report_v2.json'),('plan_sha256',out/'plan.json')):
        if digest(path) != manifest[field]:
            raise ValueError('Frozen artifact changed: '+str(path))
    for item in manifest['images']:
        if digest(item['path']) != item['sha256']:
            raise ValueError('Frozen image changed: '+item['view'])


def presentation_error_audit(out, summary):
    """Check whether failed facts were actually retained in each supplied format."""
    raw = json.loads((out/'json_evidence.json').read_text(encoding='utf-8'))
    characters = (out/'character_evidence.txt').read_text(encoding='utf-8')
    truth = json.loads((out/'ground_truth.json').read_text(encoding='utf-8'))
    questions = {question['id']:question for question in truth['questions']}
    failed = {score['id'] for result in summary['results'] for score in result['questions'] if not score['correct']}
    audit = []
    for identifier in sorted(failed):
        question = questions[identifier]
        coords = question['coordinates']
        json_value = character_value = None
        evidence_row = None
        if identifier in ('Q12','Q13','Q14'):
            face,y = coords['face'],coords['y']
            data = raw['surface_maps'][face]
            rays = data['palette_ids_y_axis_depth'][y-data['start_y']]
            indices = []
            for index,ray in enumerate(rays):
                for depth in range(4):
                    palette_id = ray[data['depths'].index(depth)]
                    name = base_block(raw['palette'][palette_id]) if palette_id is not None else None
                    if name and 'glass' in name:
                        indices.append(index)
                        break
                    if name not in AIR_BLOCKS:
                        break
            json_value = indices
            face_block = characters.split('FACE '+face+' | ',1)[1].split('\nFACE ',1)[0]
            ray_block = face_block.split('inward ray:',1)[1].split('\noutward occupancy:',1)[0]
            evidence_row = next(line.split(' | ',1)[1] for line in ray_block.splitlines() if line.startswith(f'y={y:03d} | '))
            character_value = [index for index,char in enumerate(evidence_row) if char in '0123']
        elif identifier in ('Q15','Q16','Q18'):
            axis,y = coords['axis'],coords['y']
            fixed_axis = 'z' if axis=='x' else 'x'
            fixed = coords['fixed_'+fixed_axis]
            section = next(row for row in raw['roof_slices'] if row['axis']==axis and row['fixed_coordinate']==fixed)
            row = next(row['cells'] for row in section['rows'] if row['y']==y)
            target = 'R' if identifier=='Q16' else '.'
            json_value = row.count(target)
            section_block = characters.split(f'{axis} slice @{fixed_axis}={fixed};',1)[1]
            evidence_row = next(line.split(' | ',1)[1] for line in section_block.splitlines() if line.startswith(f'y={y:03d} | '))
            character_value = evidence_row.count(target)
        known = json_value is not None and character_value is not None
        audit.append({'id':identifier,'expected':question['expected'],'json_extracted':json_value,
                      'character_extracted':character_value,'evidence_row':evidence_row,
                      'information_retained_in_both':known and json_value==question['expected'] and character_value==question['expected'],
                      'observed_responses':{arm:[next(score['actual'] for score in result['questions'] if score['id']==identifier)
                                                 for result in summary['results'] if result['arm']==arm]
                                            for arm in ('json','characters')},
                      'interpretation':('Both supplied representations retain the correct fact. The observed error is evidence extraction/counting, not missing input information; internal model reasoning was not observed.'
                                        if known and json_value==question['expected'] and character_value==question['expected']
                                        else 'Automated extraction audit is unavailable for this question; no cause claim is made.')})
    result = {'questions':audit,'limits':'Cause labels describe observed output patterns and retained input facts, not the model internal reasoning.'}
    dump(out/'error_analysis.json',result)
    return result


def exact(actual,expected):
    if actual is None or actual == 'unknown':
        return False
    return type(actual) is type(expected) and actual == expected


def run(args):
    out,images,manifest,questions,prompts = freeze(args)
    credential = load_key()
    if not credential:
        raise ProviderError('Local DPAPI credential is unavailable')
    started = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    session = out/('trials-'+started)
    session.mkdir()
    config = {'model':args.model,'base_url':'https://api.deepseek.com','vision':True,
              'max_calls':args.repeats*4,'max_total_tokens':None,'max_output_tokens':2400,
              'timeout_seconds':180,'raw_reply_dir':str(session/'raw'),
              'request_options':{'temperature':0,'thinking':{'type':'disabled'}}}
    client = MultimodalClient(config,credential=credential)
    results = []
    expected_ids = {question['id'] for question in questions}
    for trial in range(1,args.repeats+1):
        order = ('json','characters') if trial%2 else ('characters','json')
        for position,arm in enumerate(order,1):
            attempts = []
            response = None
            for attempt in range(2):
                assert_frozen(out,manifest)
                prompt = prompts[arm]
                if attempt:
                    prompt += '\nFORMAT REPAIR: Return ONLY the required responses object with all 18 question IDs; no analysis, no additional fields.'
                before_usage = len(client.usage)
                began = time.monotonic()
                try:
                    reply,receipt = client.complete(prompt,images=images,max_tokens=2400)
                    receipt_images = receipt.get('image_evidence',[])
                    if [(item['path'],item['sha256']) for item in receipt_images] != [(item['path'],item['sha256']) for item in manifest['images']]:
                        raise ValueError('Provider receipt image identity mismatch')
                    if receipt['prompt_sha256'] != sha256(prompt.encode()).hexdigest():
                        raise ValueError('Provider receipt prompt identity mismatch')
                    compliant = isinstance(reply,dict) and set(reply)=={'responses'} and isinstance(reply.get('responses'),dict) and set(reply['responses'])==expected_ids
                    attempts.append({'attempt':attempt+1,'elapsed_seconds':round(time.monotonic()-began,3),
                                     'receipt':receipt,'response':reply,'compliant':compliant})
                    if compliant:
                        response = reply['responses']
                        break
                except ProviderError as error:
                    receipts = client.usage[before_usage:]
                    attempts.append({'attempt':attempt+1,'elapsed_seconds':round(time.monotonic()-began,3),
                                     'error':str(error),'receipts':receipts,'compliant':False})
            scores = [{'id':question['id'],'expected':question['expected'],
                       'actual':response.get(question['id']) if response else None,
                       'correct':exact(response.get(question['id']),question['expected']) if response else False}
                      for question in questions]
            result = {'trial':trial,'position':position,'arm':arm,'attempts':attempts,
                      'compliant':response is not None,'correct':sum(row['correct'] for row in scores),
                      'total':len(scores),'accuracy':sum(row['correct'] for row in scores)/len(scores),'questions':scores}
            dump(session/f'trial-{trial}-{arm}.json',result)
            results.append(result)
            print(json.dumps({'trial':trial,'position':position,'arm':arm,'correct':result['correct'],'total':result['total'],'attempts':len(attempts)},ensure_ascii=True),flush=True)
    summary = {'created_at_utc':started,'model':args.model,'temperature':0,'thinking':'disabled',
               'repeats':args.repeats,'paired_order':'odd JSON then characters; even characters then JSON',
               'freeze_manifest':manifest,'session':str(session),'limitations':LIMITATIONS,'results':results,'arms':{}}
    for arm in prompts:
        rows = [row for row in results if row['arm']==arm]
        receipts = [receipt for row in rows for attempt in row['attempts']
                    for receipt in ([attempt['receipt']] if 'receipt' in attempt else attempt.get('receipts',[]))]
        correct,total = sum(row['correct'] for row in rows),sum(row['total'] for row in rows)
        summary['arms'][arm] = {'correct':correct,'total':total,'accuracy':correct/total,
                               'compliant_trials':sum(row['compliant'] for row in rows),
                               'calls':sum(len(row['attempts']) for row in rows),
                               'prompt_tokens':sum(receipt.get('usage',{}).get('prompt_tokens',0) for receipt in receipts),
                               'completion_tokens':sum(receipt.get('usage',{}).get('completion_tokens',0) for receipt in receipts),
                               'latency_seconds':round(sum(attempt['elapsed_seconds'] for row in rows for attempt in row['attempts']),3),
                               'question_correct_trials':{question['id']:sum(next(score['correct'] for score in row['questions'] if score['id']==question['id']) for row in rows) for question in questions}}
    summary['paired_accuracy_difference_characters_minus_json'] = [
        next(row['accuracy'] for row in results if row['trial']==trial and row['arm']=='characters')-
        next(row['accuracy'] for row in results if row['trial']==trial and row['arm']=='json')
        for trial in range(1,args.repeats+1)]
    summary['error_analysis'] = presentation_error_audit(out,summary)
    assert_frozen(out,manifest)
    dump(session/'summary.json',summary)
    dump(out/'summary.json',summary)
    print(json.dumps({'summary':str(out/'summary.json'),'arms':summary['arms']},ensure_ascii=True),flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schematic',type=Path,default=DEFAULT_CANDIDATE)
    parser.add_argument('--plan',type=Path,help='JSON plan or worker-input.json containing plan')
    parser.add_argument('--images',type=Path,help='Directory containing the seven fixed previews and render_metadata.json')
    parser.add_argument('--out',type=Path,default=ROOT/'runs/ATELIER-A9B3C7EE/evidence-ab-20260930')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--storey',type=int,default=2)
    parser.add_argument('--model',default='deepseek-flash')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    run(args)


if __name__=='__main__':
    main()
