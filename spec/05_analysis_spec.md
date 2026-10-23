# 05 — Analysis Specification (R)

All analysis in R with `tidyverse`/`ggplot2`, following the course SIGMA chapters (Fraser, n.d.-a to -g). Each measure is analyzed and reported on its own (Ma et al., 2024): an update can improve one measure while worsening another.

Input: the analysis dataset (one row per attempt; `03_data_schema.md` §4).

## AR-1 Descriptive statistics — `01_describe.R`

For each `llm_model` × measure (all 7 outcomes):

- n (attempts; posters scored), mean, median, SD, 5th/25th/75th/95th percentiles, skewness, kurtosis.
- Plots: boxplots with jittered points, and histograms, models side by side, with spec limits drawn as reference lines.

Output: `reports/describe_table.csv`, `reports/fig_box_<measure>.png`, `reports/fig_hist_<measure>.png`.

## AR-2 Model comparison — `01_describe.R`

- Randomized block design: `measure ~ llm_model + input_paper_id`, two-way ANOVA (no interaction; one observation per cell).
- Follow up with paired comparisons between models (Tukey HSD or pairwise paired tests with multiplicity correction).
- Check residuals (normality, equal variance). If badly violated, also report Friedman test as a robustness check.
- `workflow_success` is binary; compare success proportions (e.g., Cochran's Q across the 4 models on the same papers).
- Report effect sizes and 95% CIs, not just p-values.

## AR-3 Stability (SPC) — `02_spc.R`

Charts per model, in `run_order`:

| Measure | Chart | Notes |
|---|---|---|
| `key_information_coverage` | Individuals + moving range (I-MR) | |
| `poster_quality_score` | I-MR | |
| Unsupported claims | u-chart | Defects = unsupported claims; area of opportunity = poster words / 1,000 |
| Workflow failures | p-chart | Batches of 5 attempts (`batch_id`), 6 batches per model |

- 3σ control limits.
- Signals: point outside limits, runs, trends. A signal triggers investigation, not automatic failure.
- Output a stability flag per model × measure (`stable` / `signals`), which selects Cpk vs. Ppk in AR-4.

## AR-4 Process capability — `03_capability.R`

One-sided indices against stakeholder limits:

```
Coverage (LSL = 90):       Cpk = (mean − 90)  / (3σ)
Quality  (LSL = 4.0):      Cpk = (mean − 4.0) / (3σ)
Hallucination (USL = 2.0 per 1,000 words, proposed):   Cpk = (2.0 − mean) / (3σ)
```

- σ = within-subgroup estimate (from moving range, MR̄/1.128) for **Cpk** when AR-3 shows stability; overall sample SD for **Ppk** when it does not.
- 95% CI two ways:
  1. Normal-approximation formula for Cpk.
  2. Bootstrap: resample attempts (or papers, to respect blocking — **[TBD — OI-10]**) ≥ 2,000 times; percentile interval.
- Report both intervals; the decision uses the bootstrap interval when the two disagree in classification (coverage and quality are bounded and discrete, so the normal formula is approximate).

Decision per measure (feeds `06_acceptance_gate.md`):

| CI | Result |
|---|---|
| Entirely > 1 | Pass |
| Entirely < 1 | Fail |
| Contains 1 | Inconclusive |

## AR-5 Workflow success — `03_capability.R`

- Success rate = successes / attempts per model.
- One-sided 95% lower bound from the exact binomial (Clopper–Pearson).
- Pass if lower bound ≥ 95%; fail if the upper one-sided 95% bound < 95%; otherwise inconclusive.
- Note: with 30 attempts, 30/30 gives a lower bound of about 90.5%, so a model **cannot** pass SR-4 on 30 attempts alone. See OI-4.

## AR-6 Probability of meeting requirements — `04_probability.R`

- From each measure's empirical CDF per model, estimate P(poster meets its limit), e.g. P(coverage ≥ 90).
- Series-system estimate of meeting all requirements:

```
P(all) = P(success) × P(cov ≥ 90 | success) × P(halluc < 5 | success) × P(quality ≥ 4 | success)
```

- Compare with the share of attempts that directly meet all four. A large gap means the measures are not independent; report it.

## AR-7 Judge analysis — `05_judges.R`

Pilot outputs from `04_experiment_protocol.md` §5: agreement with humans, test–retest consistency, detection and false-flag rates, Bayes posterior, parallel-system detection, independence check, self-preference check. Also report agreement between human evaluators on the same poster.

## AR-8 Effort — `06_gate.R`

Total person-hours per candidate from `effort_log` + evaluator minutes; compare with the 4-hour baseline and the 1-hour target.

## Reporting rules

- Always state n per model and per measure; failed attempts are excluded from content measures and that exclusion is stated.
- Cost, latency, and token usage are reported with descriptive stats and comparisons only (no spec limit).
- All figures use the same model color mapping and order across the report.
