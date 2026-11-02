"""Judge validation on the human-scored pilot set.

Compares each LLM judge with the paper authors' scores and decides whether the
judge can be used to screen posters in the full experiment.

Inputs (under data/latex/, or data/latex/dry_run/ with --dry-run)
  human_scores.csv        one row per (poster_code, evaluator_id); schema 03 §2.3
  judge_scores.csv        output of judge.py; only each judge's latest prompt version is used
  judge_manifest.csv      for poster_word_count
  judge_raw/              judge reasons and quotes, for the disagreement list
Outputs (reports/, or reports/dry_run/)
  judge_pilot.md               readable report with verdict per judge
  judge_pilot.csv              all metrics in long format
  judge_disagreements.csv      every item / score where a judge and the humans disagree,
                               with the judge's reason and quote: the input for prompt revision

Usage (from harness/)
  python judge/pilot_agreement.py
  python judge/pilot_agreement.py --only-codes P-7K3Q,...   # score a held-out subset only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ITEMS = [
    "chk_problem", "chk_method", "chk_data", "chk_setup", "chk_primary_result",
    "chk_secondary_result", "chk_baseline", "chk_conclusion", "chk_limitation",
]

DEFAULT_THRESHOLDS = {           # proposed; confirm before the pilot (OI-5)
    "item_kappa_min": 0.60,      # Landis & Koch "substantial"
    "coverage_icc_min": 0.75,    # Koo & Li "good"
    "halluc_icc_min": 0.60,
    "quality_wkappa_min": 0.60,
    "quality_within1_min": 0.90,
    "detection_min": 0.80,       # share of truly failing posters the judge flags
    "retest_icc_min": 0.80,
    "evidence_found_min": 0.90,
}


# ----------------------------------------------------------------- statistics

def icc_2_1(a, b) -> float:
    """ICC(2,1): two-way random effects, absolute agreement, single rater."""
    y = np.column_stack([a, b]).astype(float)
    y = y[~np.isnan(y).any(axis=1)]
    n, k = y.shape
    if n < 3:
        return np.nan
    g = y.mean()
    msr = k * ((y.mean(1) - g) ** 2).sum() / (n - 1)
    msc = n * ((y.mean(0) - g) ** 2).sum() / (k - 1)
    sse = ((y - y.mean(1, keepdims=True) - y.mean(0, keepdims=True) + g) ** 2).sum()
    mse = sse / ((n - 1) * (k - 1))
    den = msr + (k - 1) * mse + k * (msc - mse) / n
    return float((msr - mse) / den) if den > 0 else np.nan


def kappa(a, b, weights=None, categories=None) -> float:
    """Cohen's kappa; weights='quadratic' for ordinal scales."""
    a, b = np.asarray(a), np.asarray(b)
    m = ~(pd.isna(a) | pd.isna(b))
    a, b = a[m], b[m]
    if len(a) < 3:
        return np.nan
    cats = list(categories) if categories is not None else sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    q = len(cats)
    obs = np.zeros((q, q))
    for x, y in zip(a, b):
        obs[idx[x], idx[y]] += 1
    obs /= obs.sum()
    exp = np.outer(obs.sum(1), obs.sum(0))
    if weights == "quadratic":
        w = np.array([[(i - j) ** 2 for j in range(q)] for i in range(q)]) / max((q - 1) ** 2, 1)
    else:
        w = 1 - np.eye(q)
    den = (w * exp).sum()
    return float(1 - (w * obs).sum() / den) if den > 0 else np.nan


def spear(a, b) -> float:
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    return float(spearmanr(d.a, d.b).statistic) if len(d) >= 3 and d.a.nunique() > 1 and d.b.nunique() > 1 else np.nan


def mae(a, b) -> float:
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    return float((d.a - d.b).abs().mean()) if len(d) else np.nan


# ----------------------------------------------------------------- data prep

def halluc_pct(df: pd.DataFrame) -> pd.Series:
    """% of the poster's claims unsupported (the unit humans score); empty without claims."""
    total = pd.to_numeric(df["n_claims_total"], errors="coerce")
    return 100 * pd.to_numeric(df["n_claims_unsupported"], errors="coerce") / total.where(total > 0)


def human_table(h: pd.DataFrame, words: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    h = h.copy()
    h[ITEMS] = h[ITEMS].replace({"NA": np.nan, "": np.nan}).apply(pd.to_numeric, errors="coerce")
    h["poster_word_count"] = h["poster_code"].map(words)
    h["coverage_pct"] = 100 * h[ITEMS].sum(1, min_count=1) / h[ITEMS].notna().sum(1)
    h["halluc_pct"] = halluc_pct(h)
    agg = h.groupby("poster_code").agg(
        coverage_pct=("coverage_pct", "mean"),
        halluc_pct=("halluc_pct", "mean"),
        n_claims_total=("n_claims_total", "mean"),
        quality_score=("quality_score", "mean"),
        n_evaluators=("evaluator_id", "nunique"),
    )
    # item consensus: mean of evaluators; 0.5 (a split) is treated as no consensus
    items = h.groupby("poster_code")[ITEMS].mean()
    items = items.where(items != 0.5).round()
    return agg.join(items), h


def fails(df: pd.DataFrame, lim: dict) -> pd.DataFrame:
    """True where a poster misses a spec limit (the thing the judge must detect)."""
    return pd.DataFrame({
        "coverage": df["coverage_pct"] < lim["coverage_lsl"],
        "hallucination": df["halluc_pct"] >= lim["halluc_usl"],
        "quality": df["quality_score"] < lim["quality_lsl"],
    }, index=df.index).where(df[["coverage_pct", "halluc_pct", "quality_score"]].notna().values)


def detection(truth: pd.Series, flag: pd.Series) -> dict:
    d = pd.DataFrame({"t": truth, "f": flag}).dropna().astype(bool)
    pos, neg = d[d.t], d[~d.t]
    det = pos.f.mean() if len(pos) else np.nan
    ff = neg.f.mean() if len(neg) else np.nan
    prev = d.t.mean() if len(d) else np.nan
    ppv_bayes = det * prev / (det * prev + ff * (1 - prev)) if len(pos) and len(neg) and (det * prev + ff * (1 - prev)) > 0 else np.nan
    ppv_obs = d[d.f].t.mean() if d.f.any() else np.nan
    return {"n": len(d), "n_true_fail": int(d.t.sum()), "detection": det, "false_flag": ff,
            "prevalence": prev, "ppv_bayes": ppv_bayes, "ppv_observed": ppv_obs}


# ----------------------------------------------------------------- main

def latest_judge_rows(jud: pd.DataFrame) -> pd.DataFrame:
    """Each judge's newest prompt version only, and the last row per (poster, repeat):
    judge.py appends a fresh row when it retries a failed poster."""
    if "judge_prompt_sha256" in jud:
        newest = jud.sort_values("judged_at").groupby("judge_model")["judge_prompt_sha256"].last()
        jud = jud[jud.judge_prompt_sha256 == jud.judge_model.map(newest)]
    return jud.drop_duplicates(["poster_code", "judge_model", "judge_repeat"], keep="last")


def disagreements(model: str, hum: pd.DataFrame, r1: pd.DataFrame, h_rows: pd.DataFrame,
                  raw_dir: Path, lim: dict) -> list[dict]:
    """One row per item or score where judge (repeat 1) and the human consensus differ."""
    tag = model.replace("/", "_")
    out = []
    for code in hum.index:
        if code not in r1.index or pd.isna(r1.loc[code, "parse_ok"]):
            continue
        raw = {}
        for task in ("coverage", "claims", "quality"):
            f = raw_dir / code / f"{tag}__r1__{task}.json"
            raw[task] = (json.loads(f.read_text()).get("parsed") or {}) if f.exists() else {}
        items = raw["coverage"].get("items") or {}
        for i in ITEMS:
            h, j = hum.loc[code, i], r1.loc[code, i]
            if pd.notna(h) and pd.notna(j) and h != j:
                e = items.get(i) or {}
                out.append({"judge": model, "poster_code": code, "measure": i,
                            "human": h, "judge_value": j, "judge_label": e.get("label", ""),
                            "judge_reason": e.get("reason", ""), "judge_evidence": e.get("poster_evidence", "")})
        hq, jq = hum.loc[code, "quality_score"], r1.loc[code, "quality_score"]
        if pd.notna(hq) and pd.notna(jq) and (abs(hq - jq) >= 1 or (hq < lim["quality_lsl"]) != (jq < lim["quality_lsl"])):
            q = raw["quality"]
            out.append({"judge": model, "poster_code": code, "measure": "quality_score",
                        "human": round(hq, 2), "judge_value": jq, "judge_label": "",
                        "judge_reason": " | ".join(f"{k}={(q.get(k) or {}).get('score')}: {(q.get(k) or {}).get('reason', '')}"
                                                   for k in ("holistic", "layout", "readability", "fidelity")),
                        "judge_evidence": ""})
        hh, jh = hum.loc[code, "halluc_pct"], r1.loc[code, "halluc_pct"]
        if pd.notna(hh) and pd.notna(jh) and (hh >= lim["halluc_usl"]) != (jh >= lim["halluc_usl"]):
            human_claims = "; ".join(str(x) for x in h_rows.loc[h_rows.poster_code == code, "flagged_claims"].dropna()) \
                if "flagged_claims" in h_rows else ""
            out.append({"judge": model, "poster_code": code, "measure": "halluc_pct",
                        "human": round(hh, 2), "judge_value": jh, "judge_label": "",
                        "judge_reason": r1.loc[code, "flagged_claims"] if "flagged_claims" in r1 else "",
                        "judge_evidence": human_claims})
    return out


def main(argv=None):
    import yaml
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiment.yaml")
    ap.add_argument("--dry-run", action="store_true", help="use data/latex/dry_run/ and reports/dry_run/")
    ap.add_argument("--human")
    ap.add_argument("--judge")
    ap.add_argument("--manifest")
    ap.add_argument("--raw-dir")
    ap.add_argument("--blind-key")
    ap.add_argument("--out-dir")
    ap.add_argument("--only-codes", default="", help="comma list: evaluate these posters only (e.g. a holdout set)")
    args = ap.parse_args(argv)

    sub = Path("latex") / ("dry_run" if args.dry_run else "")
    data = HARNESS / "data" / sub
    pick = lambda given, default: (HARNESS / given if not Path(given).is_absolute() else Path(given)) if given else default
    args.human = pick(args.human, data / "human_scores.csv")
    args.judge = pick(args.judge, data / "judge_scores.csv")
    args.manifest = pick(args.manifest, data / "judge_manifest.csv")
    raw_dir = pick(args.raw_dir, data / "judge_raw")
    key_path = pick(args.blind_key, HARNESS / "data" / "private" / sub / "blind_key.csv")
    args.out_dir = pick(args.out_dir, HARNESS / "reports" / ("dry_run" if args.dry_run else ""))
    config = HARNESS / args.config if not Path(args.config).is_absolute() else Path(args.config)

    cfg = yaml.safe_load(open(config))
    sl = cfg["spec_limits"]
    lim = {"coverage_lsl": sl["key_information_coverage"]["lsl"],
           "halluc_usl": sl["hallucination_rate"]["usl"],
           "quality_lsl": sl["poster_quality_score"]["lsl"]}
    th = {**DEFAULT_THRESHOLDS, **cfg.get("judge_validation", {})}

    words = pd.read_csv(args.manifest).set_index("poster_code")["poster_word_count"]
    h_all = pd.read_csv(args.human)
    if args.only_codes:
        keep = {c.strip() for c in args.only_codes.split(",")}
        h_all = h_all[h_all.poster_code.isin(keep)]
    hum, h_rows = human_table(h_all, words)
    jud = latest_judge_rows(pd.read_csv(args.judge))
    jud[ITEMS] = jud[ITEMS].replace({"NA": np.nan}).apply(pd.to_numeric, errors="coerce")
    jud["halluc_pct"] = halluc_pct(jud)
    pilot = hum.index
    jud = jud[jud.poster_code.isin(pilot)]

    rows, verdicts, flags, disagree = [], {}, {}, []
    truth = fails(hum, lim)

    def rec(judge, metric, value, threshold=None, passed=None):
        rows.append({"judge": judge, "metric": metric, "value": value,
                     "threshold": threshold, "pass": passed})

    for model, g in jud.groupby("judge_model"):
        r1 = g[g.judge_repeat == 1].set_index("poster_code").reindex(pilot)
        checks = []

        # coverage
        ks = [kappa(hum[i], r1[i], categories=[0, 1]) for i in ITEMS]
        for i, k in zip(ITEMS, ks):
            rec(model, f"kappa_{i}", k)
            # Kappa is unstable when nearly every poster gets the item right; raw agreement shows that case.
            both = pd.DataFrame({"h": hum[i], "j": r1[i]}).dropna()
            rec(model, f"agree_{i}", float((both.h == both.j).mean()) if len(both) else np.nan)
        mk = np.nanmean(ks) if not all(np.isnan(ks)) else np.nan
        checks.append(("mean item kappa", mk, th["item_kappa_min"]))
        icc_c = icc_2_1(hum.coverage_pct, r1.coverage_pct)
        checks.append(("coverage ICC", icc_c, th["coverage_icc_min"]))
        rec(model, "coverage_mae_pts", mae(hum.coverage_pct, r1.coverage_pct))
        rec(model, "coverage_spearman", spear(hum.coverage_pct, r1.coverage_pct))

        # hallucination
        icc_h = icc_2_1(hum.halluc_pct, r1.halluc_pct)
        checks.append(("hallucination ICC", icc_h, th["halluc_icc_min"]))
        rec(model, "halluc_mae_pct_pts", mae(hum.halluc_pct, r1.halluc_pct))
        rec(model, "halluc_spearman", spear(hum.halluc_pct, r1.halluc_pct))
        # the % depends on how finely claims are split: judge vs human claims per poster
        rec(model, "claims_per_poster_judge_over_human",
            float(r1.n_claims_total.mean() / hum.n_claims_total.mean()) if hum.n_claims_total.mean() else np.nan)

        # quality
        hq = hum.quality_score.round().clip(1, 5)
        wk = kappa(hq, r1.quality_score, weights="quadratic", categories=[1, 2, 3, 4, 5])
        within = float(((hum.quality_score - r1.quality_score).abs() <= 1).mean())
        checks.append(("quality weighted kappa", wk, th["quality_wkappa_min"]))
        checks.append(("quality within ±1", within, th["quality_within1_min"]))
        rec(model, "quality_mae", mae(hum.quality_score, r1.quality_score))

        # pass/fail detection against the spec limits
        jf = fails(r1, lim)
        flags[model] = jf
        for m in ["coverage", "hallucination", "quality"]:
            d = detection(truth[m], jf[m])
            for k, v in d.items():
                rec(model, f"{m}_{k}", v)
            checks.append((f"{m} detection", d["detection"], th["detection_min"]))

        # test-retest
        r2 = g[g.judge_repeat == 2].set_index("poster_code").reindex(pilot)
        if r2.coverage_pct.notna().any():
            for col in ["coverage_pct", "halluc_pct", "quality_score"]:
                checks.append((f"retest ICC {col}", icc_2_1(r1[col], r2[col]), th["retest_icc_min"]))

        # evidence honesty and parsing
        checks.append(("evidence found rate", r1.evidence_found_rate.mean(), th["evidence_found_min"]))
        rec(model, "parse_ok_rate", r1.parse_ok.mean())

        disagree += disagreements(model, hum, r1, h_rows, raw_dir, lim)

        # bias by candidate model (needs the private key; skipped if absent)
        if key_path.exists():
            key = pd.read_csv(key_path).set_index("poster_code")["llm_model"]
            diff = (r1.quality_score - hum.quality_score).groupby(key.reindex(pilot)).mean()
            for cand, v in diff.items():
                rec(model, f"quality_bias_vs_human[{cand}]", v)

        for name, val, t in checks:
            rec(model, name, val, t, bool(val >= t) if not pd.isna(val) else None)
        verdicts[model] = all(not pd.isna(v) and v >= t for _, v, t in checks)

    # parallel-system rule for the pair of judges
    models = list(flags)
    if len(models) == 2:
        a, b = models
        for m in ["coverage", "hallucination", "quality"]:
            d1 = detection(truth[m], flags[a][m])["detection"]
            d2 = detection(truth[m], flags[b][m])["detection"]
            either = (flags[a][m].astype("boolean") | flags[b][m].astype("boolean"))
            obs = detection(truth[m], either)["detection"]
            rec("both", f"{m}_parallel_predicted", 1 - (1 - d1) * (1 - d2))
            rec("both", f"{m}_parallel_observed", obs)
            # independence check: do the judges miss the same posters?
            t = truth[m].fillna(False).astype(bool)
            miss_a = ~flags[a][m].fillna(False).astype(bool)[t]
            miss_b = ~flags[b][m].fillna(False).astype(bool)[t]
            rec("both", f"{m}_miss_both_observed", float((miss_a & miss_b).mean()) if t.any() else np.nan)
            rec("both", f"{m}_miss_both_if_independent", float(miss_a.mean() * miss_b.mean()) if t.any() else np.nan)

    # human-human agreement (reference ceiling)
    two = h_rows.groupby("poster_code").filter(lambda x: x.evaluator_id.nunique() >= 2)
    if len(two):
        firsts = two.sort_values("evaluator_id").groupby("poster_code").nth([0, 1])
        p = firsts.assign(r=firsts.groupby("poster_code").cumcount()).pivot(index="poster_code", columns="r")
        for col in ["coverage_pct", "halluc_pct", "quality_score"]:
            rec("human-human", f"icc_{col}", icc_2_1(p[(col, 0)], p[(col, 1)]))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame(rows)
    res.to_csv(out / "judge_pilot.csv", index=False)
    pd.DataFrame(disagree, columns=["judge", "poster_code", "measure", "human", "judge_value", "judge_label",
                                    "judge_reason", "judge_evidence"]).to_csv(out / "judge_disagreements.csv", index=False)

    lines = ["# Judge pilot validation", "",
             f"Pilot posters: {len(pilot)}  |  with ≥2 human evaluators: {int((hum.n_evaluators >= 2).sum())}", "",
             f"Truly failing posters (human scores) — coverage: {int(truth.coverage.sum())}, "
             f"hallucination: {int(truth.hallucination.sum())}, quality: {int(truth.quality.sum())}", ""]
    for model in verdicts:
        sub = res[(res.judge == model) & res.threshold.notna()]
        ok = verdicts[model]
        sha = jud.loc[jud.judge_model == model, "judge_prompt_sha256"].iloc[0] if "judge_prompt_sha256" in jud else "n/a"
        lines += [f"## {model} — {'USE' if ok else 'DO NOT USE (or revise prompts and re-pilot)'}", "",
                  f"Judge prompts sha256: `{sha}`", "",
                  "| Check | Value | Threshold | Pass |", "|---|---|---|---|"]
        for _, r in sub.iterrows():
            v = "n/a" if pd.isna(r.value) else f"{r.value:.3f}"
            lines.append(f"| {r.metric} | {v} | {r.threshold:.2f} | {'✓' if r['pass'] is True else '✗' if r['pass'] is False else '—'} |")
        lines.append("")
    pr = res[res.judge.isin(["both", "human-human"])]
    if len(pr):
        lines += ["## Pair and human reference", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| {r.judge}: {r.metric} | {'n/a' if pd.isna(r.value) else f'{r.value:.3f}'} |" for _, r in pr.iterrows()]
    lines += ["", f"Disagreements for prompt revision: `{out / 'judge_disagreements.csv'}` ({len(disagree)} rows)"]
    (out / "judge_pilot.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
