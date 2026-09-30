"""Owned DSH SDK turns with durable receipts and user-controlled interruption."""
import hashlib
import json
import threading
import time
from uuid import uuid4

from deepseek_harness import DeepSeekHarness

from .operations import Operation, ROOT, write_json
from .providers import parse_json_object
from .cancellation import checkpoint, on_interrupt

HOME = ROOT / 'runs/LEARNING-WORKBENCH-v1/dsh-home'
BUDGET_LOCK = threading.Lock()
USAGE = {'turns': 0, 'max_turns': None}


def run_json(key, model, prompt, *, phase, context=None, emit=None, parent=None,
             required_tools=(), max_tokens=None, timeout=None):
    checkpoint()
    if not key:
        raise ValueError('请先连接 DeepSeek')
    with BUDGET_LOCK:
        USAGE['turns'] += 1
    operation = Operation('dsh.' + phase, {'prompt': prompt, 'model': model,
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'max_tokens': None},
        parent=parent, emit=emit)
    context_path = operation.folder / 'context.json'
    write_json(context_path, context or {})
    patch = operation.folder / 'runtime.patch.yml'
    patch.write_text((ROOT / 'agent/building.patch.yml').read_text(encoding='utf-8').replace(
        '__BUILDING_TOOLS_MODULE__', json.dumps(str(ROOT / 'agent/building-tools.mjs'))), encoding='utf-8')
    workspace = HOME / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    session = phase + '-' + uuid4().hex
    started = time.monotonic()
    runtime = DeepSeekHarness(provider='deepseek-official', model=model, api_key=key,
        profile='sdk-minimal', patches=(str(patch),), dsh_home=str(HOME),
        runtime_cwd=str(HOME), cwd=str(workspace), max_tokens=None,
        request_timeout_seconds=None, reasoning_effort='low',
        env={'PARIS_AGENT_CONTEXT': str(context_path), 'PARIS_AGENT_PHASE': phase,
             'PARIS_AGENT_TOOL_LOG': str(operation.folder / 'tools.jsonl')})
    unregister = on_interrupt(runtime.close)

    def notify(notification):
        raw = json.dumps({'method': notification.method, 'payload': notification.payload}, ensure_ascii=False)
        event = json.loads(raw.replace(key, '[redacted]'))
        operation.event(event)
        if emit and notification.method == 'session.status':
            emit('runtime_status', {'operation_id': operation.id, 'phase': phase,
                                  'status': notification.payload.get('status')})

    try:
        result = runtime.run(prompt, session_id=session, on_notification=notify)
        checkpoint()
        if result.finish_reason != 'completed' or not result.final_response:
            raise ValueError('DSH 未完成本轮：' + str(result.finish_reason))
        reply = operation.folder / 'reply.txt'
        reply.write_text(result.final_response, encoding='utf-8')
        tool_path = operation.folder / 'tools.jsonl'
        receipts = [json.loads(line) for line in tool_path.read_text(encoding='utf-8').splitlines()] if tool_path.exists() else []
        tools_seen = {row['tool'] for row in receipts if row.get('status') == 'SUCCEEDED'}
        if not set(required_tools) <= tools_seen:
            raise ValueError('DSH 缺少实际工具调用：' + ', '.join(sorted(set(required_tools) - tools_seen)))
        parsed = parse_json_object(result.final_response)
        receipt = {'runtime': 'deepseek-harness-sdk', 'model': model, 'session_id': session,
                   'operation_id': operation.id, 'elapsed_seconds': round(time.monotonic() - started, 3),
                   'tools': sorted(tools_seen), 'finish_reason': result.finish_reason,
                   'input_mode': 'text_evidence_only', 'usage': {'dsh_turns': 1}}
        operation.finish({'proposal': parsed, 'receipt': receipt},
                         artifacts=[context_path, reply, *([tool_path] if tool_path.exists() else [])],
                         validation={'json': 'PASS', 'required_tools': 'PASS'})
        return parsed, receipt
    except Exception as error:
        message = str(error).replace(key, '[redacted]')[:600]
        operation.fail(message)
        checkpoint()
        raise ValueError(message) from None
    finally:
        unregister()
        runtime.close()
