"""Compare the candidate LLMs and apply the acceptance gate (no model calls).

Reads results/latex/analysis/dataset.csv (analysis/build_dataset.py) and writes, under
results/latex/analysis/ (names the models: team only):

  describe.csv      AR-1  n, mean, median, SD, percentiles, skewness, kurtosis per model x measure
  compare.csv       AR-2  mixed model (paper as random effect, likelihood-ratio test), Friedman on
                          complete papers, Cochran's Q for the success measures
  pairwise.csv      AR-2  Wilcoxon signed-rank (continuous) / exact McNemar (binary) per model pair,
                          Holm-adjusted within each measure
  spc_signals.csv   AR-3  exploratory charts: I-MR, p-chart of unsupported claims, p-chart of failures
  capability.csv    AR-4  mean with bootstrap and t intervals, share of posters meeting the limit with
                          an exact interval, Ppk/Cpk (exploratory) with bootstrap intervals
  success.csv       AR-5  workflow success with exact one-sided bounds
  probability.csv   AR-6  P(meets all) as a series estimate vs observed
  gate.csv          GR-1..GR-4 and the overall recommendation, per score source
  figures/*.png, report.md

Content measures (coverage_pct, halluc_pct, quality_score) are analysed per score source
(each judge, and humans when present): failed attempts have no poster, so they are excluded
from content measures and every content result is reported next to its n.

Usage (from harness/):
    python analysis/analyze.py                    # main comparison (calibration papers left out)
    python analysis/analyze.py --split calibration
"""
from __future__ import annotations

import argparse
import itertools
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

HARNESS = Path(__file__).resolve().parent.parent
GENERATION = {"latency": "Latency (s)", "generation_cost": "Generation cost (USD)", "token_usage": "Token usage"}
BINARY = {"workflow_success": "Workflow success"}
CONTENT_LABELS = {"coverage_pct": "Key-information coverage (%)", "halluc_pct": "Hallucination (% of claims)",
                  "quality_score": "Poster quality (1-5)"}
GATE_IDS = {"coverage_pct": "GR-1", "halluc_pct": "GR-2", "quality_score": "GR-3"}


# --------------------------------------------------------------------------- helpers

def limits(cfg: dict) -> dict[str, tuple[str, float]]:
    sl = cfg["spec_limits"]
    return {"coverage_pct": ("lsl", sl["key_information_coverage"]["lsl"]),
            "halluc_pct": ("usl", sl["hallucination_rate"]["usl"]),
            "quality_score": ("lsl", sl["poster_quality_score"]["lsl"])}


def meets(values: pd.Series, side: str, limit: float) -> pd.Series:
    return values >= limit if side == "lsl" else values < limit


def sources(df: pd.DataFrame) -> list[str]:
    found = {c.split("__", 1)[1] for c in df.columns if c.startswith("coverage_pct__") or c.startswith("quality_score__")}
    return sorted(s for s in found if any(df.get(f"{m}__{s}", pd.Series(dtype=float)).notna().any() for m in CONTENT_LABELS))


def clopper_pearson(k: int, n: int, conf: float) -> tuple[float, float]:
    """Two-sided exact interval; pass conf = 0.90 for one-sided 95% bounds."""
    if n == 0:
        return math.nan, math.nan
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else stats.beta.ppf(a, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - a, k + 1, n - k)
    return float(lo), float(hi)


def boot(values: np.ndarray, fn, reps: int, rng, conf: float) -> tuple[float, float]:
    if len(values) < 2:
        return math.nan, math.nan
    draws = np.array([fn(rng.choice(values, len(values))) for _ in range(reps)], dtype=float)
    draws = draws[np.isfinite(draws)]
    if len(draws) < reps / 2:          # most resamples undefined (e.g. no spread)
        return math.nan, math.nan
    a = (1 - conf) / 2 * 100
    return float(np.percentile(draws, a)), float(np.percentile(draws, 100 - a))


def ppk(values: np.ndarray, side: str, limit: float) -> float:
    sd = np.std(values, ddof=1) if len(values) > 1 else 0.0
    if sd == 0:
        return math.nan
    return (values.mean() - limit) / (3 * sd) if side == "lsl" else (limit - values.mean()) / (3 * sd)


def decide(lo: float, hi: float, side: str, limit: float) -> str:
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return "inconclusive"
    if side == "lsl":
        return "pass" if lo >= limit else "fail" if hi < limit else "inconclusive"
    return "pass" if hi < limit else "fail" if lo >= limit else "inconclusive"


def model_order(cfg: dict, df: pd.DataFrame) -> list[str]:
    configured = [c["id"] for c in cfg.get("candidates", [])]
    return [m for m in configured if m in set(df.llm_model)] + sorted(set(df.llm_model) - set(configured))


def holm(rows: list[dict]) -> list[dict]:
    from statsmodels.stats.multitest import multipletests
    ps = [r["p"] for r in rows]
    finite = [i for i, p in enumerate(ps) if np.isfinite(p)]
    if finite:
        adj = multipletests([ps[i] for i in finite], method="holm")[1]
        for i, a in zip(finite, adj):
            rows[i]["p_holm"] = float(a)
    return rows


# --------------------------------------------------------------------------- AR-1

def describe(values: pd.Series) -> dict:
    v = values.dropna().astype(float)
    q = v.quantile([.05, .25, .75, .95]) if len(v) else pd.Series([math.nan] * 4, index=[.05, .25, .75, .95])
    return {"n": len(v), "mean": v.mean(), "median": v.median(), "sd": v.std(ddof=1),
            "p5": q[.05], "p25": q[.25], "p75": q[.75], "p95": q[.95],
            "skewness": v.skew() if len(v) > 2 else math.nan, "kurtosis": v.kurt() if len(v) > 3 else math.nan}


# --------------------------------------------------------------------------- AR-2

def mixed_model(d: pd.DataFrame, log: bool = False) -> dict:
    """y ~ model with paper as a random intercept; LR test of the model term (ML fits).
    log=True fits log(y): cost, tokens and latency differ by orders of magnitude between models."""
    import statsmodels.formula.api as smf
    d = d.dropna(subset=["y"])
    test = "mixed model LR" + (" (log scale)" if log else "")
    if log:
        d = d[d.y > 0].assign(y=lambda x: np.log(x.y))
    if d.y.nunique() < 2 or d.llm_model.nunique() < 2:
        return {"test": test, "note": "no variation"}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            full = smf.mixedlm("y ~ C(llm_model)", d, groups=d["input_paper_id"]).fit(reml=False)
            null = smf.mixedlm("y ~ 1", d, groups=d["input_paper_id"]).fit(reml=False)
        except Exception as e:          # singular or tiny data
            return {"test": test, "note": f"not fitted: {type(e).__name__}: {e}"[:200]}
    lr = max(0.0, 2 * (full.llf - null.llf))
    df_ = d.llm_model.nunique() - 1
    notes = sorted({str(w.message).splitlines()[0][:90] for w in caught})
    return {"test": test, "statistic": lr, "df": df_, "p": float(stats.chi2.sf(lr, df_)),
            "n": len(d), "papers": d.input_paper_id.nunique(), "note": "; ".join(notes)}


def complete_blocks(d: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    return d.pivot(index="input_paper_id", columns="llm_model", values="y").reindex(columns=models).dropna()


def friedman(d: pd.DataFrame, models: list[str]) -> dict:
    wide = complete_blocks(d, models)
    out = {"test": "Friedman (complete papers)", "papers": len(wide)}
    if len(wide) < 2 or len(models) < 3 or np.ptp(wide.values) == 0:
        return {**out, "note": "too few complete papers or no variation"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = stats.friedmanchisquare(*[wide[m] for m in models])
    return {**out, "statistic": float(r.statistic), "df": len(models) - 1, "p": float(r.pvalue)}


def cochran(d: pd.DataFrame, models: list[str]) -> dict:
    from statsmodels.stats.contingency_tables import cochrans_q
    wide = complete_blocks(d, models)
    out = {"test": "Cochran's Q", "papers": len(wide)}
    if len(wide) < 2 or (wide.values == wide.values[0, 0]).all():
        return {**out, "note": "too few papers or no variation"}
    r = cochrans_q(wide.values.astype(int))
    return {**out, "statistic": float(r.statistic), "df": int(r.df), "p": float(r.pvalue)}


def pairwise(d: pd.DataFrame, models: list[str], binary: bool) -> list[dict]:
    from statsmodels.stats.contingency_tables import mcnemar
    rows = []
    for a, b in itertools.combinations(models, 2):
        pair = d.pivot(index="input_paper_id", columns="llm_model", values="y").reindex(columns=[a, b]).dropna()
        x, y = pair[a].to_numpy(float), pair[b].to_numpy(float)
        row = {"model_a": a, "model_b": b, "papers": len(pair), "p": math.nan}
        if binary:
            table = [[int(((x == 1) & (y == 1)).sum()), int(((x == 1) & (y == 0)).sum())],
                     [int(((x == 0) & (y == 1)).sum()), int(((x == 0) & (y == 0)).sum())]]
            row.update(test="exact McNemar", a_minus_b=float(x.mean() - y.mean()) if len(x) else math.nan,
                       p=float(mcnemar(table, exact=True).pvalue) if len(x) else math.nan)
        else:
            row.update(test="Wilcoxon signed-rank", median_diff=float(np.median(x - y)) if len(x) else math.nan)
            if len(x) and np.any(x != y):
                row["p"] = float(stats.wilcoxon(x, y, zero_method="zsplit").pvalue)
            elif len(x):
                row["p"] = 1.0
        rows.append(row)
    return holm(rows)


# --------------------------------------------------------------------------- AR-3 (exploratory)

def imr(values: np.ndarray, sigma: float) -> dict:
    mr = np.abs(np.diff(values))
    cl, mrbar = values.mean(), mr.mean() if len(mr) else math.nan
    return {"cl": cl, "ucl": cl + sigma * mrbar / 1.128, "lcl": cl - sigma * mrbar / 1.128,
            "mr_bar": mrbar, "mr_ucl": 3.267 * mrbar}


def spc(df: pd.DataFrame, models: list[str], srcs: list[str], sigma: float, figdir: Path) -> pd.DataFrame:
    import matplotlib.pyplot as plt
    signals = []
    ordered = df.sort_values(["run_order", "original_run_id"])
    charts = [(m, "", GENERATION[m]) for m in GENERATION] + \
             [(f"{m}__{s}", s, f"{CONTENT_LABELS[m]} [{s}]") for s in srcs for m in ("coverage_pct", "quality_score")]
    for col, src, label in charts:
        fig, axes = plt.subplots(1, len(models), figsize=(4 * len(models), 3), sharey=True, squeeze=False)
        for ax, model in zip(axes[0], models):
            v = ordered.loc[ordered.llm_model == model, ["input_paper_id", col]].dropna()
            ax.set_title(model, fontsize=8)
            if len(v) < 3:
                continue
            c = imr(v[col].to_numpy(float), sigma)
            ax.plot(range(len(v)), v[col], marker="o")
            for k in ("cl", "ucl", "lcl"):
                ax.axhline(c[k], ls="-" if k == "cl" else "--", lw=1, color="grey")
            out = (v[col] > c["ucl"]) | (v[col] < c["lcl"])
            for paper, val in v[out.values].itertuples(index=False):
                signals.append({"chart": "I-MR", "measure": col, "source": src, "llm_model": model,
                                "input_paper_id": paper, "value": val, "lcl": c["lcl"], "ucl": c["ucl"]})
        fig.suptitle(f"I chart (exploratory): {label}", fontsize=9)
        fig.tight_layout()
        fig.savefig(figdir / f"imr_{col}.png", dpi=110)
        plt.close(fig)
    for s in srcs:                       # unsupported claims: defectives among the poster's claims
        for model in models:
            v = ordered.loc[ordered.llm_model == model,
                            ["input_paper_id", f"n_claims_unsupported__{s}", f"n_claims_total__{s}"]].dropna()
            v = v[v.iloc[:, 2] > 0]
            if len(v) < 3:
                continue
            pbar = v.iloc[:, 1].sum() / v.iloc[:, 2].sum()
            for paper, unsup, total in v.itertuples(index=False):
                half = sigma * math.sqrt(pbar * (1 - pbar) / total)
                if unsup / total > pbar + half:
                    signals.append({"chart": "p (claims)", "measure": "halluc_pct", "source": s, "llm_model": model,
                                    "input_paper_id": paper, "value": 100 * unsup / total, "ucl": 100 * (pbar + half)})
    for model in models:                 # workflow failures per batch
        g = df[df.llm_model == model].groupby("batch_id").agg(fail=("workflow_success", lambda x: (x == 0).sum()),
                                                               n=("workflow_success", "size"))
        if len(g) < 2:
            continue
        pbar = g.fail.sum() / g.n.sum()
        for batch, r in g.iterrows():
            half = sigma * math.sqrt(pbar * (1 - pbar) / r.n)
            if r.fail / r.n > pbar + half:
                signals.append({"chart": "p (failures)", "measure": "workflow_success", "source": "",
                                "llm_model": model, "input_paper_id": f"batch {batch}",
                                "value": 100 * r.fail / r.n, "ucl": 100 * (pbar + half)})
    return pd.DataFrame(signals, columns=["chart", "measure", "source", "llm_model", "input_paper_id", "value", "lcl", "ucl"])


# --------------------------------------------------------------------------- AR-4, AR-5, AR-6, gate

def capability(df, models, srcs, lims, an, conf, reps, rng) -> pd.DataFrame:
    rows = []
    ordered = df.sort_values(["run_order", "original_run_id"])
    for s, (m, (side, limit)) in itertools.product(srcs, lims.items()):
        col = f"{m}__{s}"
        if col not in df:
            continue
        for model in models:
            v = ordered.loc[ordered.llm_model == model, col].dropna().to_numpy(float)
            n, k = len(v), int(meets(pd.Series(v), side, limit).sum())
            mean = v.mean() if n else math.nan
            b_lo, b_hi = boot(v, np.mean, reps, rng, conf)
            t_half = stats.t.ppf(1 - (1 - conf) / 2, n - 1) * v.std(ddof=1) / math.sqrt(n) if n > 1 else math.nan
            s_lo, s_hi = clopper_pearson(k, n, conf)
            mr = np.abs(np.diff(v)).mean() if n > 1 else math.nan
            cpk = ((mean - limit) if side == "lsl" else (limit - mean)) / (3 * mr / 1.128) if n > 1 and mr > 0 else math.nan
            p_lo, p_hi = boot(v, lambda x: ppk(x, side, limit), reps, rng, conf)
            if n < an["min_scored"]:
                result = "insufficient data"
            elif an["decision_basis"] == "share":
                result = "pass" if s_lo >= an["target_share"] else "fail" if s_hi < an["target_share"] else "inconclusive"
            else:
                result = decide(b_lo, b_hi, side, limit)
            rows.append({"source": s, "measure": m, "gate": GATE_IDS[m], "llm_model": model, "limit": f"{side} {limit:g}",
                         "n_scored": n, "mean": mean, "mean_ci_boot_lo": b_lo, "mean_ci_boot_hi": b_hi,
                         "mean_ci_t_lo": mean - t_half, "mean_ci_t_hi": mean + t_half,
                         "n_meeting": k, "share_meeting": k / n if n else math.nan,
                         "share_ci_lo": s_lo, "share_ci_hi": s_hi,
                         "ppk": ppk(v, side, limit) if n > 1 else math.nan, "ppk_ci_lo": p_lo, "ppk_ci_hi": p_hi,
                         "cpk_mr": cpk, "result": result})
    return pd.DataFrame(rows)


def success(df, models, lsl_pct) -> pd.DataFrame:
    rows = []
    for model, measure in itertools.product(models, BINARY):
        v = df.loc[df.llm_model == model, measure]
        k, n = int(v.sum()), len(v)
        lo, hi = clopper_pearson(k, n, 0.90)        # one-sided 95% bounds
        target = lsl_pct / 100
        result = "pass" if lo >= target else "fail" if hi < target else "inconclusive"
        rows.append({"llm_model": model, "measure": measure, "successes": k, "attempts": n,
                     "rate": k / n if n else math.nan, "lower_95": lo, "upper_95": hi,
                     "result": result})
    return pd.DataFrame(rows)


def probability(df, models, srcs, lims) -> pd.DataFrame:
    rows = []
    for s, model in itertools.product(srcs, models):
        d = df[df.llm_model == model]
        ok = d[d.workflow_success == 1]
        cols = [f"{m}__{s}" for m in lims]
        if ok.empty or any(c not in d for c in cols):
            continue
        cond = {m: meets(ok[f"{m}__{s}"].dropna(), side, lim).mean() for m, (side, lim) in lims.items()}
        series = d.workflow_success.mean() * np.prod(list(cond.values()))
        scored = ok.dropna(subset=cols)
        all_ok = pd.concat([meets(scored[f"{m}__{s}"], side, lim) for m, (side, lim) in lims.items()], axis=1).all(axis=1)
        observed = all_ok.sum() / (len(d) - len(ok) + len(scored)) if len(scored) else math.nan
        rows.append({"source": s, "llm_model": model, "p_success": d.workflow_success.mean(),
                     **{f"p_{m}_given_success": v for m, v in cond.items()},
                     "p_all_series": series, "p_all_observed": observed})
    return pd.DataFrame(rows)


def gate(cap: pd.DataFrame, succ: pd.DataFrame, models, srcs) -> pd.DataFrame:
    rows = []
    gr4 = succ[succ.measure == "workflow_success"].set_index("llm_model").result
    for s, model in itertools.product(srcs, models):
        res = {r.gate: r.result for r in cap[(cap.source == s) & (cap.llm_model == model)].itertuples()}
        res["GR-4"] = gr4.get(model, "inconclusive")
        vals = list(res.values())
        overall = "Reject" if "fail" in vals else "Accept" if all(v == "pass" for v in vals) else "Inconclusive"
        failing = [g for g, v in sorted(res.items()) if v == "fail"]
        rows.append({"source": s, "llm_model": model, **dict(sorted(res.items())), "recommendation": overall,
                     "failing": ", ".join(failing)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- figures and report

def figures(df, models, srcs, lims, figdir: Path) -> None:
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(0)
    cols = [(m, "", GENERATION[m], None) for m in GENERATION] + \
           [(f"{m}__{s}", s, f"{CONTENT_LABELS[m]} [{s}]", lims[m][1]) for s in srcs for m in lims]
    for col, _, label, limit in cols:
        data = [df.loc[df.llm_model == m, col].dropna().to_numpy(float) for m in models]
        if not any(len(d) for d in data):
            continue
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.boxplot([d if len(d) else [np.nan] for d in data], showfliers=False)
        for i, d in enumerate(data, 1):
            ax.scatter(i + rng.uniform(-.12, .12, len(d)), d, s=14, alpha=.7)
        if limit is not None:
            ax.axhline(limit, color="red", ls="--", lw=1)
        ax.set_xticks(range(1, len(models) + 1), [m.split(".")[-1][:22] for m in models], fontsize=7)
        ax.set_title(label, fontsize=9)
        fig.tight_layout()
        fig.savefig(figdir / f"box_{col}.png", dpi=110)
        plt.close(fig)
        fig, axes = plt.subplots(1, len(models), figsize=(3 * len(models), 2.6), sharex=True, squeeze=False)
        for ax, m, d in zip(axes[0], models, data):
            ax.hist(d, bins=8)
            if limit is not None:
                ax.axvline(limit, color="red", ls="--", lw=1)
            ax.set_title(m.split(".")[-1][:22], fontsize=7)
        fig.suptitle(label, fontsize=9)
        fig.tight_layout()
        fig.savefig(figdir / f"hist_{col}.png", dpi=110)
        plt.close(fig)


def md_table(df: pd.DataFrame, cols: list[str], digits: int = 3) -> str:
    if df.empty:
        return "_none_\n"
    d = df[cols].copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda x: "" if pd.isna(x) else f"{x:.{digits}g}")
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(v) for v in r) + " |\n" for r in d.itertuples(index=False))


def report(df, split, models, srcs, desc, comp, cap, succ, prob, sig, gt, cfg, out: Path) -> None:
    an = cfg["analysis"]
    recovered = df.groupby("llm_model").from_recovery.mean().reindex(models)
    versions = df.loc[df.workflow_success == 1].groupby("llm_model").used_prompt_sha256.nunique().reindex(models)
    need = math.ceil(math.log(0.05) / math.log(cfg["spec_limits"]["workflow_success_rate"]["lsl"] / 100))
    lines = [f"# Model replacement analysis ({split} papers)\n",
             f"Papers: {df.input_paper_id.nunique()} ({', '.join(sorted(df.input_paper_id.unique()))}); "
             f"attempts: {len(df)}; score sources: {', '.join(srcs) or 'none yet'}. "
             f"Decision basis: {an['decision_basis']}"
             + (f" (target share {an['target_share']})" if an["decision_basis"] == "share" else
                " (95% bootstrap CI of the model mean vs the limit)") + ".\n",
             "## Recommendation (gate)\n", md_table(gt, list(gt.columns)) if not gt.empty else "_no content scores yet_\n",
             "## Workflow success (AR-5)\n", md_table(succ, list(succ.columns)),
             "## Content measures vs limits (AR-4)\n",
             md_table(cap, ["source", "gate", "llm_model", "n_scored", "mean", "mean_ci_boot_lo", "mean_ci_boot_hi",
                            "share_meeting", "share_ci_lo", "share_ci_hi", "ppk", "result"]),
             "## Model comparison (AR-2)\n", md_table(comp, list(comp.columns)),
             "Pairwise tests: `pairwise.csv`.\n",
             "## Descriptive statistics (AR-1)\n",
             md_table(desc, ["measure", "source", "llm_model", "n", "mean", "median", "sd", "p5", "p95", "skewness", "kurtosis"]),
             "## Probability of meeting all requirements (AR-6)\n", md_table(prob, list(prob.columns)),
             "## SPC signals (AR-3, exploratory)\n", md_table(sig, list(sig.columns)),
             "## Limitations\n",
             f"- Each poster is counted from the run it came from; a failed first attempt replaced by a checkpoint "
             f"recovery is not counted against the model (team decision). Share of attempts whose used run is a "
             f"recovery: " + ", ".join(f"{m} {100 * r:.0f}%" for m, r in recovered.items())
             + ". Recovery runs used a newer harness version and retried failed figure plans with feedback, so "
               "content and success differences mix the model with the recovery path.",
             f"- Code versions behind the scored posters (distinct prompt hashes per model): "
             + ", ".join(f"{m} {int(v) if pd.notna(v) else 0}" for m, v in versions.items()) + ".",
             "- Run order was fixed (each paper: claude, gpt, llama, qwen) and not randomized; papers are blocks, "
             "so slow drift over the run is absorbed by the paper effect, but order within a paper is not.",
             "- Content measures use only attempts that produced a poster; read them next to the success rate.",
             f"- Workflow success: at least {need} consecutive successes per model are needed for the one-sided 95% "
             f"lower bound to reach {cfg['spec_limits']['workflow_success_rate']['lsl']}%, so GR-4 cannot pass with "
             f"{df.groupby('llm_model').size().max()} attempts and Accept is not reachable in this study.",
             "- Ppk, Cpk and the control charts are exploratory: bounded, discrete scores and about 12 posters per model.",
             "- Judge scores are validated against humans only on the calibration papers that were also used to "
             "revise the judge prompts (no independent holdout), so judge agreement is optimistic.",
             "- Hallucination is % of the poster's claims; its denominator depends on how finely claims are split, "
             "which differs between judges and humans.\n"]
    out.write_text("\n".join(lines))


# --------------------------------------------------------------------------- main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiment.yaml")
    ap.add_argument("--dataset", default="results/latex/analysis/dataset.csv")
    ap.add_argument("--out-dir", default=None, help="default results/latex/analysis[/<split>]")
    ap.add_argument("--split", default="main", choices=["main", "calibration", "all"])
    args = ap.parse_args(argv)
    import matplotlib
    matplotlib.use("Agg")
    cfg = yaml.safe_load(open(HARNESS / args.config))
    an = {"decision_basis": "mean", "target_share": 0.75, "min_scored": 5, "seed": 5300, **cfg.get("analysis", {})}
    cfg["analysis"] = an
    conf, reps = cfg["spec_limits"]["confidence"], cfg["spec_limits"]["bootstrap_reps"]
    rng = np.random.default_rng(an["seed"])

    df = pd.read_csv(HARNESS / args.dataset)
    if args.split != "all":
        df = df[df.split == args.split]
    if df.empty:
        raise SystemExit(f"No {args.split} rows in {args.dataset}")
    out = HARNESS / (args.out_dir or Path("results/latex/analysis") / ("" if args.split == "main" else args.split))
    figdir = out / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    models, srcs, lims = model_order(cfg, df), sources(df), limits(cfg)

    desc = pd.DataFrame([{"measure": m, "source": "", "llm_model": mdl, **describe(df.loc[df.llm_model == mdl, m])}
                         for m in [*GENERATION, *BINARY] for mdl in models] +
                        [{"measure": m, "source": s, "llm_model": mdl, **describe(df.loc[df.llm_model == mdl, f"{m}__{s}"])}
                         for s in srcs for m in lims for mdl in models if f"{m}__{s}" in df])
    comp, pairs = [], []
    measures = [(m, "", False) for m in GENERATION] + [(m, "", True) for m in BINARY] + \
               [(f"{m}__{s}", s, False) for s in srcs for m in lims if f"{m}__{s}" in df]
    for col, s, binary in measures:
        d = df[["llm_model", "input_paper_id"]].assign(y=df[col].astype(float))
        tests = [cochran(d, models)] if binary else [mixed_model(d, log=col in GENERATION), friedman(d, models)]
        comp += [{"measure": col.split("__")[0], "source": s, **t} for t in tests]
        pairs += [{"measure": col.split("__")[0], "source": s, **p} for p in pairwise(d, models, binary)]
    comp = pd.DataFrame(comp).reindex(columns=["measure", "source", "test", "n", "papers", "statistic", "df", "p", "note"])
    cap = capability(df, models, srcs, lims, an, conf, reps, rng)
    succ = success(df, models, cfg["spec_limits"]["workflow_success_rate"]["lsl"])
    prob = probability(df, models, srcs, lims)
    sig = spc(df, models, srcs, cfg.get("spc", {}).get("sigma", 3), figdir)
    gt = gate(cap, succ, models, srcs) if not cap.empty else pd.DataFrame()
    figures(df, models, srcs, lims, figdir)

    for name, table in [("describe", desc), ("compare", comp), ("pairwise", pd.DataFrame(pairs)),
                        ("capability", cap), ("success", succ), ("probability", prob),
                        ("spc_signals", sig), ("gate", gt)]:
        table.to_csv(out / f"{name}.csv", index=False)
    report(df, args.split, models, srcs, desc, comp, cap, succ, prob, sig, gt, cfg, out / "report.md")
    print(f"{args.split}: {len(df)} attempts, {df.input_paper_id.nunique()} papers, sources {srcs or 'none'} "
          f"-> {out / 'report.md'}")
    if not gt.empty:
        print(gt.to_string(index=False))


if __name__ == "__main__":
    main()
