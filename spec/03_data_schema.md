# 03 — Data Schema

## 1. Codebook (from "Your Dataset 2")

| Variable | Role | Unit | Definition |
|---|---|---|---|
| `llm_model` | Predictor | model ID | Model used to generate the poster |
| `prompt` | Control | text (stored as hash) | Prompt used to generate the poster |
| `input_paper_id` | Control / block | paper ID | Research paper used to generate the poster |
| `run_id` | Identifier | integer | Unique per attempt, even for repeated model–paper pairs |
| `key_information_coverage` | Outcome | % | Share of checklist items correctly represented in the poster |
| `hallucination_rate` | Outcome | claims per 1,000 words | Unsupported claims in the poster per 1,000 words of poster text |
| `latency` | Outcome | seconds | Prompt submission → completed poster |
| `generation_cost` | Outcome | USD | Token usage × model pricing for one poster |
| `workflow_success` | Outcome | 0/1 | Whether the workflow produced a usable poster |
| `poster_quality_score` | Outcome | 1–5 | Holistic rating of layout, readability, and how well content represents the paper |
| `token_usage` | Outcome | integer | Tokens consumed during generation |

## 2. Tables

### 2.1 `runs` — one row per attempt (written by Runner)

| Column | Type | Required | Notes |
|---|---|---|---|
| `run_id` | int | yes | Unique, sequential |
| `run_order` | int | yes | Position within the model's batch (1–30), for control charts |
| `batch_id` | int | yes | `ceil(run_order / 5)`, for the p-chart |
| `llm_model` | str | yes | Gateway ID |
| `input_paper_id` | str | yes | |
| `prompt_sha256` | str | yes | |
| `p2p_commit` | str | yes | |
| `config_sha256` | str | yes | |
| `temperature` | float | yes | Fixed across runs |
| `seed` | int | no | If the model supports it |
| `started_at` / `finished_at` | ISO-8601 UTC | yes | |
| `latency` | float (s) | yes | `finished_at − started_at` of the generation step |
| `input_tokens` / `output_tokens` / `cached_tokens` | int | yes* | *Null only if gateway returned no usage |
| `token_usage` | int | yes* | Sum of input + output |
| `generation_cost` | float (USD) | yes* | From `prices.yaml` |
| `price_table_as_of` | date | yes | |
| `retries` | int | yes | Transport retries used |
| `workflow_success` | 0/1 | yes | Per `02_architecture.md` §5 |
| `failure_reason` | str | if failed | One code from §5 of architecture |
| `poster_path` | str | if success | |
| `poster_word_count` | int | if success | Words of extracted poster text |

### 2.2 `blind_key` — private (written by Blinder)

| Column | Type | Notes |
|---|---|---|
| `poster_code` | str | Random, e.g. `P-7K3Q`; no model info encoded |
| `run_id` | int | |
| `llm_model` | str | |

### 2.3 `human_scores` — one row per (poster, evaluator)

| Column | Type | Notes |
|---|---|---|
| `poster_code` | str | |
| `evaluator_id` | str | e.g. `E01`; never the evaluator's name |
| `input_paper_id` | str | |
| `presentation_position` | int | Order in which the evaluator saw it |
| `chk_problem` … `chk_limitation` | 0/1 | One column per checklist item (§3); 1 = accurate, 0 = wrong/missing |
| `n_claims_total` | int | Optional. Total factual claims; collect on the pilot set only, to check the claim density behind the SR-2 limit |
| `n_claims_unsupported` | int | Claims flagged as unsupported or contradicting the paper |
| `flagged_claims` | text/JSON | Each flagged claim logged individually |
| `quality_score` | int 1–5 | Holistic rubric score |
| `minutes_spent` | float | Self-reported, feeds SR-5 |
| `submitted_at` | ISO-8601 | |

### 2.4 `judge_scores` — one row per (poster, judge, repeat)

Same scoring fields as `human_scores`, with `judge_model` instead of `evaluator_id`, plus `judge_repeat` (for test–retest), `raw_response`, and `parse_ok` (0/1).

### 2.5 `review_queue`

`poster_code`, `reason` (`JUDGE_DISAGREE`, `NEAR_LIMIT`, `PARSE_FAIL`, `RANDOM_AUDIT`), `measure`, `values`, `resolved_by`, `resolved_score`, `resolved_at`.

### 2.6 `effort_log`

`llm_model`, `task` (`setup`, `generation_monitoring`, `human_review`, `analysis`, `decision`), `person_id`, `start`, `end`, `minutes`.

## 3. Key-information checklist

As listed in the codebook (9 items; the text says "8-item" — **[TBD — OI-2]**):

| Column | Item |
|---|---|
| `chk_problem` | Research problem / background |
| `chk_method` | Method / approach |
| `chk_data` | Dataset or sample |
| `chk_setup` | Experimental setup |
| `chk_primary_result` | Primary quantitative result |
| `chk_secondary_result` | Secondary result |
| `chk_baseline` | Baseline / comparison |
| `chk_conclusion` | Main conclusion |
| `chk_limitation` | Limitation / implication |

If an item does not apply to a paper (e.g., no baseline), the evaluator marks it `NA` and it is excluded from that paper's denominator. **[TBD — OI-2]**

## 4. Derived fields (per attempt, in the analysis dataset)

```
coverage_e      = 100 × sum(chk_*) / count(non-NA chk_*)        # per evaluator
key_information_coverage = mean(coverage_e across evaluators)

halluc_per1k_e  = 1000 × n_claims_unsupported / poster_word_count
hallucination_rate = mean(halluc_per1k_e across evaluators)

poster_quality_score = mean(quality_score across evaluators)
```

For failed attempts all three content outcomes are `NA`, never 0.

## 5. Validation rules (enforced on ingest)

- **DR-1** `run_id` unique; every `poster_code` maps to exactly one `run_id`.
- **DR-2** `workflow_success = 0` ⇒ `failure_reason` not null and no human/judge rows exist for that run.
- **DR-3** Checklist cells ∈ {0, 1, NA}; `quality_score` ∈ {1,2,3,4,5}.
- **DR-4** `n_claims_unsupported ≤ n_claims_total`.
- **DR-5** Every successful poster has ≥ 1 human score before analysis; target ≥ 2. Report the count per paper.
- **DR-6** Prompt hash, config hash, and Paper2Poster commit are identical across all runs in an experiment; ingest fails otherwise.
- **DR-7** Each (model, paper) pair has at least one attempt; 120 attempts expected.
