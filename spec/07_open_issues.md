# 07 — Open Issues and Decisions Needed

Found by cross-checking the working files. Each needs a team decision before build or before the step it affects.

| ID | Issue | Where it conflicts | Proposed default in this spec | Blocks |
|---|---|---|---|---|
| OI-1 | Which Paper2Poster model slot the candidate replaces (text, vision, or both) | Not stated in any doc. `deepseek.v3.2` has no image input | Replace the text model only; hold the vision model fixed | Runner build |
| OI-2 | Checklist length: text says "8-item" but lists 9 items. Also no rule for items that don't apply to a paper | Dataset 2, §III | Use all 9; allow NA, excluded from denominator | Scoring sheet |
| OI-3 | **Decided 2026-10-23:** hallucination is measured per 1,000 poster words. Still open: confirm the limit. Proposed < 2.0, converted from the charter's < 5% assuming ~40 claims per 1,000 words | Dataset 2 codebook; Charter goal statement | Count total claims on the pilot set to check the density; update the codebook unit and charter wording | SR-2 value |
| OI-4 | SR-4 (≥ 95% success) can't be shown with 30 attempts: 30/30 gives a one-sided 95% lower bound of ~90.5%. About 59 straight successes are needed to reach 95% | Charter goal vs. sample size | Report as inconclusive unless repeats are added; or define pass on the point estimate with the bound reported | GR-4 |
| OI-5 | Judge pilot size, agreement metric and threshold, disagreement margin, and near-limit bands are not set | Research Design 2, Methods doc | Pilot ≥ 20 posters; thresholds to agree before the pilot | Judge pilot, routing |
| OI-6 | Retry policy for API errors | Not stated | ≤ 2 transport retries, same `run_id`; unusable output = failure | Runner build |
| OI-7 | Who decides "usable poster" for workflow success, and how (automatic checks, team check, or both) | Codebook definition only | Automatic checks for API/pipeline/file; team check for truncation, overflow, missing figures | Runner build |
| OI-8 | Quality rubric anchors (what a 3 vs. 4 looks like) not written down | Codebook, Research Design 2 | Draft anchors in `04_experiment_protocol.md` §4 | Evaluator packets |
| OI-9 | How the 4-hour manual baseline was measured | Charter | Document the baseline method so the harness effort is measured the same way | SR-5 |
| OI-10 | Bootstrap resampling unit (attempts vs. papers) | Research Design 2 | Resample papers (keeps blocks intact) | AR-4 |
| OI-11 | Sample size: Dataset 2 says 5 models / 150 runs; later docs say 4 models / 120 | Dataset 2 vs. Research Design 1 & 2, Charter | 4 models / 120 attempts; update Dataset 2 | — |
| OI-12 | Poster quality score: Research Design 1 lists "Evaluators/LLM as Judge"; Research Design 2 says paper authors | Research Design 1 vs. 2 | Authors are the reference; judges screen only after validation | — |
| OI-13 | **Decided 2026-10-23:** judges are Gemini Flash + `meta.llama-4-maverick-17b-instruct` (GPT-4o dropped), removing the same-provider overlap with `gpt-5.6-sol`. Still open: exact Gemini Flash gateway ID; update Lit Review §X–XI and Research Design 2, which still name GPT-4o | Lit review, Research Design 2 | — | Judge runner |
| OI-14 | Small number of papers with < 2 evaluators | Dataset 2 ("hoping for at least 2") | Proceed with 1 where needed; report evaluators per paper; inter-rater agreement only on papers with ≥ 2 | — |
| OI-16 | Cornell AI Gateway details not public: base URL, key issuance, whether it is LiteLLM/OpenAI-compatible, which of the 6 model IDs it serves, rate limits, and whether research papers are within its moderate-risk data approval | Gateway page lists none of this | Request docs/onboarding via the Cornell TDX form on the platform page; run `gateway_check.py` once a key is issued | Runner build, dry run |
| OI-15 | Process capability on bounded, discrete scores (9-item coverage moves in ~11-point steps; quality averages of 1–5) is approximate | Research Design 2 | Report both normal and bootstrap CIs; also report AR-6 probabilities | AR-4 |
