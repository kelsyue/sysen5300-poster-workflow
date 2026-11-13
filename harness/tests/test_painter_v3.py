"""latex-painter-v3 checks: Painter, crop regrowth, measured fit and overflow repair (offline)."""
import json
import os
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import latex_poster
import poster_painter as pp
import runner
from combined_planner import make_panels, plan_figures, source_block, PLAN_TASK, SHARED_SYSTEM, SYSTEM_PROMPT
from gateway_chat import GatewayChat
from figure_crops import grow_box

ENTRY = Path(__file__).resolve().parents[1] / 'src/latex_prepare.py'
DOCUMENT = {'meta': {'poster_title': 'A Paper'},
            'sections': [{'title': 'Poster Title & Author', 'content': 'A Paper by X'},
                         {'title': 'Motivation', 'content': ' '.join(['word'] * 100)},
                         {'title': 'Results', 'content': 'Accuracy rises from 0.62 to 0.71 on 1,416 posters. '
                                                         + ' '.join(['word'] * 300)}]}
IMAGES = {'2': {'caption': 'Fig. 2. Accuracy by model.', 'image_path': 'x/fig.png'}}


UTILS = {'utils.src.utils': types.SimpleNamespace(get_json_from_response=json.loads)}


class FakeAsk:
    """Stands in for GatewayChat.ask: canned replies, every call kept."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, stage, system, blocks, cache=False):
        self.calls.append({'stage': stage, 'system': system, 'blocks': blocks, 'cache': cache})
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


GOOD = json.dumps({'Motivation': {'paragraph': 'Posters need **short** text.', 'bullets': []},
                   'Results': {'paragraph': 'Accuracy rises to **0.71**.', 'bullets': ['**Model A** is best']}})


class Painter(unittest.TestCase):
    def test_budgets_follow_section_length_within_limits(self):
        budgets = pp.word_budgets(DOCUMENT, {'total_words': 150})
        self.assertEqual(set(budgets), {'Motivation', 'Results'})  # title section excluded
        self.assertGreater(budgets['Results'], budgets['Motivation'])
        self.assertLessEqual(budgets['Results'], pp.DEFAULTS['max_section_words'])
        self.assertGreaterEqual(budgets['Motivation'], pp.DEFAULTS['min_section_words'])

    def test_validation_rejects_unusable_output(self):
        budgets = {'Motivation': 40, 'Results': 60}
        good = {'Motivation': 'Posters need **short** text.',                          # paragraph only
                'results': {'paragraph': 'Two results.', 'bullets': ['- Accuracy **0.71**']}}
        self.assertEqual(pp.validate_sections(good, budgets),
                         {'Motivation': {'paragraph': 'Posters need **short** text.', 'bullets': []},
                          'Results': {'paragraph': 'Two results.', 'bullets': ['Accuracy **0.71**']}})
        p = lambda text, bullets=(): {'paragraph': text, 'bullets': list(bullets)}
        for bad in ({'Motivation': p('x')},                                    # dropped section
                    {**good, 'Invented': p('x')},                              # unknown section
                    {'Motivation': p('', ['only bullets']), 'Results': p('x')},  # no paragraph
                    {'Motivation': ['a list'], 'Results': p('x')},             # bullets only, old format
                    {'Motivation': p('x', ['b'] * 5), 'Results': p('x')},      # too many bullets
                    {'Motivation': p('| a | b |'), 'Results': p('x')},         # table
                    {'Motivation': p('word ' * 200), 'Results': p('x')},       # far over budget
                    ['not', 'an', 'object']):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pp.validate_sections(bad, budgets)

    def test_numbers_not_in_the_source_are_reported(self):
        sections = {'Results': {'paragraph': 'Accuracy **0.71** on 1416 posters.', 'bullets': ['Gain of **12%**']}}
        self.assertEqual(pp.unsupported_numbers(sections, DOCUMENT, {}), {'Results': ['12']})

    def test_one_call_writes_bullets_after_the_cached_source(self):
        ask = FakeAsk('not json', GOOD)
        original = json.loads(json.dumps(DOCUMENT))
        with patch.dict(sys.modules, UTILS):
            painted, report = pp.paint_sections(DOCUMENT, {'Results': {'image': '2'}}, IMAGES, {}, ask, max_attempts=2)
        self.assertEqual(len(ask.calls), 2)                       # one rejected reply, one retry
        call = ask.calls[-1]
        self.assertEqual((call['stage'], call['system'], call['cache']), ('painter', SHARED_SYSTEM, True))
        self.assertEqual(call['blocks'][0], source_block(DOCUMENT, IMAGES, {}))  # cacheable prefix first
        self.assertIn('Fig. 2. Accuracy by model.', call['blocks'][1])          # the Painter knows the visual
        results = next(s for s in painted['sections'] if s['title'] == 'Results')
        self.assertEqual(results['content'], 'Accuracy rises to **0.71**.\n• **Model A** is best')
        self.assertEqual(report['sections_with_bullets'], ['Results'])
        self.assertEqual(painted['sections'][0]['content'], 'A Paper by X')  # title section untouched
        self.assertEqual(report['unsupported_numbers'], {})
        self.assertEqual(DOCUMENT, original)  # the parser document is not modified

    def test_attempts_are_bounded(self):
        ask = FakeAsk('{"Motivation": {"paragraph": "only one section", "bullets": []}}')
        with patch.dict(sys.modules, UTILS), self.assertRaises(ValueError):
            pp.paint_sections(DOCUMENT, {}, {}, {}, ask, max_attempts=2)
        self.assertEqual(len(ask.calls), 2)

    def test_planner_painter_and_shortening_share_one_prefix(self):
        """Prompt caching only pays off if the three calls start with identical bytes."""
        plan_ask, paint_ask = FakeAsk('{"Results": {"image": "2"}}'), FakeAsk(GOOD)
        short_ask = FakeAsk(json.dumps({'Motivation': 'One two.', 'Results': {'paragraph': 'Accuracy **0.71**.'}}))
        with patch.dict(sys.modules, UTILS):
            plan_figures(DOCUMENT, {**IMAGES, '2': {**IMAGES['2'], 'figure_size': 4, 'figure_aspect': 2}}, {},
                         None, None, ask=plan_ask)
            painted, _ = pp.paint_sections(DOCUMENT, {'Results': {'image': '2'}}, IMAGES, {}, paint_ask)
            new, report = pp.shorten(painted, DOCUMENT, IMAGES, {}, short_ask, factor=0.75)
        calls = plan_ask.calls + paint_ask.calls + short_ask.calls
        self.assertEqual({c['system'] for c in calls}, {SHARED_SYSTEM})
        self.assertEqual(len({c['blocks'][0] for c in calls}), 1)
        self.assertTrue(all(c['cache'] for c in calls))
        self.assertEqual([c['stage'] for c in calls], ['planning', 'painter', 'painter_repair'])
        self.assertEqual(report['budgets']['Motivation'], 15)  # 75% of 4 words, raised to the 15-word floor
        self.assertEqual(pp.current_sections(new)['Motivation'], {'paragraph': 'One two.', 'bullets': []})
        self.assertIn('"bullets":["**Model A** is best"]', short_ask.calls[0]['blocks'][1])  # current text sent

    def test_planner_fill_rule_only_in_v3(self):
        self.assertNotIn('every section that has a relevant one', SYSTEM_PROMPT)
        self.assertIn('every section that has a relevant one', PLAN_TASK)


class Gateway(unittest.TestCase):
    def client(self, usage):
        response = types.SimpleNamespace(
            id='r1', model='m', created=1, system_fingerprint=None,
            choices=[types.SimpleNamespace(finish_reason='stop', message=types.SimpleNamespace(content='{}'))],
            usage=types.SimpleNamespace(prompt_tokens=2517, completion_tokens=5, cache_creation_input_tokens=None,
                                        prompt_tokens_details=types.SimpleNamespace(**usage)))
        raw = types.SimpleNamespace(parse=lambda: response,
                                    headers={'x-litellm-response-cost': '0.0015', 'x-litellm-version': '1.108.3',
                                             'x-litellm-model-api-base': 'https://internal'})
        create = Mock(return_value=raw)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            with_raw_response=types.SimpleNamespace(create=create)))), create

    def test_cache_marker_usage_cost_and_call_record(self):
        with tempfile.TemporaryDirectory() as d:
            usage, saved = {}, Mock()
            client, create = self.client({'cached_tokens': 2505, 'cache_write_tokens': 0})
            chat = GatewayChat('claude-opus-5', Path(d), usage, saved, cache_markers=True, client=client,
                               env={'P2P_MAX_OUTPUT_TOKENS': '8192', 'P2P_TEMPERATURE': '0'})
            self.assertEqual(chat.ask('painter', 'sys', ['SOURCE', 'task'], cache=True), '{}')
            request = create.call_args.kwargs
            self.assertEqual((request['max_tokens'], request['temperature']), (8192, 0.0))
            parts = request['messages'][1]['content']
            self.assertEqual(parts[0]['cache_control'], {'type': 'ephemeral'})
            self.assertNotIn('cache_control', parts[1])
            self.assertEqual(usage, {'painter_in_t': 2517, 'painter_out_t': 5, 'painter_cached_t': 2505,
                                     'painter_cachewrite_t': 0, 'painter_cost_usd': 0.0015})
            saved.assert_called_once()
            record = json.loads((Path(d) / '01_painter.json').read_text())
            self.assertEqual(record['request'], json.loads(json.dumps(request)))
            self.assertNotIn('x-litellm-model-api-base', record['gateway'])  # no internal URLs

    def test_no_marker_without_cache_or_for_models_that_do_not_need_it(self):
        for markers, cache in ((False, True), (True, False)):
            client, create = self.client({'cached_tokens': 0})
            GatewayChat('m', Path(tempfile.mkdtemp()), {}, Mock(), cache_markers=markers, client=client,
                        env={}).ask('parser', 'sys', ['paper'], cache=cache)
            self.assertNotIn('cache_control', create.call_args.kwargs['messages'][1]['content'][0])
            self.assertNotIn('max_tokens', create.call_args.kwargs)


class Accounting(unittest.TestCase):
    PRICES = {'opus': {'input_per_mtok': 5.0, 'output_per_mtok': 25.0,
                       'cache_read_per_mtok': 0.5, 'cache_write_per_mtok': 6.25},
              'plain': {'input_per_mtok': 1.0, 'output_per_mtok': 2.0}}

    def test_cache_reads_and_writes_use_cache_prices(self):
        # The gateway charged 0.0014925 for 2513 prompt tokens (2505 cached) + 8 out (2026-11-12).
        self.assertAlmostEqual(runner.token_cost(self.PRICES, 'opus', 2513, 8, cached=2505), 0.0014925, places=6)
        self.assertEqual(runner.token_cost(self.PRICES, 'opus', 1000, 0, written=1000), 0.00625)
        self.assertEqual(runner.token_cost(self.PRICES, 'plain', 1000, 1000, cached=500), 0.003)  # no cache price

    def test_read_tokens_sums_cache_counts_and_gateway_cost(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'detail_log.json').write_text(json.dumps({
                'parser_in_t': 100, 'parser_out_t': 10, 'parser_cachewrite_t': 0, 'parser_cost_usd': 0.01,
                'painter_in_t': 50, 'painter_out_t': 5, 'painter_cached_t': 40, 'painter_cost_usd': 0.002,
                'parser_time': 3.5}))
            t = runner.read_tokens(Path(d))
        self.assertEqual((t['input_tokens'], t['cached_tokens'], t['token_usage']), (150, 40, 165))
        self.assertAlmostEqual(t['gateway_cost'], 0.012)

    def test_older_runs_file_keeps_its_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'runs.csv'
            path.write_text('run_id,llm_model\n1,a\n')
            runner.append_run(path, {'run_id': 2, 'llm_model': 'b', 'cache_write_tokens': 5})
            self.assertEqual(path.read_text().splitlines(), ['run_id,llm_model', '1,a', '2,b'])


class CropRegrowth(unittest.TestCase):
    def page(self):
        page = np.full((400, 400), 255, dtype=np.uint8)
        page[110:180, 110:290] = 0      # figure body, inside docling's box
        page[180:190, 120:160] = 0      # axis label below the docling box
        page[260:270, 100:300] = 0      # next paragraph of the paper, after a wide gap
        return page

    def test_clipped_label_is_completed_without_taking_the_next_paragraph(self):
        left, top, right, bottom = grow_box(self.page(), (100, 100, 300, 184), px_per_pt=2)
        self.assertGreaterEqual(bottom, 190)   # the whole label is inside
        self.assertLess(bottom, 260)           # the paragraph below is not
        self.assertEqual((left, top, right), (100, 100, 300))

    def test_box_already_in_whitespace_is_unchanged(self):
        self.assertEqual(grow_box(self.page(), (90, 90, 310, 200), px_per_pt=2), (90, 90, 310, 200))

    def test_no_blank_strip_nearby_keeps_docling_edge(self):
        page = np.zeros((400, 400), dtype=np.uint8)  # ink everywhere
        self.assertEqual(grow_box(page, (100, 100, 300, 200), px_per_pt=2), (100, 100, 300, 200))


class MeasuredFit(unittest.TestCase):
    LOG = ("P2PPAGE 3468.96pt 2601.72pt 1040.69pt\n"
           "P2PBS 0 150000000\nP2PBE 0 100000000\nP2PBS 1 99000000\nP2PBE 1 60000000\n"
           "P2PBS 2 150000000\nP2PBE 2 2000000\n"
           "Overfull \\hbox (3.0pt too wide) in paragraph\n")

    def test_markers_give_block_heights_and_column_bottoms(self):
        m = latex_poster.measure(self.LOG)
        self.assertAlmostEqual(m['page_height_pt'], 2601.72)
        weights = latex_poster.measured_weights(m, 3)
        self.assertAlmostEqual(weights[0] - weights[1], (50e6 - 39e6) / 65536)
        a = latex_poster.assess(m, [[0, 1], [2]])
        # Column 2 ends 30.5pt above the page bottom: inside the 39pt margin, so it overflows.
        self.assertFalse(a['fits'])
        self.assertAlmostEqual(a['overflow_pt'], 39.0 - 2000000 / 65536, places=0)
        self.assertTrue(latex_poster.assess(m, [[0, 1]])['fits'])

    def test_line_sticking_out_of_its_column_is_a_failure(self):
        m = latex_poster.measure(self.LOG.replace('3.0pt', '25.0pt'))
        self.assertFalse(latex_poster.assess(m, [[0, 1]])['fits'])

    def test_figures_grow_only_in_columns_with_space(self):
        new = latex_poster.grow_figures({'a.png': 0.6, 'b.png': 0.6}, {'a.png': 2.0, 'b.png': 2.0},
                                        [['a.png'], ['b.png']], [800.0, 45.0], 39.0, 2600.0, 1000.0)
        self.assertGreater(new['a.png'], 0.6)
        self.assertLessEqual(new['a.png'], 1.0)
        self.assertEqual(new['b.png'], 0.6)

    def test_tables_grow_less_than_plots(self):
        new = latex_poster.grow_figures({'P-table-1.png': 0.6, 'P-picture-1.png': 0.6},
                                        {'P-table-1.png': 3.0, 'P-picture-1.png': 3.0},
                                        [['P-table-1.png', 'P-picture-1.png']], [1500.0], 39.0, 2600.0, 1000.0)
        self.assertEqual(new['P-table-1.png'], 0.72)       # 1.2 x planned width
        self.assertEqual(new['P-picture-1.png'], 1.0)      # up to the column width

    def test_bold_key_terms(self):
        tex = latex_poster.format_content('• A **50% gain** & more', lambda s: s.replace('%', r'\%').replace('&', r'\&'))
        self.assertIn(r'\item A \keyterm{50\% gain} \& more', tex)


class TextAndSections(unittest.TestCase):
    def test_symbols_the_text_font_lacks_go_through_the_math_font(self):
        self.assertEqual(latex_poster.text_symbols('ΔAUC ≤ 0.05, Α, é'),
                         r'\ensuremath{\Delta}AUC \ensuremath{\leq} 0.05, A, é')
        m = latex_poster.measure('Missing character: There is no Ж (U+0416) in font [x]!\n')
        self.assertEqual(m['missing_glyphs'], ['Ж U+0416'])

    def test_v3_keeps_upstreams_section_choice_in_paper_order(self):
        import random
        from paper_parser import _finish
        sections = [{'title': f'S{i}', 'content': ''} for i in range(12)]
        def run(keep):
            content = {'sections': [dict(x) for x in sections]}
            cwd = os.getcwd()
            with tempfile.TemporaryDirectory() as d:
                os.chdir(d)
                try:
                    _finish(types.SimpleNamespace(model_name_t='m', model_name_v='m', poster_name='P'),
                            content, random.Random('5300-P'), None, keep_order=keep)
                finally:
                    os.chdir(cwd)
            return [x['title'] for x in content['sections']]
        upstream, ordered = run(False), run(True)
        self.assertEqual(set(upstream), set(ordered))              # the same nine sections
        self.assertEqual(ordered, sorted(ordered, key=lambda t: int(t[1:])))  # in the paper's order
        self.assertNotEqual(upstream, ordered)                     # upstream shuffles them


PAINTED = pp.painted_document(DOCUMENT, {'Motivation': {'paragraph': ' '.join(['m'] * 10), 'bullets': []},
                                         'Results': {'paragraph': ' '.join(['r'] * 10), 'bullets': []}})
EXPANDED = pp.painted_document(DOCUMENT, {'Motivation': {'paragraph': 'EXPANDED ' * 18, 'bullets': []}})
LAYOUT = {'columns': [['Motivation'], ['Results']], 'column_gap_pt': [400.0, 20.0],
          'text_height_pt': {'Motivation': 100.0, 'Results': 100.0}}


def fitted(scale, fits=True, layout=LAYOUT):
    return {'fits': fits, 'scale': scale, 'overflow_pt': 0.0, 'hbox_overflow_pt': 0.0,
            'page_height_pt': 2601.7, 'layout': layout}


class BlankSpace(unittest.TestCase):
    def test_gap_becomes_word_budget_only_for_under_filled_columns(self):
        # 20 words in 200pt of text: 0.1 words/pt; 80% of a 400pt gap -> +32 words, capped at 2x.
        self.assertEqual(pp.expansion_targets(fitted(1.0), PAINTED), {'Motivation': 20})
        self.assertEqual(pp.expansion_targets(fitted(1.0), PAINTED, {'blank_fill_share': 0.2}), {'Motivation': 18})
        small = {**LAYOUT, 'column_gap_pt': [200.0, 20.0]}   # under 10% of the page
        self.assertEqual(pp.expansion_targets(fitted(1.0, layout=small), PAINTED), {})
        self.assertEqual(pp.expansion_targets({'fits': True}, PAINTED), {})   # no measurements: no call

    def test_expand_sends_whole_poster_and_returns_only_targets(self):
        ask = FakeAsk(json.dumps({'Motivation': {'paragraph': 'Longer motivation with **0.71**.', 'bullets': []}}))
        with patch.dict(sys.modules, UTILS):
            new, report = pp.expand(PAINTED, DOCUMENT, IMAGES, {}, ask, {'Motivation': 20})
        call = ask.calls[0]
        self.assertEqual((call['stage'], call['cache']), ('painter_expand', True))
        self.assertEqual(call['blocks'][0], source_block(DOCUMENT, IMAGES, {}))  # cached prefix
        self.assertIn('"title":"Results"', call['blocks'][1])                    # sees the whole poster
        self.assertIn('"expand":[{"title":"Motivation","budget":20}]', call['blocks'][1])
        self.assertEqual(pp.current_sections(new)['Motivation']['paragraph'], 'Longer motivation with **0.71**.')
        self.assertEqual(pp.current_sections(new)['Results'], pp.current_sections(PAINTED)['Results'])
        self.assertEqual(report['unsupported_numbers'], {})

    def test_text_heights_are_measured_between_markers(self):
        m = latex_poster.measure('P2PTS 0 6553600\nP2PTE 0 3276800\n')
        self.assertEqual(m['text_heights'], {0: 50.0})


class OverflowRepair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'vendor').mkdir()
        self.pdf = self.root / 'P01.pdf'
        self.pdf.write_bytes(b'%PDF-placeholder')
        self.cfg = {'fixed': {'paper2poster': {
            'path': str(self.root / 'vendor'), 'python': sys.executable, 'vision_model': 'same_as_candidate',
            'poster_width_inches': 48, 'poster_height_inches': 36, 'workflow': 'latex-painter-v3',
            'run_set': 'latex_v3', 'painter': {'total_words': 450}, 'prompt_cache_models': ['candidate']}},
            'gateway': {'max_transport_retries': 0}}

    def run_with(self, fits_sequence, hbox=0.0):
        commands, renders = [], iter(fits_sequence)
        out = self.root / 'outputs/1'
        def execute(cmd, **kwargs):
            commands.append(cmd)
            if cmd[1].endswith('latex_prepare.py'):
                self.assertTrue(any(a.startswith('--painter_settings=') for a in cmd))
                self.assertIn('--prompt_cache', cmd)
                (out / 'intermediate').mkdir(parents=True)
                (out / 'intermediate/painted_content.json').write_text(json.dumps(PAINTED))
                (out / 'detail_log.json').write_text(json.dumps({'parser_in_t': 100, 'painter_out_t': 20}))
            elif cmd[1].endswith('poster_painter.py'):
                usage = json.loads((out / 'detail_log.json').read_text())
                stage = 'painter_expand' if '--expand' in cmd else 'painter_repair'
                usage.update({f'{stage}_in_t': 30, f'{stage}_out_t': 10})
                (out / 'detail_log.json').write_text(json.dumps(usage))
                if '--expand' in cmd:  # what the real CLI does: back up, then write the longer text
                    inter = out / 'intermediate'
                    (inter / 'painted_content.before_expand.json').write_text((inter / 'painted_content.json').read_text())
                    (inter / 'painted_content.json').write_text(json.dumps(EXPANDED))
            elif cmd[1].endswith('latex_poster.py'):
                work = out / 'latex'
                work.mkdir(exist_ok=True)
                (work / 'p01 x candidate.pdf').write_bytes(b'%PDF')
                (work / 'poster.tex').write_text(r'\includegraphics[width=0.8\linewidth]{figures/P01-picture-1.png}')
                result = next(renders)
                if isinstance(result, bool):
                    result = {'fits': result, 'scale': 0.85, 'overflow_pt': 120.0, 'hbox_overflow_pt': hbox,
                              'page_height_pt': 2601.7}
                (work / 'fit.json').write_text(json.dumps(result))
            elif cmd[0] == 'pdftotext':
                return subprocess.CompletedProcess(cmd, 0, stdout='Methods Results')
            return subprocess.CompletedProcess(cmd, 0)
        with patch.object(runner, 'HARNESS', self.root), patch.object(runner.subprocess, 'run', side_effect=execute):
            row = runner.run_attempt(run_id=1, model='candidate', paper_id='P01', pdf=self.pdf,
                                     cfg=self.cfg, out_root=self.root / 'outputs', env={})
        return row, commands

    def test_overflow_gets_one_shortening_call_and_its_tokens_are_counted(self):
        row, commands = self.run_with([False, True])
        repairs = [c for c in commands if c[1].endswith('poster_painter.py')]
        self.assertEqual(len(repairs), 1)
        self.assertIn(f'--factor={runner.repair_factor({"overflow_pt": 120.0, "page_height_pt": 2601.7})}', repairs[0])
        self.assertIn('--prompt_cache', repairs[0])
        self.assertEqual(row['workflow_success'], 1)
        self.assertEqual(row['token_usage'], 100 + 20 + 30 + 10)

    def test_still_overflowing_after_repair_fails_instead_of_cutting(self):
        row, commands = self.run_with([False, False])
        self.assertEqual(sum(c[1].endswith('poster_painter.py') for c in commands), 1)
        self.assertEqual(row['failure_reason'], 'E_OVERFLOW')

    def test_line_overflow_is_not_sent_for_shortening(self):
        row, commands = self.run_with([False], hbox=40.0)
        self.assertFalse(any(c[1].endswith('poster_painter.py') for c in commands))
        self.assertEqual(row['failure_reason'], 'E_OVERFLOW')

    def test_blank_column_gets_one_expansion_call_kept_when_it_still_fits(self):
        row, commands = self.run_with([fitted(1.0), fitted(1.0)])
        expands = [c for c in commands if c[1].endswith('poster_painter.py')]
        self.assertEqual(len(expands), 1)
        self.assertIn('--expand', expands[0])
        self.assertIn('--targets={"Motivation": 20}', expands[0])
        self.assertIn('--prompt_cache', expands[0])
        self.assertEqual(row['workflow_success'], 1)
        self.assertEqual(row['token_usage'], 100 + 20 + 30 + 10)
        painted = (self.root / 'outputs/1/intermediate/painted_content.json').read_text()
        self.assertIn('EXPANDED', painted)

    def test_expansion_that_needs_a_smaller_font_is_reverted(self):
        row, commands = self.run_with([fitted(1.0), fitted(0.95), fitted(1.0)])
        self.assertEqual(sum(c[1].endswith('latex_poster.py') for c in commands), 3)  # re-render the kept text
        painted = (self.root / 'outputs/1/intermediate/painted_content.json').read_text()
        self.assertNotIn('EXPANDED', painted)
        self.assertEqual(row['workflow_success'], 1)
        self.assertIn('expansion reverted', (self.root / 'outputs/1/run.log').read_text())

    def test_full_columns_get_no_expansion_call(self):
        full = {**LAYOUT, 'column_gap_pt': [30.0, 20.0]}
        row, commands = self.run_with([fitted(1.0, layout=full)])
        self.assertFalse(any(c[1].endswith('poster_painter.py') for c in commands))

    def test_repair_factor_bounds(self):
        self.assertEqual(runner.repair_factor({'overflow_pt': 0.0, 'page_height_pt': 2600}), 0.9)
        self.assertEqual(runner.repair_factor({'overflow_pt': 5000.0, 'page_height_pt': 2600}), 0.5)


class FakeChat:
    """GatewayChat stand-in for latex_prepare: records 10 input tokens per call in the usage log."""
    made = []

    def __init__(self, model, calls_dir, usage, save_usage, cache_markers=False):
        FakeChat.made.append((model, cache_markers))
        self.usage, self.save_usage = usage, save_usage

    def ask(self, stage, system, blocks, cache=False):
        self.usage[f'{stage}_in_t'] = self.usage.get(f'{stage}_in_t', 0) + 10
        self.save_usage()
        return '{}'


class PrepareV3(unittest.TestCase):
    def test_crop_and_painter_stages_run_once_and_resume_from_checkpoints(self):
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
            images = {'1': {'image_path': f'{tag}_images_and_tables/P01/P01-picture-1.png',
                            'caption': 'Results', 'figure_size': 100, 'figure_aspect': 1}}

            def parse(args, config, record_usage, max_attempts, rng, ask=None):
                ask('parser', 'system', ['paper'])
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(json.dumps(DOCUMENT))
                return 'docling result'

            def extract(*args):
                figure = root / images['1']['image_path']
                figure.parent.mkdir(parents=True, exist_ok=True)
                figure.write_bytes(b'image')
                (directory / 'P01_images.json').write_text(json.dumps(images))
                (directory / 'P01_tables.json').write_text('{}')
                return 0, 0, json.loads(json.dumps(images)), {}

            def plan(doc, ims, tables, config, record, raw_path=None, ask=None):
                ask('planning', 'system', ['source', 'task'], cache=True)
                chosen = {'Results': {'image': '1'}}
                return make_panels(doc, ims, tables, chosen), chosen

            def paint(doc, plan_, ims, tables, ask, settings=None, max_attempts=2, raw_path=None):
                self.assertEqual(settings, {'total_words': 300})
                ask('painter', 'system', ['source', 'task'], cache=True)
                return pp.painted_document(doc, {'Motivation': {'paragraph': 'm', 'bullets': []},
                                                 'Results': {'paragraph': 'r', 'bullets': ['b']}}), {'budgets': {}}

            regrow = Mock(return_value={'P01-picture-1.png': {}})
            parsed, planned, painted = Mock(side_effect=parse), Mock(side_effect=plan), Mock(side_effect=paint)
            inference = Mock(side_effect=RuntimeError('local layout interrupted'))
            tree = types.SimpleNamespace(
                main_train=lambda: ({}, {}), main_inference=inference,
                get_arrangments_in_inches=lambda w, h, p, f, t, u: (w / u, h / u, p, f, t),
                split_textbox=lambda t, r: (dict(t), dict(t)), to_inches=lambda v, u: v / u)
            modules = {
                'PosterAgent.parse_raw': types.SimpleNamespace(gen_image_and_table=extract,
                                                               doc_converter=Mock()),
                'PosterAgent.tree_split_layout': tree,
                'utils.wei_utils': types.SimpleNamespace(get_agent_config=lambda m: {},
                    scale_to_target_area=lambda w, h: (w, h), char_capacity=lambda **kw: 50),
            }
            argv = [str(ENTRY), '--poster_path=input/P01/paper.pdf', '--model_name_t=A', '--model_name_v=A',
                    f'--usage_path={root}/run/detail_log.json', f'--checkpoint_dir={root}/run/preparation',
                    f'--intermediate_dir={root}/run/intermediate', '--painter_settings={"total_words": 300}',
                    '--prompt_cache']
            cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(sys.modules, modules), patch('combined_planner.plan_figures', planned), \
                     patch('paper_parser.parse_paper', parsed), patch('poster_painter.paint_sections', painted), \
                     patch('figure_crops.regrow_crops', regrow), patch('gateway_chat.GatewayChat', FakeChat), \
                     patch.object(sys, 'argv', argv), patch('atexit.register'):
                    with self.assertRaises(RuntimeError):
                        runpy.run_path(str(ENTRY), run_name='__main__')
                    inference.side_effect = None
                    inference.return_value = (
                        [{'panel_id': 0, 'panel_name': 'Poster Title & Author', 'width': 100},
                         {'panel_id': 1, 'panel_name': 'Motivation', 'width': 100},
                         {'panel_id': 2, 'panel_name': 'Results', 'width': 100}],
                        [{'panel_id': 2, 'width': 80, 'height': 80}],
                        [{'panel_id': 0, 'x': 0, 'y': 0, 'width': 100, 'height': 20}])
                    runpy.run_path(str(ENTRY), run_name='__main__')
            finally:
                os.chdir(cwd)
            self.assertEqual((parsed.call_count, regrow.call_count, planned.call_count, painted.call_count),
                             (1, 1, 1, 1))
            self.assertEqual(regrow.call_args.args[0], 'docling result')  # no second PDF conversion
            usage = json.loads((root / 'run/detail_log.json').read_text())
            self.assertEqual((usage['parser_in_t'], usage['planning_in_t'], usage['painter_in_t']), (10, 10, 10))
            self.assertEqual(set(FakeChat.made), {('A', True)})  # cache markers requested by --prompt_cache
            out = json.loads((root / 'run/intermediate/painted_content.json').read_text())
            self.assertEqual(out['sections'][2]['content'], 'r\n• b')
            report = json.loads((root / 'run/cache_usage.json').read_text())
            self.assertEqual(report['reused_stages'], ['parse', 'crop', 'plan', 'paint'])


if __name__ == '__main__':
    unittest.main()
