"""Runner: one Paper2Poster attempt per (model, paper, attempt), logged to runs.csv.

Implements component 1 of spec/02_architecture.md. Each attempt is a separate
preparation process followed by local LaTeX rendering. Only `llm_model`
changes between runs. No vision critic or PPTX generation is executed.

Usage (from harness/):
    python src/runner.py --dry-run           # 1 paper x all candidates -> data/latex/dry_run/
    python src/runner.py --estimate          # scale dry-run cost/latency to the full run
    python src/runner.py                     # full run -> data/latex/runs.csv, outputs/latex/<run_id>/
    python src/runner.py --models gpt-5.6-sol --papers P01 P02   # subset
    python src/runner.py --rebuild outputs/latex/1   # saved results; no API calls

Order: papers in sorted ID order; within each paper the selected models run in a seeded
random order (model_order, experiment.seed). Re-running resumes: (model, paper, attempt)
triples already in the runs file are skipped. Failed attempts are kept as data (FR-7) and are not retried on resume.

workflow_success here covers the automatic checks only (E_API, E_PIPELINE, E_LATEX,
E_OVERFLOW, E_UNREADABLE, E_NO_FIGURES). The team fills `visual_check` afterwards (OI-7).

Workflows (fixed.paper2poster.workflow):
  latex-only-v2      parser summaries typeset as written (judged results in data/latex/)
  latex-painter-v3   adds figure-crop regrowth, the Painter call (short poster text) and, only
                     when a poster still overflows at min_font_scale, one shortening call.
                     Results go to the run set named by fixed.paper2poster.run_set.

latency is the processing time of the attempt: every try plus the local LaTeX build,
excluding the back-off waits between tries. token_usage and generation_cost count
every model call of every try (detail_log.json is cumulative). No judge model is ever
called here; judging is a separate step (judge/judge.py).
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import datetime as dt
import functools
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from poster_naming import poster_stem
from latex_poster import configure_tex_path
import poster_painter

HARNESS = Path(__file__).resolve().parent.parent

RUN_COLUMNS = [
    "run_id", "run_order", "batch_id", "llm_model", "input_paper_id", "attempt",
    "prompt_sha256", "p2p_commit", "p2p_patch_sha256", "config_sha256", "vision_model", "temperature", "seed",
    "started_at", "finished_at", "latency",
    "input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens",
    "vision_input_tokens", "vision_output_tokens", "token_usage",
    "generation_cost", "gateway_cost", "vision_cost", "price_table_as_of",
    "retries", "workflow_success", "failure_reason", "visual_check",
    "poster_path", "poster_word_count",
]

# Signs of a gateway/transport problem in Paper2Poster's output (OpenAI SDK
# exception names and HTTP codes). Anything else non-zero is E_PIPELINE.
TRANSPORT_ERRORS = re.compile(
    r"APIConnectionError|APITimeoutError|RateLimitError|InternalServerError"
    r"|Error code: (?:429|5\d\d)|ReadTimeout|ConnectTimeout"
    r"|Connection (?:reset|refused|aborted)"
)
PAPER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
BACKOFF_S = 30
SAME_AS_CANDIDATE = "same_as_candidate"
WORKFLOWS = ("latex-only-v2", "latex-painter-v3")
HBOX_TOLERANCE_PT = 10.0  # same as latex_poster.HBOX_TOLERANCE_PT


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else HARNESS / path


def run_set(cfg: dict) -> str:
    """Folder name under data/, outputs/ and results/ for this workflow's attempts."""
    return cfg["fixed"]["paper2poster"].get("run_set") or "latex"


def painter_settings(cfg: dict) -> dict | None:
    p2c = cfg["fixed"]["paper2poster"]
    return (p2c.get("painter") or {}) if p2c.get("workflow") == "latex-painter-v3" else None


def repair_factor(fit: dict) -> float:
    """Share of the current words to keep so the measured overflow disappears.

    Assumes text is about 60% of a column's usable height (85% of the page), and keeps
    a 10-point margin; never cuts more than half or less than a tenth.
    """
    page = fit.get("page_height_pt") or 2600.0
    cut = fit.get("overflow_pt", 0.0) / (0.6 * 0.85 * page) + 0.10
    return round(min(0.9, max(0.5, 1.0 - cut)), 2)


def vision_for(model: str, p2c: dict) -> str:
    """Vision (critic) model for a candidate: the candidate itself, or one fixed model (OI-1)."""
    v = p2c["vision_model"]
    return model if v == SAME_AS_CANDIDATE else v


def config_sha256(cfg: dict) -> str:
    """Hash of the `fixed` section only, so adding a candidate keeps it stable."""
    return hashlib.sha256(yaml.safe_dump(cfg["fixed"], sort_keys=True).encode()).hexdigest()


def prompt_sha256(p2p: Path) -> str:
    """Hash of Paper2Poster's agent prompts and style defaults (the "fixed prompt")."""
    files = (sorted((p2p / "utils" / "prompt_templates").glob("*.yaml"))
             + sorted((p2p / "utils" / "prompts").glob("*.txt"))
             + [p2p / "config" / "poster.yaml"])
    h = hashlib.sha256()
    for f in files:
        h.update(str(f.relative_to(p2p)).encode())
        h.update(f.read_bytes())
    h.update((HARNESS / "src/combined_planner.py").read_bytes())
    h.update((HARNESS / "src/preparation_cache.py").read_bytes())
    h.update((HARNESS / "src/latex_prepare.py").read_bytes())
    h.update((HARNESS / "src/latex_poster.py").read_bytes())
    h.update((HARNESS / "src/poster_painter.py").read_bytes())
    h.update((HARNESS / "src/figure_crops.py").read_bytes())
    h.update((HARNESS / "src/gateway_chat.py").read_bytes())
    h.update((HARNESS / "src/paper_parser.py").read_bytes())
    return h.hexdigest()


def _output(cmd: list[str], cwd: Path | None = None) -> str:
    """stdout of a version/status command; '' if it is unavailable."""
    try:
        with subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as p:
            return p.communicate(timeout=120)[0] or ""
    except (OSError, subprocess.SubprocessError):
        return ""


@functools.lru_cache(maxsize=4)
def environment_record(p2p_python: str) -> dict:
    """Everything outside the code and config that can change a poster, recorded per run.

    Package lists are hashed (the full lists are in config/*.lock.txt for Paper2Poster);
    the TeX and Poppler versions and the harness commit (with uncommitted files) are named.
    """
    def first_line(cmd):
        text = _output(cmd)
        return text.strip().splitlines()[0] if text.strip() else ""
    def freeze(python):
        listing = _output([python, "-m", "pip", "freeze", "--all"])
        pick = {line.split("==")[0].lower(): line for line in listing.splitlines() if "==" in line}
        return {"sha256": hashlib.sha256(listing.encode()).hexdigest(),
                "key_packages": [pick[p] for p in ("openai", "docling", "docling-core", "pillow", "numpy",
                                                   "json-repair", "pyyaml") if p in pick]}
    status = _output(["git", "status", "--porcelain"], cwd=HARNESS)
    return {
        "harness_commit": _output(["git", "rev-parse", "HEAD"], cwd=HARNESS).strip(),
        "harness_uncommitted_files": sorted(line[3:] for line in status.splitlines()),
        "harness_source_sha256": {str(f.relative_to(HARNESS)): hashlib.sha256(f.read_bytes()).hexdigest()
                                  for f in sorted((HARNESS / "src").glob("*.py"))},
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "harness_python": {"version": platform.python_version(), **freeze(sys.executable)},
        "paper2poster_python": {"version": _output([p2p_python, "-c", "import platform; print(platform.python_version())"]).strip(),
                                **freeze(p2p_python)},
        "xelatex": first_line(["xelatex", "--version"]),
        "pdftoppm": (_output(["pdftoppm", "-v"]) or "").strip().splitlines()[0:1],
    }


def model_order(models: list[str], seed, paper_id: str) -> list[str]:
    """The candidates for one paper in a seeded random order (paper-major generation).

    All four models run on a paper before the next paper, so drift on the gateway over the
    batch hits every model alike; the order within each paper is random, so no model is
    always first or last (the earlier fixed configuration order was a listed limitation).
    Depends only on experiment.seed and the paper ID, so a resumed batch keeps its order.
    """
    order = sorted(models)
    random.Random(f"{seed}-{paper_id}-models").shuffle(order)
    return order


def check_p2p_commit(p2p: Path, expected: str, patch: Path | None) -> tuple[str, str]:
    """Return (HEAD, patch sha256) of the Paper2Poster checkout.

    Exit unless it is the pinned commit with exactly the configured patch applied
    (applied here if the checkout is clean), or no changes at all if there is no patch.
    """
    # Pin every git setting that changes `git diff` output, so the comparison with the
    # patch file doesn't depend on the user's git config.
    git = ["git", "-C", str(p2p), "-c", "color.ui=never", "-c", "diff.noprefix=false",
           "-c", "diff.mnemonicPrefix=false", "-c", "diff.algorithm=myers", "-c", "core.autocrlf=false"]
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if head != expected:
        sys.exit(f"Paper2Poster is at {head}, config pins {expected}. Run: git -C {p2p} checkout {expected}")
    diff = lambda: subprocess.run(git + ["diff", "--no-ext-diff", "--unified=3", "--inter-hunk-context=0",
                                         "--indent-heuristic", "--src-prefix=a/", "--dst-prefix=b/"],
                                  capture_output=True, text=True, check=True).stdout
    want = patch.read_text() if patch else ""
    if patch and diff() == "":
        subprocess.run(git + ["apply", str(patch)], check=True)
    if diff() != want:
        sys.exit(f"Paper2Poster checkout has local changes other than {patch or 'none'} "
                 f"(scope rule: no pipeline edits). Inspect with: git -C {p2p} diff")
    return head, hashlib.sha256(want.encode()).hexdigest() if patch else ""


def list_papers(papers_dir: Path) -> list[tuple[str, Path]]:
    papers = []
    for pdf in sorted(papers_dir.glob("*.pdf")):
        if not PAPER_ID.match(pdf.stem):
            sys.exit(f"Bad paper file name {pdf.name}: use <input_paper_id>.pdf with letters, digits, _ or -")
        papers.append((pdf.stem, pdf))
    return papers


def read_runs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_run(path: Path, row: dict) -> None:
    """Append in the file's own column order (older runs files keep their header)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    columns = RUN_COLUMNS
    if not new:
        with open(path, newline="") as f:
            columns = next(csv.reader(f), RUN_COLUMNS)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow({k: "" if row.get(k) is None else row.get(k) for k in columns})


def acquire_run_lock(data_dir: Path):
    """Keep one generation/recovery writer per run set."""
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = (data_dir / '.runner.lock').open('a')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError('Another generation/recovery command is using this run set')
    return handle


def load_prices(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, ""
    p = yaml.safe_load(open(path)) or {}
    return p.get("models") or {}, str(p.get("as_of") or "")


def token_cost(prices: dict, model: str, tin, tout, cached=0, written=0):
    """USD from per-million-token list prices; None if tokens or prices are missing.

    tin counts every prompt token. Of these, `cached` were read from the prompt cache and
    `written` were written to it; they are priced at the gateway's cache-read and
    cache-write prices (the gateway charges GPT-5.6 cache writes on most input tokens,
    checked 2026-11-12). Without cache prices they cost the plain input price.
    """
    pr = prices.get(model) or {}
    pin, pout = pr.get("input_per_mtok"), pr.get("output_per_mtok")
    if tin is None or tout is None or pin is None or pout is None:
        return None
    cached, written = cached or 0, written or 0
    pread = pr.get("cache_read_per_mtok") if pr.get("cache_read_per_mtok") is not None else pin
    pwrite = pr.get("cache_write_per_mtok") if pr.get("cache_write_per_mtok") is not None else pin
    plain = tin - cached - written
    return round((plain * pin + cached * pread + written * pwrite + tout * pout) / 1e6, 6)


def run_cost(row: dict) -> float:
    return sum(float(row[k]) for k in ("generation_cost", "vision_cost") if row.get(k) not in (None, ""))


FIGURE = re.compile(r"\\includegraphics\[[^\]]*\]\{figures/")


def has_figure(run_dir: Path) -> bool:
    """At least one figure or table image from the paper is placed (logos excluded)."""
    tex = run_dir / "latex" / "poster.tex"
    return tex.exists() and bool(FIGURE.search(tex.read_text(errors="replace")))


def poster_text(pdf_path: Path) -> str:
    """Extract the delivered PDF text for scoring."""
    return subprocess.run(["pdftotext", str(pdf_path), "-"],
                          capture_output=True, text=True, check=True).stdout


def read_tokens(out_dir: Path) -> dict:
    """Token totals summed from detail_log.json's per-step `<step>_{in,out}_{t,v}` counts.

    log.json's text totals are wrong at the pinned commit: new_pipeline.py adds the
    outline step's tokens again where it should add the content step's, so the
    content step (most of the text tokens) is missing.
    """
    detail = out_dir / "detail_log.json"
    if not detail.exists():
        return {}
    d = json.loads(detail.read_text())
    def total(suffix):
        return sum(v for k, v in d.items() if k.endswith(suffix) and isinstance(v, (int, float)))
    tin, tout = total("_in_t"), total("_out_t")
    tokens = {"input_tokens": tin, "output_tokens": tout,
              "cached_tokens": total("_cached_t"), "cache_write_tokens": total("_cachewrite_t"),
              "vision_input_tokens": total("_in_v"), "vision_output_tokens": total("_out_v"),
              "token_usage": tin + tout + total("_in_v") + total("_out_v")}
    if any(k.endswith("_cost_usd") for k in d):  # gateway_chat calls: cost the gateway charged
        tokens["gateway_cost"] = round(total("_cost_usd"), 6)
    return tokens


def budget_exhausted(log_text: str) -> bool:
    return "ExceededBudget" in log_text or "budget_exceeded" in log_text


def prompt_cache_flag(cfg: dict, model: str) -> list[str]:
    """--prompt_cache for models whose gateway route needs explicit cache markers."""
    return ["--prompt_cache"] if model in (cfg["fixed"]["paper2poster"].get("prompt_cache_models") or []) else []


def render_saved(run_dir: Path, cfg: dict) -> tuple[dict, str]:
    """Render only archived intermediate files. This function makes no model calls."""
    config_path = run_dir / "render_config.yaml"
    config_path.write_text(yaml.safe_dump(cfg))
    cmd = [sys.executable, str(HARNESS / "src/latex_poster.py"), str(run_dir),
           "--config", str(config_path)]
    with open(run_dir / "run.log", "a") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                       timeout=cfg["fixed"]["paper2poster"].get("timeout_s", 3600), check=True)
    fit = json.loads((run_dir / "latex/fit.json").read_text())
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    pdf_path = run_dir / "latex" / f"{poster_stem(metadata['input_paper_id'], metadata['llm_model'])}.pdf"
    text = poster_text(pdf_path) if fit['fits'] else ''
    if text:
        (run_dir / "poster_text.txt").write_text(text)
    return fit, text


def rebuild_saved(run_dir: Path, config_path: Path | None = None) -> dict:
    """Rebuild locally, preserving the original experiment row and generation usage."""
    if not run_dir.is_dir():
        raise ValueError(f"Run directory not found: {run_dir}")
    saved_config = run_dir / "run_config.yaml"
    config_path = config_path or (saved_config if saved_config.exists() else resolve("config/experiment.yaml"))
    cfg = yaml.safe_load(config_path.read_text())
    # Older runs identify their paper/model via the legacy runs.csv.
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise ValueError(f"Missing run metadata: {metadata_path}; use latex_poster.py for legacy exports")
    result = {"api_tokens_used": 0, "rebuilt_at": now_utc(), "workflow_success": 0}
    try:
        fit, text = render_saved(run_dir, cfg)
        result.update(fit=fit, poster_word_count=len(text.split()))
        if not fit['fits']:
            result['failure_reason'] = 'E_OVERFLOW'
        elif not text.strip():
            result['failure_reason'] = 'E_UNREADABLE'
        elif not has_figure(run_dir):
            result['failure_reason'] = 'E_NO_FIGURES'
        else:
            result['workflow_success'] = 1
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        result.update(failure_reason='E_LATEX', error=str(exc))
    (run_dir / "rebuild_result.json").write_text(json.dumps(result, indent=2))
    return result


def run_attempt(*, run_id: int, model: str, paper_id: str, pdf: Path, cfg: dict,
                out_root: Path, env: dict, planning_feedback: Path | None = None) -> dict:
    """Run one Paper2Poster attempt. Never raises on model/pipeline failure."""
    p2c = cfg["fixed"]["paper2poster"]
    p2p = resolve(p2c["path"])
    vision = vision_for(model, p2c)
    max_retries = cfg["gateway"].get("max_transport_retries", 2)

    staged = p2p / "harness_input" / paper_id
    staged.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, staged / "paper.pdf")
    poster_rel = f"harness_input/{paper_id}/paper.pdf"
    tmp_rel = f"tmp/run_{run_id}"
    cmd = [str(resolve(p2c["python"])), str(HARNESS / "src/latex_prepare.py"),
           f"--poster_path={poster_rel}", f"--model_name_t={model}", f"--model_name_v={vision}",
           f"--tmp_dir={tmp_rel}",
           f"--poster_width_inches={p2c['poster_width_inches']}",
           f"--poster_height_inches={p2c['poster_height_inches']}",
           f"--max_parse_attempts={p2c.get('max_parse_attempts', 2)}",
           f"--seed={cfg['fixed'].get('generation', {}).get('seed') or 0}"]
    cmd += [str(a) for a in p2c.get("extra_args") or []]
    if planning_feedback:
        cmd.append(f"--planning_feedback={planning_feedback}")
    painter = painter_settings(cfg)
    if painter is not None:
        cmd.append(f"--painter_settings={json.dumps(painter, sort_keys=True)}")
        cmd += prompt_cache_flag(cfg, model)

    out_dir = out_root / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = poster_stem(paper_id, model)
    (out_dir / "run_metadata.json").write_text(json.dumps(
        {"input_paper_id": paper_id, "llm_model": model, "workflow": p2c.get("workflow", "latex-only-v2")}, indent=2))
    max_parse = p2c.get("max_parse_attempts", 2)
    log_path = out_dir / "run.log"
    cmd.append(f"--usage_path={out_dir / 'detail_log.json'}")
    cmd.append(f"--checkpoint_dir={out_dir / 'preparation'}")
    cmd.append(f"--intermediate_dir={out_dir / 'intermediate'}")
    (out_dir / "run_config.yaml").write_text(yaml.safe_dump(cfg))
    (out_dir / "environment.json").write_text(json.dumps(environment_record(str(resolve(p2c["python"]))), indent=2))

    row = {"retries": 0, "workflow_success": 0}
    busy = 0.0  # seconds spent working, summed over tries; back-off waits excluded
    for attempt_try in range(max_retries + 1):
        row.setdefault("started_at", now_utc())
        t0 = time.monotonic()
        with open(log_path, "a") as log:
            log.write(f"=== try {attempt_try + 1} {row['started_at']}\n$ {' '.join(cmd)}\n")
            log.flush()
            try:
                rc = subprocess.run(cmd, cwd=p2p, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=p2c.get("timeout_s", 3600)).returncode
            except subprocess.TimeoutExpired:
                rc = None
                log.write("\n=== harness: attempt timed out\n")
        busy += time.monotonic() - t0
        row["latency"] = round(busy, 2)
        row["finished_at"] = now_utc()
        if rc == 0:
            break
        this_try = log_path.read_text(errors="replace").rsplit("=== try ", 1)[-1]
        if budget_exhausted(this_try):
            row["failure_reason"] = "E_BUDGET"
            break
        transport = rc is not None and bool(TRANSPORT_ERRORS.search(this_try))
        if transport and attempt_try < max_retries:
            row["retries"] += 1
            time.sleep(BACKOFF_S * 2 ** attempt_try)
            continue
        row["failure_reason"] = "E_API" if transport else "E_PIPELINE"
        break

    shutil.rmtree(p2p / tmp_rel, ignore_errors=True)

    row.update(read_tokens(out_dir))

    if row.get("failure_reason"):
        return row

    pdf_path = out_dir / "latex" / f"{name}.pdf"
    t0 = time.monotonic()

    def render():
        try:
            return render_saved(out_dir, cfg)
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            with open(log_path, "a") as log:
                log.write(f"\n=== harness: LaTeX rendering/text extraction failed: {e!r}\n")
            return None, ""
    fit, text = render()
    painted = out_dir / "intermediate" / "painted_content.json"

    def painter_call(mode: list[str], note: str) -> int | None:
        """One Painter follow-up call (poster_painter.py) from the Paper2Poster directory.
        Returns its exit code (None on timeout); E_BUDGET is recorded in row."""
        cmd = [str(resolve(p2c["python"])), str(HARNESS / "src/poster_painter.py"), *mode,
               f"--intermediate_dir={out_dir / 'intermediate'}", f"--usage_path={out_dir / 'detail_log.json'}",
               f"--model_name_t={model}", f"--max_attempts={max_parse}",
               f"--settings={json.dumps(painter, sort_keys=True)}", *prompt_cache_flag(cfg, model)]
        with open(log_path, "a") as log:
            log.write(f"\n=== harness: {note}\n$ {' '.join(cmd)}\n")
            log.flush()
            try:
                rc = subprocess.run(cmd, cwd=p2p, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=p2c.get("timeout_s", 3600)).returncode
            except subprocess.TimeoutExpired:
                rc = None
        row.update(read_tokens(out_dir))
        if budget_exhausted(log_path.read_text(errors="replace").rsplit(f"=== harness: {note}", 1)[-1]):
            row["failure_reason"] = "E_BUDGET"
        return rc

    if (fit is not None and not fit["fits"] and painter is not None and painted.exists()
            and painter.get("overflow_repair_calls", 1) > 0
            and fit.get("hbox_overflow_pt", 0.0) <= HBOX_TOLERANCE_PT):
        # The Commenter's "overflow": the poster overflows even at min_font_scale, so ask the
        # same model once to shorten its text, then render again. Never cut text locally.
        factor = repair_factor(fit)
        rc = painter_call(["--repair", f"--factor={factor}"],
                          f"overflow {fit['overflow_pt']}pt at scale {fit['scale']}; shortening call "
                          f"(keep {factor:.0%} of words)")
        if row.get("failure_reason"):
            row["latency"], row["finished_at"] = round(busy + time.monotonic() - t0, 2), now_utc()
            return row
        if rc == 0:
            fit, text = render()

    if (fit is not None and fit["fits"] and painter is not None and painted.exists()
            and painter.get("blank_fill_calls", 1) > 0):
        # The Commenter's "too much blank space": one call lengthens the sections of columns
        # that end far above the page bottom. Kept only if the poster still fits at the same or
        # a larger font; otherwise the earlier text is restored, so this never causes a cutoff.
        targets = poster_painter.expansion_targets(fit, json.loads(painted.read_text()), painter)
        if targets:
            before = fit
            rc = painter_call(["--expand", f"--targets={json.dumps(targets, ensure_ascii=False)}"],
                              f"blank space {before['layout']['column_gap_pt']}pt per column; expansion call "
                              f"for {len(targets)} section(s)")
            if row.get("failure_reason"):
                row["latency"], row["finished_at"] = round(busy + time.monotonic() - t0, 2), now_utc()
                return row
            if rc == 0:
                fit, text = render()
                kept = fit is not None and fit["fits"] and fit["scale"] >= before["scale"] - 1e-9
                with open(log_path, "a") as log:
                    log.write(f"=== harness: expansion {'kept' if kept else 'reverted'}: scale "
                              f"{before['scale']} -> {fit and fit['scale']}, fits {fit and fit['fits']}\n")
                if not kept:
                    backup = out_dir / "intermediate" / "painted_content.before_expand.json"
                    shutil.copyfile(backup, painted)
                    fit, text = render()
    row["latency"] = round(busy + time.monotonic() - t0, 2)
    row["finished_at"] = now_utc()
    if fit is None:
        row["failure_reason"] = "E_LATEX"
        return row
    if not fit["fits"]:
        row["failure_reason"] = "E_OVERFLOW"
        return row
    if fit.get("missing_glyphs"):  # a character no poster font has: kept visible for the team check
        with open(log_path, "a") as log:
            log.write(f"\n=== harness: WARNING characters missing from the fonts: {fit['missing_glyphs']}\n")
    (out_dir / "poster_text.txt").write_text(text)
    words = len(text.split())
    if words == 0:
        row["failure_reason"] = "E_UNREADABLE"
        return row
    if not has_figure(out_dir):
        row["failure_reason"] = "E_NO_FIGURES"
        return row

    row.update(workflow_success=1, poster_path=str(pdf_path.relative_to(HARNESS)), poster_word_count=words)
    return row


def estimate(cfg: dict) -> None:
    """Scale mean dry-run cost and latency per model to the full run (NFR-5)."""
    dry = HARNESS / "data" / run_set(cfg) / "dry_run" / "runs.csv"
    rows = [r for r in read_runs(dry) if r["workflow_success"] == "1"]
    if not rows:
        sys.exit(f"No successful dry-run attempts in {dry.relative_to(HARNESS)}. Run --dry-run first.")
    n = cfg["fixed"]["n_papers"] * cfg["fixed"].get("attempts_per_pair", 1)
    total, missing = 0.0, []
    print(f"{'model':40} {'cost/poster':>12} {'latency/poster':>15} {'full run cost':>14}")
    for c in cfg["candidates"]:
        mr = [r for r in rows if r["llm_model"] == c["id"]]
        if not mr:
            print(f"{c['id']:40} {'no successful dry run':>43}")
            missing.append(c["id"])
            continue
        if any(r["generation_cost"] == "" for r in mr):
            missing.append(c["id"])
        cost = sum(run_cost(r) for r in mr) / len(mr)
        lat = sum(float(r["latency"]) for r in mr) / len(mr)
        total += cost * n
        print(f"{c['id']:40} {cost:12.4f} {lat / 60:12.1f} min {cost * n:14.2f}")
    print(f"\nEstimated full-run cost ({n} attempts per model): ${total:.2f}")
    if missing:
        print(f"Incomplete (no dry run or no prices in prices.yaml): {', '.join(missing)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="configuration (saved run configuration is used for --rebuild)")
    ap.add_argument("--rebuild", nargs="+", metavar="RUN_DIR",
                    help="rebuild saved LaTeX locally; no credentials or API calls")
    ap.add_argument("--dry-run", action="store_true", help="first paper only; results go to data/latex/dry_run/")
    ap.add_argument("--estimate", action="store_true", help="estimate full-run cost from the dry run, then exit")
    ap.add_argument("--models", nargs="+", help="subset of candidate IDs")
    ap.add_argument("--papers", nargs="+", help="subset of input_paper_ids")
    recovery = ap.add_mutually_exclusive_group()
    recovery.add_argument("--retry-failed", action="store_true",
                          help="retry each unfinished poster once from its own checkpoints; preserve original rows")
    recovery.add_argument("--summary", action="store_true",
                          help="write initial/recovery outcomes and token/cost totals; no API calls")
    args = ap.parse_args()

    if args.retry_failed or args.summary:
        if args.rebuild or args.estimate:
            ap.error("--retry-failed/--summary cannot be combined with --rebuild/--estimate")
        from recovery import recover_batch, write_summary
        if args.summary:
            write_summary(HARNESS, dry_run=args.dry_run, papers=args.papers, models=args.models,
                          config_path=resolve(args.config) if args.config else None)
        else:
            recover_batch(HARNESS, dry_run=args.dry_run, papers=args.papers,
                          models=args.models, config_path=resolve(args.config) if args.config else None)
        return

    if args.rebuild:
        failed = False
        for directory in args.rebuild:
            result = rebuild_saved(resolve(directory), resolve(args.config) if args.config else None)
            print(f"{directory}: {json.dumps(result)}")
            failed |= not result['workflow_success']
        if failed:
            sys.exit("Some local rebuilds failed; see rebuild_result.json and run.log.")
        return
    cfg = yaml.safe_load(open(resolve(args.config or "config/experiment.yaml")))
    run_lock = acquire_run_lock(HARNESS / 'data' / run_set(cfg) / ('dry_run' if args.dry_run else ''))
    if args.estimate:
        return estimate(cfg)

    fixed, p2c, g = cfg["fixed"], cfg["fixed"]["paper2poster"], cfg["gateway"]
    if p2c.get("workflow") not in WORKFLOWS:
        sys.exit(f"Set fixed.paper2poster.workflow to one of {', '.join(WORKFLOWS)}.")
    if p2c["workflow"] == "latex-painter-v3" and run_set(cfg) == "latex":
        sys.exit("latex-painter-v3 needs its own fixed.paper2poster.run_set (data/latex holds the v2 results).")
    configure_tex_path()
    for executable in ("xelatex", "pdftoppm", "pdftotext"):
        if not shutil.which(executable):
            sys.exit(f"Missing {executable}; add your TeX Live/TinyTeX and Poppler binaries to PATH before running.")
    if p2c.get("vision_model") in (None, "", "TBD"):
        sys.exit(f"Set fixed.paper2poster.vision_model in the config: a gateway ID or {SAME_AS_CANDIDATE} (OI-1).")
    logo = p2c.get("institution_logo_path")
    if logo == "TBD":
        sys.exit("Set fixed.paper2poster.institution_logo_path to a logo file, or null to omit the logo (OI-18).")
    if logo and not resolve(logo).is_file():
        sys.exit(f"Logo file not found: {resolve(logo)}")
    base_url, api_key = os.environ.get(g["base_url_env"]), os.environ.get(g["api_key_env"])
    if not base_url or not api_key:
        sys.exit(f"Set {g['base_url_env']} and {g['api_key_env']} first.")
    # camel's OpenAICompatibleModel reads the COMPATIBILIY variables (its spelling) but then
    # builds the client from the unset constructor args, so the OpenAI SDK falls back to
    # OPENAI_API_KEY / OPENAI_BASE_URL. Set both pairs.
    env = dict(os.environ,
               OPENAI_COMPATIBILIY_API_KEY=api_key,
               OPENAI_COMPATIBILIY_API_BASE_URL=base_url,
               OPENAI_API_KEY=api_key,
               OPENAI_BASE_URL=base_url)
    # First-run model downloads (docling, EasyOCR): Hugging Face's Xet transfer timed out
    # on slow networks; plain HTTP with a longer timeout didn't. Users can still override.
    env.setdefault("HF_HUB_DISABLE_XET", "1")
    env.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    temperature = fixed.get("generation", {}).get("temperature")
    if (p2c.get("max_output_tokens") or temperature is not None) and not p2c.get("patch"):
        sys.exit("max_output_tokens and generation.temperature need the generation-params patch (OI-17).")
    if p2c.get("max_output_tokens"):
        env["P2P_MAX_OUTPUT_TOKENS"] = str(p2c["max_output_tokens"])  # read by the patch
    if temperature is not None:
        env["P2P_TEMPERATURE"] = str(temperature)  # read by the patch

    p2p = resolve(p2c["path"])
    commit, patch_sha = check_p2p_commit(p2p, p2c["commit"], resolve(p2c["patch"]) if p2c.get("patch") else None)
    hashes = {"prompt_sha256": prompt_sha256(p2p), "p2p_commit": commit, "p2p_patch_sha256": patch_sha,
              "config_sha256": config_sha256(cfg)}

    papers = list_papers(resolve(fixed["papers_dir"]))
    if not papers:
        sys.exit(f"No PDFs in {fixed['papers_dir']}")
    if not args.dry_run and not args.papers and len(papers) != fixed["n_papers"]:
        sys.exit(f"Found {len(papers)} papers, config expects {fixed['n_papers']} (DR-7).")
    order = {pid: i + 1 for i, (pid, _) in enumerate(papers)}  # run_order, same for every model
    if args.papers:
        unknown = set(args.papers) - set(order)
        if unknown:
            sys.exit(f"Unknown paper IDs: {sorted(unknown)}")
        papers = [p for p in papers if p[0] in args.papers]
    if args.dry_run:
        papers = papers[:1]

    models = [c["id"] for c in cfg["candidates"]]
    if args.models:
        unknown = set(args.models) - set(models)
        if unknown:
            sys.exit(f"Not in config candidates: {sorted(unknown)}")
        models = [m for m in models if m in args.models]

    data_dir = HARNESS / "data" / run_set(cfg) / ("dry_run" if args.dry_run else "")
    runs_path = data_dir / "runs.csv"
    out_root = HARNESS / "outputs" / run_set(cfg) / ("dry_run" if args.dry_run else "")
    prices, as_of = load_prices(resolve(fixed.get("prices_file", "config/prices.yaml")))
    cap = cfg["experiment"].get("spend_cap_usd")
    batch_size = cfg.get("spc", {}).get("p_chart_batch_size", 5)

    runs = read_runs(runs_path)
    for r in runs:
        if (r["p2p_commit"] != commit or r["prompt_sha256"] != hashes["prompt_sha256"]
                or r.get("p2p_patch_sha256", "") != patch_sha
                or r.get("config_sha256") != hashes["config_sha256"]):
            sys.exit(f"{runs_path} has run {r['run_id']} from a different commit, patch, prompts or fixed configuration (DR-6).")
    done = {(r["llm_model"], r["input_paper_id"], int(r["attempt"])) for r in runs}
    output_ids = [int(p.name) for p in out_root.iterdir() if p.name.isdigit() and p.is_dir()] if out_root.exists() else []
    next_id = max([int(r["run_id"]) for r in runs] + output_ids, default=0) + 1
    spent = sum(run_cost(r) for r in runs + read_runs(data_dir / 'recovery_attempts.csv'))
    if cap is not None and any(not (prices.get(m) or {}).get("input_per_mtok") for m in models):
        print("WARNING: spend_cap_usd is set but prices.yaml is incomplete; the cap can't count those models.")

    seed = cfg["experiment"].get("seed", 0)
    for paper_id, pdf in papers:
        if len(models) > 1:
            print(f"{paper_id}: model order {', '.join(model_order(models, seed, paper_id))}", flush=True)
        for model in model_order(models, seed, paper_id):
            for attempt in range(1, fixed.get("attempts_per_pair", 1) + 1):
                if (model, paper_id, attempt) in done:
                    continue
                if cap is not None and spent >= cap:
                    sys.exit(f"Spend cap reached: ${spent:.2f} >= ${cap} (NFR-5). Stopping.")
                vision = vision_for(model, p2c)
                print(f"[run {next_id}] {model} × {paper_id} (attempt {attempt}) ...", flush=True)
                row = run_attempt(run_id=next_id, model=model, paper_id=paper_id, pdf=pdf,
                                  cfg=cfg, out_root=out_root, env=env)
                row.update(hashes, run_id=next_id, run_order=order[paper_id],
                           batch_id=math.ceil(order[paper_id] / batch_size),
                           llm_model=model, input_paper_id=paper_id, attempt=attempt,
                           vision_model="",
                           temperature=fixed.get("generation", {}).get("temperature"),
                           seed=fixed.get("generation", {}).get("seed"),
                           generation_cost=token_cost(prices, model, row.get("input_tokens"), row.get("output_tokens"),
                                                      row.get("cached_tokens"), row.get("cache_write_tokens")),
                           vision_cost=token_cost(prices, vision,
                                                  row.get("vision_input_tokens"), row.get("vision_output_tokens")),
                           price_table_as_of=as_of)
                append_run(runs_path, row)
                spent += run_cost(row)
                status = "ok" if row["workflow_success"] else row["failure_reason"]
                print(f"[run {next_id}] {status}  {row['latency']}s  tokens={row.get('token_usage')}", flush=True)
                if row.get("failure_reason") == "E_BUDGET":
                    sys.exit("Gateway budget exhausted. Attempt saved; batch stopped.")
                next_id += 1
    run_lock.close()


if __name__ == "__main__":
    main()
