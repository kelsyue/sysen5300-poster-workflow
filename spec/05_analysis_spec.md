# 05 — Analysis Specification (Python)

Revised 2026-11-01. The analysis is in Python (`harness/analysis/`), not R; methods follow the course SIGMA chapters (Fraser, n.d.-a to -g). Each measure is analyzed and reported on its own (Ma et al., 2024): an update can improve one measure while worsening another.

Why the methods changed from v0.1: the study has 12 main papers (≈ 12 posters per model, fewer after failures), content scores are bounded and discrete (coverage in steps of one checklist item, quality 1–5, hallucination mostly 0%), and failed attempts leave cells empty. Cpk and control charts assume roughly normal, stable data and about 20+ points, so they are kept as exploratory; decisions use intervals that hold for small, discrete samples.

## Inputs and dataset — `analysis/build_dataset.py`

One row per paper × candidate (`results/latex/analysis/dataset.csv`), from `data/latex/runs.csv` (first attempts), `data/latex/recovery_attempts.csv` (checkpoint recoveries), the private blind key, `data/latex/judge_scores.csv` and, when present, `data/latex/human_scores.csv`.

| Field | Definition |
|---|---|
| `workflow_success` | The used run produced a usable poster (the run the poster came from: the first attempt if it succeeded, otherwise its checkpoint recovery; a failed first attempt replaced by a recovery is not counted against the model; team decision 2026-11-01) |
| `from_recovery`, `n_attempts` | The used run is a recovery run; attempts made |
| `latency`, `token_usage`, `input_tokens`, `output_tokens`, `generation_cost` | Summed over every attempt of the poster: a recovery reuses the paper summary made in the earlier attempt, so this is the full cost of getting the poster (recovery rows hold only new usage) |
| `coverage_pct__<source>`, `halluc_pct__<source>`, `quality_score__<source>` | Per score source (each judge; `human`): mean over repeats / evaluators. A failed judge task empties only its own measure |
| `halluc_pct` | 100 × `n_claims_unsupported` / `n_claims_total` (% of claims; SR-2) |
| `split` | `calibration` for `analysis.calibration_papers` (P06, P11, P13), else `main` |

A judge with more than one prompt version on the analysed posters must be pinned (`--judge-prompt JUDGE=SHA256`); the script refuses to mix versions.

Failed attempts have no poster: content measures are `NA` for them, never 0, and every content result is reported with its n.

## AR-1 Descriptive statistics — `describe.csv`, `figures/box_*.png`, `figures/hist_*.png`

Per model × measure (all generation, success and content measures, content per source): n, mean, median, SD, 5th/25th/75th/95th percentiles, skewness, excess kurtosis. Boxplots with jittered points and histograms, spec limits drawn as reference lines.

## AR-2 Model comparison — `compare.csv`, `pairwise.csv`

- **Continuous measures:** linear mixed model `y ~ llm_model + (1 | input_paper_id)` (paper as a random block effect; handles papers where a model failed), likelihood-ratio test of the model term on ML fits. Cost, tokens and latency are fitted on the log scale (they differ by orders of magnitude between models). Convergence and boundary warnings are recorded in `note`.
- **Robustness:** Friedman test on papers where every model has a value (the classic randomized block, nonparametric).
- **Pairwise:** Wilcoxon signed-rank on the papers both models share, Holm-adjusted within each measure; median paired difference as the effect size.
- **Success (binary):** Cochran's Q across models on the same papers, pairwise exact McNemar, Holm-adjusted; on `workflow_success`.

## AR-3 Stability (exploratory) — `spc_signals.csv`, `figures/imr_*.png`

In `run_order`, per model: I-MR charts (coverage, quality per source; latency, cost, tokens), a p-chart of unsupported claims (each poster: unsupported out of its claims) and a p-chart of workflow failures by `batch_id`. 3σ limits; signals are points beyond them. With about 12 points per model the limits are rough: signals are investigated and listed in the report, but they do not select Cpk vs. Ppk and do not block the gate.

## AR-4 Requirements on content measures — `capability.csv`

Per score source × model × requirement:

- **Decision interval (`analysis.decision_basis: mean`, default):** 95% bootstrap percentile interval of the model mean (`spec_limits.bootstrap_reps` resamples of the model's posters, one per paper; seed `analysis.seed`). Also reported: t interval.
- **Share meeting the limit:** k of n posters, exact (Clopper–Pearson) 95% interval. With `decision_basis: share` the decision uses this interval against `analysis.target_share`; note that 12/12 gives a lower bound of only 0.74.
- **Ppk** (overall SD) with a bootstrap interval and **Cpk** (σ from the moving range): exploratory. Undefined (blank) when the scores have no spread, e.g. every poster at 0% hallucination.

| Limit | Pass | Fail | Inconclusive |
|---|---|---|---|
| LSL (coverage ≥ 90, quality ≥ 4.0) | interval lower end ≥ LSL | upper end < LSL | otherwise |
| USL (hallucination < 5%) | upper end < USL | lower end ≥ USL | otherwise |

Fewer than `analysis.min_scored` (5) scored posters → `insufficient data` (treated as inconclusive).

## AR-5 Workflow success — `success.csv`

`workflow_success` successes / attempts per model, with exact one-sided 95% bounds. GR-4: pass if the lower bound ≥ 95%, fail if the upper bound < 95%, else inconclusive. At least 59 consecutive successes are needed for the lower bound to reach 95%, so with 12 attempts GR-4 can be failed but not passed.

## AR-6 Probability of meeting requirements — `probability.csv`

```
P(all) = P(success) × P(cov ≥ 90 | success) × P(halluc < 5 | success) × P(quality ≥ 4 | success)
```

compared with the observed share of attempts meeting all of them (failed attempts count as not meeting). A large gap means the measures are not independent.

## AR-7 Judge analysis — `harness/judge/pilot_agreement.py`

Agreement with humans, test–retest, detection and false-flag rates, Bayes posterior, parallel-system detection, independence and self-preference checks, human–human agreement (`08_llm_judge.md` §5). As run, measured on the calibration papers only (see `04_experiment_protocol.md`, As run).

## AR-8 Effort

Not built: no `effort_log` was kept in this study.

## Reporting rules (`report.md`)

- State n per model and per measure; failed attempts are excluded from content measures and that exclusion is stated next to the success rates.
- Cost, latency and token usage: descriptive statistics and comparisons only (no spec limit).
- Same model order and colours across figures.
- Limitations listed in every report: used-run rule and recovery path confounded with model, code versions behind the posters, fixed run order, survivor-only content measures, GR-4 unreachable at this n, exploratory Ppk/Cpk/SPC, judge validated only on the calibration papers, claim-splitting dependence of the hallucination %.

Usage (from `harness/`):

```bash
python analysis/build_dataset.py            # -> results/latex/analysis/dataset.csv
python analysis/analyze.py                  # main comparison -> results/latex/analysis/report.md
python analysis/analyze.py --split calibration
python analysis/tests/test_analysis.py      # offline test with known answers
```
