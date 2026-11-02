"""Collect a run set into one folder for the team to evaluate (no model calls).

Joins the runs file, the judge scores (un-blinded with the private key) and, when they
exist, the human scores, and writes under results/latex/ (results/latex/dry_run/ with --dry-run):

  by_run.csv     one row per attempt: the codebook variables (llm_model, input_paper_id,
                 run_id, latency, generation_cost, workflow_success, token_usage), the
                 failure reason, the fitted font scale, and per judge / human the mean
                 coverage_pct, halluc_pct (% of claims unsupported), quality_score, plus judge_cost
  by_model.csv   one row per candidate: attempts, success rate, mean and total latency,
                 tokens and cost, mean judge and human scores
  posters/<input_paper_id>/<llm_model>.pdf/.png   links to each successful poster, so all
                 candidates for one paper sit side by side

These files name the model, so they are for the team only: evaluators score the blinded
copies in data/latex/blinded/.

Usage (from harness/):
    python src/results.py --dry-run
    python src/results.py
    python src/results.py --dry-run --runs data/dry_run/runs.csv   # older runs file
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import yaml

from blinder import poster_pdf

HARNESS = Path(__file__).resolve().parent.parent
MEASURES = ["coverage_pct", "halluc_pct", "quality_score"]
ITEMS = ["chk_problem", "chk_method", "chk_data", "chk_setup", "chk_primary_result",
         "chk_secondary_result", "chk_baseline", "chk_conclusion", "chk_limitation"]


def judge_table(path: Path, key: pd.DataFrame, prices: dict) -> pd.DataFrame:
    """Mean of each judge's usable rows (newest prompt version, all repeats), per run_id."""
    if not path.exists() or key.empty:
        return pd.DataFrame()
    j = pd.read_csv(path)
    j["halluc_pct"] = 100 * j.n_claims_unsupported / j.n_claims_total.where(j.n_claims_total > 0)
    newest = j.sort_values("judged_at").groupby("judge_model")["judge_prompt_sha256"].last()
    j = j[(j.judge_prompt_sha256 == j.judge_model.map(newest)) & (j.parse_ok == 1)]
    j = j.drop_duplicates(["poster_code", "judge_model", "judge_repeat"], keep="last")
    price = lambda m, col: (prices.get(m) or {}).get(col) or float("nan")
    j["judge_cost"] = [(ti * price(m, "input_per_mtok") + to * price(m, "output_per_mtok")) / 1e6
                       for m, ti, to in zip(j.judge_model, j.tokens_in, j.tokens_out)]
    j = j.merge(key[["poster_code", "run_id"]], on="poster_code")
    agg = j.groupby(["run_id", "judge_model"]).agg(
        **{m: (m, "mean") for m in MEASURES}, judge_cost=("judge_cost", "sum"), judge_tokens=("tokens_in", "sum"))
    agg["judge_tokens"] += j.groupby(["run_id", "judge_model"])["tokens_out"].sum()
    wide = agg.unstack("judge_model")
    wide.columns = [f"{m}__{judge}" for m, judge in wide.columns]
    return wide.reset_index()


def human_table(path: Path, key: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    """Mean across evaluators per run_id, computed as in 03_data_schema.md §4."""
    if not path.exists() or key.empty:
        return pd.DataFrame()
    h = pd.read_csv(path)
    h[ITEMS] = h[ITEMS].replace({"NA": float("nan")}).apply(pd.to_numeric, errors="coerce")
    h = h.merge(manifest[["poster_code", "poster_word_count"]], on="poster_code")
    h["coverage_pct"] = 100 * h[ITEMS].sum(axis=1, min_count=1) / h[ITEMS].notna().sum(axis=1)
    h["halluc_pct"] = 100 * h["n_claims_unsupported"] / h["n_claims_total"].where(h["n_claims_total"] > 0)
    h = h.merge(key[["poster_code", "run_id"]], on="poster_code")
    agg = h.groupby("run_id").agg(**{f"{m}__human": (m, "mean") for m in MEASURES},
                                  n_evaluators=("evaluator_id", "nunique"))
    return agg.reset_index()


def link(target: Path, link_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    try:
        link_path.symlink_to(os.path.relpath(target, link_path.parent))
    except OSError:  # file systems without symlinks
        shutil.copyfile(target, link_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--runs", help="runs file; default data/latex/runs.csv (or data/latex/dry_run/runs.csv)")
    ap.add_argument("--config", default="config/experiment.yaml")
    args = ap.parse_args()

    sub = Path("latex") / ("dry_run" if args.dry_run else "")
    data, out = HARNESS / "data" / sub, HARNESS / "results" / sub
    runs_path = HARNESS / (args.runs or Path("data") / sub / "runs.csv")
    runs_file = str(runs_path.relative_to(HARNESS))
    runs = pd.read_csv(runs_path, dtype={"visual_check": str, "failure_reason": str})
    cfg = yaml.safe_load(open(HARNESS / args.config))
    prices = (yaml.safe_load(open(HARNESS / cfg["fixed"].get("prices_file", "config/prices.yaml"))) or {}).get("models") or {}

    key_path = HARNESS / "data" / "private" / sub / "blind_key.csv"
    key = pd.read_csv(key_path) if key_path.exists() else pd.DataFrame(columns=["poster_code", "runs_file", "run_id"])
    key = key[key.runs_file == runs_file]
    manifest_path = data / "judge_manifest.csv"
    manifest = pd.read_csv(manifest_path) if manifest_path.exists() else pd.DataFrame(columns=["poster_code", "poster_word_count"])

    fit_scale, posters = [], []
    for _, r in runs.iterrows():
        scale, poster = None, ""
        if r.workflow_success == 1:
            pdf = poster_pdf({"poster_path": r.poster_path})
            fit = pdf.parent / "fit.json"
            scale = json.loads(fit.read_text()).get("scale") if fit.exists() else None
            dest = out / "posters" / r.input_paper_id / f"{r.llm_model}.pdf"
            if pdf.exists():
                link(pdf, dest)
                png = pdf.with_suffix(".png")
                if png.exists():
                    link(png, dest.with_suffix(".png"))
                poster = str(dest.relative_to(out))
        fit_scale.append(scale)
        posters.append(poster)

    cols = ["run_id", "llm_model", "input_paper_id", "attempt", "workflow_success", "failure_reason",
            "visual_check", "latency", "token_usage", "input_tokens", "output_tokens", "generation_cost",
            "retries", "poster_word_count"]
    by_run = runs[cols].assign(fit_scale=fit_scale, poster=posters)
    by_run = by_run.merge(key[["run_id", "poster_code"]], on="run_id", how="left")
    for extra in (judge_table(data / "judge_scores.csv", key, prices), human_table(data / "human_scores.csv", key, manifest)):
        if not extra.empty:
            by_run = by_run.merge(extra, on="run_id", how="left")

    g = by_run.groupby("llm_model")
    by_model = pd.DataFrame({
        "attempts": g.size(),
        "successes": g.workflow_success.sum(),
        "success_rate_pct": 100 * g.workflow_success.mean(),
        "latency_mean_s": g.latency.mean(),
        "latency_total_s": g.latency.sum(),
        "token_usage_mean": g.token_usage.mean(),
        "token_usage_total": g.token_usage.sum(),
        "generation_cost_mean": g.generation_cost.mean(),
        "generation_cost_total": g.generation_cost.sum(min_count=1),
        "fit_scale_mean": g.fit_scale.mean(),
    })
    score_cols = [c for c in by_run.columns if "__" in c]
    if score_cols:
        by_model = by_model.join(g[score_cols].mean())

    out.mkdir(parents=True, exist_ok=True)
    by_run.to_csv(out / "by_run.csv", index=False)
    by_model.reset_index().to_csv(out / "by_model.csv", index=False)
    print(f"{len(by_run)} runs, {int(by_run.workflow_success.sum())} successful -> {out.relative_to(HARNESS)}/")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(by_model.round(3).to_string())


if __name__ == "__main__":
    main()
