"""Offline checks for automatic paper-grouped PDF and preview exports."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from poster_naming import group_poster_exports, poster_stem


class PosterExports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "outputs" / "latex"

    def render(self, root, run_id, paper, model, content=b"rendered poster"):
        run = root / str(run_id)
        (run / "latex").mkdir(parents=True, exist_ok=True)
        (run / "run_metadata.json").write_text(json.dumps({
            "input_paper_id": paper, "llm_model": model}))
        for suffix in (".pdf", ".png"):
            (run / "latex" / f"{poster_stem(paper, model)}{suffix}").write_bytes(content)
        return group_poster_exports(run)

    def test_four_models_share_paper_folder_and_other_papers_are_separate(self):
        models = ["claude-opus-5", "gpt-5.6-sol",
                  "meta.llama-4-maverick-17b-instruct", "qwen.qwen3-vl-235b-a22b"]
        for run_id, model in enumerate(models, 1):
            folder = self.render(self.root, run_id, "P01", model)
            self.assertEqual(folder, self.root / "posters/p01")
        self.assertEqual({p.name for p in folder.iterdir()}, {
            f"{poster_stem('P01', model)}{suffix}"
            for model in models for suffix in (".pdf", ".png")})
        other = self.render(self.root, 5, "P02", models[0])
        self.assertEqual(other, self.root / "posters/p02")
        self.assertEqual(len(list(folder.iterdir())), 8)

    def test_rebuild_refreshes_copies_and_dry_runs_are_isolated(self):
        folder = self.render(self.root, 1, "P01", "model", b"original")
        dry = self.render(self.root / "dry_run", 1, "P01", "model", b"pilot")
        self.render(self.root, 1, "P01", "model", b"rebuilt")
        for suffix in (".pdf", ".png"):
            self.assertEqual((folder / f"p01 x model{suffix}").read_bytes(), b"rebuilt")
            self.assertEqual((dry / f"p01 x model{suffix}").read_bytes(), b"pilot")
        self.assertEqual((self.root / "1/latex/p01 x model.pdf").read_bytes(), b"rebuilt")


if __name__ == "__main__":
    unittest.main()
