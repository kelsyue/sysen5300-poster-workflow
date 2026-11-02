"""Analysis dataset: one row per paper x candidate (no model calls).

Each row combines the original attempt (data/latex/runs.csv) with its checkpoint
recoveries (data/latex/recovery_attempts.csv):

  first_attempt_success   the original attempt produced a usable poster
  eventual_success        the original attempt or a recovery did
  workflow_success        = eventual_success (the codebook variable, includes both)
  recovered               eventual_success and not first_attempt_success
  n_attempts              original + recoveries
  latency                 seconds, summed over every attempt (recoveries reuse checkpoints,
                          so the sum is the total time spent to get this poster)
  token_usage, input_tokens, output_tokens, generation_cost
                          summed over every attempt (recovery rows hold only new usage)
  token_records_missing   attempts interrupted before the provider reported usage

Content scores come from the blinded judge rows (data/latex/judge_scores.csv) and, when
present, the human scores (data/latex/human_scores.csv), joined through the private blind
key. Per source and poster: coverage_pct, halluc_pct, quality_score, n_claims_total,
n_claims_unsupported. A judge task that failed leaves only that measure empty. Repeats
and evaluators are averaged.

  halluc_pct = 100 x n_claims_unsupported / n_claims_total    (% of the poster's claims;
               the unit the human evaluators use; unsupported includes contradicted)

Papers listed in analysis.calibration_papers were used to tune the judge prompts; their
rows are kept with split = calibration and left out of the main comparison.

Writes results/latex/analysis/dataset.csv (names the models: team only).

Usage (from harness/):
    python analysis/build_dataset.py
    python analysis/build_dataset.py --judge-prompt openai.gpt-4o=<sha256>   # several prompt versions
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HARNESS = Path(__file__).resolve().parent.parent
ITEMS = ["chk_problem", "chk_method", "chk_data", "chk_setup", "chk_primary_result",
         "chk_secondary_result", "chk_baseline", "chk_conclusion", "chk_limitation"]
SUMMED = ["latency", "token_usage", "input_tokens", "output_tokens", "generation_cost"]
CONTENT = ["coverage_pct", "halluc_pct", "quality_score", "n_claims_total", "n_claims_unsupported"]
# a failed judge task (failed_tasks) empties only the measures it produces
TASK_MEASURES = {"coverage": ["coverage_pct"],
                 "claims": ["halluc_pct", "n_claims_total", "n_claims_unsupported"],
                 "quality": ["quality_score"]}


def read(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, **kw) if path.exists() else pd.DataFrame()


def halluc_pct(unsupported: pd.Series, total: pd.Series) -> pd.Series:
    """% of claims unsupported; empty when there were no claims to audit."""
    return (100 * unsupported / total.where(total > 0)).astype(float)


def attempt_chains(runs: pd.DataFrame, recoveries: pd.DataFrame, runs_file: str, recovery_file: str) -> pd.DataFrame:
    rows = []
    for _, first in runs.iterrows():
        later = (recoveries[recoveries.original_run_id == first.run_id].sort_values(["completion_attempt", "run_id"])
                 if not recoveries.empty else recoveries)
        chain = [(runs_file, first)] + [(recovery_file, r) for _, r in later.iterrows()]
        won = [(f, r) for f, r in chain if r.workflow_success == 1]
        poster_file, poster = won[0] if won else (chain[-1][0], chain[-1][1])
        row = {
            "input_paper_id": first.input_paper_id, "llm_model": first.llm_model,
            "original_run_id": first.run_id, "run_order": first.run_order, "batch_id": first.batch_id,
            "started_at": first.started_at,
            "first_attempt_success": int(first.workflow_success == 1),
            "eventual_success": int(bool(won)),
            "n_attempts": len(chain),
            "final_failure_reason": "" if won or pd.isna(chain[-1][1].failure_reason) else chain[-1][1].failure_reason,
            "token_records_missing": sum(int(r.get("token_usage") in (0, "0") and r.workflow_success != 1
                                             and str(r.failure_reason) in ("E_INTERRUPTED", "E_API")) for _, r in chain),
            "poster_runs_file": poster_file if won else "", "poster_run_id": poster.run_id if won else np.nan,
            "poster_prompt_sha256": poster.prompt_sha256 if won else "",
            "poster_word_count": poster.poster_word_count if won else np.nan,
        }
        for col in SUMMED:
            row[col] = sum(float(r.get(col) or 0) for _, r in chain)
        rows.append(row)
    df = pd.DataFrame(rows)
    df["workflow_success"] = df["eventual_success"]
    df["recovered"] = ((df.eventual_success == 1) & (df.first_attempt_success == 0)).astype(int)
    return df


def judge_scores(path: Path, chosen: dict[str, str], codes: set[str]) -> dict[str, pd.DataFrame]:
    """Per judge: one row per poster_code, averaged over repeats, one prompt version only."""
    j = read(path)
    if j.empty:
        return {}
    j = j[j.poster_code.isin(codes)].copy()
    j["halluc_pct"] = halluc_pct(j.n_claims_unsupported, j.n_claims_total)
    failed = j.failed_tasks.fillna("").astype(str).str.split(";")
    for task, cols in TASK_MEASURES.items():
        j.loc[failed.map(lambda f: task in f), cols] = np.nan
    out = {}
    for judge, rows in j.groupby("judge_model"):
        hashes = sorted(rows.judge_prompt_sha256.unique())
        if judge in chosen:
            rows = rows[rows.judge_prompt_sha256 == chosen[judge]]
        elif len(hashes) > 1:
            sys.exit(f"{judge} has {len(hashes)} prompt versions on these posters: {hashes}. "
                     f"Pick one with --judge-prompt {judge}=<sha256>.")
        rows = rows.drop_duplicates(["poster_code", "judge_repeat"], keep="last")
        out[judge] = rows.groupby("poster_code")[CONTENT].mean()
    return out


def human_scores(path: Path) -> pd.DataFrame:
    h = read(path)
    if h.empty:
        return h
    h[ITEMS] = h[ITEMS].replace({"NA": np.nan}).apply(pd.to_numeric, errors="coerce")
    h["coverage_pct"] = 100 * h[ITEMS].sum(axis=1, min_count=1) / h[ITEMS].notna().sum(axis=1)
    h["halluc_pct"] = halluc_pct(h.n_claims_unsupported, h.n_claims_total)
    return h.groupby("poster_code")[CONTENT].mean()


def build(data: Path, key_path: Path, cfg: dict, chosen: dict[str, str]) -> pd.DataFrame:
    runs_path, recovery_path = data / "runs.csv", data / "recovery_attempts.csv"
    # the blind key names runs files relative to harness/, as blinder.py writes them
    runs_file, recovery_file = (str(p.relative_to(HARNESS)) if p.is_relative_to(HARNESS) else str(p)
                                for p in (runs_path, recovery_path))
    df = attempt_chains(read(runs_path), read(recovery_path), runs_file, recovery_file)
    calibration = set(cfg.get("analysis", {}).get("calibration_papers") or [])
    df.insert(2, "split", np.where(df.input_paper_id.isin(calibration), "calibration", "main"))

    key = read(key_path, dtype=str)
    if key.empty:
        print(f"No blind key at {key_path}: content scores left empty.")
        df["poster_code"] = ""
        return df
    key["run_id"] = pd.to_numeric(key.run_id)
    df = df.merge(key[["poster_code", "runs_file", "run_id"]], how="left",
                  left_on=["poster_runs_file", "poster_run_id"], right_on=["runs_file", "run_id"]).drop(columns=["runs_file", "run_id"])
    if df.poster_code.dropna().duplicated().any():
        sys.exit("A poster_code maps to more than one attempt (DR-1).")
    codes = set(df.poster_code.dropna())
    sources = judge_scores(data / "judge_scores.csv", chosen, codes)
    human = human_scores(data / "human_scores.csv")
    if not human.empty:
        sources["human"] = human
    for name, scores in sources.items():
        df = df.merge(scores.add_suffix(f"__{name}"), how="left", left_on="poster_code", right_index=True)
    return df


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiment.yaml")
    ap.add_argument("--data-dir", default="data/latex")
    ap.add_argument("--key", default="data/private/latex/blind_key.csv")
    ap.add_argument("--out", default="results/latex/analysis/dataset.csv")
    ap.add_argument("--judge-prompt", action="append", default=[], metavar="JUDGE=SHA256",
                    help="judge prompt version to use when a judge has several on these posters")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(open(HARNESS / args.config))
    chosen = dict(s.split("=", 1) for s in args.judge_prompt)
    df = build(HARNESS / args.data_dir, HARNESS / args.key, cfg, chosen)
    out = HARNESS / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    main_rows = df[df.split == "main"]
    print(f"{len(df)} paper x model rows ({len(main_rows)} main, {len(df) - len(main_rows)} calibration) "
          f"-> {out}")
    print(main_rows.groupby("llm_model")[["first_attempt_success", "eventual_success", "recovered"]].sum().to_string())


if __name__ == "__main__":
    main()
