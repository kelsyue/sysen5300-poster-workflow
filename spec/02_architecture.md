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

- Upstream: <https://github.com/Paper2Poster/Paper2Poster>, pinned to commit `623d042f283acee782b2644d6abd63f75eccfa1f` (2026-06-08). Record the hash in every run row (`p2p_commit`). The Runner refuses to start if the checkout is on a different commit or has local changes.
- Paper2Poster takes separate text-model and vision-model settings (`--model_name_t`, `--model_name_v`). The vision model is the critic: it looks at rendered panel images and tells the text model to fix overflow and overlap. **Decided (OI-1):** the candidate fills **both** slots (`vision_model: same_as_candidate`), so each poster comes from one model and the experiment tests a whole-model swap. The cost is that a candidate's results combine its writing and its visual critique, which can't be separated. All four candidates accept image input. Setting `vision_model` to a gateway ID instead holds one critic fixed across candidates.
- Do not modify the Paper2Poster pipeline, prompts, or layout logic between models (scope rule).
- **Prompt.** Paper2Poster has no single prompt. It runs several agents (parser, figure filter, outline, layout, content filler, critics), each with its own built-in prompt in `utils/prompt_templates/*.yaml`, plus style defaults in `config/poster.yaml`. The "fixed prompt" is these files at the pinned commit. `prompt_sha256` is the SHA-256 over those files (sorted by path), computed by the Runner from the checkout.
- **Invocation.** One attempt is one process, run from the Paper2Poster root:

```bash
python -m PosterAgent.new_pipeline \
  --poster_path="harness_input/<input_paper_id>/paper.pdf" \
  --model_name_t="<llm_model>" --model_name_v="<llm_model>" \
  --tmp_dir="tmp/<run_id>" \
  --poster_width_inches=48 --poster_height_inches=36 \
  --institution_logo_path=assets/CornellLogo.png   # OI-18
```

- **Model names.** `get_agent_config()` in `utils/wei_utils.py` maps a few built-in names (`4o`, `vllm_qwen`, …). Any other name falls through to camel's `OPENAI_COMPATIBLE_MODEL` platform, which reads its endpoint from environment variables. So gateway model IDs are passed as-is and no Paper2Poster code changes are needed (§4.1).
- **Generation parameters.** For fall-through model names Paper2Poster passes no model config, so no temperature or max-token setting is sent and each provider's default applies. **[TBD — OI-17]**
- **Outputs.** Paper2Poster writes to `<{model_t}_{model_v}>_generated_posters/<poster_path dir>/`: `<input_paper_id>.pptx`, PNG renders of the poster, `log.json` (total input/output tokens for the text and vision models, `time_taken`) and `detail_log.json` (tokens per pipeline step). The Runner moves this folder to `outputs/<run_id>/` right after each attempt so repeats don't overwrite each other.
- **System dependencies.** LibreOffice (`soffice` on `PATH`, for PPTX → PNG) and Poppler (PDF parsing).
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
CORNELL_AI_GATEWAY_URL   # https://api.ai.it.cornell.edu/v1
CORNELL_AI_GATEWAY_KEY   # personal LiteLLM API key issued by Cornell (not the key ID)
```

- Client: the `openai` Python SDK pointed at the gateway (`base_url`, `api_key`). If Paper2Poster's internals need a provider-style config, route through LiteLLM's `litellm_proxy/<model>` prefix instead.
- Paper2Poster's model calls MUST be redirected to the gateway by env, without editing pipeline logic. camel's OpenAI-compatible client reads these two variables. The names are misspelled upstream (`COMPATIBILIY`, no T) and must be used exactly as written:

```
OPENAI_COMPATIBILIY_API_KEY       = $CORNELL_AI_GATEWAY_KEY
OPENAI_COMPATIBILIY_API_BASE_URL  = $CORNELL_AI_GATEWAY_URL
```

  The Runner sets them for each Paper2Poster process from the gateway variables above.
- `scripts/gateway_check.py` (provided) MUST pass before the dry run. It lists available models, confirms every configured model ID exists, sends one text call and one image call per model, and checks that `usage` token counts are returned.

### 4.2 Models

| Role | Alias | Gateway ID | Vision input |
|---|---|---|---|
| Candidate | claude | `claude-opus-5` | yes |
| Candidate | gpt | `gpt-5.6-sol` | yes |
| Candidate | llama | `meta.llama-4-maverick-17b-instruct` | yes |
| Candidate | qwen | `qwen.qwen3-vl-235b-a22b` | yes |
| Judge | gemini | `gemini-3.5-flash` | yes |
| Judge | gpt4o | `openai.gpt-4o` | yes |

Judges must accept image input because they score the rendered poster. GPT-4o shares a provider (OpenAI) with the candidate `gpt-5.6-sol`, so self-preference bias toward that candidate is possible (Panickssery et al., 2024). The pilot bias check in `04_experiment_protocol.md` §5 step 6 MUST test for it; Gemini Flash (Google) shares no provider with any candidate.

### 4.3 Cost and limits

- The gateway is free during the pilot, so `generation_cost` is computed from **list prices** in `prices.yaml` (what the run would cost on the provider's API), not from a bill. Record the price source and `as_of` date.
- Rate limits and quotas are not published **[TBD — OI-16]**. The Runner MUST handle HTTP 429 with backoff and log it.
- Data: the 30 papers and evaluator details must fall within the gateway's moderate-risk approval. Unpublished papers should be cleared with their authors before upload.

- Token counts come from Paper2Poster's `log.json`, which sums the gateway `usage` fields over every call in the attempt. Text-model (candidate) and vision-model tokens are recorded separately. Paper2Poster does not report cached tokens, so `cached_tokens` stays empty. Cost = input tokens × input price + output tokens × output price, using `prices.yaml`.
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
├── assets/
│   └── CornellLogo.png          # fixed institution logo (OI-18)
├── config/
│   ├── experiment.yaml          # see config.example.yaml
│   └── prices.yaml              # per-model token prices, with as_of date
├── prompts/
│   └── judge_rubric.txt         # fixed before grading (generation prompts live in Paper2Poster)
├── papers/                      # 30 PDFs, named <input_paper_id>.pdf (gitignored)
├── vendor/Paper2Poster/         # pinned checkout + its own Python env (gitignored)
├── scripts/
│   └── gateway_check.py         # connection smoke test (provided)
├── src/
│   ├── runner.py                # built (first version)
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
├── outputs/<run_id>/            # poster .pptx + PNGs, log.json, detail_log.json, poster_text.txt, run.log
└── reports/<llm_model>/decision_report.md
```

The analysis dataset (one row per attempt, see `03_data_schema.md` §2) is built by joining `runs`, aggregated `human_scores`, and `judge_scores`. The team's shared Google Sheet mirrors `runs.csv` and the scoring sheets; CSV in the repo is the source of truth for analysis.
