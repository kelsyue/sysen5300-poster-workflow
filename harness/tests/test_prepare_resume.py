"""Execute the preparation entry point twice to verify checkpoints skip model stages."""
import json
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from combined_planner import make_panels

ENTRY = Path(__file__).resolve().parents[1] / 'src/latex_prepare.py'


class PrepareResume(unittest.TestCase):
    def test_completed_stages_survive_a_later_layout_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ['PosterAgent/parse_raw.py', 'utils/wei_utils.py',
                        'utils/prompts/gen_poster_raw_content_v2.txt', 'input/P01/paper.pdf']:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('fixture')
            tag = '<A_A>'
            raw = root / f'contents/{tag}_P01_raw_content.json'
            directory = root / f'{tag}_images_and_tables'
            document = {'sections': [{'title': 'Poster Title & Authors', 'content': 'Title'},
                                     {'title': 'Results', 'content': 'A measured result'}]}
            images = {'1': {'image_path': f'{tag}_images_and_tables/P01/figure.png',
                             'caption': 'Results', 'figure_size': 100, 'figure_aspect': 1}}
            def parse(*args, **kwargs):
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(json.dumps(document))
                return 100, 20, object()
            def extract(*args):
                figure = root / images['1']['image_path']
                figure.parent.mkdir(parents=True, exist_ok=True)
                figure.write_bytes(b'image')
                (directory / 'P01_images.json').write_text(json.dumps(images))
                (directory / 'P01_tables.json').write_text('{}')
                return 0, 0, images, {}
            def plan(doc, ims, tables, config, record):
                record(40, 5)
                chosen = {'Results': {'image': '1'}}
                return make_panels(doc, ims, tables, chosen), chosen
            parsed, extracted, planned = Mock(side_effect=parse), Mock(side_effect=extract), Mock(side_effect=plan)
            inference = Mock(side_effect=RuntimeError('local layout interrupted'))
            tree = types.SimpleNamespace(
                main_train=lambda: ({}, {}), main_inference=inference,
                get_arrangments_in_inches=lambda w,h,p,f,t,u: (w/u,h/u,p,f,t),
                split_textbox=lambda t,r: (dict(t), dict(t)), to_inches=lambda v,u:v/u)
            modules = {
                'PosterAgent.parse_raw': types.SimpleNamespace(parse_raw=parsed, gen_image_and_table=extracted),
                'PosterAgent.tree_split_layout': tree,
                'utils.wei_utils': types.SimpleNamespace(get_agent_config=lambda m: {},
                    scale_to_target_area=lambda w,h:(w,h), char_capacity=lambda **kw: 50),
            }
            argv = [str(ENTRY), '--poster_path=input/P01/paper.pdf', '--model_name_t=A',
                    '--model_name_v=A', f'--usage_path={root}/run/detail_log.json',
                    f'--checkpoint_dir={root}/run/preparation',
                    f'--intermediate_dir={root}/run/intermediate']
            cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(sys.modules, modules), patch('combined_planner.plan_figures', planned), \
                     patch.object(sys, 'argv', argv), patch('atexit.register'):
                    with self.assertRaises(RuntimeError):
                        runpy.run_path(str(ENTRY), run_name='__main__')
                    raw.unlink()
                    (root / images['1']['image_path']).unlink()
                    inference.side_effect = None
                    inference.return_value = (
                        [{'panel_id': 0, 'panel_name': 'Poster Title & Authors', 'width': 100},
                         {'panel_id': 1, 'panel_name': 'Results', 'width': 100}],
                        [{'panel_id': 1, 'width': 80, 'height': 80}],
                        [{'panel_id': 0, 'x':0,'y':0,'width':100,'height':20}])
                    runpy.run_path(str(ENTRY), run_name='__main__')
            finally:
                os.chdir(cwd)
            self.assertEqual(parsed.call_count, 1)
            self.assertEqual(extracted.call_count, 1)
            self.assertEqual(planned.call_count, 1)
            self.assertTrue((root / f'tree_splits/{tag}_P01_tree_split_0.json').exists())
            usage = json.loads((root / 'run/detail_log.json').read_text())
            self.assertEqual(usage['parser_in_t'], 100)
            self.assertEqual(usage['planning_in_t'], 40)
            report = json.loads((root / 'run/cache_usage.json').read_text())
            self.assertEqual(report['reused_stages'], ['parse', 'plan'])
