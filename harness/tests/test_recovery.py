"""Recovery accounting, failure audit and checkpoint isolation without API calls."""
import json
import sys
import tempfile
import unittest
import yaml
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import recovery
import runner


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.outputs, self.results = recovery.locations(self.root)
        self.cfg = {'fixed': {'paper2poster': {'path': 'vendor', 'vision_model': 'same_as_candidate'},
                              'papers_dir': 'papers'}, 'gateway': {}}
        self.first = {key: '' for key in runner.RUN_COLUMNS}
        self.first.update(run_id='1', input_paper_id='P01', llm_model='A', attempt='1',
                          input_tokens='140', output_tokens='25', token_usage='165',
                          workflow_success='0', failure_reason='E_PIPELINE', generation_cost='0.00019',
                          prompt_sha256='initial-prompts', config_sha256=runner.config_sha256(self.cfg))
        self.source = self.outputs / '1'
        (self.source / 'preparation').mkdir(parents=True)
        (self.source / 'preparation/saved.txt').write_text('A-only checkpoint')
        (self.source / 'intermediate').mkdir()
        (self.source / 'intermediate/planner_response.txt').write_text('{"Poster Title":{"image":"1"}}')
        (self.source / 'run_metadata.json').write_text('{"input_paper_id":"P01","llm_model":"A"}')
        (self.source / 'run_config.yaml').write_text(yaml.safe_dump(self.cfg))
        (self.source / 'run.log').write_text('ValueError: Invalid figure section: Poster Title\n')
        (self.source / 'detail_log.json').write_text(json.dumps({
            'parser_in_t': 100, 'parser_out_t': 20, 'planning_in_t': 40, 'planning_out_t': 5}))
        runner.append_run(self.data / 'runs.csv', self.first)
        self.original_csv = (self.data / 'runs.csv').read_bytes()
        self.prices = {'A': {'input_per_mtok': 1, 'output_per_mtok': 2}}

    def recover(self, execute, first=None, run_id=2, parent=None, history=None):
        with patch.object(runner, 'HARNESS', self.root), \
             patch.object(runner, 'prompt_sha256', return_value='recovery-code'), \
             patch.object(runner, 'run_attempt', side_effect=execute):
            return recovery.recover_one(self.root, first or self.first, parent or self.first,
                history or [], self.cfg, self.outputs, run_id, self.prices, 'today', {})

    def new_planning(self, **kwargs):
        target = self.outputs / str(kwargs['run_id'])
        self.assertEqual((target / 'preparation/saved.txt').read_text(), 'A-only checkpoint')
        self.assertEqual(runner.read_tokens(target)['token_usage'], 165)
        feedback = json.loads(kwargs['planning_feedback'].read_text())
        self.assertIn('Invalid figure section', feedback['failure'])
        (target / 'detail_log.json').write_text(json.dumps({
            'parser_in_t': 100, 'parser_out_t': 20, 'planning_in_t': 80, 'planning_out_t': 10}))
        (target / 'cache_usage.json').write_text('{"reused_stages":["parse"]}')
        return target

    def test_only_new_tokens_billed_and_originals_preserved(self):
        def execute(**kwargs):
            self.new_planning(**kwargs)
            return {'workflow_success': 1, 'poster_path': 'outputs/latex/2/latex/p01 x A.pdf'}
        row, interrupted = self.recover(execute)
        self.assertFalse(interrupted)
        self.assertEqual(row['completion_attempt'], 2)
        self.assertEqual(row['token_usage'], 45)
        self.assertEqual(row['input_tokens'], 40)
        self.assertEqual(row['output_tokens'], 5)
        self.assertEqual(row['cumulative_token_usage'], 210)
        self.assertEqual(row['generation_cost'], 0.00005)
        self.assertEqual(row['checkpoint_used'], 1)
        self.assertEqual(row['original_prompt_sha256'], 'initial-prompts')
        self.assertEqual(row['prompt_sha256'], 'recovery-code')
        self.assertEqual((self.data / 'runs.csv').read_bytes(), self.original_csv)
        self.assertEqual(runner.read_tokens(self.source)['token_usage'], 165)

    def test_failed_recovery_records_reason_and_consumed_tokens(self):
        def execute(**kwargs):
            target = self.new_planning(**kwargs)
            (target / 'run.log').write_text('ValueError: Figure selected more than once\n')
            return {'workflow_success': 0, 'failure_reason': 'E_PIPELINE'}
        row, _ = self.recover(execute)
        self.assertEqual(row['workflow_success'], 0)
        self.assertIn('Figure selected more than once', row['failure_detail'])
        self.assertEqual(row['token_usage'], 45)
        self.assertEqual(row['checkpoint_used'], 1)
        self.assertEqual(row['poster_path'], '')
        audit = json.loads((self.outputs / '2/recovery_attempt.json').read_text())
        self.assertEqual(audit['record']['previous_failure_reason'], 'E_PIPELINE')
        self.assertEqual(audit['status'], 'complete')

    def test_interrupt_is_recorded_as_failure_with_usage(self):
        def execute(**kwargs):
            self.new_planning(**kwargs)
            raise KeyboardInterrupt()
        row, interrupted = self.recover(execute)
        self.assertTrue(interrupted)
        self.assertEqual(row['failure_reason'], 'E_INTERRUPTED')
        self.assertEqual(row['token_usage'], 45)

    def test_other_model_checkpoint_is_rejected(self):
        wrong = {**self.first, 'llm_model': 'B'}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.recover(lambda **kwargs: self.fail('must not generate'), first=wrong)
        self.assertFalse((self.outputs / '2').exists())

    def test_render_only_recovery_costs_zero_and_keeps_failure(self):
        (self.source / 'intermediate/tree_split.json').write_text('{}')
        with patch.object(runner, 'rebuild_saved', return_value={
                'workflow_success': 0, 'failure_reason': 'E_OVERFLOW'}):
            row, _ = self.recover(lambda **kwargs: self.fail('must not call a model'))
        self.assertEqual(row['token_usage'], 0)
        self.assertEqual(row['generation_cost'], 0)
        self.assertEqual(row['workflow_success'], 0)
        self.assertEqual(row['failure_reason'], 'E_OVERFLOW')
        self.assertEqual(row['checkpoint_used'], 1)

    def test_summary_separates_first_attempt_recovered_and_failed(self):
        success = {**self.first, 'run_id': '2', 'llm_model': 'B', 'workflow_success': '1',
                   'failure_reason': '', 'token_usage': '100', 'generation_cost': '0.01'}
        failed = {**self.first, 'run_id': '3', 'input_paper_id': 'P02'}
        runner.append_run(self.data / 'runs.csv', success)
        runner.append_run(self.data / 'runs.csv', failed)
        rows = [{**self.first, 'run_id': '4', 'original_run_id': '1', 'parent_run_id': '1',
                 'completion_attempt': 2, 'workflow_success': 1, 'token_usage': 45,
                 'input_tokens': 40, 'output_tokens': 5, 'generation_cost': 0.00005,
                 'failure_reason': '', 'checkpoint_used': 1},
                {**self.first, 'run_id': '5', 'original_run_id': '3', 'parent_run_id': '3',
                 'completion_attempt': 2, 'workflow_success': 0, 'token_usage': 30,
                 'generation_cost': 0.00003, 'failure_detail': 'Invalid plan again', 'checkpoint_used': 1}]
        recovery.write_csv(self.data / 'recovery_attempts.csv', rows, recovery.RECOVERY_COLUMNS)
        summary = recovery.write_summary(self.root)
        self.assertEqual(summary['first_attempt_successes'], 1)
        self.assertEqual(summary['finished_after_recovery'], 1)
        self.assertEqual(summary['still_failed'], 1)
        self.assertEqual(summary['first_attempt_tokens'], 430)
        self.assertEqual(summary['recovery_tokens'], 75)
        self.assertEqual(summary['total_token_usage'], 505)
        posters = runner.read_runs(self.results / 'completion_by_poster.csv')
        self.assertEqual(posters[0]['success_on_attempt'], '2')
        self.assertIn('Invalid plan again', posters[2]['failure_history'])

    def test_lock_prevents_concurrent_writers(self):
        handle = runner.acquire_run_lock(self.data)
        try:
            with self.assertRaisesRegex(RuntimeError, 'Another generation'):
                runner.acquire_run_lock(self.data)
        finally:
            handle.close()

    def test_third_attempt_uses_latest_checkpoint_and_adds_only_its_increment(self):
        def failed(**kwargs):
            self.new_planning(**kwargs)
            return {'workflow_success': 0, 'failure_reason': 'E_PIPELINE'}
        second, _ = self.recover(failed)
        second['run_id'] = str(second['run_id'])
        def succeeded(**kwargs):
            target = self.outputs / str(kwargs['run_id'])
            self.assertEqual(runner.read_tokens(target)['token_usage'], 210)
            (target / 'detail_log.json').write_text(json.dumps({
                'parser_in_t': 100, 'parser_out_t': 20, 'planning_in_t': 100, 'planning_out_t': 15}))
            (target / 'cache_usage.json').write_text('{"reused_stages":["parse"]}')
            return {'workflow_success': 1}
        third, _ = self.recover(succeeded, run_id=3, parent=second, history=[second])
        self.assertEqual(third['completion_attempt'], 3)
        self.assertEqual(third['parent_run_id'], '2')
        self.assertEqual(third['token_usage'], 25)
        self.assertEqual(third['cumulative_token_usage'], 235)

    def test_unknown_prices_remain_unknown(self):
        self.prices = {}
        def execute(**kwargs):
            self.new_planning(**kwargs)
            return {'workflow_success': 0, 'failure_reason': 'E_PIPELINE'}
        row, _ = self.recover(execute)
        self.assertIsNone(row['generation_cost'])
        self.assertEqual(row['cumulative_generation_cost'], '')

    def test_deleted_interrupted_archive_falls_back_without_losing_history_or_tokens(self):
        interrupted = {**self.first, 'run_id': '61', 'original_run_id': '1',
                       'completion_attempt': '2', 'workflow_success': '0',
                       'failure_reason': 'E_INTERRUPTED', 'token_usage': '30',
                       'generation_cost': '0.00003'}
        def execute(**kwargs):
            self.new_planning(**kwargs)
            return {'workflow_success': 1}
        row, _ = self.recover(execute, run_id=62, parent=interrupted, history=[interrupted])
        self.assertEqual(row['parent_run_id'], '61')
        self.assertEqual(row['completion_attempt'], 3)
        self.assertEqual(row['checkpoint_source'], 'outputs/latex/1')
        self.assertIn('archive missing or incomplete', row['checkpoint_fallback_reason'])
        self.assertEqual(row['previous_failure_reason'], 'E_INTERRUPTED')
        self.assertEqual(row['token_usage'], 45)
        self.assertEqual(row['cumulative_token_usage'], 240)

    def test_incomplete_archive_falls_back_but_missing_entire_lineage_is_clear_error(self):
        (self.outputs / '61').mkdir()
        interrupted = {**self.first, 'run_id': '61', 'completion_attempt': '2'}
        self.assertEqual(recovery.checkpoint_source(self.outputs, self.first, [interrupted]), self.first)
        (self.source / 'run_config.yaml').unlink()
        with self.assertRaisesRegex(ValueError, 'No saved configuration/metadata survives'):
            recovery.checkpoint_source(self.outputs, self.first, [interrupted])


if __name__ == '__main__':
    unittest.main()
