# Judge pilot validation

Pilot posters: 8  |  with ≥2 human evaluators: 0

Truly failing posters (human scores) — coverage: 3, hallucination: 0, quality: 6

## gemini-3.5-flash — DO NOT USE (or revise prompts and re-pilot)

Judge prompts sha256: `d68c41ba9fcb81e0b6ca71c927f15884f0e00bb0cd2d9c521934502fa8ab3e38`

| Check | Value | Threshold | Pass |
|---|---|---|---|
| mean item kappa | 0.601 | 0.60 | ✓ |
| coverage ICC | 0.901 | 0.75 | ✓ |
| hallucination ICC | 0.103 | 0.60 | ✗ |
| quality weighted kappa | 0.556 | 0.60 | ✗ |
| quality within ±1 | 0.875 | 0.90 | ✗ |
| coverage detection | 1.000 | 0.80 | ✓ |
| hallucination detection | n/a | 0.80 | — |
| quality detection | 0.500 | 0.80 | ✗ |
| evidence found rate | 0.987 | 0.90 | ✓ |

## openai.gpt-4o — DO NOT USE (or revise prompts and re-pilot)

Judge prompts sha256: `d68c41ba9fcb81e0b6ca71c927f15884f0e00bb0cd2d9c521934502fa8ab3e38`

| Check | Value | Threshold | Pass |
|---|---|---|---|
| mean item kappa | 0.744 | 0.60 | ✓ |
| coverage ICC | 0.973 | 0.75 | ✓ |
| hallucination ICC | 0.000 | 0.60 | ✗ |
| quality weighted kappa | 0.684 | 0.60 | ✓ |
| quality within ±1 | 1.000 | 0.90 | ✓ |
| coverage detection | 1.000 | 0.80 | ✓ |
| hallucination detection | n/a | 0.80 | — |
| quality detection | 1.000 | 0.80 | ✓ |
| evidence found rate | 0.976 | 0.90 | ✓ |

## Pair and human reference

| Metric | Value |
|---|---|
| both: coverage_parallel_predicted | 1.000 |
| both: coverage_parallel_observed | 1.000 |
| both: coverage_miss_both_observed | 0.000 |
| both: coverage_miss_both_if_independent | 0.000 |
| both: hallucination_parallel_predicted | n/a |
| both: hallucination_parallel_observed | n/a |
| both: hallucination_miss_both_observed | n/a |
| both: hallucination_miss_both_if_independent | n/a |
| both: quality_parallel_predicted | 1.000 |
| both: quality_parallel_observed | 1.000 |
| both: quality_miss_both_observed | 0.000 |
| both: quality_miss_both_if_independent | 0.000 |

Disagreements for prompt revision: `/Users/allyanna/Desktop/Coding/sixsigma/sysen5300-poster-workflow/harness/reports/latex_v3_calibration_P01_P03_rev2/judge_disagreements.csv` (18 rows)
