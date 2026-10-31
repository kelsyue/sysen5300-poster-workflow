"""Planner, checkpoint and offline rebuild regression tests."""
import copy
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from combined_planner import make_panels, plan_figures, validate_plan
from preparation_cache import StageCache
import runner

DOCUMENT = {'sections': [{'title': 'Poster Title & Authors', 'content': 'Title'},
                         {'title': 'Results', 'content': 'The main quantitative result.'}]}
IMAGES = {'1': {'caption': 'Result comparison', 'image_path': 'figures/1.png',
                'figure_size': 200, 'figure_aspect': 2}}


class CombinedPlanning(unittest.TestCase):
    def test_one_request_selects_and_assigns_figures(self):
        response = types.SimpleNamespace(msgs=[types.SimpleNamespace(content='{"Results":{"image":1}}')])
        agent = Mock()
        agent.step.return_value = response
        modules = {
            'camel.models': types.SimpleNamespace(ModelFactory=Mock()),
            'camel.agents': types.SimpleNamespace(ChatAgent=Mock(return_value=agent)),
            'utils.src.utils': types.SimpleNamespace(get_json_from_response=json.loads),
            'utils.wei_utils': types.SimpleNamespace(account_token=lambda r: (100, 20)),
        }
        record = Mock()
        original = copy.deepcopy(DOCUMENT)
        with patch.dict(sys.modules, modules):
            panels, figures = plan_figures(DOCUMENT, IMAGES, {},
                {'model_platform': 'gateway', 'model_type': 'candidate', 'model_config': {}}, record)
        self.assertEqual(agent.step.call_count, 1)
        record.assert_called_once_with(100, 20)
        self.assertEqual(figures, {'Results': {'image': '1'}})
        self.assertEqual(panels[1]['gp'], 1)
        self.assertEqual(DOCUMENT, original)
        self.assertNotIn('image_path', agent.step.call_args.args[0])

    def test_bad_plan_is_rejected_locally(self):
        for plan in ({'Invented section': {'image': '1'}},
                     {'Results': {'image': '999'}},
                     {'Results': {'image': '1', 'table': '2'}},
                     {'Poster Title & Authors': {'image': '1'}}):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(plan, DOCUMENT, IMAGES, {})
        self.assertEqual(make_panels(DOCUMENT, {}, {}, {})[1]['gp'], 0)

    def test_usage_recorded_before_bad_json_is_rejected(self):
        response = types.SimpleNamespace(msgs=[types.SimpleNamespace(content='bad json')])
        agent = Mock()
        agent.step.return_value = response
        modules = {'camel.models': types.SimpleNamespace(ModelFactory=Mock()),
                   'camel.agents': types.SimpleNamespace(ChatAgent=Mock(return_value=agent)),
                   'utils.src.utils': types.SimpleNamespace(get_json_from_response=json.loads),
                   'utils.wei_utils': types.SimpleNamespace(account_token=lambda r: (50, 10))}
        record = Mock()
        with patch.dict(sys.modules, modules), self.assertRaises(ValueError):
            plan_figures(DOCUMENT, IMAGES, {},
                {'model_platform': 'gateway', 'model_type': 'candidate', 'model_config': {}}, record)
        record.assert_called_once_with(50, 10)
        self.assertEqual(agent.step.call_count, 1)


class Checkpoints(unittest.TestCase):
    def test_artifacts_restore_and_never_cross_candidates_or_papers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'source'
            source.mkdir()
            (source / 'summary.json').write_text('{"content":"saved summary"}')
            identity = {'candidate': 'A', 'pdf_sha256': 'paper-one', 'prompt': 'v1'}
            cache = StageCache(root / 'cache', identity)
            cache.save('parse', {}, {'tokens': 100}, source, ['summary.json'])
            restored = root / 'restored'
            self.assertEqual(cache.load('parse', {}, restored), {'tokens': 100})
            self.assertEqual((restored / 'summary.json').read_text(), (source / 'summary.json').read_text())
            for changed in ({**identity, 'candidate': 'B'},
                            {**identity, 'pdf_sha256': 'paper-two'},
                            {**identity, 'prompt': 'v2'}):
                self.assertIsNone(StageCache(root / 'cache', changed).load('parse', {}))
            cache.save('plan', {'prompt': 'v1'}, {'figures': {}})
            self.assertIsNone(cache.load('plan', {'prompt': 'v2'}))
            saved = cache.directory('parse', {}) / 'files/summary.json'
            saved.write_text('corrupted')
            with self.assertRaises(ValueError):
                cache.load('parse', {}, restored)


class Rebuild(unittest.TestCase):
    def test_no_credentials_or_preparation_are_needed(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / 'run_metadata.json').write_text('{"input_paper_id":"P01","llm_model":"A"}')
            (run / 'run_config.yaml').write_text('fixed:\n  paper2poster: {}\n')
            (run / 'detail_log.json').write_text('{"parser_in_t":100}')
            before = (run / 'detail_log.json').read_bytes()
            commands = []
            def execute(cmd, **kwargs):
                commands.append(cmd)
                if cmd[0] == 'pdftotext':
                    return subprocess.CompletedProcess(cmd, 0, stdout='Results and conclusions')
                self.assertTrue(cmd[1].endswith('latex_poster.py'))
                (run / 'latex').mkdir()
                (run / 'latex/fit.json').write_text('{"fits":true}')
                return subprocess.CompletedProcess(cmd, 0)
            with patch.dict('os.environ', {}, clear=True), patch.object(runner.subprocess, 'run', side_effect=execute):
                result = runner.rebuild_saved(run)
            self.assertEqual(result['api_tokens_used'], 0)
            self.assertEqual(result['workflow_success'], 1)
            self.assertEqual((run / 'detail_log.json').read_bytes(), before)
            self.assertEqual(len(commands), 2)


if __name__ == '__main__':
    unittest.main()
