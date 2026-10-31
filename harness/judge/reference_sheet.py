"""Reference sheets: what each checklist item is in each paper (OI-20), with no person in the loop.

The coverage and quality judges compare a poster against a short sheet instead of the
whole paper. Each sheet is made once per paper and reused for every poster and every
future model swap:
  1. Each model in reference_sheets.models (the two judges) drafts the sheet from the full
     paper: a short value per checklist item plus one sentence copied from the paper.
  2. Code checks that every quote really is in the paper (same check as the judges' evidence).
  3. Each model then compares the two drafts item by item. An item is accepted when both
     models call the drafts the same and both quotes are found; it is "na" when both drafts
     say the paper has no such item.
  4. Everything else is "uncertain": the judge sees both drafts and the paper passages
     around the verified quotes, and decides from the paper. These items are also listed
     in data/reference_review.csv; a team member may resolve one by editing the sheet
     (status "accepted" with a value, or "na"), which changes its reference_sha256.

Outputs
  papers/<id>.reference.json                 the sheet (committed with the PDFs)
  data/reference_raw/<id>/<model>__<step>.json   raw drafts and comparisons, for audit
  data/reference_review.csv                  uncertain items, one row each

Usage (from harness/, credentials loaded)
  python judge/reference_sheet.py                 # every paper in papers/ without a sheet
  python judge/reference_sheet.py --papers P01 P02
  python judge/reference_sheet.py --papers P01 --force    # redo an existing sheet
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import (ITEMS, PROMPTS, JudgeClient, load_prompt, norm, paper_text_for,  # noqa: E402
                   quote_found, resolve)

REVIEW_COLUMNS = ["paper_id", "item", "why", "model_a", "value_a", "quote_a_found",
                  "model_b", "value_b", "quote_b_found", "compare_reasons"]


def reference_prompt_sha256() -> str:
    h = hashlib.sha256()
    for f in sorted((PROMPTS / "reference").glob("*.md")):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def excerpt(paper_text: str, quotes: list[str], chars: int) -> str:
    """The paper paragraph best matching each quote, with its neighbours, up to `chars` each."""
    paras = [p for p in re.split(r"\n\s*\n", paper_text) if p.strip()]
    words = [set(norm(p).split()) for p in paras]
    picked: list[int] = []
    for q in quotes:
        qw = norm(q).split()
        if not qw or not paras:
            continue
        best = max(range(len(paras)), key=lambda i: sum(w in words[i] for w in qw))
        for i in (best - 1, best, best + 1):
            if 0 <= i < len(paras) and i not in picked:
                picked.append(i)
    out, budget = [], chars * max(len(quotes), 1)
    for i in sorted(picked):
        text = paras[i].strip()
        if budget <= 0:
            break
        out.append(text[:budget])
        budget -= len(text)
    return "\n\n".join(out)


def read_draft(data: dict | None, paper_text: str) -> dict | None:
    """Normalize one model's draft; None if it doesn't have the expected shape."""
    if not data or not isinstance(data.get("items"), dict):
        return None
    items = {}
    for i in ITEMS:
        e = data["items"].get(i)
        e = e if isinstance(e, dict) else {}
        value = str(e.get("value") or "").strip() or None
        quote = str(e.get("paper_quote") or "").strip() or None
        items[i] = {"value": value, "paper_quote": quote, "reason": str(e.get("reason") or ""),
                    "quote_found": bool(quote and quote_found(quote, paper_text))}
    return {"summary": str(data.get("summary") or "").strip(), "items": items}


def save_raw(raw_dir: Path, model: str, step: str, res, prompt_sha: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{model.replace('/', '_')}__{step}.json").write_text(json.dumps(
        {"model": model, "reference_prompt_sha256": prompt_sha, "error": res.error,
         "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "parsed": res.data, "raw": res.raw},
        indent=2, ensure_ascii=False))


def build_sheet(pid: str, clients: list[JudgeClient], cfg: dict, paths: dict) -> tuple[dict, list[dict], int]:
    paper_text = paper_text_for(pid, paths["papers"], paths["paper_text"])[:cfg.get("paper_char_limit", 400_000)]
    raw_dir = paths["raw"] / pid
    tokens = 0

    drafts = []
    for jc in clients:
        res = jc.ask(load_prompt("reference/draft", paper_text=paper_text))
        save_raw(raw_dir, jc.model, "draft", res, paths["prompt_sha"])
        tokens += res.tokens_in + res.tokens_out
        d = read_draft(res.data, paper_text)
        if d is None:
            print(f"    {jc.model}: draft unusable ({res.error or 'wrong shape'})")
        drafts.append(d)
    a, b = drafts

    both = [i for i in ITEMS if a and b and a["items"][i]["value"] and b["items"][i]["value"]]
    same: dict[str, list[bool | None]] = {i: [] for i in both}
    reasons: dict[str, list[str]] = {i: [] for i in both}
    if both:
        pairs = "\n".join(f"{i}:\n  A: {a['items'][i]['value']}\n  B: {b['items'][i]['value']}" for i in both)
        for jc in clients:
            res = jc.ask(load_prompt("reference/compare", pairs=pairs))
            save_raw(raw_dir, jc.model, "compare", res, paths["prompt_sha"])
            tokens += res.tokens_in + res.tokens_out
            verdicts = (res.data or {}).get("items")
            verdicts = verdicts if isinstance(verdicts, dict) else {}
            for i in both:
                v = verdicts.get(i) if isinstance(verdicts.get(i), dict) else {}
                same[i].append(v.get("same") if isinstance(v.get("same"), bool) else None)
                reasons[i].append(f"{jc.model}: {v.get('reason', 'no answer')}")

    items, review = {}, []
    for i in ITEMS:
        da = a["items"][i] if a else None
        db = b["items"][i] if b else None
        drafts_i = [dict(d, model=jc.model) for d, jc in zip((da, db), clients) if d is not None]
        if da and db and not da["value"] and not db["value"]:
            items[i] = {"status": "na", "drafts": drafts_i}
            continue
        if i in same and all(x is True for x in same[i]) and da["quote_found"] and db["quote_found"]:
            items[i] = {"status": "accepted", "value": da["value"], "paper_quote": da["paper_quote"],
                        "drafts": drafts_i}
            continue
        why = []
        if not (da and db):
            why.append("a draft is missing")
        elif not (da["value"] and db["value"]):
            why.append("one draft says the item does not apply")
        elif not all(x is True for x in same[i]):
            why.append("drafts differ")
        why += [f"quote not found ({d['model']})" for d in drafts_i if d["value"] and not d["quote_found"]]
        verified = [d["paper_quote"] for d in drafts_i if d["quote_found"]]
        items[i] = {"status": "uncertain", "why": "; ".join(why), "drafts": drafts_i,
                    "paper_excerpt": excerpt(paper_text, verified, cfg.get("excerpt_chars", 2500))}
        review.append({"paper_id": pid, "item": i, "why": items[i]["why"],
                       "model_a": clients[0].model, "value_a": (da or {}).get("value"),
                       "quote_a_found": (da or {}).get("quote_found"),
                       "model_b": clients[1].model, "value_b": (db or {}).get("value"),
                       "quote_b_found": (db or {}).get("quote_found"),
                       "compare_reasons": " | ".join(reasons.get(i, []))})

    sheet = {
        "paper_id": pid,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": [jc.model for jc in clients],
        "reference_prompt_sha256": paths["prompt_sha"],
        "paper_text_sha256": hashlib.sha256(paper_text.encode()).hexdigest(),
        "summary": (a or b or {}).get("summary", ""),
        "items": items,
    }
    return sheet, review, tokens


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiment.yaml")
    ap.add_argument("--papers", nargs="+", help="paper IDs; default every PDF in --papers-dir")
    ap.add_argument("--papers-dir", default="papers")
    ap.add_argument("--paper-text-dir", default="data/paper_text")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--force", action="store_true", help="redo papers that already have a sheet")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(open(resolve(args.config)))
    rcfg = {**cfg.get("judge_settings", {}), **cfg.get("reference_sheets", {}),
            "max_transport_retries": cfg["gateway"].get("max_transport_retries", 2)}
    models = rcfg.get("models") or [m["id"] for m in cfg["judges"]["models"]]
    if len(models) != 2:
        sys.exit(f"reference_sheets.models needs exactly two models, got {models}")
    candidates = {c["id"] for c in cfg["candidates"]}
    if candidates & set(models):
        sys.exit(f"{sorted(candidates & set(models))} is a candidate; a candidate must not write the reference")

    papers_dir = resolve(args.papers_dir)
    pids = args.papers or sorted(p.stem for p in papers_dir.glob("*.pdf"))
    data = resolve(args.data_dir)
    paths = {"papers": papers_dir, "paper_text": resolve(args.paper_text_dir), "raw": data / "reference_raw",
             "prompt_sha": reference_prompt_sha256()}

    if client is None:
        from openai import OpenAI
        g = cfg["gateway"]
        client = OpenAI(base_url=os.environ[g["base_url_env"]], api_key=os.environ[g["api_key_env"]],
                        timeout=g.get("timeout_s", 600))
    clients = [JudgeClient(client, m, rcfg, system="reference/system") for m in models]

    review_path = data / "reference_review.csv"
    review = []
    if review_path.exists():
        with review_path.open(newline="") as f:
            review = list(csv.DictReader(f))
    for pid in pids:
        out = papers_dir / f"{pid}.reference.json"
        if out.exists() and not args.force:
            continue
        print(f"[{pid}] drafting with {' + '.join(models)}", flush=True)
        sheet, rows, tokens = build_sheet(pid, clients, rcfg, paths)
        out.write_text(json.dumps(sheet, indent=2, ensure_ascii=False) + "\n")
        review = [r for r in review if r["paper_id"] != pid] + rows
        counts = {s: sum(e["status"] == s for e in sheet["items"].values()) for s in ("accepted", "na", "uncertain")}
        print(f"    {counts}  tokens {tokens}", flush=True)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        with review_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
            w.writeheader()
            w.writerows(review)


if __name__ == "__main__":
    main()
