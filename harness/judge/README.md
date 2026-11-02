# LLM-as-Judge module

Scores blinded LaTeX posters with the two judge models in `config/experiment.yaml` through the Cornell AI Gateway, then validates the judges against human scores. Full design: [`spec/08_llm_judge.md`](../../spec/08_llm_judge.md).

## Files

```
judge/
├── judge.py              # 4 judge calls per poster -> data/latex/judge_scores.csv
├── pilot_agreement.py    # judge vs. human agreement -> reports/judge_pilot.md, judge_disagreements.csv
├── reference_sheet.py    # per-paper checklist answers, drafted and cross-checked by both judges
├── prompts/              # the frozen rubric; any edit changes judge_prompt_sha256
│   ├── reference/        # reference-sheet prompts (hashed separately, into the sheet)
│   ├── system.md
│   ├── coverage.md       # 9-item checklist
│   ├── claims_extract.md # hallucination step 1
│   ├── claims_verify.md  # hallucination step 2
│   └── quality.md        # layout / readability / fidelity + holistic 1-5
└── tests/test_offline.py # end-to-end test with a fake gateway (no key needed)
```

Needs the harness environment (`pip install -r requirements.txt`) and Poppler (`pdftoppm`, `pdftotext`).

## Run (from `harness/`)

```bash
source .venv/bin/activate
set -a; source .env; set +a

# 0. Reference sheets, once per paper (skips papers that already have one)
python judge/reference_sheet.py                # or --papers P01 P02

# 1. Blind the successful LaTeX posters (writes codes, blinded PDFs/text, the manifest)
python src/blinder.py                 # data/latex/runs.csv
python src/blinder.py --dry-run       # data/latex/dry_run/runs.csv

# 2. Judge them (both judges; add --dry-run for the dry-run posters)
python judge/judge.py --repeats 2 --only-codes P-7K3Q,P-2M9X,...   # pilot posters, twice
python judge/judge.py                                              # everything in the manifest, once

# 3. After humans have scored the pilot posters
python judge/pilot_agreement.py       # -> reports/judge_pilot.md: USE / DO NOT USE per judge
```

Re-running skips posters already scored with the current prompts. Raw judge replies are in `data/latex/judge_raw/` for audit.

## Human scores

`src/blinder.py` writes `data/latex/human_scores_template.csv` with one row per poster in a random presentation order. Copy it to `data/latex/human_scores.csv`, one row per (poster, evaluator), and fill:

| Column | Value |
|---|---|
| `evaluator_id` | `E01`, `E02`, … never a name |
| `chk_problem` … `chk_limitation` | `1` accurate, `0` wrong or missing, `NA` item does not apply to the paper |
| `n_claims_total` | number of factual claims on the poster (denominator of the hallucination %) |
| `n_claims_unsupported` | claims not supported by, or contradicting, the paper |
| `flagged_claims` | the flagged claims, e.g. `["Accuracy 0.71", "uses PanDerm"]` |
| `quality_score` | 1–5, anchors in `spec/04_experiment_protocol.md` |
| `minutes_spent`, `submitted_at` | for SR-5 |

Score from the blinded PDF in `data/latex/blinded/`, without looking at the judge output.

## Reference sheets

`judge/reference_sheet.py` writes `papers/<id>.reference.json` with no person in the loop: both judges draft the sheet from the paper with a quote per item, code checks the quotes, and each model compares the two drafts. Each item ends up as:

| Status | When | What the coverage judge gets |
|---|---|---|
| `accepted` | both models call the drafts the same, both quotes found | the value |
| `na` | both drafts say the paper has no such item | "not applicable"; the item is excluded |
| `uncertain` | anything else | both drafts and the paper paragraphs around the verified quotes; accurate if the poster states either |

Uncertain items are also listed in `data/reference_review.csv`. To resolve one by hand, set its `"status"` to `"accepted"` with a `"value"`, or to `"na"`. Commit the sheets with the papers; regenerating a sheet (`--force`) gives a slightly different one, and judge rows record which sheet they used (`reference_sha256`).

A sheet costs about 28,000 tokens once per paper and saves about 10,000 input tokens per poster per judge. Without one, coverage and quality get the paper text instead and the judge decides NA itself.

## From your own scores to a better judge

1. Before looking at judge output, split the pilot posters into a calibration half and a holdout half (each with all four candidates).
2. Run `pilot_agreement.py --only-codes <calibration codes>` and open `reports/judge_disagreements.csv`: each row is an item or score where the judge and the human consensus differ, with the judge's label, reason and quote.
3. Look for a pattern, not single cases, and change the prompt wording or anchors in `judge/prompts/` to address it. Edits change `judge_prompt_sha256`, so old scores are kept but not mixed with new ones.
4. Re-run `judge.py` on the pilot posters, then `pilot_agreement.py --only-codes <holdout codes>`. Only the holdout result counts.
5. One revision per judge (protocol §5). Record what changed and both prompt hashes.

## Test without a key

```bash
python judge/tests/test_offline.py
```
