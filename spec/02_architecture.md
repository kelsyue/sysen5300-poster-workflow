# 02 — Architecture

## 1. Overview

```
            config.yaml (fixed: prompt, params, papers, judges | varies: llm_model)
                                   │
 papers/ ──► [1 Runner] ──► Paper2Poster (pinned) ──► Cornell AI gateway ──► candidate LLM
                │                                                     
                ├─► runs.csv (run_id, latency, tokens, cost, success)
                └─► outputs/<run_id>/ (poster file, extracted text, logs)
                                   │
                         [2 Blinder] ──► poster_code ↔ run_id key (team only)
                                   │
              ┌────────────────────┴───────────────────┐
     [3a Author packets]                       [3b Judge runner]
      randomized, blinded                       Gemini Flash + GPT-4o        
              │                                         │
      human_scores.csv                          judge_scores.csv
              └────────────────────┬───────────────────┘
                         [4 Review router] ──► review_queue.csv ──► human review
                                   │
                         [5 Analysis (R)] ──► stats, SPC charts, Cpk, bounds
                                   │
                         [6 Acceptance gate] ──► decision_report.md per candidate
```

## 2. Components

| # | Component | Language | Responsibility |
|---|---|---|---|
| 1 | Runner | Python | Iterate (model, paper) pairs in protocol order; call Paper2Poster; capture timing, tokens, cost, outputs, success flag |
| 2 | Blinder | Python | Assign anonymous `poster_code`; write key file; build randomized evaluator packets |
| 3a | Scoring sheet I/O | Python | Generate scoring sheets (spreadsheet/form); ingest completed sheets into `human_scores` |
| 3b | Judge runner | Python | Send each poster image + source paper to both judges with the fixed rubric; parse structured responses into `judge_scores` |
| 4 | Review router | Python | Apply flag rules (`06_acceptance_gate.md` §3); write review queue |
| 5 | Analysis | R | Everything in `05_analysis_spec.md` |
| 6 | Acceptance gate | R | Apply decision rules; render one report per candidate plus a comparison summary |
| 7 | Effort logger | Python/sheet | Record start/stop timestamps of human tasks per candidate |

## 3. Paper2Poster integration

- Pin Paper2Poster to one commit; record the hash in every run row (`p2p_commit`).
- Paper2Poster takes separate text-model and vision-model settings. **[TBD — OI-1]** which of these the candidate replaces. Default in this spec: the candidate replaces the **text model**; the vision model is held fixed across all runs so `llm_model` stays the only factor. All four candidates accept image input, so swapping the vision model is technically possible, but it would make the candidate change two pipeline roles at once.
- Do not modify the Paper2Poster pipeline, prompts, or layout logic between models (scope rule).
- Wrap Paper2Poster in a single function:

```python
def generate_poster(paper_path: str, llm_model: str, cfg: Config) -> RunResult:
    """Run one stateless Paper2Poster attempt. Never raises on model failure;
    returns RunResult(success=False, failure_reason=...) instead."""
```

## 4. Model gateway (Cornell AI Platform → AI Gateway)

The Cornell AI Platform has two modules, AI Gateway and AI Agent Studio. The gateway serves Gemini, Claude, GPT and other models, is free during its pilot, and is approved for **moderate-risk data and below** (Cornell AI Innovation Hub). Cornell IT has run a workshop on "AI Gateway and LiteLLM", so this spec assumes the gateway is a **LiteLLM proxy with an OpenAI-compatible API**. Confirm with the gateway team (OI-16).

### 4.1 Connection

- All generation and judge calls go through the gateway. No direct provider keys.
- Credentials come from environment variables, never from the repo:

```
CORNELL_AI_GATEWAY_URL   # base URL issued by Cornell, e.g. https://<host>/v1  [TBD]
CORNELL_AI_GATEWAY_KEY   # personal/virtual key issued by Cornell               [TBD]
```

- Client: the `openai` Python SDK pointed at the gateway (`base_url`, `api_key`). If Paper2Poster's internals need a provider-style config, route through LiteLLM's `litellm_proxy/<model>` prefix instead.
- Paper2Poster's model calls MUST be redirected to the gateway by config/env (e.g., `OPENAI_BASE_URL`, `OPENAI_API_KEY`), without editing pipeline logic.
- `scripts/gateway_check.py` (provided) MUST pass before the dry run. It lists available models, confirms every configured model ID exists, sends one text call and one image call per model, and checks that `usage` token counts are returned.

### 4.2 Models

| Role | Alias | Gateway ID | Vision input |
|---|---|---|---|
| Candidate | claude | `claude-opus-5` | yes |
| Candidate | gpt | `gpt-5.6-sol` | yes |
| Candidate | llama | `meta.llama-4-maverick-17b-instruct` | yes |
| Candidate | qwen | `qwen.qwen3-vl-235b-a22b` | yes |
| Judge | gemini | Gemini Flash — exact ID **[TBD]** | yes |
| Judge | gpt4o | `gpt-4o` (confirm with `gateway_check.py`) | yes |

Judges must accept image input because they score the rendered poster. GPT-4o shares a provider (OpenAI) with the candidate `gpt-5.6-sol`, so self-preference bias toward that candidate is possible (Panickssery et al., 2024). The pilot bias check in `04_experiment_protocol.md` §5 step 6 MUST test for it; Gemini Flash (Google) shares no provider with any candidate.

### 4.3 Cost and limits

- The gateway is free during the pilot, so `generation_cost` is computed from **list prices** in `prices.yaml` (what the run would cost on the provider's API), not from a bill. Record the price source and `as_of` date.
- Rate limits and quotas are not published **[TBD — OI-16]**. The Runner MUST handle HTTP 429 with backoff and log it.
- Data: the 30 papers and evaluator details must fall within the gateway's moderate-risk approval. Unpublished papers should be cleared with their authors before upload.

- Token counts come from the gateway response `usage` field. Cost = input tokens × input price + output tokens × output price (+ cached-token price where applicable), using `prices.yaml`.
- Retries: **[TBD — OI-6]** Default: up to 2 retries on transport errors (timeouts, 429, 5xx) with backoff; retries are logged and do not get a new `run_id`. Model output that is unusable is a workflow failure, not a retry.

## 5. Workflow success definition

An attempt is `workflow_success = 1` only if all of the following hold; otherwise 0 with a `failure_reason` code:

| Code | Check |
|---|---|
| `E_API` | Gateway call completed after allowed retries |
| `E_PIPELINE` | Paper2Poster finished without an exception |
| `E_NO_FILE` | A poster file was written |
| `E_UNREADABLE` | Poster text can be extracted / text is legible |
| `E_TRUNCATED` | Content is not cut off at poster edges |
| `E_OVERFLOW` | Text does not run outside its boxes |
| `E_NO_FIGURES` | Poster contains at least one figure from the paper |

The visual checks (`E_TRUNCATED`, `E_OVERFLOW`, `E_NO_FIGURES`) come from failure modes reported by Pang et al. (2025). **[TBD — OI-7]** whether these are checked automatically, by the team, or both.

## 6. Directory layout

```
harness/
├── config/
│   ├── experiment.yaml          # see config.example.yaml
│   └── prices.yaml              # per-model token prices, with as_of date
├── prompts/
│   ├── generation_prompt.txt    # fixed; SHA-256 stored per run
│   └── judge_rubric.txt         # fixed before grading
├── papers/                      # 30 PDFs, named <input_paper_id>.pdf
├── scripts/
│   └── gateway_check.py         # connection smoke test (provided)
├── src/
│   ├── runner.py
│   ├── blinder.py
│   ├── judges.py
│   ├── sheets.py
│   ├── router.py
│   └── effort_log.py
├── analysis/
│   ├── 01_describe.R
│   ├── 02_spc.R
│   ├── 03_capability.R
│   ├── 04_probability.R
│   ├── 05_judges.R
│   └── 06_gate.R
├── data/
│   ├── runs.csv
│   ├── human_scores.csv
│   ├── judge_scores.csv
│   ├── review_queue.csv
│   ├── effort_log.csv
│   └── private/blind_key.csv   # team only, gitignored
├── outputs/<run_id>/            # poster file, poster_text.txt, run.log
└── reports/<llm_model>/decision_report.md
```

The analysis dataset (one row per attempt, see `03_data_schema.md` §2) is built by joining `runs`, aggregated `human_scores`, and `judge_scores`. The team's shared Google Sheet mirrors `runs.csv` and the scoring sheets; CSV in the repo is the source of truth for analysis.
