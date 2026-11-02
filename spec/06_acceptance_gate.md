# 06 — Acceptance Gate

The gate turns the analysis into an accept/reject recommendation per candidate. It is a pass/fail regression check in the sense of Breck et al. (2017): each requirement is its own test.

## 1. Per-requirement results

| ID | Requirement | Method | Pass | Fail | Inconclusive |
|---|---|---|---|---|---|
| GR-1 | Coverage ≥ 90% | 95% bootstrap CI of the model mean (AR-4) | CI lower end ≥ 90 | CI upper end < 90 | Otherwise |
| GR-2 | Hallucination < 5% of claims | 95% bootstrap CI of the model mean (AR-4) | CI upper end < 5 | CI lower end ≥ 5 | Otherwise |
| GR-3 | Quality ≥ 4.0 | 95% bootstrap CI of the model mean (AR-4) | CI lower end ≥ 4.0 | CI upper end < 4.0 | Otherwise |
| GR-4 | Workflow success (used run) ≥ 95% | Exact one-sided 95% bounds (AR-5) | Lower bound ≥ 95% | Upper bound < 95% | Otherwise |

Revised 2026-11-01 (was: Cpk/Ppk interval vs. 1). Cpk/Ppk are reported but exploratory: with about 12 bounded, discrete scores per model they are unstable and undefined when scores do not vary. Fewer than 5 scored posters → inconclusive. GR-1 to GR-3 are evaluated per score source (each judge; humans where available). With 12 attempts GR-4 cannot pass (59 straight successes are needed), so **Accept** is not reachable in this study; a model is either rejected or inconclusive.

## 2. Overall recommendation

| Condition | Recommendation |
|---|---|
| All of GR-1…GR-4 pass | **Accept** |
| Any requirement fails | **Reject** (list failing requirements) |
| None fail, at least one inconclusive | **Inconclusive** — collect more attempts on the inconclusive measures, or escalate to stakeholders |

SPC signals (AR-3) are exploratory at this sample size: they are listed in the report for explanation but do not block a decision.

## 3. Human-review routing (full experiment, after judges pass the pilot)

A poster goes to `review_queue` if any of these hold:

| Reason | Rule |
|---|---|
| `JUDGE_DISAGREE` | The two judges fall on opposite sides of a spec limit, or differ by more than a set margin **[TBD — OI-5]** |
| `NEAR_LIMIT` | Either judge's score is within a band around a limit **[TBD — OI-5]** (e.g., coverage 80–100, quality 3.5–4.5) |
| `PARSE_FAIL` | A judge response could not be parsed |
| `RANDOM_AUDIT` | A random sample of non-flagged posters (suggested 10%) to monitor judge drift (Rao et al., 2026) |

Unflagged posters use the mean of the two judges' scores. Flagged posters use the human score. The report states how many scores came from each source.

> In the first full experiment, authors score every poster anyway (that is the study design). The routing rules are applied in parallel to measure how much human review **would** have been needed — this is the evidence for SR-5. In future replacements, only routed posters go to humans.

## 4. Decision report (`reports/<llm_model>/decision_report.md`)

Generated per candidate:

1. Header: model ID, date, Paper2Poster commit, prompt hash, config hash, n attempts, n posters scored, evaluators per paper.
2. Result table: GR-1…GR-4 with point estimate, index (Cpk or Ppk), both CIs, result.
3. Overall recommendation and reasons.
4. SPC summary: signals found and explanations.
5. Cost, latency, token usage: mean, median, total.
6. Probability of meeting all requirements (series estimate vs. observed).
7. Review routing: share of posters flagged, by reason.
8. Effort: person-hours vs. 4 h baseline and 1 h target.
9. Limitations: fixed prompt, non-determinism, judge bias, sequential run order.

Plus `reports/comparison_summary.md`: all four candidates side by side.

## 5. Re-use for future model changes (Control phase)

To validate a new candidate later:

1. Add the model ID to `config/experiment.yaml` and its prices to `prices.yaml`.
2. Run the Runner on the same 30 papers with the same prompt, commit, and settings.
3. Run judges; route flagged posters to human review.
4. Run analysis and gate; read the decision report.

If the Paper2Poster commit, prompt, or rubric changes, earlier results are no longer comparable and the baseline candidates must be rerun.
