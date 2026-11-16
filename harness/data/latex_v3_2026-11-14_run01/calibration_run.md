# P01–P03 two-judge calibration run

Started 2026-11-15 on the eight successful posters in this run's `runs.csv`.
Four unsuccessful generation attempts have no poster and are excluded.

- Judges: `gemini-3.5-flash` and `openai.gpt-4o`.
- Two repeats per judge: 32 expected poster evaluations.
- Saved configuration: `config/experiment_2026-11-14_run01.yaml`.
- Frozen rubric SHA-256: `4ec65050cfdc718218dbc587f672291e733fd03b1254c20d77b61b0933e16162`.
- Existing P01, P02 and P03 reference sheets are reused.
- Blinded inputs: `judge_manifest.csv` and `blinded/`; generator identities are
  retained separately in `data/private/latex_v3_2026-11-14_run01/blind_key.csv`.
- Raw task responses: `judge_raw/`; common rendered images: `judge_images/`.

Completed 2026-11-15: all 32 expected evaluations succeeded. The judges ran
concurrently in separate processes. Two GPT-4o first-repeat claims audits
(P-2NCM and P-JFMG) initially omitted verdicts; both succeeded on one retry with
the same settings, reusing completed coverage and quality tasks.

`judge_scores.csv` contains the 32 latest complete evaluations for both judges.
Separate attempt histories are retained in `judge_scores_gemini_attempts.csv`
and `judge_scores_gpt4o.csv`. See `calibration_summary.md` for aggregate results,
`calibration_poster_summary.csv` for per-poster means, and
`calibration_retest.csv` for repeatability. The summary calculations use each
completed poster/repeat once; failed attempts do not enter those means.

No completed human scores are present for this batch. These runs support judge
comparison and test–retest assessment, but cannot establish agreement with human
ratings. `human_scores_template.csv` is blank and is not treated as observations.
All eight successful runs lack a recorded `visual_check`; scores for posters
that subsequently fail that check must be excluded.

The configured calibration papers for the main analysis remain P06/P11/P13.
This requested P01–P03 batch does not change that split or the main analysis
configuration, and no prompts are tuned from these scores.

The runner records `halluc_per1k`, a word-normalized diagnostic. Claim-based
hallucination percentage is separately calculated as
`100 * n_claims_unsupported / n_claims_total` only for completed claims audits;
missing or failed audits are never interpreted as zero.
