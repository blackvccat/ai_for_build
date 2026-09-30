import unittest
import tempfile
import sys
import threading
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from paris_builder.learning_web import design_run, revise_design, suggest_design
from paris_builder.harness_planner import evidence_ids
from paris_builder import learning_web as web
from paris_builder import harness_planner, operations
from paris_builder.operations import write_json


class DesignStudioTests(unittest.TestCase):
    def test_operation_images_include_views_and_reject_outside_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'assets' / 'project'; root.mkdir(parents=True)
            image = root / 'front.png'; image.write_bytes(b'fixture')
            source = root.parent / 'source.png'; source.write_bytes(b'fixture')
            outside = Path(directory) / 'outside.png'; outside.write_bytes(b'fixture')
            bundle = root / 'views.json'
            write_json(bundle, {'front': {'path': str(image)}})
            receipt = {'artifacts': [{'path': str(bundle)}, {'path': str(image)}, {'path': str(source)}, {'path': str(outside)}]}
            with patch.object(web, 'ROOT', root), patch.object(web, 'operation_receipt', return_value=receipt):
                # Only the configured asset root and its source-asset parent are allowed.
                self.assertEqual(web.operation_images(receipt), [image, source])
                with self.assertRaises(HTTPException): web.operation_image('fixture', -1)
                with self.assertRaises(HTTPException): web.operation_image('fixture', 2)
    @unittest.skipUnless(sys.platform == 'win32', 'Windows file sharing regression')
    def test_atomic_save_survives_actual_windows_reader(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            write_json(path, {'events': [1]})
            handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 128, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
            release = threading.Timer(.12, kernel.CloseHandle, args=(handle,))
            release.start()
            failures = []
            original = Path.replace
            def replace(source, target):
                try: return original(source, target)
                except PermissionError as error:
                    failures.append(error.winerror)
                    raise
            try:
                with patch.object(Path, 'replace', replace): write_json(path, {'events': [1, 2]})
            finally:
                release.join()
            self.assertTrue(failures)
            self.assertTrue(set(failures) <= {5, 32, 33})
            self.assertEqual(web.read_json(path)['events'], [1, 2])

    def test_prompt_confirmation_returns_actual_draft(self):
        history = [{'role': 'user', 'content': '先写一份豪斯曼建筑提示词，暂时不建造'}]
        draft = '完整建筑设计要求、框架屋顶形制审核、分层窗户立面细节审核。' * 15
        with patch.object(harness_planner, 'run_json', return_value=({'action': 'draft', 'reply': draft}, {})) as call:
            result = harness_planner.classify_turn('fixture', '请开始', history, 'fixture')
            self.assertEqual(result['reply'], draft)
            self.assertIn('most recent unfinished user task', call.call_args.args[2])
        with patch.object(harness_planner, 'run_json', return_value=({'action': 'draft', 'reply': '好的，我现在就整理'}, {})):
            with self.assertRaisesRegex(ValueError, '提示词任务未完成'):
                harness_planner.classify_turn('fixture', '请开始', history, 'fixture')

    def test_atomic_save_retries_windows_sharing_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            write_json(path, {'events': [1]})
            replace = Path.replace
            attempts = []
            def transient(source, target):
                attempts.append(source)
                if len(attempts) < 3:
                    error = PermissionError('busy'); error.winerror = 5
                    raise error
                return replace(source, target)
            with patch.object(Path, 'replace', transient), patch.object(operations.time, 'sleep'):
                write_json(path, {'events': [1, 2]})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(web.read_json(path)['events'], [1, 2])
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_atomic_save_failure_preserves_previous_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            write_json(path, {'events': [1]})
            error = PermissionError('busy'); error.winerror = 5
            with patch.object(Path, 'replace', side_effect=error), patch.object(operations.time, 'sleep'):
                with self.assertRaises(PermissionError): write_json(path, {'events': [2]})
            self.assertEqual(web.read_json(path)['events'], [1])
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_review_pass_queues_next_stage_and_reject_does_not(self):
        for decision, stage in [('pass', 'facades'), ('reject', 'frameworks')]:
            with patch.object(web, 'design_run', return_value=Path('test-run')), \
                    patch.object(web, 'jobs', {}), patch.object(web, 'Operation'), \
                    patch.object(web.atelier_workflow, 'submit_review', return_value={'stage': stage}), \
                    patch.object(web, 'queue_workflow_build', return_value={'job_id': 'next'}) as queue:
                result = web.workflow_review(web.WorkflowReviewRequest(run='test', review={'decision': decision}))
                self.assertEqual(result['stage'], stage)
                self.assertEqual(queue.call_count, int(decision == 'pass'))
                if decision == 'pass': self.assertEqual(result['build']['job_id'], 'next')

    def test_review_preserves_saved_success_when_queue_is_full(self):
        with patch.object(web, 'design_run', return_value=Path('test-run')), \
                patch.object(web, 'jobs', {}), patch.object(web, 'Operation'), \
                patch.object(web.atelier_workflow, 'submit_review', return_value={'stage': 'facades'}), \
                patch.object(web, 'queue_workflow_build', side_effect=HTTPException(429, 'Queue full')):
            result = web.workflow_review(web.WorkflowReviewRequest(run='test', review={'decision': 'pass'}))
            self.assertEqual(result['stage'], 'facades')
            self.assertEqual(result['build_error'], 'Queue full')

    def test_delete_is_recoverable_and_active_work_is_protected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'OUTPUT', Path(directory)), patch.object(web, 'jobs', {}):
            ident = 'abcd1234abcd1234'
            write_json(web.agent_path(ident), {'id': ident, 'created_at': 'test', 'events': [{'kind': 'user', 'text': 'Delete test'}]})
            body = web.SessionChange(id=ident)
            web.active_sessions.add(ident)
            try:
                with self.assertRaises(HTTPException): web.delete_agent_session(body)
            finally: web.active_sessions.discard(ident)
            web.delete_agent_session(body)
            self.assertEqual(web.agent_sessions()['items'], [])
            with self.assertRaises(HTTPException): web.agent_session(ident)
            web.restore_agent_session(body)
            self.assertEqual(web.agent_session(ident)['events'][0]['text'], 'Delete test')
            self.assertEqual(web.agent_sessions()['items'][0]['id'], ident)

    def test_layered_model_citations_keep_ids_without_inventing_evidence(self):
        self.assertEqual(evidence_ids({'structure': ['structure:street_house'],
            'component': ['v3:s3-window-bay']}), ['structure:street_house', 'v3:s3-window-bay'])
        for invalid in ({'unknown': ['invented']}, {'component': 'v3:s3-window-bay'}, [None], []):
            with self.assertRaises(ValueError): evidence_ids(invalid)

    def test_single_apartment_is_not_a_street_row(self):
        plan = suggest_design('一栋巴黎街区公寓，底层有咖啡店')
        self.assertEqual(plan['form'], 'apartment_block')
        self.assertEqual(plan['facade'], 'haussmann_apartment')

    def test_explicit_street_row_and_slope_take_precedence(self):
        self.assertEqual(suggest_design('一整排沿街住宅')['form'], 'street_row')
        self.assertEqual(suggest_design('沿斜坡的一整排街屋')['form'], 'slope_terrace')

    def test_run_path_rejects_non_generated_names(self):
        with self.assertRaises(HTTPException):
            design_run('../PAR-002-v0.4')

    def test_followup_preserves_form_and_changes_requested_storeys(self):
        prior = suggest_design('沿斜坡的街屋')
        revised = revise_design('改成 7 层，其他保持', prior)
        self.assertEqual(revised['form'], 'slope_terrace')
        self.assertEqual(revised['storeys'], 7)
        self.assertEqual(revised['width'], prior['width'])


if __name__ == '__main__':
    unittest.main()
