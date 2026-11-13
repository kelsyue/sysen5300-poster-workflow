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

Don't edit anything inside `vendor/Paper2Poster`. The one allowed change is [`patches/p2p-generation-params.patch`](patches/p2p-generation-params.patch) (OI-17), which sends the same `max_tokens` (8192) and `temperature` (0) on every candidate call: the Runner applies it to a clean checkout, and refuses to start if the checkout has any other changes. Its hash goes in `p2p_patch_sha256`.

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

The runner now uses **latex-painter-v3** (`fixed.paper2poster.workflow`). It follows
Paper2Poster's own stages, Parser → Planner → Painter → Commenter, with the Painter and
Commenter in a cheaper form:

| Stage | Upstream | Here |
|---|---|---|
| Parser | long section summaries ("keep as much raw text as possible") | upstream prompt, unchanged |
| Planner | zero or one figure/table per section | one combined call (`src/combined_planner.py`), same rule; v3 adds "give every section a fitting visual" |
| Painter | `bullet_point_agent`: bullets with bold key terms, one call per section | **one call for the whole poster** (`src/poster_painter.py`): a 2–4 sentence paragraph per section, plus 2–4 bullets only where a section lists parallel items (results, contributions, limitations), as in the README poster; `**key terms**`; 450 words in total (upstream skill: 250–500) |
| Commenter | vision model flags overflow ("1") or too much blank space ("2"); the Painter shortens the text or "adds one more bullet point", up to 10 rounds per text box | LaTeX log + position markers (no model). Overflow at `min_font_scale`: **one** shortening call. A column ending more than `blank_min_frac` (10%) of the page above the bottom: **one** expansion call that lengthens that column's sections with source facts not yet on the poster, kept only if the poster still fits at the same or a larger font (otherwise the earlier text is restored) |

Locally, without model calls: figure/table crops that cut through a label are regrown to
the surrounding blank page (`src/figure_crops.py`); columns are re-balanced with block
heights measured in the compiled PDF; the font scale is the largest of 1.5…0.85 that fits;
figures in columns with empty space are enlarged (up to the column width); duplicate
tables disappear because the Painter writes short text, not the paper's tables. A poster
that still overflows (bottom margin, or a line sticking out of its column by more than
10pt) fails `E_OVERFLOW`; text is never cut.

Each poster costs three candidate calls (paper summary, figure plan, Painter), plus one
short call only when it overflows and one only when a column has too much blank space
(the gap is converted to words with the poster's own measured text density; P03, Opus:
column 2's gap fell from 21% to 10% of the page at the same font, $0.10). The Painter reads the summaries, not the paper. The
Painter's audit, `intermediate/painter_check.json`, lists per-section budgets and word
counts and any number in a bullet that does not appear in the summaries or captions.
Generation never calls a judge model; judging is a separate command (see "Judging the
LaTeX posters"), so test runs of either step are independent.

v3 results go to their own run set, `fixed.paper2poster.run_set: latex_v3`
(`data/latex_v3/`, `outputs/latex_v3/`), never mixed with the judged **latex-only-v2**
posters in `data/latex/`. Saved v2 runs still rebuild with their own `run_config.yaml`.

**Model calls (v3).** Every call goes through `src/gateway_chat.py`, which sends what
camel sent at the pinned commit (model, messages, `max_tokens`, `temperature`; client
timeout 180 s, 3 SDK retries) without camel's message windows or context truncation. Each
call is saved as `intermediate/calls/NN_<stage>.json`: the full request, the reply, its
finish reason and usage, and the gateway's own record (LiteLLM version, deployment ID,
charged cost). v2 runs keep camel.

**Prompt caching (v3).** The Planner, Painter and shortening calls start with the same
system message and source block (section summaries and captions, serialized identically),
followed by their own task. For the models in `fixed.paper2poster.prompt_cache_models`
(Opus) the source block carries a 5-minute cache breakpoint, so the Painter and the
shortening call read it at 0.1× the input price; the Planner pays 1.25× to write it.
Measured on P03 (Opus): 4,393 cached tokens, about $0.014 net saving per poster (about 4%).
The parser call (the whole paper) is not marked: it is sent once, and a write would cost
more than it saves. Gateway checks (2026-11-12): GPT-5.6 on Azure never reported a cache
read, but the gateway charges it the cache-write price (1.25×) on almost all input tokens
of every call; Llama and Qwen have no prompt cache. Caching never changes a model's output.

**Reproducibility (v3).** Given a run folder, everything after the model replies is
deterministic: `python src/runner.py --rebuild <run>` makes a byte-identical PDF (fixed
`SOURCE_DATE_EPOCH`, single XeLaTeX pass, fixed fonts, seeded section selection). Each run
also saves `environment.json` (harness commit, uncommitted files, sha256 of every
`src/*.py`, package-list hashes and key versions of both Python environments, XeLaTeX and
Poppler versions) next to `run_config.yaml`. Model replies themselves are not
reproducible even at temperature 0; the saved calls are the record.

Every attempt is one row in `runs.csv`. The codebook variables:

| Column | Meaning |
|---|---|
| `llm_model` | candidate that generated the poster (predictor) |
| `input_paper_id` | paper used (control) |
| `run_id` | unique number per attempt in that runs file, including repeats of the same pair |
| `latency` | seconds of processing for the attempt: every try plus the LaTeX build, without back-off waits |
| `generation_cost` | USD from `config/prices.yaml`: input tokens × input price + output tokens × output price, except that prompt tokens read from (`cached_tokens`) or written to (`cache_write_tokens`) the prompt cache use the cache-read and cache-write prices |
| `gateway_cost` | v3: USD the gateway reported charging (`x-litellm-response-cost`), summed over the attempt's calls; a check on `generation_cost` |
| `workflow_success` | 1 if a usable poster was produced (automatic checks below), else 0 with `failure_reason` |
| `token_usage` | all tokens of every candidate call in the attempt, including calls in failed tries |

Automatic failure codes: `E_API` (gateway failed after retries), `E_BUDGET`, `E_PIPELINE`
(parser or planner output unusable), `E_LATEX`, `E_OVERFLOW` (text still overflows at the
smallest font scale), `E_UNREADABLE` (no extractable text), `E_NO_FIGURES` (no figure or
table from the paper placed). The team check adds `E_TRUNCATED` (OI-7).

Prices come from the gateway's own price list. Refresh them before a run with
`python scripts/fetch_prices.py` (writes `config/prices.yaml` with the date).

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

Find the result in `outputs/latex_v3/posters/p03/p03 x claude-opus-5.pdf`.
The PNG preview and all other models' posters for P03 are in that same folder.
The runner also prints `[run N]`; the archived result is in
`outputs/latex_v3/N/latex/p03 x claude-opus-5.pdf`.
`caffeinate -i` keeps a Mac awake; omit it on other operating systems.
Generation makes real API calls and needs available gateway budget.

More generation commands, from the same `harness/` terminal:

```bash
# Several papers with one candidate.
caffeinate -i python src/runner.py --models claude-opus-5 --papers P03 P04 P05

# The selected papers with all four configured candidates.
caffeinate -i python src/runner.py --papers P03 P04 P05

# Papers P01–P15: all four models for each paper before the next paper.
caffeinate -i python src/runner.py --papers P{01..15}

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
Generation processes papers in sorted ID order, running all selected candidates for
each paper before moving to the next paper, in a seeded random order per paper (printed at
the start of each paper; `experiment.seed`). Each model generates one poster per paper.

New results are isolated from the original PPTX experiment:

- Full runs: `data/<run_set>/runs.csv`, `outputs/<run_set>/<run_id>/` (`<run_set>` is
  `latex_v3` for v3, `latex` for the judged v2 posters)
- Dry runs: `data/<run_set>/dry_run/runs.csv`, `outputs/<run_set>/dry_run/<run_id>/`
- Grouped exports: `outputs/<run_set>/posters/<paper_id lowercase>/`, containing
  `<paper_id lowercase> x <model>.pdf` and `.png` for every generated model.
  Dry-run exports go in `outputs/<run_set>/dry_run/posters/<paper_id lowercase>/`.
  Generation and rebuilds refresh these copies automatically; repeated attempts
  replace that model's grouped copy while preserving each run's archive.
- Poster: `latex/<paper_id lowercase> x <model>.pdf` inside each run folder,
  alongside a PNG preview, `poster.tex`, `fit.json` and `build.log`.

Previous posters and `data/runs.csv` remain as historical results. They are not
counted as completed attempts in the new workflow. Do not pool the two workflows
in the model comparison. Re-running skips attempts already recorded in the new CSV,
including failed attempts (FR-7). The v2 configuration/prompt hashes prevent mixing
results from the previous two-call LaTeX workflow into the same runs table.

The runner checks for `xelatex`, `pdftoppm` and `pdftotext` on PATH before
making model calls. Install TeX dependencies with `bash scripts/install_latex_deps.sh`
and Poppler with `brew install poppler`. The runner also detects the project-local vendor/TinyTeX installation.

Generation still needs Paper2Poster's pinned environment and the generation-params patch.
The harness-owned `src/latex_prepare.py` adapts upstream's preparation stages;
the vendor checkout remains unchanged. The old batch helper under `outputs/` is
historical; use `src/runner.py` for new batches.

Token totals include text and vision (vision is zero in this workflow). Completed
preparation stages are logged even if a later stage fails. The paper-summary call is
tried at most `max_parse_attempts` times (2) when its output is unusable, and every
attempt's tokens are counted; upstream's parser retried without limit and reported only
the last call. A call cut off by a dropped connection can still go unreported. A gateway
`budget_exceeded` error is recorded as `E_BUDGET` and stops the whole batch;
`experiment.spend_cap_usd` stops the run once the summed `generation_cost` reaches it.

Local LaTeX fitting balances columns and tries a fixed set of scales without
model calls; `fit.json` records the scale, overflow in both directions, column bottoms
and figure widths. Remaining overflow fails the automatic check. The team still needs
to review readability, content accuracy and figures in the PNG/PDF.

#### Pilot before the full v3 run

Generate the papers with the worst v2 overflows plus one calibration paper, then blind
and judge them in the v3 run set, and compare with the v2 scores for the same posters:

```bash
caffeinate -i python src/runner.py --papers P03 P10 P06            # 12 posters, about $1-2
python src/blinder.py --run-set latex_v3
python judge/judge.py --data-dir data/latex_v3
python src/results.py --run-set latex_v3
```

### Reuse saved results without spending tokens

Each new run saves its original `run_config.yaml`, extracted summaries/figures,
layout, and checkpoints under `preparation/`. During a transport retry, completed
parsing and planning stages are reused. Checkpoints validate source PDF content,
candidate, generation settings and prompt/code hashes; candidate summaries are
never shared across models. `cache_usage.json` records reused stages. Fresh,
explicit experiment attempts have their own checkpoints.

Each paper–model pair generates its own summaries and figure selections from the
source paper with fresh model agents. A different model never receives another
model's summaries, selections, or poster. The source paper, prompts, template and
layout rules are common experimental inputs. Grouped export folders are only for
viewing results; generation does not read them. Layout rebuilds reuse only the
selected run's saved content, and retry checkpoints are scoped to that attempt.

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

### Recover failed posters from their checkpoints

With the same environment and gateway credentials loaded, run:

```bash
# Retry each unfinished poster once. Successful posters are skipped.
caffeinate -i python src/runner.py --retry-failed --papers P{01..15}

# Recreate the completion/token/cost report without any API calls.
python src/runner.py --summary --papers P{01..15}
```

`--models` and `--dry-run` also work with these commands. Recovery uses each
original run's saved configuration, source paper and model. A new numbered output
folder receives a copy of only that run's checkpoints, intermediate artifacts and
cumulative usage counters. Original run folders and `data/latex/runs.csv` remain
unchanged. Recovery runs cannot share checkpoints across candidates or papers.

Completed summaries are reused when their checkpoint identity validates. Failed
figure plans are retried with their own previous response and validation error as
explicit recovery feedback. This extra prompt is saved and hashed. If a complete
layout already exists, recovery only rebuilds locally, with no API calls. All
automatic success checks still apply: an invalid plan, overflow, compilation error,
empty PDF text or missing scientific figures leaves the recovery marked failed.
This is a separate recovery condition; it does not change the first-attempt result.

Each invocation makes at most one recovery attempt per unfinished original run.
Run the command again only when you intend to make another recovery attempt.
It stops on exhausted gateway budget or the configured spend cap. Generation and
recovery use an advisory lock to avoid concurrent writes. Unrecorded output folders
from an interrupted process must be resolved before starting another recovery.

Records and reports:

- `data/latex/recovery_attempts.csv`: one row per recovery, linked to its original
  and parent run; success/failure reason, detailed error, checkpoint use, timestamps,
  new input/output/total tokens, new cost and cumulative totals.
- `outputs/latex/<new_run_id>/recovery_attempt.json`: the attempt audit, including
  baseline/cumulative token counters and status; `run.log` has processing details.
- `results/latex/completion_attempts.csv`: original and recovery attempt history.
- `results/latex/completion_by_poster.csv`: first-attempt success, success on a later
  attempt or final failure, failure history, checkpoint runs and total tokens/cost.
- `results/latex/completion_summary.md` and `.json`: overall completion and usage totals.

Recovery CSV token/cost fields count **only new usage**. `detail_log.json` remains
cumulative for checkpoint accounting, so do not add its totals across recovery
folders. The summary adds original usage plus recovery increments exactly once.
If an interrupted recovery folder was deleted, the next recovery falls back to the
latest surviving archive for that original run. Its parent still references the
interrupted attempt; `checkpoint_source` and `checkpoint_fallback_reason` identify
the older archive used. Recorded usage and interrupted-attempt history are retained.
Missing cost data is reported as unknown; a request interrupted before the provider
returns usage can be undercounted. Human visual review remains a separate check.
Dry-run records/reports use the corresponding `latex/dry_run/` locations.

### Collecting results for evaluation

```bash
python src/results.py --dry-run       # or without --dry-run for the full run
```

Writes `results/latex[/dry_run]/by_run.csv` (one row per attempt: codebook variables,
failure reason, font scale, and judge and human means once those exist), `by_model.csv`
(per candidate: success rate, latency, tokens, cost, mean scores) and
`posters/<input_paper_id>/<llm_model>.pdf/.png`, links that put all candidates for one
paper side by side. These name the model: team only, never for evaluators.

### After a run: team visual check (OI-7)

The Runner sets `workflow_success` from the automatic checks only. For every successful row, a team member opens the LaTeX poster PNG/PDF and fills `visual_check` in `runs.csv` with `pass`, or with `E_TRUNCATED` / `E_OVERFLOW` / `E_NO_FIGURES`. For a failure, also set `workflow_success` to 0 and copy the code into `failure_reason`. Log each manual edit (protocol §7).

### Judging the LaTeX posters

The judges score the LaTeX PDF, never the PPTX. From `harness/`, with credentials loaded:

```bash
python judge/reference_sheet.py       # once per paper: papers/<id>.reference.json (commit these)
python src/blinder.py --dry-run       # poster codes, blinded PDFs/text, judge manifest (drop --dry-run for the full run)
python judge/judge.py --dry-run       # both judges -> data/latex/dry_run/judge_scores.csv
```

**Finishing the main judging after the budget stop (2026-11-02).** The run stops at the first "budget exceeded" error. Run the same command again once the key has budget. It skips posters already scored and re-calls only the failed tasks of the others. Tasks that already succeeded are reused from `judge_raw/`.

```bash
python judge/judge.py --data-dir data/latex/remaining_p01_p15 --manifest data/latex/judge_manifest.csv --main-only
```

Judging order: per judge and repeat, papers come in seeded random order and each paper's
posters in seeded random order within its block, so GPT-4o's automatic prompt cache reuses the
paper text (`claims_verify`) and reference sheet (`coverage`) across that paper's posters
(cache reads cost half; Gemini reported no cache use). Every call still judges one poster.
`tokens_cached` in `judge_scores.csv` records the cached prompt tokens, and `src/results.py`
prices them at the cache-read price. Score files from before this change keep their columns.

The output caps are set per judge in `judges.models`: Gemini 32,768 (its thinking counts toward the cap, and 8,192 truncated 14 claim checks) and GPT-4o 16,384.

The blind key goes to `data/private/` (gitignored). With a reference sheet each poster costs about 35,000 tokens per judge (P01: GPT-4o 26,408 in / 7,909 out; Gemini 20,710 / 17,231); the sheet itself costs about 28,000 tokens once per paper. How to fill human scores, check reference sheets, run the pilot and revise the prompts: [`judge/README.md`](judge/README.md) and [`spec/08_llm_judge.md`](../spec/08_llm_judge.md).

### Analysing the model replacement

After the judges have scored the main posters (the blind key must be in `data/private/latex/`):

```bash
python analysis/build_dataset.py      # one row per paper x model -> results/latex/analysis/dataset.csv
python analysis/analyze.py            # main comparison (12 papers) -> results/latex/analysis/report.md
python analysis/analyze.py --split calibration   # P06, P11, P13, e.g. next to human scores
```

`dataset.csv` counts each poster from its used run: the first attempt in `data/latex/runs.csv`
if it succeeded, otherwise its recovery in `data/latex/recovery_attempts.csv` (`from_recovery`).
Latency, tokens and cost are summed over every attempt of a poster, since a recovery reuses
the earlier paper summary. `data/runs.csv` (old PPTX workflow) is not used.
Hallucination is `halluc_pct`, the % of the poster's claims unsupported (limit < 5%).
`report.md` holds the gate (GR-1 to GR-4 per score source), success rates, requirement
intervals, model comparisons, descriptive statistics, exploratory SPC and the limitations;
the CSVs and `figures/` sit next to it. Methods: [`spec/05_analysis_spec.md`](../spec/05_analysis_spec.md).
If a judge has scored the posters with more than one prompt version, pin one with
`--judge-prompt JUDGE=SHA256`. These files name the models: team only.

## Validation

Run `python -m unittest discover -s tests` for offline workflow checks.
Run `python judge/tests/test_offline.py` for the judge and pilot-agreement checks (fake gateway, no key).
Run `python analysis/tests/test_analysis.py` for the analysis pipeline (synthetic data with known answers).
Offline checks cover one-call planning, invalid figure references, checkpoint
isolation/restoration, resumed preparation, zero-credential rebuilds and failure
handling. A new gateway pilot is still required to measure v2 token use and quality.
