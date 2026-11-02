"""Figures for the preliminary report (no model calls).

Reads the outputs of build_dataset.py and analyze.py (results/latex/analysis/) and the judge
calibration files, and writes one PNG per figure to results/latex/report_figures/:

  fig1_workflow_success.png   success rate per model, exact one-sided 95% bounds, 95% target
  fig2_latency.png            latency per poster by model
  fig3_cost.png               generation cost per poster by model (log scale)
  fig4_coverage.png           judge coverage by model, mean with bootstrap 95% CI, 90% limit
  fig5_quality.png            judge quality by model, mean with bootstrap 95% CI, 4.0 limit
  fig6_judge_validation.png   GPT-4o vs human quality on the calibration posters, before/after
  fig7_latency_ichart.png     individuals chart of latency in run order (exploratory)

Usage (from harness/, after analyze.py):
    python analysis/report_figures.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent
RES = HARNESS / "results/latex/analysis"
OUT = HARNESS / "results/latex/report_figures"
MODELS = ["claude-opus-5", "gpt-5.6-sol", "meta.llama-4-maverick-17b-instruct", "qwen.qwen3-vl-235b-a22b"]
LABELS = {"claude-opus-5": "Claude Opus 5", "gpt-5.6-sol": "GPT-5.6 Sol",
          "meta.llama-4-maverick-17b-instruct": "Llama 4 Maverick", "qwen.qwen3-vl-235b-a22b": "Qwen3-VL 235B"}
COLORS = {"claude-opus-5": "#C2410C", "gpt-5.6-sol": "#0F766E",
          "meta.llama-4-maverick-17b-instruct": "#1D4ED8", "qwen.qwen3-vl-235b-a22b": "#7C3AED"}
JUDGE = "gemini-3.5-flash"
CALIBRATION = {"Original prompt": "data/latex/judge_scores.csv",
               "Revision 2": "data/latex/gpt4o_calibration_2/judge_scores.csv"}
HUMAN = "data/latex/gpt4o_calibration_2/human_summary_manual_scoring.csv"

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 11, "axes.titleweight": "bold"})


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=200)
    plt.close(fig)
    print(f"wrote {(OUT / name).relative_to(HARNESS)}")


def strip(ax, values: list[np.ndarray], seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    for i, (m, v) in enumerate(zip(MODELS, values)):
        ax.scatter(i + rng.uniform(-.13, .13, len(v)), v, s=22, alpha=.75, color=COLORS[m], edgecolor="white", lw=.5, zorder=3)
    ax.set_xticks(range(len(MODELS)), [LABELS[m] for m in MODELS])


def per_model_box(df, col, ylabel, title, name, log=False):
    vals = [df.loc[df.llm_model == m, col].dropna().to_numpy(float) for m in MODELS]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.boxplot(vals, positions=range(len(MODELS)), widths=.5, showfliers=False,
               medianprops={"color": "black"}, boxprops={"color": "#6B7280"}, whiskerprops={"color": "#6B7280"},
               capprops={"color": "#6B7280"})
    strip(ax, vals)
    if log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    save(fig, name)


def judged_measure(df, cap, measure, limit, ylabel, title, name, ylim):
    col = f"{measure}__{JUDGE}"
    vals = [df.loc[df.llm_model == m, col].dropna().to_numpy(float) for m in MODELS]
    c = cap[(cap.source == JUDGE) & (cap.measure == measure)].set_index("llm_model")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    strip(ax, vals)
    for i, m in enumerate(MODELS):
        if m in c.index and c.loc[m, "n_scored"] >= 2:
            lo, hi, mean = c.loc[m, ["mean_ci_boot_lo", "mean_ci_boot_hi", "mean"]]
            ax.errorbar(i + .28, mean, yerr=[[mean - lo], [hi - mean]], fmt="D", color="black", ms=5, capsize=3, zorder=4)
        n = len(vals[i])
        ax.text(i, ylim[0] + .03 * (ylim[1] - ylim[0]), f"n = {n}", ha="center", fontsize=8, color="#374151")
    ax.axhline(limit, color="#B91C1C", ls="--", lw=1.2)
    ax.text(len(MODELS) - .5, limit, f" limit {limit:g}", color="#B91C1C", va="bottom", ha="right", fontsize=8)
    ax.set_ylim(*ylim)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    save(fig, name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RES / "dataset.csv")
    df = df[df.split == "main"]
    cap = pd.read_csv(RES / "capability.csv")
    succ = pd.read_csv(RES / "success.csv").set_index("llm_model")

    # 1 workflow success
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for i, m in enumerate(MODELS):
        r = succ.loc[m]
        ax.bar(i, 100 * r.rate, color=COLORS[m], width=.6, alpha=.85)
        ax.errorbar(i, 100 * r.rate, yerr=[[100 * (r.rate - r.lower_95)], [100 * (r.upper_95 - r.rate)]],
                    color="black", capsize=4, lw=1)
        ax.text(i, 3, f"{int(r.successes)}/{int(r.attempts)}", ha="center", color="white", fontweight="bold")
    ax.axhline(95, color="#B91C1C", ls="--", lw=1.2)
    ax.text(len(MODELS) - .5, 95, " target 95%", color="#B91C1C", va="bottom", ha="right", fontsize=8)
    ax.set_xticks(range(len(MODELS)), [LABELS[m] for m in MODELS])
    ax.set_ylim(0, 105)
    ax.set_ylabel("Workflow success (%)")
    ax.set_title("Workflow success per model")
    save(fig, "fig1_workflow_success.png")

    # 2-3 latency and cost
    per_model_box(df, "latency", "Latency per poster (s)", "Latency per poster", "fig2_latency.png")
    per_model_box(df, "generation_cost", "Cost per poster (USD, log scale)", "Generation cost per poster",
                  "fig3_cost.png", log=True)

    # 4-5 judged content measures
    judged_measure(df, cap, "coverage_pct", 90, "Key-information coverage (%)",
                   "Coverage by model (Gemini judge)", "fig4_coverage.png", (0, 105))
    judged_measure(df, cap, "quality_score", 4, "Poster quality (1-5)",
                   "Quality by model (Gemini judge)", "fig5_quality.png", (0.5, 5.5))

    # 6 judge validation: GPT-4o vs human quality, before and after the prompt revision
    human = pd.read_csv(HARNESS / HUMAN).set_index("poster_code")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6), sharex=True, sharey=True)
    rng = np.random.default_rng(1)
    for ax, (label, path) in zip(axes, CALIBRATION.items()):
        j = pd.read_csv(HARNESS / path)
        j = j[j.judge_model == "openai.gpt-4o"].drop_duplicates("poster_code", keep="last").set_index("poster_code")
        d = pd.DataFrame({"h": human.quality_score, "j": j.quality_score}).dropna()
        ax.plot([1, 5], [1, 5], color="#9CA3AF", lw=1)
        ax.scatter(d.h + rng.uniform(-.12, .12, len(d)), d.j + rng.uniform(-.12, .12, len(d)), s=30,
                   color="#0F766E", alpha=.8, edgecolor="white")
        mae, bias = (d.j - d.h).abs().mean(), (d.j - d.h).mean()
        ax.set_title(f"{label}\nMAE {mae:.2f}, bias {bias:+.2f}, n = {len(d)}", fontsize=10)
        ax.set_xlabel("Human quality score")
        ax.set_xticks(range(1, 6))
        ax.set_yticks(range(1, 6))
    axes[0].set_ylabel("GPT-4o quality score")
    fig.suptitle("Judge validation on the calibration posters (line = perfect agreement)", fontsize=10, fontweight="bold")
    save(fig, "fig6_judge_validation.png")

    # 7 individuals chart of latency (exploratory)
    fig, axes = plt.subplots(1, len(MODELS), figsize=(9, 2.8), sharey=True)
    order = df.sort_values(["run_order", "original_run_id"])
    for ax, m in zip(axes, MODELS):
        v = order.loc[order.llm_model == m, "latency"].to_numpy(float)
        mrbar = np.abs(np.diff(v)).mean()
        cl, ucl, lcl = v.mean(), v.mean() + 3 * mrbar / 1.128, max(0, v.mean() - 3 * mrbar / 1.128)
        ax.plot(range(1, len(v) + 1), v, marker="o", ms=4, color=COLORS[m])
        for y, ls in ((cl, "-"), (ucl, "--"), (lcl, "--")):
            ax.axhline(y, color="#6B7280", ls=ls, lw=.9)
        ax.set_title(LABELS[m], fontsize=9)
        ax.set_xlabel("Paper in run order")
    axes[0].set_ylabel("Latency (s)")
    fig.suptitle("Individuals chart of latency (exploratory)", fontsize=10, fontweight="bold")
    save(fig, "fig7_latency_ichart.png")


if __name__ == "__main__":
    main()
