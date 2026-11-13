"""Seeded paper-block order for generation (runner) and judging (judge.py); offline."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'judge'))
import runner
from judge import presentation_order

MODELS = ['claude-opus-5', 'gpt-5.6-sol', 'meta.llama-4-maverick-17b-instruct', 'qwen.qwen3-vl-235b-a22b']


class GenerationOrder(unittest.TestCase):
    def test_seeded_random_per_paper_and_independent_of_config_order(self):
        orders = {p: runner.model_order(MODELS, 5300, p) for p in (f'P{i:02d}' for i in range(1, 31))}
        self.assertTrue(all(sorted(o) == sorted(MODELS) for o in orders.values()))
        self.assertEqual(runner.model_order(MODELS[::-1], 5300, 'P07'), orders['P07'])  # reproducible
        firsts = {o[0] for o in orders.values()}
        self.assertEqual(firsts, set(MODELS))      # no model is always first


class JudgeOrder(unittest.TestCase):
    ROWS = [{'poster_code': f'P-{p}{m}', 'input_paper_id': p} for p in 'ABCDE' for m in 'WXYZ']

    def test_posters_of_a_paper_are_consecutive_in_random_order(self):
        order = presentation_order(self.ROWS, 5300, 'openai.gpt-4o', 1)
        self.assertEqual(sorted(r['poster_code'] for r in order), sorted(r['poster_code'] for r in self.ROWS))
        papers = [r['input_paper_id'] for r in order]
        blocks = [p for i, p in enumerate(papers) if i == 0 or papers[i - 1] != p]
        self.assertEqual(len(blocks), 5)                 # one contiguous block per paper
        self.assertNotEqual(blocks, sorted(blocks))      # paper order is shuffled
        positions = {r['poster_code'][-1] for r in order[::4]}
        self.assertGreater(len(positions), 1)            # no poster suffix always first

    def test_order_depends_on_seed_not_on_manifest_order(self):
        a = presentation_order(self.ROWS, 5300, 'openai.gpt-4o', 1)
        self.assertEqual(presentation_order(self.ROWS[::-1], 5300, 'openai.gpt-4o', 1), a)
        self.assertNotEqual(presentation_order(self.ROWS, 5300, 'openai.gpt-4o', 2), a)  # repeats differ


if __name__ == '__main__':
    unittest.main()
