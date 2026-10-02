"""Task-local generator patches, immutable versions and independent validation."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .operations import ROOT, Operation, write_json
from .learning import read_json, digest
from .cancellation import checkpoint, on_interrupt

#: The modules a repair may rewrite. `technique_library.py` is included so the agent can
#: SEE the detail vocabulary it is instructed to use — without it in this list the agent
#: correctly reported "no technique_library id-stamp registry exists in this module set",
#: which is why 34 repaired generator versions never called a single library technique.
MODULES = ('design.py', 'house.py', 'facade.py', 'technique.py', 'haussmann_reference.py',
           'technique_library.py', 'atlas_assembly.py', 'atlas_composition.py',
           'atlas_street1.py', 'atlas_street1_frame.py', 'atlas_street1_composed.py')
STAGES = ('frameworks', 'facades', 'tier2', 'tier3')
WORKER = ROOT / 'tools/generator_worker.py'


def version_files(version):
    folder = Path(version['path'])
    manifest = read_json(folder / 'version.json')
    if manifest['id'] != version['id']:
        raise ValueError('生成器版本标识不匹配')
    for name, sha in manifest['files'].items():
        if name not in MODULES or digest(folder / name) != sha:
            raise ValueError('生成器版本文件已变化：' + name)
    files = {}
    for name in MODULES:
        candidate = folder / name
        if candidate.is_file():
            files[name] = candidate.read_text(encoding='utf-8')
        else:
            # A module added to MODULES after this version was cut is read from the live
            # source rather than invalidating the version: the agent keeps its accumulated
            # repairs AND gains sight of the newly listed module.
            files[name] = (ROOT / 'src/paris_builder' / name).read_text(encoding='utf-8')
    return files


def sources(task):
    if task.get('generator_version'):
        return version_files(task['generator_version'])
    return {name: (ROOT / 'src/paris_builder' / name).read_text(encoding='utf-8') for name in MODULES}


def validate_edit(before, after, name):
    old, new = ast.parse(before, filename=name), ast.parse(after, filename=name)
    def imports(tree):
        return [ast.dump(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    old_imports, new_imports = imports(old), imports(new)
    # The detail vocabulary lives in its own module and a repair MUST be able to import it,
    # so ADDING a technique_library import is allowed. Removing or altering any existing
    # import is still rejected.
    added = [row for row in new_imports if row not in old_imports]
    if added and not all('technique_library' in row for row in added):
        raise ValueError('生成器补丁不能新增导入依赖：' + name)
    if [row for row in old_imports if row not in new_imports]:
        raise ValueError('生成器补丁不能移除导入依赖：' + name)
    # Generation repairs may change geometry functions, not module initialization or source I/O.
    registries = {'FORMS', 'SCHEMES', 'TECHNIQUES', 'DEFAULT_SCHEME', 'TECHNIQUES_BY_TIER'}
    def mutable_assignment(node):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)): return False
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return (all(isinstance(target, ast.Name) and target.id in registries for target in targets)
                or isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                and node.value.value.startswith('minecraft:'))
    protected = lambda tree: [ast.dump(node) for node in tree.body
                             if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not mutable_assignment(node)]
    if protected(old) != protected(new):
        raise ValueError('生成器补丁不能改变模块初始化：' + name)
    risky = {'open', 'eval', 'exec', 'compile', 'getattr', 'setattr', '__import__', 'globals', 'locals',
             'read_text', 'read_bytes', 'write_text', 'write_bytes', 'unlink', 'rmdir', 'mkdir',
             'system', 'popen', 'run', 'Popen', 'replace', 'rename', 'load', 'loads', 'dump', 'dumps'}
    def calls(tree):
        return [ast.dump(node) for node in ast.walk(tree) if isinstance(node, ast.Call)
                and ((isinstance(node.func, ast.Name) and node.func.id in risky)
                     or (isinstance(node.func, ast.Attribute) and
                         (node.func.attr in risky or node.func.attr.startswith('__'))))]
    if calls(old) != calls(new):
        raise ValueError('生成器补丁不能新增或修改文件、进程及动态执行操作：' + name)


def create_version(folder, base, edits, reason):
    if not isinstance(edits, list) or not edits:
        raise ValueError('生成器修复缺少实际源码修改')
    changed = dict(base)
    for edit in edits:
        name, before, after = edit.get('file'), edit.get('before'), edit.get('after')
        if name not in MODULES or not isinstance(before, str) or not before or not isinstance(after, str):
            raise ValueError('生成器补丁路径或内容不合法')
        if changed[name].count(before) != 1 or before == after:
            raise ValueError('生成器补丁需要唯一且有变化的原文：' + name)
        changed[name] = changed[name].replace(before, after, 1)
    for name in MODULES:
        validate_edit(base[name], changed[name], name)
    hashes = {name: hashlib.sha256(text.encode('utf-8')).hexdigest() for name, text in changed.items()}
    ident = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    target = Path(folder) / 'generator-versions' / ident
    if not target.exists():
        temporary = target.with_name(ident + '.pending-' + uuid.uuid4().hex)
        temporary.mkdir(parents=True)
        for name, text in changed.items():
            (temporary / name).write_text(text, encoding='utf-8', newline='\n')
        write_json(temporary / 'version.json', {'id': ident, 'files': hashes, 'reason': reason, 'edits': edits})
        temporary.rename(target)
    return {'id': ident, 'path': str(target)}


def worker(version, action, plan, tier, output):
    version_files(version)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    request = output / 'worker-input.json'
    write_json(request, {'version': version, 'plan': plan, 'tier': tier})
    env = dict(os.environ)
    for name in list(env):
        if any(word in name.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            env.pop(name, None)
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['PYTHONIOENCODING'] = 'utf-8'
    with (output / 'worker.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-u', str(WORKER), action, str(request), str(output)],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        unregister = on_interrupt(process.terminate)
        try:
            process.wait()
            checkpoint()
        finally:
            unregister()
            if process.poll() is None: process.terminate(); process.wait()
    if process.returncode:
        return {'status': 'FAIL', 'log': (output / 'worker.log').read_text(encoding='utf-8')[-16000:]}
    return read_json(output / 'worker-result.json')


def repair_generator(task, folder, review, key, model, emit=None):
    from .harness_runtime import run_json
    base = sources(task)
    operation = Operation('generator.repair', {'stage': task['stage'], 'review': review,
        'base_version': task.get('generator_version')}, emit=emit)
    seen = set()
    proposals = set()
    feedback = None
    empty = 0
    try:
        while True:
            checkpoint()
            snapshot = operation.folder / ('source-' + str(len(seen)))
            snapshot.mkdir(exist_ok=True)
            for name, text in base.items(): (snapshot / name).write_text(text, encoding='utf-8', newline='\n')
            from .technique_library import brief as technique_brief
            context = {'generator_sources': {'root': str(snapshot), 'files': list(MODULES)},
                'failures': review, 'validation_feedback': feedback,
                # The detail vocabulary. Without it the repair agent could only rearrange
                # the eight techniques already hardcoded in the source, because none of the
                # project's own libraries were ever in its context.
                'technique_catalogue': technique_brief(),
                # 先造型后细节：修复必须落在正确的层，不能拿细节去掩盖形制问题。
                'layer_contract': {
                    'massing_tier0': '体量、屋顶形制（三段芒萨尔）、转角切角与檐口交圈、开间与洞口、入口轴、阳台大线',
                    'detail_tier123': '窗套窗台窗楣、竖梃横梃、层间带、店面与招牌带、栏杆、锈石、转角石、老虎窗、屋顶交接',
                    'order': '造型未成立不得堆细节；细节问题不得倒逼造型，除非结构形制本身不成立',
                },
                'module_roles': {'design.py': 'generic assembly and generic roof', 'house.py': 'structure and levels',
                    'facade.py': 'opening composition', 'technique.py': 'block decoration',
                    'haussmann_reference.py': 'reference_haussmann profile ONLY; inactive without that profile'}}
            atlas = task.get('intent', {}).get('detail_profile') == 'atlas_street1'
            if atlas:
                context['module_roles'].update({
                    'atlas_composition.py': 'Shared grouped bay, level and projection layout; no blocks',
                    'atlas_street1.py': 'atlas_street1 profile dispatch, source level order and budget',
                    'atlas_street1_frame.py': 'Tier0/1 realistic relief massing in four ordinary materials',
                    'atlas_street1_composed.py': 'Tier2/3 grouped source-piece assembly',
                    'atlas_assembly.py': 'Source-backed piece replay, rotation and finite stamp auditing',
                })
                context['layer_contract'] = {
                    'massing_tier01': '写实骨相：前凸基座/勒脚、凸出体、真窗洞进深、阳台挑板、叠涩檐口、'
                                     '曼萨德、坡面老虎窗小屋、转角塔亭与帽；四种普通素材质，不放源件',
                    'detail_tier23': '框架获审后才装配完整源库；使用 Assembler 的来源回放、原样状态及有限覆盖审计',
                    'order': '后续修复须保留已审 composition；改变布局必须 rollback_stage=frameworks 并重新评审',
                }
            proposal, receipt = run_json(key, model, json.dumps({'brief': task['brief'], 'intent': task['intent'],
                'failed_stage': task['stage'], 'validation_feedback': feedback,
                'design_language': task['brief'].get('design_language'),
                'active_profile_contract': context['layer_contract'] if atlas else None,
                'instruction': 'Diagnose and FIX the ACTIVE generator implementation. First call generator_source_map, '
                'and read_generator_source; use search_generator_source when needed. Trace design.build and detail_profile dispatch '
                'to identify code actually used by this plan. Follow active_profile_contract for the atlas stage boundaries '
                'and its Assembler source-audit path; source stamps never belong in its tier0/1 bare massing. '
                'Audit visual criticism against source geometry; future-tier '
                'decoration absence is not a defect. Return JSON diagnosis, reason, rollback_stage '
                '(frameworks|facades|tier2|tier3), edits [{file,before,after}]. Each before must be exact UNIQUE source '
                'text. This is a general architecture synthesis system, not a fixed Paris template engine. '
                'Treat the requested architectural rules as invariants and design choices as variable compositions. '
                'Preserve coherent variation, not literal copying. Modify generation functions/classes, registries '
                '(FORMS,SCHEMES,TECHNIQUES,DEFAULT_SCHEME,TECHNIQUES_BY_TIER) and minecraft block constants only; keep imports and other initialization, '
                'source-reading and all I/O unchanged. Preserve requested dimensions, form and seed. Fix roof form at '
                'frameworks, openings/composition at facades and decorations at their tier. Never alter tests, validation, '
                'review thresholds or acceptance. No arbitrary scripts or shell commands. Include concrete geometry '
                'reasoning. If no supported correction exists, return diagnosis=unsupported, reason and edits=[]. '
                'The technique_catalogue in the context lists the whole addressable detail vocabulary '
                '(45 families, 135 recipe variants, 43 annotated windows, 770 extracted details, 25 audited '
                'techniques). The id-stamp REGISTRY you look for IS `technique_library.registry()`: call it '
                'and you get every addressable id mapped to its entry, plus `__place__` and `__size__`. Do '
                'NOT record technique_library_stamp_dispatch as not_applicable — the registry exists in this '
                'module set. USE IT rather than hand-rolling blocks: '
                '`from .technique_library import stamp, registry, size_of` then '
                '`stamp(scene, "v1:window:window-source-00", x, y, z, turns=0)` writes that entry verbatim, '
                'block states already resolved. Worked example: to add a cornice band, pick a '
                '`v1:recipe:cornice-*` id, call `size_of(id)` for its bounds, then stamp it along the wall. '
                'Prefer naming an id over re-implementing geometry. '
                'IMPORTING OR COUNTING THE REGISTRY IS NOT USING IT. A previous revision called '
                '`len(registry())` into a local it never read and then recorded '
                'technique_library_stamp_dispatch as active, and the technical validation now fails such a '
                'claim: a stamp is only believed when the exported .schem actually contains the library '
                'entry\'s blocks. So if you record that capability as active you MUST (a) really call '
                '`stamp(...)` for at least one id, and (b) list every stamp in the manifest as '
                '`"stamp_audit": [{"id": <library id>, "x": <int>, "y": <int>, "z": <int>, "turns": <int>}]` '
                'using the same anchor coordinates you passed to `stamp`. The audit re-loads each id and '
                'compares its cells against the exported geometry cell by cell; a declared stamp that is '
                'entirely overwritten later, or an anchor that does not match, is a failed claim. If you '
                'cannot place a library entry, record the capability as not_applicable with the reason '
                'instead of claiming it active. '
                'You MAY replace a whole function: set `before` to the entire current function and `after` '
                'to your replacement. The validator accepts whole-function replacement, and a structural '
                'defect (roof section, storey hierarchy, bay anchoring, corner geometry) deserves a '
                'structural rewrite, not a nibble. Nibbling at a structural failure is why the same '
                'criticism returns every round. '
                'Validation failures must be repaired using the supplied feedback, not ignored.'}, ensure_ascii=False),
                phase='generator_repair', context=context, emit=emit, parent=operation.id,
                required_tools=('generator_source_map', 'read_generator_source'))
            # An unparseable model response leaves `proposal` as None. Calling .get() on
            # it aborted the whole run with "'NoneType' object has no attribute 'get'",
            # killing a repair that was otherwise progressing. Treat it as a failed round
            # and retry a bounded number of times instead of taking the run down.
            if not isinstance(proposal, dict):
                empty += 1
                feedback = {'status': 'FAIL',
                            'log': '模型未返回可解析的生成器修复方案（第 %d 次）' % empty}
                operation.event({'repair_response': feedback})
                if emit:
                    emit('agent_progress', {'summary': '修复方案无法解析，重试 %d/3' % empty})
                if empty >= 3:
                    raise ValueError('模型连续 3 次未返回可解析的生成器修复方案，已保存诊断并停下')
                continue
            # Surface what the agent actually reasoned. The proposal (diagnosis, reason,
            # patches) used to stay inside the operation record, so the page could only
            # ever show "生成器修复 / 执行中". The model runs with thinking disabled, so
            # this diagnosis IS its reasoning and belongs on screen.
            if emit:
                emit('agent_progress', {'summary': '源码诊断：' + str(proposal.get('diagnosis'))[:400]})
                emit('agent_progress', {'summary': '修复理由：' + str(proposal.get('reason'))[:500]})
                for edit in (proposal.get('edits') or [])[:6]:
                    if isinstance(edit, dict):
                        emit('agent_progress', {'summary': '补丁 %s：%s 字符 → %s 字符'
                            % (edit.get('file'), len(str(edit.get('before') or '')),
                               len(str(edit.get('after') or '')))})
            rollback = proposal.get('rollback_stage')
            if proposal.get('diagnosis') == 'unsupported':
                if proposal.get('edits'):
                    empty += 1
                    feedback = {'status': 'FAIL', 'log':
                        'Contradictory repair response: diagnosis=unsupported requires edits=[]. '
                        'Return a supported diagnosis for concrete edits, or explain why no edit is possible.'}
                    operation.event({'repair_response': feedback})
                    if empty >= 3:
                        raise ValueError('模型连续 3 次返回矛盾的生成器修复方案，已保存诊断并停下')
                    continue
                raise ValueError('Agent 源码诊断无法继续：' + str(proposal.get('reason', '缺少可执行修复')))
            empty = 0
            signature = hashlib.sha256(json.dumps({'base': base, 'proposal': proposal}, sort_keys=True).encode()).hexdigest()
            if signature in proposals:
                raise ValueError('Agent 重复提交未通过的源码补丁，已保存具体诊断')
            proposals.add(signature)
            try:
                if rollback not in STAGES or STAGES.index(rollback) > STAGES.index(task['stage']):
                    raise ValueError('生成器修复必须回到当前或更早阶段审核')
                if not isinstance(proposal.get('reason'), str) or not proposal['reason'].strip():
                    raise ValueError('生成器修复需要具体原因')
                version = create_version(folder, base, proposal.get('edits'), proposal.get('reason'))
            except (ValueError, SyntaxError) as error:
                feedback = {'status': 'FAIL', 'log': 'Patch validation: ' + str(error)}
                operation.event({'patch_validation': feedback})
                continue
            if version['id'] in seen:
                raise ValueError('Agent 重复提交同一未通过的生成器版本；修复记录已保留')
            seen.add(version['id'])
            validation = worker(version, 'validate', task['intent'], STAGES.index(task['stage']),
                                operation.folder / ('validation-' + version['id'][:12]))
            if validation['status'] == 'PASS':
                from .schematic import load_schematic
                from .geometry import inspect_geometry
                from .fonts import node_binary
                out = operation.folder / ('validation-' + version['id'][:12])
                schematic = load_schematic(out / 'candidate.schem')
                # A worker that did not write manifest.json leaves read_json returning
                # None, and .get() on it aborted the whole repair with "'NoneType' object
                # has no attribute 'get'" — the crash that killed live autonomous runs.
                manifest = read_json(out / 'manifest.json') or {}
                file_check = schematic.validation()
                geometry = inspect_geometry(schematic, decorative_doors=manifest.get('decorative_doors', []))
                try:
                    registry = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'),
                        str(out / 'candidate.schem'), str(out / 'registry.json')], cwd=ROOT,
                        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
                    registry_code = registry.returncode
                except subprocess.TimeoutExpired:
                    registry_code = -1
                validation.update(file_validation=file_check, geometry=geometry,
                    registry=read_json(out / 'registry.json') if (out / 'registry.json').exists() else {'status': 'FAIL'})
                if file_check['status'] != 'PASS' or geometry['status'] != 'PASS' or registry_code:
                    validation['status'] = 'FAIL'
            write_json(operation.folder / 'latest-validation.json', validation)
            if emit:
                detail = '' if validation['status'] == 'PASS' else \
                    '（' + str(validation.get('log'))[:240] + '）'
                emit('agent_progress', {'summary': '补丁验证：%s%s' % (validation['status'], detail)})
            if validation['status'] != 'PASS':
                feedback = validation; base = version_files(version)
                operation.event({'version': version, 'validation': validation})
                if emit: emit('agent_progress', {'summary': '生成器补丁验证未通过，Agent 正在依据日志继续修复。'})
                continue
            operation.finish({'version': version, 'proposal': proposal, 'receipt': receipt, 'validation': validation},
                artifacts=[Path(version['path']) / 'version.json'], validation=validation)
            return version, rollback, {'operation_id': operation.id, 'proposal': proposal,
                                      'receipt': receipt, 'validation': validation}
    except Exception as error:
        import traceback
        # Keep the stack: a bare message ("'NoneType' object has no attribute 'get'") gave
        # no way to find which call failed when a live run died mid-repair.
        operation.event({'traceback': traceback.format_exc()[-4000:]})
        operation.fail(str(error)); raise
