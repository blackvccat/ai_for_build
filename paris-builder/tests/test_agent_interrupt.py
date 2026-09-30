import tempfile
import threading
import unittest
import base64
import io
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from paris_builder import cancellation, harness_runtime, learning_web as web, operations
from paris_builder.operations import write_json


class AgentInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ident = '12345678abcdef01'
        for target, name, value in ((web, 'OUTPUT', self.root), (web, 'jobs', {}),
                (web, 'job_cancellations', {}), (web, 'active_sessions', set()),
                (operations, 'DIRECTORY', self.root / 'operations')):
            mock = patch.object(target, name, value); mock.start(); self.addCleanup(mock.stop)
        write_json(web.agent_path(self.ident), {'id': self.ident, 'created_at': 'test', 'events': []})

    def test_reference_pixels_reach_vision_and_cached_observations_are_reused(self):
        buffer = io.BytesIO(); Image.new('RGB', (12, 12), 'red').save(buffer, format='PNG')
        reference = web.save_reference(self.ident, {'name': 'reference.png', 'data': base64.b64encode(buffer.getvalue()).decode()})
        def complete(prompt, images=(), max_tokens=0):
            self.assertEqual(len(images), 1)
            with Image.open(images[0]) as image: self.assertEqual(image.size, (12, 12))
            return {'observations': ['Actual fixture pixel observation']}, {'image_evidence': [{'sha256': web.digest(images[0])}]}
        with patch('paris_builder.providers.MultimodalClient') as client:
            client.return_value.complete.side_effect = complete
            analysis = web.inspect_agent_references(self.ident, [reference], [], lambda *args: None)
            self.assertEqual(analysis['scope'], 'actual_reference_image_analysis')
            history = web.read_json(web.agent_path(self.ident))['events']
            cached = web.inspect_agent_references(self.ident, [reference], history, lambda *args: None)
            self.assertEqual(cached['observations'], analysis['observations'])
            self.assertEqual(client.return_value.complete.call_count, 1)
        with self.assertRaises(ValueError):
            web.inspect_agent_references('fedcba9876543210', [reference], [], lambda *args: None)

    def test_dsh_has_no_service_turn_deadline_or_token_ceiling(self):
        with patch.object(harness_runtime, 'DeepSeekHarness') as runtime, \
                patch.object(harness_runtime, 'HOME', self.root / 'home'), \
                patch.object(harness_runtime, 'USAGE', {'turns': 1000, 'max_turns': None}):
            runtime.return_value.run.return_value = SimpleNamespace(finish_reason='completed', final_response='{}')
            harness_runtime.run_json('fixture-key', 'fixture-model', '{}', phase='fixture', max_tokens=1, timeout=.001)
            self.assertIsNone(runtime.call_args.kwargs['max_tokens'])
            self.assertIsNone(runtime.call_args.kwargs['request_timeout_seconds'])
            self.assertEqual(harness_runtime.USAGE['turns'], 1001)

    def test_running_job_stops_preserves_artifact_and_resumes(self):
        entered = threading.Event()
        def worker():
            write_json(self.root / 'completed-candidate.json', {'status': 'PASS'})
            entered.set()
            while True:
                cancellation.checkpoint()
                threading.Event().wait(.01)
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(web, 'pool', pool):
            queued = web.submit('workflow.build', worker, {'session': self.ident, 'run': 'ATELIER-12345678'})
            web.jobs[queued['job_id']]['run'] = 'ATELIER-12345678'
            self.assertTrue(entered.wait(2))
            self.assertTrue(web.agent_session(self.ident)['active'])
            response = web.interrupt_agent_session(web.SessionChange(id=self.ident))
            self.assertEqual(response['status'], 'stopping')
        job = web.jobs[queued['job_id']]
        self.assertEqual(job['status'], 'interrupted')
        self.assertEqual(web.read_json(self.root / 'completed-candidate.json')['status'], 'PASS')
        self.assertFalse(web.agent_session(self.ident)['active'])
        self.assertEqual(web.agent_session(self.ident)['task']['status'], 'interrupted')
        with patch.object(web, 'queue_workflow_build', return_value={'job_id': 'resumed'}) as resume:
            result = web.resume_agent_session(web.SessionChange(id=self.ident))
            resume.assert_called_once_with('ATELIER-12345678')
            self.assertEqual(result['job_id'], 'resumed')
        operation = web.read_json(operations.DIRECTORY / job['operation_id'] / 'operation.json')
        self.assertEqual(operation['status'], 'INTERRUPTED')

    def test_queued_job_is_interrupted_without_starting_worker(self):
        release = threading.Event(); invoked = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(web, 'pool', pool):
            pool.submit(release.wait)
            queued = web.submit('agent.turn', invoked.set, {'session': self.ident, 'text': 'test'})
            web.active_sessions.add(self.ident)
            web.interrupt_agent_session(web.SessionChange(id=self.ident))
            release.set()
        self.assertFalse(invoked.is_set())
        self.assertEqual(web.jobs[queued['job_id']]['status'], 'interrupted')
        self.assertNotIn(self.ident, web.active_sessions)

    def test_worker_error_marks_job_and_session_failed(self):
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(web, 'pool', pool):
            queued = web.submit('agent.turn', lambda: {'error': 'reference analysis failed'},
                                {'session': self.ident, 'text': 'test'})
        job = web.jobs[queued['job_id']]
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(web.agent_session(self.ident)['task']['status'], 'failed')
        operation = web.read_json(operations.DIRECTORY / job['operation_id'] / 'operation.json')
        self.assertEqual(operation['status'], 'FAILED')

    def test_resume_uses_original_text_and_images(self):
        inputs = {'session': self.ident, 'text': 'original request', 'references': [{'name': 'original.png', 'data': 'saved'}]}
        web.jobs['old'] = {'id': 'old', 'kind': 'agent.turn', 'status': 'interrupted', 'inputs': inputs}
        with patch.object(web, 'queue_agent_turn', return_value={'job_id': 'new'}) as resume:
            web.resume_agent_session(web.SessionChange(id=self.ident))
            body = resume.call_args.args[0]
            self.assertEqual(body.text, inputs['text'])
            self.assertEqual(body.references, inputs['references'])
            self.assertTrue(resume.call_args.kwargs['resume'])

    def test_resume_is_blocked_while_still_stopping(self):
        web.jobs['old'] = {'id': 'old', 'kind': 'agent.turn', 'status': 'stopping', 'inputs': {'session': self.ident}}
        with self.assertRaises(web.HTTPException) as error:
            web.resume_agent_session(web.SessionChange(id=self.ident))
        self.assertEqual(error.exception.status_code, 409)

    def test_failed_build_can_retry_its_saved_workflow(self):
        web.jobs['old'] = {'id': 'old', 'kind': 'workflow.build', 'status': 'failed',
                           'run': 'ATELIER-12345678', 'inputs': {'session': self.ident}}
        with patch.object(web, 'queue_workflow_build', return_value={'job_id': 'retry'}) as retry:
            result = web.resume_agent_session(web.SessionChange(id=self.ident))
        retry.assert_called_once_with('ATELIER-12345678')
        self.assertEqual(result['job_id'], 'retry')

    def test_dsh_is_closed_by_interrupt_and_receipt_is_not_failed(self):
        started = threading.Event(); closed = threading.Event(); token = cancellation.Cancellation()
        class Runtime:
            def __init__(self, **kwargs): pass
            def run(self, *args, **kwargs):
                started.set(); closed.wait(2)
                raise RuntimeError('runtime closed')
            def close(self): closed.set()
        errors = []
        def execute():
            with cancellation.scope(token):
                try: harness_runtime.run_json('fixture', 'fixture', '{}', phase='intent')
                except Exception as error: errors.append(error)
        with patch.object(harness_runtime, 'DeepSeekHarness', Runtime), patch.object(harness_runtime, 'HOME', self.root / 'home'):
            thread = threading.Thread(target=execute); thread.start()
            self.assertTrue(started.wait(2)); token.request(); thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertTrue(closed.is_set())
        self.assertIsInstance(errors[0], cancellation.RunInterrupted)
        receipts = [web.read_json(path) for path in operations.DIRECTORY.glob('*/operation.json')]
        self.assertEqual(receipts[0]['status'], 'INTERRUPTED')


if __name__ == '__main__': unittest.main()
