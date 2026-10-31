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

Don't edit anything inside `vendor/Paper2Poster`. The one allowed change is [`patches/p2p-max-output-tokens.patch`](patches/p2p-max-output-tokens.patch) (OI-17): the Runner applies it to a clean checkout, and refuses to start if the checkout has any other changes. Its hash goes in `p2p_patch_sha256`.

### 3. Gateway credentials

```bash
cp .env.example .env        # gitignored; put your LiteLLM API key in it
source .env                 # once per terminal session
python scripts/gateway_check.py                     # must print ALL CHECKS PASSED
```

Use the **LiteLLM API key** as `CORNELL_AI_GATEWAY_KEY`. The key ID only identifies the key in Cornell's portal and isn't sent with requests.

The Runner passes these to Paper2Poster as `OPENAI_API_KEY` / `OPENAI_BASE_URL`, and also as camel's `OPENAI_COMPATIBILIY_API_KEY` / `OPENAI_COMPATIBILIY_API_BASE_URL` (misspelling is upstream). camel reads the COMPATIBILIY pair but never passes it to the OpenAI client, so the standard pair is the one that takes effect.

### 4. Papers

Put the 30 PDFs in `papers/` as `<input_paper_id>.pdf` (e.g. `P01.pdf`). IDs may use letters, digits, `_` and `-`. Sorted ID order is the fixed `run_order`. The PDFs are committed in `papers/`, so a clone has the same inputs.

## Running

### Make a LaTeX poster

The runner now uses **latex-only-v2**: parse the paper, then select figures and assign them to
sections in one compact candidate-model request. Code computes sizing and layout
and compiles the existing LaTeX template locally.
It does not generate PPTX, bullet-formatting JSON, or run visual critic loops.
PDF and PNG previews are produced automatically; no separate export command is needed.

### Quick start: generate new posters

Run these commands from the repository root using the existing setup:

```bash
cd harness
source .venv/bin/activate

# Load credentials from harness/.env, or the repository-root .env.
set -a
if [ -f .env ]; then
  source .env
else
  source ../.env
fi
set +a

# Generate one new poster using the combined planner, then compile LaTeX.
caffeinate -i python src/runner.py --models claude-opus-5 --papers P03
```

The runner prints `[run N]`; use that number to find the result:
`outputs/latex/N/latex/p03 x claude-opus-5.pdf`. The PNG preview is alongside it.
`caffeinate -i` keeps a Mac awake; omit it on other operating systems.
Generation makes real API calls and needs available gateway budget.

More generation commands, from the same `harness/` terminal:

```bash
# Several papers with one candidate.
caffeinate -i python src/runner.py --models claude-opus-5 --papers P03 P04 P05

# The selected papers with all four configured candidates.
caffeinate -i python src/runner.py --papers P03 P04 P05

# All 30 papers with all four configured candidates.
caffeinate -i python src/runner.py

# A separate pilot: first selected paper only, with one candidate.
# --dry-run DOES make API calls; it saves results in a separate directory.
caffeinate -i python src/runner.py --dry-run --models claude-opus-5 --papers P01

# Estimate full-run cost from pilot results; requires prices in config/prices.yaml.
python src/runner.py --estimate
```

Use `--models` with one or more of: `claude-opus-5`, `gpt-5.6-sol`,
`meta.llama-4-maverick-17b-instruct`, `qwen.qwen3-vl-235b-a22b`.
Omit `--models` to use all four. Paper IDs match filenames under `papers/`.

New results are isolated from the original PPTX experiment:

- Full runs: `data/latex/runs.csv`, `outputs/latex/<run_id>/`
- Dry runs: `data/latex/dry_run/runs.csv`, `outputs/latex/dry_run/<run_id>/`
- Poster: `latex/<paper_id lowercase> x <model>.pdf` inside each run folder,
  alongside a PNG preview, `poster.tex`, `fit.json` and `build.log`.

Previous posters and `data/runs.csv` remain as historical results. They are not
counted as completed attempts in the new workflow. Do not pool the two workflows
in the model comparison. Re-running skips attempts already recorded in the new CSV,
including failed attempts (FR-7). The v2 configuration/prompt hashes prevent mixing
results from the previous two-call LaTeX workflow into the same runs table.

The runner checks for `latexmk`, `xelatex`, `pdftoppm` and `pdftotext` on PATH before
making model calls. Install TeX dependencies with `bash scripts/install_latex_deps.sh`
and Poppler with `brew install poppler`. The runner also detects the project-local vendor/TinyTeX installation.

Generation still needs Paper2Poster's pinned environment and the token-cap patch.
The harness-owned `src/latex_prepare.py` adapts upstream's preparation stages;
the vendor checkout remains unchanged. The old batch helper under `outputs/` is
historical; use `src/runner.py` for new batches.

Token totals include text and vision (vision is zero in this workflow). Completed
preparation stages are logged even if a later stage fails; an interrupted call or
failed internal retry can still have unreported usage. Prices remain unset until
filled in `config/prices.yaml`; local spend caps need those prices. A gateway
`budget_exceeded` error is recorded as `E_BUDGET` and stops the whole batch.

Local LaTeX fitting balances columns and tries a fixed set of scales without
model calls. Remaining overflow fails the automatic check. The team still needs
to review readability, content accuracy and figures in the PNG/PDF.

### Reuse saved results without spending tokens

Each new run saves its original `run_config.yaml`, extracted summaries/figures,
layout, and checkpoints under `preparation/`. During a transport retry, completed
parsing and planning stages are reused. Checkpoints validate source PDF content,
candidate, generation settings and prompt/code hashes; candidate summaries are
never shared across models. `cache_usage.json` records reused stages. Fresh,
explicit experiment attempts have their own checkpoints.

If compilation fails or you want to change the local layout, rebuild the saved run.
From a fresh terminal at the repository root, activate the harness environment;
there is no need to load credentials:

```bash
cd harness
source .venv/bin/activate

# Replace 1 with the run number printed during generation.
python src/runner.py --rebuild outputs/latex/1
# A pilot saved with --dry-run has a different path.
python src/runner.py --rebuild outputs/latex/dry_run/1

# Also works for the existing P01 and P02 runs:
python src/runner.py --rebuild outputs/1 outputs/2
# Optional layout/page-size changes, without regenerating summaries:
python src/runner.py --rebuild outputs/latex/1 --config config/experiment.yaml
```

Rebuild requires archived `intermediate/raw_content.json`, `tree_split.json` and
referenced figures. It needs no API key, source PDF or model environment. It uses
the original run configuration unless `--config` is supplied, updates the rendered
PDF/PNG and `poster_text.txt`, and writes `rebuild_result.json` with zero new API
tokens. The original generation usage and runs.csv row are preserved. A rebuild
of an already rendered poster uses zero additional API tokens; it does not erase
the tokens spent generating that poster originally.

For older archives without run metadata, the existing direct renderer remains:

```bash
python src/latex_poster.py outputs/1
```

### After a run: team visual check (OI-7)

The Runner sets `workflow_success` from the automatic checks only. For every successful row, a team member opens the LaTeX poster PNG/PDF and fills `visual_check` in `runs.csv` with `pass`, or with `E_TRUNCATED` / `E_OVERFLOW` / `E_NO_FIGURES`. For a failure, also set `workflow_success` to 0 and copy the code into `failure_reason`. Log each manual edit (protocol §7).

## Validation

Run `python -m unittest discover -s tests` for offline workflow checks.
Offline checks cover one-call planning, invalid figure references, checkpoint
isolation/restoration, resumed preparation, zero-credential rebuilds and failure
handling. A new gateway pilot is still required to measure v2 token use and quality.
