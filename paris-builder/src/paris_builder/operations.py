"""Durable atomic operation receipts. Model output never grants acceptance."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
from .cancellation import checkpoint, interrupted

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'runs/LEARNING-WORKBENCH-v1/operations'
LOCK = threading.RLock()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        # Windows readers/antivirus can briefly deny replacement of an open file.
        for attempt in range(8):
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                    raise
                time.sleep(min(.025 * 2 ** attempt, .4))
    finally:
        temporary.unlink(missing_ok=True)


def file_receipt(path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


class Operation:
    def __init__(self, kind, inputs, *, parent=None, dependencies=(), evidence=(), attempt=1, emit=None):
        self.id = uuid.uuid4().hex
        self.folder = DIRECTORY / self.id
        self.emit = emit
        self.data = {'id': self.id, 'kind': kind, 'parent': parent,
                     'dependencies': list(dependencies), 'evidence_ids': list(evidence),
                     'attempt': attempt, 'inputs': inputs, 'status': 'RUNNING',
                     'started_at': timestamp(), 'artifacts': [], 'validation': None}
        self.save()

    def save(self):
        if self.data['status'] == 'RUNNING': checkpoint()
        with LOCK:
            write_json(self.folder / 'operation.json', self.data)
        if self.emit:
            self.emit('operation', self.data.copy())

    def event(self, event):
        with LOCK:
            with (self.folder / 'events.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'at': timestamp(), **event}, ensure_ascii=False) + '\n')

    def finish(self, result, artifacts=(), validation=None):
        checkpoint()
        write_json(self.folder / 'result.json', result)
        self.data.update(status='SUCCEEDED', finished_at=timestamp(),
                         artifacts=[file_receipt(p) for p in [self.folder / 'result.json', *artifacts]],
                         validation=validation)
        self.save()

    def fail(self, message):
        self.data.update(status='INTERRUPTED' if interrupted() else 'FAILED', finished_at=timestamp(), error=message)
        self.save()


def recover_interrupted():
    if not DIRECTORY.exists():
        return
    for path in DIRECTORY.glob('*/operation.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['status'] == 'RUNNING':
            data.update(status='INTERRUPTED', finished_at=timestamp(),
                        error='Service stopped before this operation completed; retry creates a new receipt.')
            write_json(path, data)
