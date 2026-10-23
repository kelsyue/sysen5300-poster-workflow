# LLM Replacement Validation Harness

Implementation of [`../spec/`](../spec/README.md). Built so far: the gateway smoke test and the Runner (component 1). Still to build: blinder, scoring sheets, judge runner, review router, effort log, and the R analysis.

## Setup

### 1. Harness environment

```bash
cd harness
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../spec/config.example.yaml config/experiment.yaml   # then fill in the TBDs
```

### 2. Paper2Poster (pinned, with its own environment)

Needs about 10 GB of free disk. Tested on macOS (Apple silicon) with Python 3.12.

```bash
# Code at the pinned commit. Git LFS files are skipped; they are only in demo/ and aren't used.
mkdir -p vendor/Paper2Poster && cd vendor/Paper2Poster
git init -q && git remote add origin https://github.com/Paper2Poster/Paper2Poster
git config filter.lfs.smudge "" && git config filter.lfs.process "" && git config filter.lfs.required false
git fetch --depth 1 origin 623d042f283acee782b2644d6abd63f75eccfa1f && git checkout -f FETCH_HEAD
cd ../..

# Python environment
python3.12 -m venv vendor/Paper2Poster/.venv
grep -v -E '^(vllm|triton|xformers|pandasai)([=<> ]|$)' vendor/Paper2Poster/requirements.txt > /tmp/p2p-req.txt
vendor/Paper2Poster/.venv/bin/pip install --no-cache-dir -r /tmp/p2p-req.txt
vendor/Paper2Poster/.venv/bin/pip install --no-cache-dir "scipy>1.15.1" "numpy==1.26.4" \
    "docling-parse<5" "docling-ibm-models<4"

brew install --cask libreoffice     # PPTX -> PNG (soffice must be on PATH)
brew install poppler                # PDF parsing

# Check: should print the pipeline's options
cd vendor/Paper2Poster && .venv/bin/python -m PosterAgent.new_pipeline --help
```

**Differences from Paper2Poster's `requirements.txt`.** These change the environment only; the Paper2Poster code is untouched.

| Change | Why |
|---|---|
| Skip `vllm`, `triton`, `xformers` | Linux + NVIDIA GPU only. Used only for running local models; all our models go through the gateway |
| Skip `pandasai` | Forces pandas 1.5.3, which won't install on Python 3.12. Only used by an optional camel data loader the poster pipeline never calls |
| `scipy` 1.15.1 → 1.17.1 | The 1.15.1 macOS build fails to load on current macOS (`__thread_bss` dlopen error) |
| `docling-parse` < 5, `docling-ibm-models` < 4 | Unpinned upstream; the newest releases removed modules (`pdf_parser_v2`, `layoutmodel`) that Paper2Poster's bundled docling imports |

The exact resulting versions are in [`config/paper2poster-env.lock.txt`](config/paper2poster-env.lock.txt) (`pip freeze`). To rebuild the same environment: `pip install --no-cache-dir -r config/paper2poster-env.lock.txt`.

Don't edit anything inside `vendor/Paper2Poster`: the Runner refuses to start if the checkout has local changes.

### 3. Gateway credentials

```bash
cp .env.example .env        # gitignored; put your LiteLLM API key in it
source .env                 # once per terminal session
python scripts/gateway_check.py                     # must print ALL CHECKS PASSED
```

Use the **LiteLLM API key** as `CORNELL_AI_GATEWAY_KEY`. The key ID only identifies the key in Cornell's portal and isn't sent with requests.

The Runner passes these to Paper2Poster as `OPENAI_COMPATIBILIY_API_KEY` / `OPENAI_COMPATIBILIY_API_BASE_URL`. The misspelling is Paper2Poster's (camel's), so keep it as written.

### 4. Papers

Put the 30 PDFs in `papers/` as `<input_paper_id>.pdf` (e.g. `P01.pdf`). IDs may use letters, digits, `_` and `-`. Sorted ID order is the fixed `run_order`. PDFs are gitignored; keep them in team storage.

## Running

```bash
python src/runner.py --dry-run     # 1 paper × 4 candidates → data/dry_run/runs.csv, outputs/dry_run/
python src/runner.py --estimate    # full-run cost estimate from the dry run (fill config/prices.yaml first)
python src/runner.py               # all candidates × all papers → data/runs.csv, outputs/<run_id>/
```

- **Resumable.** Re-running skips (model, paper, attempt) triples already in `runs.csv`. Failed attempts are kept as data (FR-7) and are not re-run automatically.
- **Subsets.** `--models <id> ...` and `--papers <id> ...`.
- **Spend cap.** The run stops when `experiment.spend_cap_usd` is reached (counts only models with prices filled in).
- **Retries.** Gateway errors (429, 5xx, timeouts) are retried up to `gateway.max_transport_retries` times with backoff, under the same `run_id`.

Each `outputs/<run_id>/` holds the poster `.pptx` and PNGs, Paper2Poster's `log.json` / `detail_log.json`, the extracted `poster_text.txt`, and `run.log` (full Paper2Poster output).

### After a run: team visual check (OI-7)

The Runner sets `workflow_success` from the automatic checks only. For every successful row, a team member opens the poster PNG and fills `visual_check` in `runs.csv` with `pass`, or with `E_TRUNCATED` / `E_OVERFLOW` / `E_NO_FIGURES`. For a failure, also set `workflow_success` to 0 and copy the code into `failure_reason`. Log each manual edit (protocol §7).

## Not yet verified

Nothing here has run against the real gateway yet. Check these in the dry run:

- Paper2Poster accepts gateway model IDs through its OpenAI-compatible fallback (no code changes).
- `log.json` token counts are non-zero for every model. Some gateways leave out `usage`.
- The error patterns in `TRANSPORT_ERRORS` (`src/runner.py`) match what the gateway actually returns.
