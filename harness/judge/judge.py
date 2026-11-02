"""LLM-as-judge runner for the Paper2Poster replacement harness.

For every blinded poster, each judge model runs four calls:
  1. coverage        (poster image + poster text + paper reference)  -> 9 checklist labels
  2. claims_extract  (poster text)                                    -> atomic claims
  3. claims_verify   (claims + full paper text)                       -> supported / unsupported / contradicted
  4. quality         (poster image + paper reference)                 -> 3 criteria + holistic 1-5

Outputs (under data/latex/, or data/latex/dry_run/ with --dry-run)
  judge_scores.csv              one row per (poster_code, judge_model, judge_repeat, judge_prompt_sha256)
  judge_raw/<code>/<judge>__r<k>__<task>.json   raw prompt + response, for audit
  judge_images/<code>.png       the image both judges see

Inputs
  judge_manifest.csv            written by src/blinder.py; must NOT contain llm_model
  papers/<id>.pdf               source paper; its text is extracted once with pdftotext
                                into data/paper_text/<id>.txt (or put a cleaner <id>.txt there)
  papers/<id>.reference.json    reference sheet from judge/reference_sheet.py (recommended)

Usage (from harness/)
  python judge/judge.py --dry-run                     # every poster in the dry-run manifest
  python judge/judge.py --only-codes P-7K3Q,P-2M9X    # subset (e.g. the pilot set)
  python judge/judge.py --repeats 2                   # test-retest on the pilot

Editing anything in judge/prompts/ changes judge_prompt_sha256: earlier rows are kept,
and the new prompt version is scored as fresh rows instead of being skipped on resume.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
PROMPTS = HERE / "prompts"

ITEMS = [
    "chk_problem", "chk_method", "chk_data", "chk_setup", "chk_primary_result",
    "chk_secondary_result", "chk_baseline", "chk_conclusion", "chk_limitation",
]
ITEM_LABELS = {"accurate": 1, "wrong": 0, "missing": 0, "na": None}
CLAIM_LABELS = {"supported", "unsupported", "contradicted"}

OUT_COLUMNS = (
    ["poster_code", "judge_model", "judge_repeat", "judge_prompt_sha256", "input_paper_id"]
    + ITEMS
    + ["coverage_pct",
       "n_claims_total", "n_claims_unsupported", "n_claims_contradicted",
       "poster_word_count", "halluc_per1k", "flagged_claims",
       "quality_score", "quality_layout", "quality_readability", "quality_fidelity",
       "parse_ok", "failed_tasks", "evidence_found_rate", "paper_truncated", "reference_sha256",
       "latency_s", "tokens_in", "tokens_out", "judged_at"]
)


# --------------------------------------------------------------------------- utilities

def resolve(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else HARNESS / path


def prompt_sha256() -> str:
    """SHA-256 over every judge prompt file, sorted by name (the frozen rubric)."""
    h = hashlib.sha256()
    for f in sorted(PROMPTS.glob("*.md")):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def load_prompt(name: str, **values: str) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def norm(s: str) -> str:
    # NFKC turns PDF ligatures (ﬁ, ﬂ) back into letters before anything is stripped.
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)  # words hyphenated across a line break
    s = s.replace("–", "-").replace("—", "-").replace("’", "'").replace("−", "-")
    return re.sub(r"[^a-z0-9%.\-' ]+", " ", re.sub(r"\s+", " ", s)).strip()


def quote_found(quote: str, source: str) -> bool:
    """True if a judge's quote is really in the source (exact after normalizing,
    or >= 80% of its words appear in order-insensitive overlap for long quotes)."""
    q, s = norm(quote), norm(source)
    if not q:
        return False
    if q in s:
        return True
    words = q.split()
    if len(words) < 6:
        return False
    s_words = set(s.split())
    return sum(w in s_words for w in words) / len(words) >= 0.8


def parse_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (handles ``` fences and stray prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
        start = text.find("{")
        depth = 0
        for i in range(start, len(text)) if start >= 0 else []:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    data = json.loads(text[start:i + 1])
                    break
    if not isinstance(data, dict):
        raise ValueError("no JSON object found")
    return data


def render_poster(poster_path: Path, out: Path, max_px: int) -> Path:
    """Write a PNG of the poster to `out` (cached). PDF -> PNG with pdftoppm, long side
    max_px; PPTX goes through LibreOffice first. Rendering to an image also drops file
    metadata that could reveal the generating model."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    suffix = poster_path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        shutil.copy(poster_path, out)
        return out
    with tempfile.TemporaryDirectory() as tmp:
        pdf = poster_path
        if suffix in (".pptx", ".ppt", ".odp", ".html"):
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(poster_path)],
                           check=True, capture_output=True, timeout=300)
            pdf = Path(tmp) / (poster_path.stem + ".pdf")
        elif suffix != ".pdf":
            raise ValueError(f"unsupported poster format: {suffix}")
        stem = Path(tmp) / "poster"
        subprocess.run(["pdftoppm", "-png", "-singlefile", "-f", "1", "-l", "1",
                        "-scale-to", str(max_px), str(pdf), str(stem)],
                       check=True, capture_output=True, timeout=300)
        shutil.move(str(stem) + ".png", out)
    return out


CANVAS_GRID = (12, 9)     # columns x rows; a 48 x 36 in poster gives 4 x 4 in cells
CANVAS_INK = 0.004        # a cell with less than this share of non-background pixels is blank


def canvas_map(png: Path) -> tuple[float, list[str]]:
    """Share of the poster left blank, and a coarse map of it ('#' content, '.' blank).

    Judges miss large unused areas in a downscaled poster, so the quality prompt is given
    this measurement. Background is the most common grey level; a pixel is ink when it
    differs from it by more than 24 of 255. Same rule for every poster, no model involved."""
    import numpy as np
    from PIL import Image
    with Image.open(png) as im:
        a = np.asarray(im.convert("L"), dtype=np.int16)
    ink = np.abs(a - np.bincount(a.ravel()).argmax()) > 24
    (h, w), (cols, rows) = a.shape, CANVAS_GRID
    lines = ["".join("#" if ink[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols].mean() >= CANVAS_INK
                     else "." for c in range(cols)) for r in range(rows)]
    return sum(l.count(".") for l in lines) / (cols * rows), lines


def paper_text_for(pid: str, papers: Path, text_dir: Path) -> str:
    """Full paper text: data/paper_text/<id>.txt, extracted from papers/<id>.pdf on first use."""
    txt = text_dir / f"{pid}.txt"
    if not txt.exists():
        pdf = papers / f"{pid}.pdf"
        if not pdf.exists():
            sys.exit(f"Neither {txt} nor {pdf} exists")
        text_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(txt)], check=True, capture_output=True)
    return txt.read_text(encoding="utf-8", errors="ignore")


def image_part(png: Path) -> dict:
    b64 = base64.b64encode(png.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


REFERENCE_STATUSES = {"accepted", "na", "uncertain"}


def check_reference(ref: dict, path: Path) -> None:
    """A sheet from judge/reference_sheet.py, possibly hand-resolved: every item needs a status."""
    items = ref.get("items") if isinstance(ref.get("items"), dict) else {}
    bad = [i for i in ITEMS if (items.get(i) or {}).get("status") not in REFERENCE_STATUSES
           or (items[i]["status"] == "accepted" and not items[i].get("value"))]
    if bad:
        sys.exit(f"{path}: items {bad} need status accepted (with a value), na, or uncertain")


def reference_text(ref: dict | None, paper_text: str, fallback_chars: int, excerpts: bool = True) -> str:
    """The reference block of the coverage and quality prompts. Quality judges fidelity from
    the summary and item values, so it gets no paper excerpts (excerpts=False)."""
    if not ref:
        return ("No reference sheet is available. Use the paper text below:\n<<<\n"
                + paper_text[:fallback_chars] + "\n>>>")
    lines = [f"Summary: {ref['summary']}"] if ref.get("summary") else []
    need_paper = False
    for item in ITEMS:
        e = ref["items"][item]
        if e["status"] == "accepted":
            lines.append(f"- {item}: {e['value']}")
        elif e["status"] == "na":
            lines.append(f"- {item}: not applicable")
        else:
            drafts = " / ".join(f"({chr(97 + k)}) {d.get('value') or 'not applicable'}"
                                for k, d in enumerate(e.get("drafts", [])))
            lines.append(f"- {item}: UNCERTAIN: {drafts}")
            if not excerpts:
                continue
            if e.get("paper_excerpt"):
                lines.append(f"  Paper text for {item}:\n  <<<\n{e['paper_excerpt']}\n  >>>")
            else:
                need_paper = True
    if need_paper:
        lines.append("Paper text (for UNCERTAIN items without their own excerpt):\n<<<\n"
                     + paper_text[:fallback_chars] + "\n>>>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- model calls

@dataclass
class CallResult:
    data: dict | None
    raw: str
    latency: float
    tokens_in: int
    tokens_out: int
    error: str | None = None


class JudgeClient:
    def __init__(self, client, model: str, cfg: dict, system: str = "system"):
        self.client = client
        self.model = model
        self.temperature = cfg.get("temperature", 0)
        self.max_tokens = cfg.get("max_output_tokens", 8192)
        self.transport_retries = cfg.get("max_transport_retries", 2)
        self.system = load_prompt(system)

    def _create(self, messages):
        delay = 5
        for attempt in range(self.transport_retries + 1):
            try:
                return self.client.chat.completions.create(
                    model=self.model, messages=messages,
                    temperature=self.temperature, max_tokens=self.max_tokens)
            except Exception as e:  # timeouts, 429, 5xx
                if attempt == self.transport_retries or "budget_exceeded" in str(e):
                    raise
                print(f"    transport error ({e}); retry in {delay}s", file=sys.stderr)
                time.sleep(delay)
                delay *= 3

    def ask(self, prompt: str, images: list[Path] | None = None) -> CallResult:
        content = [{"type": "text", "text": prompt}] + [image_part(p) for p in images or []]
        if not images:
            content = prompt
        messages = [{"role": "system", "content": self.system},
                    {"role": "user", "content": content}]
        t0, tin, tout, raw, err = time.time(), 0, 0, "", None
        for attempt in range(2):  # one repair attempt for invalid JSON
            try:
                r = self._create(messages)
            except Exception as e:
                return CallResult(None, raw, time.time() - t0, tin, tout, f"transport: {e}")
            raw = r.choices[0].message.content or ""
            if r.usage:
                tin += r.usage.prompt_tokens or 0
                tout += r.usage.completion_tokens or 0
            if getattr(r.choices[0], "finish_reason", None) == "length":
                # Cut off at max_output_tokens: a repair turn would be cut off too.
                return CallResult(None, raw, time.time() - t0, tin, tout,
                                  f"truncated at max_output_tokens={self.max_tokens}")
            try:
                return CallResult(parse_json(raw), raw, time.time() - t0, tin, tout)
            except Exception as e:
                err = f"parse: {e}"
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "That was not a single valid JSON object. "
                                                "Return only the JSON object, matching the schema."}]
        return CallResult(None, raw, time.time() - t0, tin, tout, err)


# --------------------------------------------------------------------------- tasks

def task_coverage(j: JudgeClient, png, poster_text, ref_text, ref):
    res = j.ask(load_prompt("coverage", reference=ref_text, poster_text=poster_text), [png])
    out, quotes = {}, []
    if res.data:
        items = res.data.get("items")
        items = items if isinstance(items, dict) else {}
        for item in ITEMS:
            entry = items.get(item)
            entry = entry if isinstance(entry, dict) else {}
            label = str(entry.get("label", "")).lower().strip()
            if label not in ITEM_LABELS:
                res.error = res.error or f"bad label for {item}: {label!r}"
                out[item] = 0
                continue
            status = ref["items"][item]["status"] if ref else None
            # Whether an item applies is a fact about the paper, not the poster: a settled
            # reference item decides it, so judge and human denominators match.
            if status == "na":
                out[item] = None
                continue
            if status == "accepted" and label == "na":
                label = "missing"
            out[item] = ITEM_LABELS[label]
            if label in ("accurate", "wrong") and entry.get("poster_evidence"):
                quotes.append(str(entry["poster_evidence"]))
    return res, out, quotes


def task_claims(j: JudgeClient, poster_text, paper_text, batch_size):
    ext = j.ask(load_prompt("claims_extract", poster_text=poster_text))
    if not ext.data:
        return ext, [], None
    claims = [c for c in ext.data.get("claims", []) if isinstance(c, dict) and str(c.get("text", "")).strip()]
    for i, c in enumerate(claims, 1):
        c["id"] = i
    verdicts, results = {}, [ext]
    for start in range(0, len(claims), batch_size):
        batch = claims[start:start + batch_size]
        # Numbered 1..n within each batch: models renumber later batches from 1 anyway.
        listing = "\n".join(f'{k}. {c["text"]}' for k, c in enumerate(batch, 1))
        ver = j.ask(load_prompt("claims_verify", paper_text=paper_text, claims=listing))
        results.append(ver)
        for v in (ver.data or {}).get("verdicts", []):
            try:
                k = int(v["id"])
            except (TypeError, KeyError, ValueError):
                continue
            if 1 <= k <= len(batch) and str(v.get("label", "")).lower() in CLAIM_LABELS:
                verdicts[batch[k - 1]["id"]] = v
    for c in claims:
        v = verdicts.get(c["id"])
        c["label"] = v["label"].lower() if v else None
        c["paper_evidence"] = (v or {}).get("paper_evidence", "")
        c["reason"] = (v or {}).get("reason", "")
    merged = CallResult(
        data={"claims": claims}, raw=json.dumps([r.raw for r in results], ensure_ascii=False),
        latency=sum(r.latency for r in results),
        tokens_in=sum(r.tokens_in for r in results), tokens_out=sum(r.tokens_out for r in results),
        error=next((r.error for r in results if r.error), None)
              or (f"{sum(c['label'] is None for c in claims)} claims without verdict"
                  if any(c["label"] is None for c in claims) else None))
    return merged, claims, ext


def task_quality(j: JudgeClient, png, ref_text, size_in):
    blank, lines = canvas_map(png)
    res = j.ask(load_prompt("quality", reference=ref_text,
                            width_in=f"{size_in[0]:g}", height_in=f"{size_in[1]:g}",
                            canvas_map="\n".join(lines), blank_pct=f"{100 * blank:.0f}",
                            cell_in=f"{size_in[0] / CANVAS_GRID[0]:g} × {size_in[1] / CANVAS_GRID[1]:g}"), [png])
    out = {}
    if res.data:
        for key, col in [("holistic", "quality_score"), ("layout", "quality_layout"),
                         ("readability", "quality_readability"), ("fidelity", "quality_fidelity")]:
            try:
                s = int((res.data.get(key) or {}).get("score"))
                out[col] = s if 1 <= s <= 5 else None
            except (TypeError, ValueError, AttributeError):
                out[col] = None
        if out.get("quality_score") is None:
            res.error = res.error or "missing holistic score"
    return res, out


# --------------------------------------------------------------------------- per poster

def judge_poster(j: JudgeClient, row: dict, repeat: int, cfg: dict, paths: dict) -> dict:
    code, pid = row["poster_code"], row["input_paper_id"]
    raw_dir = paths["raw"] / code
    raw_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{j.model.replace('/', '_')}__r{repeat}"

    poster_text = resolve(row["poster_text_path"]).read_text(encoding="utf-8", errors="ignore")
    paper_text = paper_text_for(pid, paths["papers"], paths["paper_text"])
    limit = cfg.get("paper_char_limit", 400_000)
    truncated = int(len(paper_text) > limit)
    paper_text = paper_text[:limit]
    ref_path = paths["papers"] / f"{pid}.reference.json"
    ref = json.loads(ref_path.read_text()) if ref_path.exists() else None
    if ref is not None:
        check_reference(ref, ref_path)
    fallback = cfg.get("reference_fallback_chars", 100_000)
    ref_text = reference_text(ref, paper_text, fallback)
    # Cached by poster_code: every LaTeX run names its file the same way, so a stem-keyed
    # cache would hand later posters the first poster's image.
    png = render_poster(resolve(row["poster_path"]), paths["images"] / f"{code}.png", cfg.get("max_image_px", 2000))
    words = int(row.get("poster_word_count") or len(poster_text.split()))

    cov_res, cov, cov_quotes = task_coverage(j, png, poster_text, ref_text, ref)
    clm_res, claims, _ = task_claims(j, poster_text, paper_text, cfg.get("claims_batch_size", 40))
    q_res, qual = task_quality(j, png, reference_text(ref, paper_text, fallback, excerpts=bool(not ref)),
                               cfg["poster_size_in"])

    for name, res in [("coverage", cov_res), ("claims", clm_res), ("quality", q_res)]:
        (raw_dir / f"{tag}__{name}.json").write_text(json.dumps(
            {"model": j.model, "repeat": repeat, "judge_prompt_sha256": paths["prompt_sha"],
             "error": res.error, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
             "parsed": res.data, "raw": res.raw},
            indent=2, ensure_ascii=False))

    # evidence check: do the judge's quotes actually exist in the poster / paper?
    checks = [quote_found(q, poster_text) for q in cov_quotes]
    for c in claims:
        if c.get("poster_quote"):
            checks.append(quote_found(str(c["poster_quote"]), poster_text))
        if c.get("label") in ("supported", "contradicted") and c.get("paper_evidence"):
            checks.append(quote_found(str(c["paper_evidence"]), paper_text))

    applicable = [cov[i] for i in ITEMS if cov.get(i) is not None] if cov else []
    verified = [c for c in claims if c.get("label")]
    unsup = [c for c in verified if c["label"] == "unsupported"]
    contra = [c for c in verified if c["label"] == "contradicted"]
    flagged = [{"text": c["text"], "label": c["label"], "reason": c.get("reason", "")} for c in unsup + contra]
    failed = [n for n, r in [("coverage", cov_res), ("claims", clm_res), ("quality", q_res)] if r.error]
    # A claims task with any batch failed or any claim unverdicted is an incomplete audit:
    # its counts would read as "0 unsupported", so they stay blank (flagged_claims keeps what was found).
    claims_ok = bool(clm_res.data) and not clm_res.error

    out = {
        "poster_code": code, "judge_model": j.model, "judge_repeat": repeat,
        "judge_prompt_sha256": paths["prompt_sha"], "input_paper_id": pid,
        **{i: ("NA" if cov.get(i, "x") is None else cov.get(i, "")) for i in ITEMS},
        "coverage_pct": round(100 * sum(applicable) / len(applicable), 2) if applicable else "",
        "n_claims_total": len(verified) if claims_ok else "",
        "n_claims_unsupported": len(unsup) + len(contra) if claims_ok else "",
        "n_claims_contradicted": len(contra) if claims_ok else "",
        "poster_word_count": words,
        "halluc_per1k": round(1000 * (len(unsup) + len(contra)) / words, 3) if claims_ok and words else "",
        "flagged_claims": json.dumps(flagged, ensure_ascii=False),
        **{k: ("" if qual.get(k) is None else qual[k]) for k in
           ["quality_score", "quality_layout", "quality_readability", "quality_fidelity"]},
        "parse_ok": int(not failed),
        "failed_tasks": ";".join(failed),
        "evidence_found_rate": round(sum(checks) / len(checks), 3) if checks else "",
        "paper_truncated": truncated,
        "reference_sha256": hashlib.sha256(ref_path.read_bytes()).hexdigest() if ref is not None else "",
        "latency_s": round(cov_res.latency + clm_res.latency + q_res.latency, 2),
        "tokens_in": cov_res.tokens_in + clm_res.tokens_in + q_res.tokens_in,
        "tokens_out": cov_res.tokens_out + clm_res.tokens_out + q_res.tokens_out,
        "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return out


# --------------------------------------------------------------------------- main

def already_done(out_csv: Path) -> set:
    if not out_csv.exists():
        return set()
    with out_csv.open() as f:
        return {(r["poster_code"], r["judge_model"], int(r["judge_repeat"]), r["judge_prompt_sha256"])
                for r in csv.DictReader(f) if r.get("parse_ok") == "1"}


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiment.yaml")
    ap.add_argument("--dry-run", action="store_true", help="use the dry-run blinding under data/latex/dry_run/")
    ap.add_argument("--data-dir", help="default data/latex, or data/latex/dry_run with --dry-run")
    ap.add_argument("--manifest", help="default <data-dir>/judge_manifest.csv")
    ap.add_argument("--papers", default="papers")
    ap.add_argument("--paper-text-dir", default="data/paper_text")
    ap.add_argument("--out", help="default <data-dir>/judge_scores.csv")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only-codes", default="")
    ap.add_argument("--judges", default="", help="comma list; default = all judges in config")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(open(resolve(args.config)))
    p2c = cfg["fixed"]["paper2poster"]
    jcfg = {**cfg.get("judge_settings", {}),
            "max_transport_retries": cfg["gateway"].get("max_transport_retries", 2),
            "poster_size_in": (p2c["poster_width_inches"], p2c["poster_height_inches"])}
    judges = [m["id"] for m in cfg["judges"]["models"]]
    if args.judges:
        judges = [x.strip() for x in args.judges.split(",")]

    data = resolve(args.data_dir or ("data/latex/dry_run" if args.dry_run else "data/latex"))
    manifest = resolve(args.manifest) if args.manifest else data / "judge_manifest.csv"
    out_csv = resolve(args.out) if args.out else data / "judge_scores.csv"
    with open(manifest) as f:
        rows = list(csv.DictReader(f))
    if "llm_model" in (rows[0].keys() if rows else []):
        sys.exit("Manifest contains llm_model. Judges must be blind: remove that column.")
    if args.only_codes:
        keep = {c.strip() for c in args.only_codes.split(",")}
        rows = [r for r in rows if r["poster_code"] in keep]

    if client is None:
        from openai import OpenAI
        g = cfg["gateway"]
        client = OpenAI(base_url=os.environ[g["base_url_env"]], api_key=os.environ[g["api_key_env"]],
                        timeout=g.get("timeout_s", 600))

    paths = {"papers": resolve(args.papers), "paper_text": resolve(args.paper_text_dir),
             "raw": data / "judge_raw", "images": data / "judge_images", "prompt_sha": prompt_sha256()}
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if out_csv.exists():
        with out_csv.open() as f:
            header = next(csv.reader(f), [])
        if header != OUT_COLUMNS:
            sys.exit(f"{out_csv} has different columns (written by an older judge.py); move it aside.")
    done = already_done(out_csv)
    new_file = not out_csv.exists()
    seed = cfg["experiment"].get("seed", 0)
    print(f"judge prompts sha256 {paths['prompt_sha'][:12]}…  ->  {out_csv}")

    with out_csv.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        if new_file:
            w.writeheader()
        for model in judges:
            jc = JudgeClient(client, model, jcfg)
            for rep in range(1, args.repeats + 1):
                order = rows[:]
                random.Random(f"{seed}-{model}-{rep}").shuffle(order)  # randomized presentation order
                for k, row in enumerate(order, 1):
                    key = (row["poster_code"], model, rep, paths["prompt_sha"])
                    if key in done:
                        continue
                    print(f"[{model} r{rep}] {k}/{len(order)} {row['poster_code']}", flush=True)
                    rec = judge_poster(jc, row, rep, jcfg, paths)
                    w.writerow(rec)
                    f.flush()
                    print(f"    coverage {rec['coverage_pct']}%  halluc/1k {rec['halluc_per1k']}  "
                          f"quality {rec['quality_score']}  tokens {rec['tokens_in']}+{rec['tokens_out']}", flush=True)
                    if rec["failed_tasks"]:
                        print(f"    failed tasks: {rec['failed_tasks']} (will go to review as PARSE_FAIL)")


if __name__ == "__main__":
    main()
