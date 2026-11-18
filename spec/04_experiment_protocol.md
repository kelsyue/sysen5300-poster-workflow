# 04 — Experiment Protocol

## As run (revised 2026-11-01; supersedes §1, §3 and §5 where they differ)

The token budget cut the study from 30 papers to 15 and the posters are not regenerated.

- **Papers:** 15 (P01–P15) × 4 candidates = 60 attempts. P06, P11 and P13 are the judge
  calibration papers; the **main comparison uses the other 12 papers** (48 attempts).
- **Run order:** paper by paper; within each paper always claude → gpt → llama → qwen. Not
  randomized. Paper blocks absorb drift over the run; order within a paper is a limitation.
- **Recovery:** failed attempts were re-run once from their checkpoints (`src/recovery.py`); a
  failed figure plan was retried with its own error as feedback, under a newer harness version.
  Each poster is counted from its **used run**: the first attempt if it succeeded, otherwise its
  recovery (team decision, 2026-11-01); a failed first attempt replaced by a recovery is not
  counted against the model. Latency, tokens and cost are summed over all attempts of a poster,
  because a recovery reuses the paper summary made in the earlier attempt. Recovery is
  confounded with the model (every claude and qwen attempt in the main set used a recovery run),
  so differences mix model and recovery path; reported as a limitation. `data/runs.csv` is the
  old PPTX workflow and is not used.
- **Judge validation:** human scores exist only for the 3 calibration papers, which were also
  used to revise the judge prompts. Agreement (§5) is measured on those 12 posters; there is no
  independent holdout, so agreement is optimistic and the judge's use on the 12 main papers rests
  on it. The bias check (§5 step 6) is run on the same posters.
- **Analysis:** Python (`harness/analysis/`), methods in `05_analysis_spec.md`.

## 1. Design

- **Unit of observation:** one poster-generation attempt = one paper × one LLM.
- **Factor:** `llm_model`, 4 levels.
- **Blocks:** `input_paper_id`, 30 blocks (randomized block design; every model sees every paper).
- **Attempts:** 120. Repeat attempts per pair MAY be added if budget allows; each gets its own `run_id`.
- **Held fixed:** Paper2Poster commit, prompt, system settings, generation parameters, rubric, checklist, judges.

## 2. Pre-run checklist

1. Check out Paper2Poster at `623d042f283acee782b2644d6abd63f75eccfa1f` in `harness/vendor/Paper2Poster`, with no local changes. The Runner checks this and records the hash.
2. Freeze the judge prompts (`harness/judge/prompts/`; `judge.py` records their SHA-256 as `judge_prompt_sha256` on every row, and the one allowed revision after the pilot gets a new hash, see `08_llm_judge.md` §5). The generation prompts are Paper2Poster's own templates at the pinned commit; the Runner hashes them per run. No edits to either after the first run.
3. Collect 30 papers; assign `input_paper_id`; confirm each author agrees to evaluate.
4. Fill `prices.yaml` from the gateway's current price list; set `as_of`.
5. Dry run: 1 paper × 4 models (`python src/runner.py --dry-run`). Confirm all four model IDs respond, usage is returned, and outputs parse. Dry-run posters go to `data/dry_run/` and are excluded from analysis.
6. Run the cost estimator (`python src/runner.py --estimate`), which scales dry-run cost to the full run; confirm the total is within budget and set `spend_cap_usd`.

## 3. Run order

- Papers run in one fixed order (sorted ID), recorded as `run_order`. Each model generates one poster per paper.
- Paper-major: all four models run on a paper before the next paper starts, so gateway drift over the batch affects every model alike.
- Within each paper the four models run in a seeded random order (`runner.model_order`, `experiment.seed`; latex-painter-v3 batches from 2026-11-13). Earlier batches used the fixed alphabetical order.
- Every attempt is a separate stateless call. No prompt iteration.

> Note: models still share the batch's time span with each other, not with other batches; latency is reported, not gated.

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
| 4 | Presentable with minor edits. Only a couple of minor issues in layout, readability, or emphasis |
| 3 | Usable draft. Several minor issues or one major issue (e.g., key result under-emphasized, crowded text block) |
| 2 | Needs substantial rework. Poor structure, sections too thin to explain the research without the paper, a large share of unused canvas, or misleading representation of the paper |

Sections: Abstract, Introduction, Methods (or Methodology / Experimental Setup / Experimental Design), Results, Discussion, Conclusion are expected as headings containing those words ("Discussion & Impact" counts; "Motivation" or "Implications" does not). Each missing one is a minor issue, never by itself a 2. A section is too thin when a reader who has not read the paper cannot understand that part of the research from it; that is a major issue. Length is not rewarded for its own sake. Revised 2026-11-17 (latex-v3 judge calibration, revisions 1-2).
| 1 | Not usable. Unreadable, missing core content, or misrepresents the work |

## 5. Judge validation pilot (before the full experiment)

**Purpose:** confirm Gemini Flash and GPT-4o score posters closely enough to humans to be used for screening (Hashemi et al., 2024; Zheng et al., 2023).

1. **Pilot set:** a subset of posters with completed human scores. Size **[TBD — OI-5]**; suggested ≥ 20 posters covering all 4 models.
2. Both judges score the pilot set with the same rubric and checklist used by humans. Present posters in randomized order; run each judge twice to measure test–retest consistency.
3. Compare each judge with the human mean:
   - Coverage and quality: agreement metric and acceptance threshold **[TBD — OI-5]** (e.g., ICC or weighted kappa).
   - Pass/fail classification against each spec limit: detection rate *d* (share of truly failing posters the judge flags) and false-flag rate.
4. **Bayes check:** P(truly fails | judge flags) from pilot counts.
5. **Parallel rule:** P(at least one judge flags a truly failing poster) = 1 − (1 − d₁)(1 − d₂). Check the independence assumption by comparing with the observed joint flag rate on the pilot.
6. **Bias check:** GPT-4o shares a provider (OpenAI) with the candidate `gpt-5.6-sol`, so self-preference is possible (Panickssery et al., 2024). Compare GPT-4o's error against humans on `gpt-5.6-sol` posters versus the other candidates; if it is more lenient there, use Gemini Flash alone (or human review) for `gpt-5.6-sol` posters. Also compare each judge's error against humans by candidate model; a judge that is consistently lenient or harsh on one candidate is flagged. Human scores remain the reference throughout.
7. A judge is used in the full experiment only if it meets the threshold set in OI-5. If neither passes, all posters go to human review.

## 6. Effort timing (SR-5)

- Log start/stop of every human task per candidate in `effort_log` (setup, monitoring, review, analysis, decision).
- Evaluator minutes come from the scoring sheet.
- Compare total person-hours per candidate under the harness with the 4-hour manual baseline. **[TBD — OI-9]** how the 4-hour baseline was measured, so the comparison is like-for-like.

## 7. Data recording

- One row per attempt in `runs`; the shared Google Sheet mirrors it for the team.
- All team members record together; any manual edit to a run row is logged with who/when/why.
