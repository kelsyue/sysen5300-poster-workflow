"""parse_paper: bounded attempts, every attempt's tokens recorded, seeded section selection."""
import json
import os
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import paper_parser  # noqa: E402

PAPER_MD = 'x' * 600


def fake_modules(replies):
    """Paper2Poster's modules, with a model that returns `replies` in order."""
    calls = []

    class Agent:
        def __init__(self, **kwargs):
            pass

        def reset(self):
            pass

        def step(self, prompt):
            calls.append(prompt)
            return types.SimpleNamespace(msgs=[types.SimpleNamespace(content=replies[len(calls) - 1])])

    converted = types.SimpleNamespace(document=types.SimpleNamespace(export_to_markdown=lambda: PAPER_MD))
    upstream = types.SimpleNamespace(doc_converter=types.SimpleNamespace(convert=lambda path: converted))
    template = lambda text: types.SimpleNamespace(render=lambda markdown_document: f'PROMPT {markdown_document}')
    modules = {
        'PosterAgent': types.SimpleNamespace(parse_raw=upstream), 'PosterAgent.parse_raw': upstream,
        'camel': types.SimpleNamespace(), 'camel.agents': types.SimpleNamespace(ChatAgent=Agent),
        'camel.models': types.SimpleNamespace(ModelFactory=types.SimpleNamespace(create=lambda **kw: None)),
        'jinja2': types.SimpleNamespace(Template=template),
        'utils': types.SimpleNamespace(), 'utils.src': types.SimpleNamespace(),
        'utils.src.utils': types.SimpleNamespace(get_json_from_response=json.loads),
        'utils.wei_utils': types.SimpleNamespace(account_token=lambda r: (1000, 50)),
    }
    return modules, calls


def sections(n):
    return {'sections': [{'title': 'Poster Title & Author' if i == 0 else f'S{i}', 'content': 'c'}
                         for i in range(n)]}


class ParsePaper(unittest.TestCase):
    def run_parse(self, replies, max_attempts=2, seed='0-P01'):
        modules, calls = fake_modules(replies)
        usage = []
        args = types.SimpleNamespace(poster_path='paper.pdf', model_name_t='A', model_name_v='A', poster_name='P01')
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, modules):
            prompt = Path(d) / 'utils/prompts/gen_poster_raw_content_v2.txt'
            prompt.parent.mkdir(parents=True)
            prompt.write_text('{{ markdown_document }}')
            os.chdir(d)  # the parser runs from the Paper2Poster working directory
            try:
                paper_parser.parse_paper(args, {'model_platform': 'p', 'model_type': 't', 'model_config': {}},
                                         lambda i, o: usage.append((i, o)), max_attempts, random.Random(seed))
                out = json.loads(Path('contents/<A_A>_P01_raw_content.json').read_text())
            finally:
                os.chdir(cwd)
        return out, usage, calls

    def test_retries_are_bounded_and_every_attempt_is_counted(self):
        with self.assertRaises(RuntimeError):
            self.run_parse(['{}', '{}', json.dumps(sections(3))], max_attempts=2)
        out, usage, calls = self.run_parse(['{}', json.dumps(sections(3))])
        self.assertEqual(len(calls), 2)
        self.assertEqual(usage, [(1000, 50), (1000, 50)])
        self.assertEqual(len(out['sections']), 3)

    def test_section_selection_is_seeded(self):
        a, _, _ = self.run_parse([json.dumps(sections(14))])
        b, _, _ = self.run_parse([json.dumps(sections(14))])
        self.assertEqual(len(a['sections']), 9)
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
