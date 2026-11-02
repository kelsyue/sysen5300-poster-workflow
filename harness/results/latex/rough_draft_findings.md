# Rough-draft findings: LLM replacement in Paper2Poster (2026-11-01)

Team only: names the models. Generated from `analysis/build_dataset.py` + `analysis/analyze.py`
(full tables in `results/latex/analysis/`, regenerate any time). Main comparison = 12 papers
(P01–P05, P07–P10, P12, P14, P15) × 4 candidates = 48 attempts; P06, P11, P13 were used to
calibrate the judge. Each poster counts from its used run (first attempt, or its checkpoint
recovery if the first failed); latency, tokens and cost are summed over all attempts.

## 1. What data exists

| Item | Status |
|---|---|
| Generation (latency, cost, tokens, workflow success) | Complete: 48/48 attempts, 35 posters |
| Judge scores, main papers | **Partial.** Gemini 3.5 Flash (prompt revision 2): coverage 22/35 posters, quality 21/35, hallucination 8/35. GPT-4o: 0/35 (all calls refused, gateway budget exhausted) |
| Judge vs human, calibration papers | GPT-4o revision 2 on 12 posters vs the team's hand scores (aggregates). Gemini revision 2 never compared with humans |
| Human scores file (`gpt4o_calibration_2/human_scores.csv`) | Not yet pushed; the numbers below use the aggregates from the team's manual scoring sheet |

Why the main judge scores are incomplete:

| Model | Posters | Gemini quality scored | Gemini claims: ok / truncated / budget |
|---|---|---|---|
| claude-opus-5 | 5 | 3 | 0 / 3 / 2 |
| gpt-5.6-sol | 11 | 4 | 0 / 5 / 6 |
| llama-4-maverick | 12 | 10 | 8 / 2 / 2 |
| qwen3-vl-235b | 7 | 4 | 0 / 4 / 3 |

- **Budget:** the gateway key ran out partway through; every later call failed (13 Gemini posters, all GPT-4o).
- **Truncation:** Gemini's claim extraction/verification hit the 8,192-token output cap (its thinking tokens count toward it) on long posters. Median length: truncated 1,088 words, completed 410 words. Missing hallucination scores are therefore **not random**: only Llama's short posters have them.

## 2. Results

### Workflow success (complete data)

| Model | Success | Rate | Exact one-sided 95% bounds | GR-4 (≥ 95%) |
|---|---|---|---|---|
| claude-opus-5 | 5/12 | 41.7% | 18.1%–68.5% | **Fail** |
| gpt-5.6-sol | 11/12 | 91.7% | 66.1%–99.6% | Inconclusive |
| llama-4-maverick | 12/12 | 100% | 77.9%–100% | Inconclusive |
| qwen3-vl-235b | 7/12 | 58.3% | 31.5%–81.9% | **Fail** |

Models differ (Cochran's Q = 11.23, df 3, p = 0.011). With 12 attempts no model can pass GR-4 (59 straight successes are needed). Every Claude and Qwen poster came from a recovery run (vs 6 GPT, 1 Llama). The 13 failures are 7 Claude and 1 GPT overflows (text too long for the poster) and 5 Qwen invalid figure plans.

### Latency, cost, tokens (complete data; reported, not gated)

| Model | Latency mean (s) | Cost mean (USD) | Tokens mean |
|---|---|---|---|
| claude-opus-5 | 149.0 | 0.359 | 39,816 |
| gpt-5.6-sol | 88.9 | 0.146 | 20,798 |
| llama-4-maverick | 40.9 | 0.004 | 14,997 |
| qwen3-vl-235b | 72.1 | 0.013 | 18,941 |

All three differ by model (Friedman p < 0.001; mixed model on log scale p < 0.001). Every pairwise difference is significant after Holm correction except tokens for GPT vs Qwen. Claude is about 90× Llama's cost and 3.6× its latency.

### Content measures (Gemini, revision 2; partial, see §1)

| Model | Coverage mean (n) | Quality mean (n) | Hallucination mean (n) |
|---|---|---|---|
| claude-opus-5 | 92.6% (3) | 2.67 (3) | — (0) |
| gpt-5.6-sol | 93.3% (5) | 3.25 (4) | — (0) |
| llama-4-maverick | 67.4% (10) | 2.40 (10) | 0.57% (8) |
| qwen3-vl-235b | 97.2% (4) | 2.75 (4) | — (0) |

- Coverage differs by model (mixed model LR = 23.9, p < 0.001, n = 22) and quality as well (LR = 8.58, p = 0.036, n = 21). Both fits warned about convergence, and Friedman could not run because no paper has all four models scored.
- Gate (bootstrap 95% CI of the mean vs the limit), where n ≥ 5:
  - Llama **fails** coverage (59.6–75.6 < 90) and quality (2.10–2.70 < 4.0), and passes hallucination (0–1.7 < 5).
  - GPT is inconclusive on coverage (88.9–97.8).
  - The other cells have too few scores.
- No model's mean quality reaches 4.0, and no control-chart signals.
- Overall gate:
  - **Reject:** Claude (GR-4), Qwen (GR-4), Llama (GR-1, GR-3).
  - **Inconclusive:** GPT (no "Accept" is reachable at n = 12).

### Judge calibration (GPT-4o, calibration papers, vs team hand scores)

| Measure | Original prompt | Revision 2 |
|---|---|---|
| Quality mean signed error (judge − human) | +1.58 | +0.17 |
| Quality MAE | 1.58 | 0.50 |
| Quality exact / within ±1 | 2/12 / 7/12 | 6/12 / 12/12 |
| Quality Spearman ρ | — | 0.65 (p = 0.023) |
| Coverage MAE (pts) | 6.06 | 5.05 (ρ = 0.73) |
| Llama posters (human 1, 2, 2) | 5, 5, 5 | 2, 2, 3 |

The revision removed GPT-4o's inflation and its preference for sparse posters. Hallucination: humans flagged 2 posters (0.63%, 1.57%) and GPT-4o flagged a different one (5.26% on P-Z8KP); per-poster agreement on rare errors is poor.

## 3. Limitations

1. **Incomplete, non-random judge coverage.** 13/35 main posters have no Gemini score (budget) and 27/35 no hallucination score. Truncation hit long posters, so hallucination results describe only Llama. Content results for Claude, GPT and Qwen rest on 3–5 posters each.
2. **The judge that scored the main papers was not validated with the prompt it used.** Gemini scored the main posters with revision 2, but only GPT-4o revision 2 was compared with humans. GPT-4o, the validated judge, has no main scores. The planned two-judge design (mean of judges, disagreement routing) could not be applied.
3. **Agreement is optimistic.** The 12 calibration posters (3 papers) were also used to revise the prompts; there is no independent holdout. Human scores are from one scorer per poster, were not blinded (the scoring sheet names the model), and coverage was recorded as totals, not per item.
4. **Recovery confounds model.** Recovered posters ran on a newer harness version and retried failed figure plans with feedback; all Claude and Qwen posters are recoveries. Failed first attempts are not counted against the model (team decision).
5. **Survivor bias.** Content measures exist only for posters that were produced (Claude 5/12, Qwen 7/12).
6. **Small n.** 12 papers instead of 30. GR-4 cannot pass. Cpk/Ppk and control charts are exploratory. Mixed models hit boundary/convergence warnings.
7. **Fixed run order** (claude → gpt → llama → qwen within each paper). Paper blocks absorb drift over the run, but not order within a paper.
8. **Hallucination unit.** % of claims depends on how finely claims are split. Judges and humans split differently, and most posters have 0, so the measure has little power to separate models.

## 4. Future fixes

| Fix | Status |
|---|---|
| Stop the judge at the first "budget exceeded" error instead of failing every remaining poster | **Done** (`judge.py`, tested) |
| Analysis reads the new score files (`analysis.judge_scores`, `analysis.human_scores`); prompt-version check per split | **Done** |
| Finish judging: Gemini on the 13 unscored posters + 14 truncated claims; GPT-4o on all 35 main posters (about $11) | Needs budget |
| Gemini claim truncation: per-judge output cap (Gemini about 32,768; GPT-4o's maximum is 16,384) and 20 claims per verification call, or lower Gemini thinking effort | To do before the re-run |
| Re-run only the failed task of a poster, not all three | To do (saves about 40% of a re-run) |
| Push human calibration scores to `data/latex/gpt4o_calibration_2/human_scores.csv` (per-item checklist, `n_claims_total`); then run `pilot_agreement.py` for both judges and score Gemini revision 2 on the calibration posters | Team |
| Independent, blinded holdout (e.g. human-score a few main posters by code only) to validate the judge outside the calibration set | Team |
| More attempts per model (≥ 59) if GR-4 must be testable; randomized run order for latency | Future study |
