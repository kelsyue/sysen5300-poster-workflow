# 01 — Requirements

## 1. Problem

Organizations running LLM-based applications must decide repeatedly whether to replace the current model. Providers retire models on their own schedule (Anthropic: ≥ 60 days' notice; OpenAI: 6 months for GA models, as little as 2 weeks for previews), and a model's behavior can change even under the same name (Chen et al., 2024). Validating a replacement today is ad hoc, manual, hard to reproduce, and takes about **4 hours** per candidate (charter baseline).

## 2. Stakeholder requirements (specification limits)

These are the acceptance limits. Each is checked on its own; there is no combined score.

| ID | Measure | Limit type | Limit | Unit | Source |
|---|---|---|---|---|---|
| SR-1 | `key_information_coverage` | LSL | ≥ 90 | % of checklist items accurate | Charter goal |
| SR-2 | `hallucination_rate` | USL | < 2.0 **[proposed]** | unsupported claims per 1,000 poster words | Charter goal (< 5%), converted — see note |
| SR-3 | `poster_quality_score` | LSL | ≥ 4.0 | 1–5 rating | Charter goal |
| SR-4 | `workflow_success` rate | LSL | ≥ 95 | % of attempts | Charter goal |
| SR-5 | Validation effort per candidate | Target | ≤ 1 hour (from 4 h baseline, −75%) | person-hours, incl. human review | Charter goal |

**Note on SR-2:** the team chose to measure hallucination as unsupported claims per 1,000 words of poster text (decided 2026-10-23). The charter's "< 5%" was a share of claims, so it was converted: assuming about 40 claims per 1,000 poster words, 5% ≈ 2 unsupported claims per 1,000 words. The 40-claim density is an assumption; check it on the judge pilot set and update the limit before the full run. See `07_open_issues.md` → OI-3. The charter goal statement should be updated to match.

Measures recorded without a specification limit (reported, not gated): `latency`, `generation_cost`, `token_usage`.

## 3. Scope

**In scope**
- End-to-end replacement validation in Paper2Poster: integrate candidate → generate posters → automated evaluation → targeted human review → accept/reject.
- 30 Cornell research papers, 4 candidate LLMs, the seven codebook outcomes.

**Out of scope**
- AI applications other than research-poster generation.
- LLMs not selected for the study.
- Fine-tuning any model.
- Changing the Paper2Poster workflow, prompt, or settings between models.
- Per-model prompt tuning (a known limitation; Tripathi et al., 2025).

## 4. Functional requirements

### Model integration
- **FR-1** The harness MUST route every generation call through one model interface (Cornell AI gateway) so that changing the candidate is a single config value (`llm_model`).
- **FR-2** Adding a new candidate MUST NOT require code changes to the pipeline, scoring, or analysis — only a config entry.
- **FR-3** Each attempt MUST be an independent, stateless API call with no conversation history carried between runs.

### Generation
- **FR-4** The harness MUST run every (paper, model) pair with the same Paper2Poster commit, prompt, system settings, and generation parameters.
- **FR-5** The harness MUST assign a unique `run_id` to every attempt, including repeats of the same pair.
- **FR-6** The harness MUST record latency, token usage, and cost for every attempt, including failed ones where available.
- **FR-7** A failed attempt MUST be kept in the data with `workflow_success = 0` and MUST NOT be scored for coverage, hallucination, or quality.
- **FR-8** The harness MUST save the raw poster output (PPTX/image/HTML as produced) and extracted poster text for every successful attempt.
- **FR-9** The harness SHOULD use prompt caching where the gateway supports it, without changing prompt content.

### Blinding and evaluation
- **FR-10** The harness MUST assign each poster an anonymous code and keep the code ↔ `llm_model` key in a file accessible only to the research team.
- **FR-11** The harness MUST produce, per evaluator, a packet of that author's posters in randomized order with a scoring sheet.
- **FR-12** The harness MUST ingest completed scoring sheets and compute coverage, hallucination, and quality per evaluator, then the mean across evaluators.
- **FR-13** The harness MUST run both LLM judges (Gemini Flash, `meta.llama-4-maverick-17b-instruct`) on the same rendered posters with the same fixed rubric.
- **FR-14** Judges MUST NOT be used to score the full experiment until they pass the pilot validation in `04_experiment_protocol.md` §5.

### Decision
- **FR-15** The harness MUST flag posters for human review when the two judges disagree or a score falls near a specification limit (rules in `06_acceptance_gate.md`).
- **FR-16** The harness MUST output, per candidate, a pass / fail / inconclusive result for each requirement SR-1 to SR-4, plus an overall accept/reject recommendation.
- **FR-17** The harness MUST log human time spent per candidate so SR-5 can be measured.

## 5. Non-functional requirements

- **NFR-1 Reproducibility.** Every run MUST be reproducible from: Paper2Poster commit hash, config file, prompt hash, paper ID, model ID, and generation parameters, all stored with the run.
- **NFR-2 Isolation.** The scoring and analysis code MUST be independent of which candidate is plugged in.
- **NFR-3 Non-determinism handling.** Because outputs vary even at temperature 0 with a fixed seed (Blackwell et al., 2024), decisions MUST rest on statistical tests across attempts, never single comparisons.
- **NFR-4 Auditability.** Raw outputs, scoring sheets, judge responses, and the blinding key MUST be retained until the final report is submitted.
- **NFR-5 Budget.** The harness SHOULD support a dry-run cost estimate before a full run, and MUST stop a run if a configured spend cap is reached.
- **NFR-6 Data handling.** Source papers and evaluator identities MUST stay within team-controlled storage; evaluator names MUST NOT appear in the analysis dataset (use evaluator IDs).
