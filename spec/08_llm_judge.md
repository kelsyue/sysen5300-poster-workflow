# 08 — LLM-as-Judge Workflow

Implements component 3b (judge runner) and the judge pilot in `04_experiment_protocol.md` §5. Code: `harness/judge/judge.py`, `harness/judge/pilot_agreement.py`, `harness/judge/reference_sheet.py`, prompts in `harness/judge/prompts/` (the reference-sheet prompts in `prompts/reference/` are hashed separately). The Blinder (`harness/src/blinder.py`, component 2) prepares its input.

Judges score the **LaTeX poster** (the `latex-only-v2` workflow's PDF). The PPTX workflow is historical and is not judged.

## 1. Design principles

| Principle | How it is applied | Why |
|---|---|---|
| One rubric task per call | Coverage, hallucination and quality are separate calls, never one "rate this poster" prompt | Decomposed, multi-criterion rubrics agree better with humans than one holistic prompt (Hashemi et al., 2024) |
| Same instrument as humans | Judges use the same 9-item checklist, claim flagging, and 1–5 anchors as the author scoring sheet | Judge and human scores must be directly comparable for validation |
| Pointwise, blinded | One poster per call; files named by `poster_code`; posters rendered to PNG (drops file metadata); manifest refuses an `llm_model` column; order shuffled per judge and repeat | Removes position bias and model identity (Zheng et al., 2023) |
| Evidence required | Every label must quote the poster and/or paper; code checks the quotes really exist | Catches the judge inventing evidence; low `evidence_found_rate` is a red flag |
| Anti-verbosity | Prompts tell the judge not to reward length or polish | Verbosity bias (Zheng et al., 2023) |
| Judges from the config | `judges.models` in `config/experiment.yaml`: Gemini Flash (`gemini-3.5-flash`) and GPT-4o (`openai.gpt-4o`) (OI-13). GPT-4o shares a provider with `gpt-5.6-sol`, so the pilot bias check tests for self-preference (protocol §5 step 6). A judge must not be a candidate model | Self-preference bias (Panickssery et al., 2024) |
| Deterministic settings, versioned rubric | Temperature 0; the prompt files are hashed into `judge_prompt_sha256` on every row; repeats on the pilot | Outputs still vary run to run (Blackwell et al., 2024), so test–retest is measured. The hash keeps scores from different prompt versions apart |

## 2. Inputs per poster

| Input | Source | Used by |
|---|---|---|
| Poster image (PNG, long side 2,000 px) | Rendered by `judge.py` from the blinded LaTeX PDF with `pdftoppm`; cached as `judge_images/<poster_code>.png`, so both judges see the same image | Coverage, quality |
| Poster text | `pdftotext` of the same PDF, written by the Blinder (`blinded/<poster_code>.txt`). The LaTeX PDF has a real text layer, so this is exact text, including table cells and captions | Coverage, claim extraction |
| Poster word count | Words in that text; the denominator of `halluc_per1k` for judges and humans alike | Hallucination rate |
| Full paper text | `pdftotext` of `papers/<id>.pdf`, cached in `data/paper_text/<id>.txt` (a cleaner hand-made `.txt` there takes precedence) | Claim verification; coverage and quality when no reference sheet exists |
| Reference sheet | `papers/<id>.reference.json`, made by `reference_sheet.py` (§2.1) | Coverage, quality |

### 2.1 Reference sheets (OI-20, decided 2026-10-31)

One JSON per paper stating what each checklist item is in that paper, plus a 2–3 sentence summary. It is made once per paper with no person in the loop, committed next to the PDF, and reused for every poster and every future model swap.

1. Each model in `reference_sheets.models` (the two judges, Gemini Flash and GPT-4o) drafts the sheet from the full paper: per item, a short value and one sentence copied from the paper, or `null` if the paper has no such item.
2. Code checks that each quote is in the paper (the same `quote_found` check as the judges' evidence).
3. Each model compares the two drafts item by item. An item is **accepted** when both models call the drafts the same and both quotes are found; the first model's value is used. It is **na** when both drafts say the item does not apply.
4. Every other item is **uncertain**. The coverage judge sees both drafts and the paper paragraphs around the verified quotes, and counts the item accurate if the poster correctly states either draft (the rule is in `prompts/coverage.md`). Uncertain items are listed in `data/reference_review.csv`; a team member may resolve one by editing the sheet (`"status": "accepted"` with a `"value"`, or `"na"`).

With a sheet, `NA` comes from the sheet, not the judge, so judge and human denominators match; an accepted item labelled `na` by the judge counts as missing. Every judge row records the sheet's `reference_sha256`. Without a sheet, coverage and quality receive the paper text (`reference_fallback_chars`) and the judge decides NA.

Uncertain is common and not an error: on P01, 3 of 9 items were uncertain, because the paper has more than one valid secondary result, or because GPT-4o called a more detailed draft "different" from a shorter one even when told that counts as the same.

**Limitation.** The judges write the sheet they later score against, so a misreading of the paper by a judge can appear in both. The quote check and the two-model agreement limit this, and the human pilot measures the judge and sheet together: evaluators score from the paper, not from the sheet. The setup brief proposed models that are neither judges nor candidates; the team chose the judges (2026-10-31).

## 3. The four calls

| # | Task | Inputs | Output | Becomes |
|---|---|---|---|---|
| 1 | Coverage | image + poster text + reference | label per item: accurate / wrong / missing / na, with poster quote | `chk_*` (1/0/NA), `coverage_pct` |
| 2 | Claim extraction | poster text | list of atomic claims with source quote | `n_claims_total` |
| 3 | Claim verification | claims (batches of 40) + full paper | supported / unsupported / contradicted, with paper quote | `n_claims_unsupported` (unsupported + contradicted), `halluc_per1k`, `flagged_claims` |
| 4 | Quality | image + reference summary and values (no excerpts) + printed size | eight yes/no observations (raw JSON only), then layout, readability, fidelity (1–5) + holistic 1–5 | `quality_score` (holistic), sub-scores for diagnosis |

Hallucination follows the FActScore approach (Min et al., 2023): break text into atomic claims, then check each against the source. Rate = 1,000 × (unsupported + contradicted) / poster words, matching SR-2.

The quality prompt states the printed size (from `poster_width_inches` × `poster_height_inches`) and tells the judge that blurry text in the downscaled image is not by itself a readability problem; otherwise every 48 × 36 in poster looks unreadable at 2,000 px.

Since judge prompt revision 2 (2026-11-01), before scoring the quality judge records eight yes/no observations (empty space, overflow, duplicated visual, small figure/table text, dense text, caption mismatch, unclear order, hidden main result) with locations. They are kept in `judge_raw/` only; `quality_score` is still the judge's holistic 1–5 rating, and no column or formula changed. Revision 2 also gives the quality judge a code measurement of blank canvas (`canvas_map`: share of blank cells and a 12 × 9 map), because GPT-4o did not notice a half-empty poster without it, and treats unused canvas as a layout weakness (judged by blank space, not word count) and makes claim verification recompute derived numbers. See `harness/judge/calibration_revision_note.md`.

## 4. Reliability handling

- **Invalid JSON:** one repair turn ("return only the JSON object"); if still invalid, the task is recorded in `failed_tasks`, `parse_ok = 0`, and the poster is routed to human review as `PARSE_FAIL`.
- **Truncated reply** (`finish_reason = length`): recorded as a failed task without a repair turn. `max_output_tokens` is 8,192 because Gemini 3.5 Flash's thinking tokens count toward it.
- **Claim batches:** claims are numbered 1…n within each verification batch and mapped back. On the first real run GPT-4o renumbered a later batch from 1, which left 15 claims without a verdict.
- **Transport errors:** retried with backoff per gateway config; `budget_exceeded` is not retried.
- **Resume:** reruns skip (poster, judge, repeat, prompt hash) rows already scored with `parse_ok = 1`. A failed row is re-scored and the new row appended; readers keep the last row per key.
- **Prompt revision:** editing any file in `judge/prompts/` changes `judge_prompt_sha256`; the next run scores every poster again as new rows, and old rows stay as the record of the earlier version.
- **Audit:** raw responses, parsed output and per-task tokens are saved to `judge_raw/<poster_code>/<judge>__r<k>__<task>.json`.
- **Long papers:** truncated at `paper_char_limit` and flagged (`paper_truncated = 1`).

## 5. Pilot validation (`pilot_agreement.py`)

Run both judges with `--repeats 2` on the pilot posters, then compare with the authors' scores.

| Check | Metric | Proposed pass |
|---|---|---|
| Coverage items | Mean Cohen's kappa across 9 items (vs. human consensus; split votes excluded). Raw agreement per item is also reported, since kappa is unstable when nearly every poster gets an item right | ≥ 0.60 |
| Coverage % | ICC(2,1), absolute agreement | ≥ 0.75 |
| Hallucination per 1k | ICC(2,1) | ≥ 0.60 |
| Quality | Quadratic-weighted kappa | ≥ 0.60 |
| Quality | Share within ±1 point of human mean | ≥ 90% |
| Detection, each measure | Share of truly failing posters (by human score) the judge flags | ≥ 0.80 |
| Test–retest | ICC between repeat 1 and 2 | ≥ 0.80 |
| Evidence honesty | Share of judge quotes found in poster/paper | ≥ 0.90 |

Also reported, not gated: false-flag rate; Bayes P(truly fails | flagged) vs. observed; parallel-system detection 1 − (1 − d₁)(1 − d₂) vs. observed, plus an independence check (do both judges miss the same posters?); human–human ICC as the ceiling; mean judge-counted claims per 1,000 words (checks the ~40 assumption behind the SR-2 limit); per-candidate bias vs. humans (needs the private blind key).

`judge_disagreements.csv` lists every checklist item, quality score and hallucination pass/fail where a judge and the human consensus differ, with the judge's own label, reason and quote. It is the input for a prompt revision.

**Revising a prompt (calibration).** Split the pilot posters before looking at any judge output: a calibration half and a holdout half, each covering all four candidates. Read the disagreements on the calibration half only, find the pattern (e.g., the judge credits a vague method description as `accurate`; the quality judge ignores duplicated tables), and change the prompt wording or anchors to address that pattern. Then re-run both judges and score agreement on the holdout half with `--only-codes`. A judge that fails: revise its prompt **once**, re-run the pilot, and record the change and both prompt hashes. A judge that fails twice is not used; if both fail, every poster goes to human review. Judge scores are not rescaled after the fact to match humans: a systematic offset shows up as low ICC and is fixed in the prompt, so the instrument stays the same for future model swaps.

Thresholds follow common conventions (kappa ≥ 0.60 "substantial", Landis & Koch, 1977; ICC ≥ 0.75 "good", Koo & Li, 2016) and are set in `config.yaml` → `judge_validation`. **[TBD — OI-5]**

## 6. Cost of judging

Per poster per judge: 4+ calls (one extra verification call per 40 claims). P01 LaTeX poster, tokens in / out:

| Judge | Coverage | Claims (extract + verify) | Quality | Total | Total without a sheet |
|---|---|---|---|---|---|
| `openai.gpt-4o` | 6,544 / 1,266 | 17,671 / 6,408 | 2,193 / 235 | 26,408 / 7,909 | 36,444 / 8,647 |
| `gemini-3.5-flash` | 7,086 / 2,797 | 11,189 / 12,738 | 2,435 / 1,696 | 20,710 / 17,231 | 31,207 / 17,699 |

Gemini's output includes thinking tokens. Claim verification always gets the full paper. The image is a small part (the gateway providers downscale it to about 1,000 px); a single PNG of the whole poster is cheaper than tiles or the PDF. Revision 2 adds about 850 input and 150–200 output tokens to the quality call (observation list and canvas map; GPT-4o on P01: about 3,430 in); four zoomed quarters were tried and dropped: about 4,000 more tokens per poster, and they did not help GPT-4o see the layout.

A reference sheet costs about 28,000 tokens once per paper (P01: two drafts and two comparisons) and saves about 10,000 input tokens per poster per judge, so it pays for itself on the first poster: 30 papers × 4 candidates × 2 judges ≈ 2.4 M tokens saved for ≈ 0.85 M spent. Full run: two judges × 120 posters ≈ 960+ calls and ≈ 9 M tokens, plus pilot repeats. Track `tokens_in` / `tokens_out` in `judge_scores.csv`.

## 7. Known limitations

- Claim counts depend on how finely the judge splits claims (P01: Gemini 35, GPT-4o 58–95 on the same poster); the rate uses unsupported claims only, which is less sensitive to this.
- Temperature 0 does not make a judge repeatable: GPT-4o gave P01 quality 4, then 5. Test–retest on the pilot measures this.
- The judge sees extracted poster text, so coverage can be credited for text that is present but visually unreadable; readability is caught by the quality call instead. Text inside figure images is not in the extracted text.
- `pdftotext` reads the three columns in an order that can interleave headings; the text is complete but not always in reading order.
