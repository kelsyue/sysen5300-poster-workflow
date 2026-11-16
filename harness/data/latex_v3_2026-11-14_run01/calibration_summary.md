# P01–P03 calibration results

Completed: 8 posters × 2 judges × 2 repeats = 32 complete evaluations.

Rubric SHA-256: `4ec65050cfdc718218dbc587f672291e733fd03b1254c20d77b61b0933e16162`.

| Judge | Evaluations | Mean coverage % | Mean quality / 5 | Mean claim hallucination % | Evidence found |
|---|---:|---:|---:|---:|---:|
| gemini-3.5-flash | 16 | 83.33 | 4.12 | 1.93 | 0.991 |
| openai.gpt-4o | 16 | 84.72 | 3.62 | 0.00 | 0.988 |

Means give each poster/repeat equal weight. Claim hallucination is 100 × unsupported claims / audited claims; it is not the runner's word-normalized halluc_per1k.

## Repeatability

| Judge | Metric | Poster pairs | ICC(2,1) | Mean absolute repeat difference |
|---|---|---:|---:|---:|
| gemini-3.5-flash | coverage_pct | 8 | 1.000 | 0.000 |
| gemini-3.5-flash | quality_score | 8 | 1.000 | 0.000 |
| gemini-3.5-flash | claim_hallucination_pct | 8 | 0.971 | 0.281 |
| openai.gpt-4o | coverage_pct | 8 | 0.972 | 2.777 |
| openai.gpt-4o | quality_score | 8 | 1.000 | 0.000 |
| openai.gpt-4o | claim_hallucination_pct | 8 | undefined | 0.000 |

These are descriptive results from eight posters across three papers. No completed human ratings exist for this batch, so human agreement and judge acceptance cannot be determined. No prompts were revised. The main analysis calibration split remains unchanged.

All eight posters still lack recorded visual checks. Four failed generation attempts were excluded because no poster exists.

The combined judge_scores.csv retains the latest complete row per poster/judge/repeat. Earlier attempts remain in judge_scores_gemini_attempts.csv and judge_scores_gpt4o.csv, with raw task responses and replaced .prev.json files under judge_raw/.
