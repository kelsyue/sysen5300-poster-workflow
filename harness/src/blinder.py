"""Blinder: give each successful LaTeX poster an anonymous poster_code (component 2).

Implements FR-10 for the judge and the human scoring sheet. For every row with
workflow_success = 1 in the runs file it:
  - picks a random code (e.g. P-7K3Q) that encodes nothing about the run;
  - copies the poster PDF to blinded/<code>.pdf (the run's own file name contains the
    model ID) and writes the PDF's text to blinded/<code>.txt with pdftotext, the same
    extraction the Runner uses for poster_word_count;
  - records code <-> run_id <-> llm_model in data/private/ (gitignored, team only).

Outputs, under data/latex/ (data/latex/dry_run/ with --dry-run):
  blinded/<code>.pdf, blinded/<code>.txt
  judge_manifest.csv           poster_code, input_paper_id, poster_path, poster_text_path, poster_word_count
  human_scores_template.csv    one row per poster in random order, columns of 03_data_schema.md §2.3
and data/private/latex[/dry_run]/blind_key.csv: poster_code, runs_file, run_id, llm_model.

Re-running keeps existing codes and only adds new posters.

Usage (from harness/):
    python src/blinder.py                    # data/latex/runs.csv
    python src/blinder.py --dry-run          # data/latex/dry_run/runs.csv
    python src/blinder.py --dry-run --runs data/dry_run/runs.csv   # older runs with a latex/poster.pdf
"""
from __future__ import annotations

import argparse
import csv
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"  # no 0/O, 1/I/L, U
ITEMS = ["chk_problem", "chk_method", "chk_data", "chk_setup", "chk_primary_result",
         "chk_secondary_result", "chk_baseline", "chk_conclusion", "chk_limitation"]
MANIFEST_COLUMNS = ["poster_code", "input_paper_id", "poster_path", "poster_text_path", "poster_word_count"]
KEY_COLUMNS = ["poster_code", "runs_file", "run_id", "llm_model"]
HUMAN_COLUMNS = (["poster_code", "evaluator_id", "input_paper_id", "presentation_position"] + ITEMS
                 + ["n_claims_total", "n_claims_unsupported", "flagged_claims", "quality_score",
                    "minutes_spent", "submitted_at"])


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def poster_pdf(row: dict) -> Path:
    """The LaTeX PDF for a run. New runs record it as poster_path; older runs recorded
    the PPTX and have the LaTeX build in latex/poster.pdf next to it."""
    p = HARNESS / row["poster_path"]
    if p.suffix.lower() == ".pdf":
        return p
    return p.parent / "latex" / "poster.pdf"


def new_code(taken: set[str]) -> str:
    while True:
        code = "P-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        if code not in taken:
            taken.add(code)
            return code


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--runs", help="runs file; default data/latex/runs.csv (or data/latex/dry_run/runs.csv)")
    args = ap.parse_args()

    sub = Path("latex") / ("dry_run" if args.dry_run else "")
    runs_path = HARNESS / (args.runs or Path("data") / sub / "runs.csv")
    data, private = HARNESS / "data" / sub, HARNESS / "data" / "private" / sub
    runs_file = str(runs_path.relative_to(HARNESS))
    runs = [r for r in read_csv(runs_path) if r.get("workflow_success") == "1"]
    if not runs:
        sys.exit(f"No successful runs in {runs_file}")

    key = read_csv(private / "blind_key.csv")
    manifest = {r["poster_code"]: r for r in read_csv(data / "judge_manifest.csv")}
    by_run = {(k["runs_file"], k["run_id"]): k["poster_code"] for k in key}
    taken = {k["poster_code"] for k in key}
    added, pending = 0, 0
    for r in runs:
        if (runs_file, r["run_id"]) in by_run:
            continue
        pdf = poster_pdf(r)
        if not pdf.exists():
            sys.exit(f"Run {r['run_id']}: no LaTeX poster at {pdf.relative_to(HARNESS)}")
        if not r.get("visual_check"):
            pending += 1
        code = new_code(taken)
        out_pdf, out_txt = data / "blinded" / f"{code}.pdf", data / "blinded" / f"{code}.txt"
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, out_pdf)
        text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(out_pdf), "-"],
                              capture_output=True, text=True, check=True).stdout
        out_txt.write_text(text, encoding="utf-8")
        words = len(text.split())
        if r.get("poster_word_count") and int(r["poster_word_count"]) != words:
            print(f"  note: run {r['run_id']} runs.csv word count {r['poster_word_count']}, PDF text {words}"
                  " (the manifest uses the PDF text)")
        key.append({"poster_code": code, "runs_file": runs_file, "run_id": r["run_id"], "llm_model": r["llm_model"]})
        manifest[code] = {"poster_code": code, "input_paper_id": r["input_paper_id"],
                          "poster_path": str(out_pdf.relative_to(HARNESS)),
                          "poster_text_path": str(out_txt.relative_to(HARNESS)), "poster_word_count": words}
        added += 1

    write_csv(private / "blind_key.csv", KEY_COLUMNS, key)
    rows = list(manifest.values())
    secrets.SystemRandom().shuffle(rows)  # file order says nothing about run order
    write_csv(data / "judge_manifest.csv", MANIFEST_COLUMNS, rows)
    # Append new posters only, so a template someone is already filling in is never reshuffled.
    template = read_csv(data / "human_scores_template.csv")
    listed = {t["poster_code"] for t in template}
    template += [{"poster_code": m["poster_code"], "input_paper_id": m["input_paper_id"],
                  "presentation_position": len(template) + i}
                 for i, m in enumerate((m for m in rows if m["poster_code"] not in listed), 1)]
    write_csv(data / "human_scores_template.csv", HUMAN_COLUMNS, template)
    print(f"{added} new poster(s), {len(rows)} total -> {(data / 'judge_manifest.csv').relative_to(HARNESS)}")
    print(f"Key: {(private / 'blind_key.csv').relative_to(HARNESS)} (team only)")
    if pending:
        print(f"WARNING: {pending} new poster(s) have no visual_check yet (OI-7); "
              "a poster that later fails it must be dropped from the scores (DR-2).")


if __name__ == "__main__":
    main()
