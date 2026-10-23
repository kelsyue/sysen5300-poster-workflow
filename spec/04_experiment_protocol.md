# 04 — Experiment Protocol

## 1. Design

- **Unit of observation:** one poster-generation attempt = one paper × one LLM.
- **Factor:** `llm_model`, 4 levels.
- **Blocks:** `input_paper_id`, 30 blocks (randomized block design; every model sees every paper).
- **Attempts:** 120. Repeat attempts per pair MAY be added if budget allows; each gets its own `run_id`.
- **Held fixed:** Paper2Poster commit, prompt, system settings, generation parameters, rubric, checklist, judges.

## 2. Pre-run checklist

1. Pin Paper2Poster commit; record hash.
2. Freeze `generation_prompt.txt` and `judge_rubric.txt`; record SHA-256. No edits after the first run.
3. Collect 30 papers; assign `input_paper_id`; confirm each author agrees to evaluate.
4. Fill `prices.yaml` from the gateway's current price list; set `as_of`.
5. Dry run: 1 paper × 4 models. Confirm all four model IDs respond, usage is returned, and outputs parse. Dry-run posters are excluded from analysis.
6. Run the cost estimator; confirm the total is within budget and set `spend_cap_usd`.

## 3. Run order

- Models run in alphabetical order of gateway ID: `claude-opus-5` → `deepseek.v3.2` → `gpt-5.6-sol` → `qwen.qwen3-vl-235b-a22b`.
- Within each model, papers run in one fixed order (same for every model), recorded as `run_order` 1–30.
- Finish all 30 papers for a model before switching.
- Every attempt is a separate stateless call. No prompt iteration.

> Note: running models in sequence confounds model with time of day / gateway load for latency. Latency is reported, not gated, so this is acceptable; mention it as a limitation.

## 4. Blinded author evaluation

1. Blinder assigns each successful poster a random `poster_code`.
2. Each author receives only the posters made from **their** paper (up to 4), in randomized order, labeled by code only.
3. Rubric and checklist are fixed and sent before grading starts; evaluators do not revise criteria mid-grading (Shankar et al., 2024).
4. For each poster the evaluator completes:
   - **Coverage:** mark each checklist item accurate (1), wrong/missing (0), or not applicable (NA).
   - **Hallucination:** flag every claim not supported by, or contradicting, the paper; log each claim separately.
   - **Quality:** one holistic 1–5 score using the rubric below.
   - **Time spent** in minutes.
5. Target ≥ 2 evaluators per paper (e.g., co-authors, postdocs). Scores are averaged per poster.
6. The blind key stays with the team. Evaluators are never told which model made which poster.

### Quality rubric (1–5) **[TBD — OI-8: confirm anchor wording]**

Based on Watson (2015) poster criteria and the codebook definition (layout, readability, how well content represents the paper):

| Score | Anchor |
|---|---|
| 5 | Ready to present. Logical flow, efficient use of space, readable text, labeled figures that carry the main findings, content faithful to the paper |
| 4 | Presentable with minor edits. One small issue in layout, readability, or emphasis |
| 3 | Usable draft. Several issues or one major issue (e.g., key result under-emphasized, crowded text block) |
| 2 | Needs substantial rework. Poor structure or misleading representation of the paper |
| 1 | Not usable. Unreadable, missing core content, or misrepresents the work |

## 5. Judge validation pilot (before the full experiment)

**Purpose:** confirm Gemini Flash and Llama 4 Maverick (`meta.llama-4-maverick-17b-instruct`) score posters closely enough to humans to be used for screening (Hashemi et al., 2024; Zheng et al., 2023).

1. **Pilot set:** a subset of posters with completed human scores. Size **[TBD — OI-5]**; suggested ≥ 20 posters covering all 4 models.
2. Both judges score the pilot set with the same rubric and checklist used by humans. Present posters in randomized order; run each judge twice to measure test–retest consistency.
3. Compare each judge with the human mean:
   - Coverage and quality: agreement metric and acceptance threshold **[TBD — OI-5]** (e.g., ICC or weighted kappa).
   - Pass/fail classification against each spec limit: detection rate *d* (share of truly failing posters the judge flags) and false-flag rate.
4. **Bayes check:** P(truly fails | judge flags) from pilot counts.
5. **Parallel rule:** P(at least one judge flags a truly failing poster) = 1 − (1 − d₁)(1 − d₂). Check the independence assumption by comparing with the observed joint flag rate on the pilot.
6. **Bias check:** neither judge shares a provider with a candidate, so direct self-preference is unlikely (Panickssery et al., 2024). Still compare each judge's error against humans by candidate model; a judge that is consistently lenient or harsh on one candidate is flagged. Human scores remain the reference throughout.
7. A judge is used in the full experiment only if it meets the threshold set in OI-5. If neither passes, all posters go to human review.

## 6. Effort timing (SR-5)

- Log start/stop of every human task per candidate in `effort_log` (setup, monitoring, review, analysis, decision).
- Evaluator minutes come from the scoring sheet.
- Compare total person-hours per candidate under the harness with the 4-hour manual baseline. **[TBD — OI-9]** how the 4-hour baseline was measured, so the comparison is like-for-like.

## 7. Data recording

- One row per attempt in `runs`; the shared Google Sheet mirrors it for the team.
- All team members record together; any manual edit to a run row is logged with who/when/why.
