"""Shared filenames for poster exports."""
import csv
import json
import re
from pathlib import Path


def poster_stem(paper_id: str, model: str) -> str:
    """Keep gateway model punctuation while replacing filename separators."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", f"{paper_id.lower()} x {model}")


def run_poster_stem(run_dir: Path) -> str:
    """Read new run metadata, or the runs table for older archived runs."""
    metadata = run_dir / "run_metadata.json"
    if metadata.exists():
        row = json.loads(metadata.read_text())
        return poster_stem(row["input_paper_id"], row["llm_model"])
    harness = Path(__file__).resolve().parent.parent
    runs = harness / "data" / ("dry_run" if run_dir.parent.name == "dry_run" else "") / "runs.csv"
    if runs.exists():
        with runs.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["run_id"] == run_dir.name:
                    return poster_stem(row["input_paper_id"], row["llm_model"])
    raise ValueError(f"Cannot identify paper and model for {run_dir}: missing run metadata and runs.csv entry")
