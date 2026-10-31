# LLM Replacement Validation Harness — Specification

**Project:** Maintaining AI System Performance Across LLM Model Changes: A Poster-Making Application
**Course:** SYSEN 5300 (Team J / Team Data Analytics Trio)
**Team:** Khai Xin Kuan, Allyanna Panganiban, Kelly Yue
**Spec version:** 0.1 (draft, 2026-10-23)
**Target completion:** 2026-12-04 (charter goal date)

## Purpose

Build a fixed evaluation harness around Paper2Poster so that a candidate LLM can be swapped in, run on a fixed set of 30 research papers, scored, and accepted or rejected against stakeholder requirements, with less manual effort than the current process.

The harness holds everything constant except `llm_model`. It is the engineering artifact the project delivers; the 4-model experiment is its first full use.

## What the harness must answer

> When the underlying LLM of Paper2Poster is replaced, do poster content accuracy and quality change, and which candidate LLMs meet the stakeholder requirements (≥ 90% key-information coverage, < 2.0 unsupported claims per 1,000 poster words [proposed], ≥ 4.0/5 quality, ≥ 95% workflow success)?

## Spec files

| File | Contents |
|---|---|
| [01_requirements.md](01_requirements.md) | Stakeholder requirements, specification limits, functional and non-functional requirements, scope |
| [02_architecture.md](02_architecture.md) | Components, data flow, Paper2Poster integration, model gateway, directory layout |
| [03_data_schema.md](03_data_schema.md) | Codebook, table schemas, derived fields, validation rules |
| [04_experiment_protocol.md](04_experiment_protocol.md) | Run order, blinding, evaluator procedure, judge pilot, effort timing |
| [05_analysis_spec.md](05_analysis_spec.md) | Descriptive stats, SPC charts, capability analysis, probability methods (R) |
| [06_acceptance_gate.md](06_acceptance_gate.md) | Pass / fail / inconclusive rules, human-review routing, decision report |
| [07_open_issues.md](07_open_issues.md) | Inconsistencies across source docs and decisions still needed |
| [config.example.yaml](config.example.yaml) | Reference configuration for one experiment |

The harness implementation lives in [`../harness/`](../harness/README.md), including `scripts/gateway_check.py` (Cornell AI Gateway smoke test) and `src/runner.py`.

## LaTeX-only workflow revision (2026-10-30)

New runs use `latex-only-v2`: candidate-generated summaries, one combined figure
selection/section assignment call, followed by local LaTeX rendering. Per-run
checkpoints reuse completed generation stages, keyed to PDF, candidate and
prompts. `runner.py --rebuild` renders saved content without API credentials
or further model calls. PPTX generation and vision correction
loops are removed. No vision model calls or judge calls occur during generation.
The harness owns the preparation adapter; upstream remains pinned with its existing
token-cap patch. New CSVs and outputs live under `data/latex/` and `outputs/latex/`.
Legacy runs remain separate. Older sections describing PPTX/vision generation are
historical until revised; the harness README documents the active workflow.

## Fixed parameters (v0.1; original experiment)

| Parameter | Value |
|---|---|
| Application under test | Paper2Poster (Pang et al., 2025), [github.com/Paper2Poster/Paper2Poster](https://github.com/Paper2Poster/Paper2Poster) @ `623d042f283acee782b2644d6abd63f75eccfa1f` (2026-06-08) |
| Candidate LLMs (4) | `claude-opus-5`, `gpt-5.6-sol`, `meta.llama-4-maverick-17b-instruct`, `qwen.qwen3-vl-235b-a22b` |
| Vision (critic) model | Same as the candidate, so each poster comes from one model (OI-1) |
| Paper2Poster patch | One: `max_tokens: 8192` on every gateway call (OI-17) |
| Institution logo | `assets/CornellLogo.png` for every run (OI-18) |
| Model interface | Cornell AI Platform → AI Gateway (assumed LiteLLM, OpenAI-compatible) |
| Input papers | 30 papers by Cornell researchers |
| Attempts | 30 papers × 4 LLMs = 120 (fewer posters if attempts fail) |
| Prompt | Paper2Poster's built-in agent prompts at the pinned commit (`utils/prompt_templates/`), not tuned per model |
| LLM judges | Gemini Flash (`gemini-3.5-flash`), GPT-4o (`openai.gpt-4o`) (used only after pilot validation) |
| Human evaluators | Paper authors, blinded, target ≥ 2 per paper |
| Analysis | R (ggplot2), per course SIGMA chapters (Fraser, n.d.) |

## Source documents

Derived from the team's working files: Project Charter, Literature Review 1, Your Dataset 2 (codebook), Research Design 1 and 2, and Methods: How Prior Studies Inform Our Experimental Design. Where these disagree, the latest research design (v2) wins and the conflict is logged in `07_open_issues.md`.

## Conventions

- **MUST / SHOULD / MAY** follow RFC 2119 meaning.
- Requirement IDs: `SR-` stakeholder, `FR-` functional, `NFR-` non-functional, `DR-` data, `AR-` analysis, `GR-` gate.
- Items marked **[TBD]** need a team decision before build; each one has an entry in `07_open_issues.md`.
