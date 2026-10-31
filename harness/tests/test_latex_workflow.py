"""Offline integration checks; no credentials or gateway requests."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import runner


class LatexWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'vendor'
        self.vendor.mkdir()
        self.pdf = self.root / 'P01.pdf'
        self.pdf.write_bytes(b'%PDF-placeholder')
        self.cfg = {'fixed': {'paper2poster': {
            'path': str(self.vendor), 'python': sys.executable,
            'vision_model': 'same_as_candidate', 'poster_width_inches': 48,
            'poster_height_inches': 36}}, 'gateway': {'max_transport_retries': 2}}

    def attempt(self):
        with patch.object(runner, 'HARNESS', self.root):
            return runner.run_attempt(run_id=1, model='candidate', paper_id='P01',
                                      pdf=self.pdf, cfg=self.cfg,
                                      out_root=self.root / 'outputs', env={})

    def test_pdf_success_without_pptx_or_vision(self):
        commands = []
        def execute(cmd, **kwargs):
            commands.append(cmd)
            out = self.root / 'outputs/1'
            if cmd[1].endswith('latex_prepare.py'):
                (out / 'detail_log.json').write_text(json.dumps({'parser_in_t': 100, 'parser_out_t': 20}))
            elif cmd[1].endswith('latex_poster.py'):
                work = out / 'latex'
                work.mkdir()
                (work / 'p01 x candidate.pdf').write_bytes(b'%PDF-placeholder')
                (work / 'fit.json').write_text('{"fits": true}')
            elif cmd[0] == 'pdftotext':
                return subprocess.CompletedProcess(cmd, 0, stdout='Methods Results Conclusion')
            else:
                self.fail(f'Unexpected command: {cmd}')
            return subprocess.CompletedProcess(cmd, 0)
        with patch.object(runner.subprocess, 'run', side_effect=execute):
            row = self.attempt()
        self.assertEqual(row['workflow_success'], 1)
        self.assertTrue(row['poster_path'].endswith('.pdf'))
        self.assertEqual(row['token_usage'], 120)
        self.assertEqual(row['vision_input_tokens'], 0)
        self.assertFalse(list(self.root.rglob('*.pptx')))
        self.assertEqual(len(commands), 3)

    def test_budget_error_is_not_retried_or_rendered(self):
        def execute(cmd, **kwargs):
            kwargs['stdout'].write('ExceededBudget: budget_exceeded')
            return subprocess.CompletedProcess(cmd, 1)
        with patch.object(runner.subprocess, 'run', side_effect=execute) as mocked:
            row = self.attempt()
        self.assertEqual(row['failure_reason'], 'E_BUDGET')
        self.assertEqual(row['retries'], 0)
        self.assertEqual(mocked.call_count, 1)

    def test_unfitted_pdf_does_not_pass(self):
        def execute(cmd, **kwargs):
            if cmd[1].endswith('latex_poster.py'):
                work = self.root / 'outputs/1/latex'
                work.mkdir()
                (work / 'fit.json').write_text('{"fits": false}')
            return subprocess.CompletedProcess(cmd, 0)
        with patch.object(runner.subprocess, 'run', side_effect=execute):
            row = self.attempt()
        self.assertEqual(row['workflow_success'], 0)
        self.assertEqual(row['failure_reason'], 'E_OVERFLOW')


if __name__ == '__main__':
    unittest.main()
