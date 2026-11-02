"""Offline end-to-end test: fake gateway client, real rendering, real CSV output.

Run:  python judge/tests/test_offline.py   (from harness/)
"""
import csv
import json
import random
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import judge  # noqa: E402
import pilot_agreement  # noqa: E402
import reference_sheet  # noqa: E402

POSTER_TEXT = ("Graph Pruning for Fast Inference. We propose GP, a pruning method for graph neural networks. "
               "We evaluate on the OGB-Products dataset. GP reaches 91.7% accuracy, 2.1 points above the GraphSAGE baseline. "
               "GP cuts inference time by 40%. GP also works on protein graphs. Limitation: tested on one GPU type.")
PAPER_TEXT = ("We propose GP, a pruning method for graph neural networks. Experiments use the OGB-Products dataset "
              "on a single A100 GPU. GP reaches 91.7% accuracy, 2.1 points above the GraphSAGE baseline. "
              "Inference time drops by 35%. A limitation is that we tested on one GPU type.")


class FakeCompletions:
    """Returns plausible JSON per task; first quality call returns broken JSON to test the repair path."""
    def __init__(self):
        self.calls = 0
        self.broke_once = False
        self.drop_verdict = False   # True: verifier skips one claim, as truncated replies do

    def create(self, model, messages, temperature, max_tokens):
        self.calls += 1
        user = messages[1]["content"]
        text = user if isinstance(user, str) else user[0]["text"]
        has_image = not isinstance(user, str) and any(p["type"] == "image_url" for p in user)
        if "KEY-INFORMATION COVERAGE" in text:
            assert has_image and "chk_setup: UNCERTAIN" in text and "single A100 GPU" in text
            # chk_secondary_result is "na" in the reference (forced NA); "na" on chk_limitation,
            # which the reference says applies, must count as missing.
            labels = ["accurate", "accurate", "accurate", "missing", "accurate", "wrong", "accurate", "accurate", "na"]
            body = {"items": {i: {"label": l, "poster_evidence": "GP reaches 91.7% accuracy" if l != "missing" else "",
                                  "reason": "x"} for i, l in zip(judge.ITEMS, labels)}}
        elif "CLAIM EXTRACTION" in text:
            body = {"claims": [
                {"id": 1, "text": "GP is a pruning method for GNNs", "poster_quote": "We propose GP, a pruning method for graph neural networks"},
                {"id": 2, "text": "Evaluated on OGB-Products", "poster_quote": "We evaluate on the OGB-Products dataset"},
                {"id": 3, "text": "GP reaches 91.7% accuracy", "poster_quote": "GP reaches 91.7% accuracy"},
                {"id": 4, "text": "GP cuts inference time by 40%", "poster_quote": "GP cuts inference time by 40%"},
                {"id": 5, "text": "GP works on protein graphs", "poster_quote": "GP also works on protein graphs"},
            ]}
        elif "CLAIM VERIFICATION" in text:
            # Answer each listed claim by its text, numbered 1..n per batch whatever ids were sent
            # (what GPT-4o did on the first real run).
            verdict = {"GP is a pruning method for GNNs": ("supported", "We propose GP, a pruning method for graph neural networks."),
                       "Evaluated on OGB-Products": ("supported", "Experiments use the OGB-Products dataset"),
                       "GP reaches 91.7% accuracy": ("supported", "GP reaches 91.7% accuracy"),
                       "GP cuts inference time by 40%": ("contradicted", "Inference time drops by 35%."),
                       "GP works on protein graphs": ("unsupported", "")}
            listed = re.findall(r"^(\d+)\. (.+)$", text.split("CLAIMS:")[1], flags=re.M)
            body = {"verdicts": [{"id": i, "label": verdict[t][0], "paper_evidence": verdict[t][1]}
                                 for i, (_, t) in enumerate(listed, 1)]}
            if self.drop_verdict and len(body["verdicts"]) > 1:
                body["verdicts"].pop()
        elif "POSTER QUALITY" in text:
            assert has_image and "48 × 36 inches" in text
            if not self.broke_once:
                self.broke_once = True
                return self._resp("Sure! Here is my rating: {layout: 4")
            body = {k: {"score": s, "reason": "x"} for k, s in
                    [("layout", 4), ("readability", 3), ("fidelity", 4), ("holistic", 4)]}
            return self._resp("```json\n" + json.dumps(body) + "\n```")
        else:
            raise AssertionError("unknown task")
        return self._resp(json.dumps(body))

    @staticmethod
    def _resp(content):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200))


def make_pdf(path: Path, shade: int):
    """Image-only PDF poster; every LaTeX run names its file the same, so both test posters do too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (480, 360), (shade, shade, 255))
    ImageDraw.Draw(im).text((20, 20), POSTER_TEXT[:60], fill=(0, 0, 0))
    im.save(path, "PDF", resolution=10)


def test_judge_run(tmp: Path):
    (tmp / "papers").mkdir()
    (tmp / "papers" / "paper01.txt").write_text(PAPER_TEXT)
    ref = {"summary": "GP prunes GNNs for faster inference.",
           "items": {i: {"status": "accepted", "value": "x"} for i in judge.ITEMS}}
    ref["items"]["chk_secondary_result"] = {"status": "na"}
    ref["items"]["chk_setup"] = {"status": "uncertain", "drafts": [{"value": "one A100"}, {"value": "two GPUs"}],
                                 "paper_excerpt": "Experiments use the OGB-Products dataset on a single A100 GPU."}
    (tmp / "papers" / "paper01.reference.json").write_text(json.dumps(ref))
    with open(tmp / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["poster_code", "input_paper_id", "poster_path", "poster_text_path", "poster_word_count"])
        for code, shade in [("P-AAAA", 40), ("P-BBBB", 200)]:
            make_pdf(tmp / code / "poster.pdf", shade)
            (tmp / f"{code}.txt").write_text(POSTER_TEXT)
            w.writerow([code, "paper01", tmp / code / "poster.pdf", tmp / f"{code}.txt", len(POSTER_TEXT.split())])
    cfg = yaml.safe_load((HERE.parent.parent / "spec" / "config.example.yaml").read_text())
    cfg["judge_settings"]["claims_batch_size"] = 2   # 5 claims -> 3 verification batches
    (tmp / "cfg.yaml").write_text(yaml.safe_dump(cfg))

    fake = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    args = ["--config", str(tmp / "cfg.yaml"), "--manifest", str(tmp / "manifest.csv"),
            "--papers", str(tmp / "papers"), "--paper-text-dir", str(tmp / "papers"),
            "--data-dir", str(tmp / "data"), "--repeats", "2"]
    judge.main(args, client=client)
    out = tmp / "data" / "judge_scores.csv"
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 2 * 2 * 2, rows                   # 2 posters x 2 judges x 2 repeats
    r = rows[0]
    print(json.dumps({k: r[k] for k in ["judge_model", "chk_secondary_result", "chk_limitation", "coverage_pct",
                                       "n_claims_total", "n_claims_unsupported", "halluc_per1k", "quality_score",
                                       "parse_ok", "evidence_found_rate"]}, indent=1))
    assert r["chk_setup"] == "0" and r["chk_secondary_result"] == "NA" and r["chk_limitation"] == "0"
    assert float(r["coverage_pct"]) == round(100 * 6 / 8, 2)
    assert r["n_claims_unsupported"] == "2" and r["parse_ok"] == "1" and len(r["reference_sha256"]) == 64
    assert {x["quality_score"] for x in rows} == {"4"}
    assert float(r["evidence_found_rate"]) > 0.9
    a, b = (tmp / "data" / "judge_images" / f"{c}.png" for c in ("P-AAAA", "P-BBBB"))
    assert a.read_bytes() != b.read_bytes(), "posters with the same file name must not share a cached image"
    # resume: a second run must not duplicate rows
    judge.main(args, client=client)
    assert len(list(csv.DictReader(open(out)))) == 8
    # a prompt edit is a new rubric version: scored again as new rows, old rows kept
    real = judge.prompt_sha256
    judge.prompt_sha256 = lambda: "edited"
    try:
        judge.main(args + ["--repeats", "1", "--only-codes", "P-AAAA"], client=client)
    finally:
        judge.prompt_sha256 = real
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 10 and sum(x["judge_prompt_sha256"] == "edited" for x in rows) == 2
    # an incomplete claim audit must leave the counts blank, not report "0 unsupported"
    fake.drop_verdict = True
    judge.prompt_sha256 = lambda: "partial"
    try:
        judge.main(args + ["--repeats", "1", "--only-codes", "P-AAAA"], client=client)
    finally:
        judge.prompt_sha256 = real
        fake.drop_verdict = False
    partial = [x for x in csv.DictReader(open(out)) if x["judge_prompt_sha256"] == "partial"]
    assert len(partial) == 2 and all(x["failed_tasks"] == "claims" and x["parse_ok"] == "0" for x in partial)
    assert all(x[k] == "" for x in partial for k in
               ["n_claims_total", "n_claims_unsupported", "n_claims_contradicted", "halluc_per1k"]), partial
    assert all(x["coverage_pct"] and x["quality_score"] == "4" for x in partial)   # other tasks still count
    print("judge.py offline run: OK  (model calls:", fake.calls, ")")


def test_pilot(tmp: Path):
    """Synthetic pilot: judge A tracks humans closely, judge B is noisy."""
    rng = np.random.default_rng(1)
    codes = [f"P-{i:04d}" for i in range(24)]
    words = {c: int(rng.integers(600, 1200)) for c in codes}
    pd.DataFrame({"poster_code": codes, "poster_word_count": [words[c] for c in codes]}).to_csv(tmp / "man.csv", index=False)
    truth = {c: {"items": (rng.random(9) < rng.uniform(0.6, 1)).astype(int), "unsup": int(rng.poisson(1.5)),
                 "q": int(rng.integers(2, 6))} for c in codes}
    h = []
    for c in codes:
        for e in ["E01", "E02"]:
            items = truth[c]["items"].copy()
            if rng.random() < 0.1:
                items[rng.integers(9)] ^= 1
            h.append({"poster_code": c, "evaluator_id": e, **dict(zip(pilot_agreement.ITEMS, items)),
                      "n_claims_unsupported": max(0, truth[c]["unsup"] + int(rng.integers(-1, 2)) * (rng.random() < .2)),
                      "quality_score": int(np.clip(truth[c]["q"] + (rng.random() < .2) * rng.choice([-1, 1]), 1, 5))})
    pd.DataFrame(h).to_csv(tmp / "human.csv", index=False)
    j = []
    for model, noise in [("judge-good", 0.01), ("judge-noisy", 0.35)]:
        for rep in [1, 2]:
            for c in codes:
                items = truth[c]["items"].copy()
                flip = rng.random(9) < noise
                items[flip] ^= 1
                unsup = max(0, truth[c]["unsup"] + int(rng.normal(0, noise * 6)))
                q = int(np.clip(truth[c]["q"] + round(rng.normal(0, noise * 4)), 1, 5))
                j.append({"poster_code": c, "judge_model": model, "judge_repeat": rep,
                          "judge_prompt_sha256": "v1", "judged_at": "2026-10-31T00:00:00+00:00",
                          **dict(zip(pilot_agreement.ITEMS, items)),
                          "coverage_pct": 100 * items.mean(), "n_claims_total": int(words[c] / 25),
                          "poster_word_count": words[c], "halluc_per1k": 1000 * unsup / words[c],
                          "quality_score": q, "parse_ok": 1, "evidence_found_rate": 0.97})
    pd.DataFrame(j).to_csv(tmp / "judge.csv", index=False)
    cfg = yaml.safe_load((HERE.parent.parent / "spec" / "config.example.yaml").read_text())
    (tmp / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    pilot_agreement.main(["--config", str(tmp / "cfg.yaml"), "--human", str(tmp / "human.csv"),
                          "--judge", str(tmp / "judge.csv"), "--manifest", str(tmp / "man.csv"),
                          "--raw-dir", str(tmp / "raw"), "--blind-key", str(tmp / "no_key.csv"),
                          "--out-dir", str(tmp / "rep")])
    md = (tmp / "rep" / "judge_pilot.md").read_text()
    res = pd.read_csv(tmp / "rep" / "judge_pilot.csv")
    passed = res[res.threshold.notna()].groupby("judge")["pass"].apply(lambda s: (s == True).sum())  # noqa: E712
    assert passed["judge-good"] >= 10 and passed["judge-noisy"] <= 4, passed
    assert "judge-noisy — DO NOT USE" in md, md
    dis = pd.read_csv(tmp / "rep" / "judge_disagreements.csv")
    assert (dis.judge == "judge-noisy").sum() > (dis.judge == "judge-good").sum()
    print("pilot_agreement.py synthetic run: OK")


class FakeReference:
    """Two drafting models: agree on most items, disagree on one, one invented quote,
    both say no conclusion, only one says no limitation."""
    def __init__(self):
        self.calls = 0

    def create(self, model, messages, temperature, max_tokens):
        self.calls += 1
        text = messages[1]["content"]
        assert "careful research assistant" in messages[0]["content"]
        if "REFERENCE SHEET FOR A RESEARCH PAPER" in text:
            q = {"problem": "We propose GP, a pruning method for graph neural networks.",
                 "data": "Experiments use the OGB-Products dataset on a single A100 GPU.",
                 "result": "GP reaches 91.7% accuracy, 2.1 points above the GraphSAGE baseline.",
                 "limit": "A limitation is that we tested on one GPU type."}
            b = model == "openai.gpt-4o"
            items = {
                "chk_problem": ("slow GNN inference", q["problem"]),
                "chk_method": ("GP pruning", q["problem"]),
                "chk_data": ("OGB-Products", "We use the Reddit dataset of social posts." if b else q["data"]),
                "chk_setup": ("single A100 GPU", q["data"]),
                "chk_primary_result": ("35% faster inference" if b else "91.7% accuracy", "Inference time drops by 35%." if b else q["result"]),
                "chk_secondary_result": ("+2.1 points over GraphSAGE", q["result"]),
                "chk_baseline": ("GraphSAGE", q["result"]),
                "chk_conclusion": (None, None),
                "chk_limitation": ((None, None) if b else ("one GPU type", q["limit"])),
            }
            body = {"summary": "GP prunes GNNs.", "items": {
                i: {"value": v, "paper_quote": qq, "reason": "" if v else "not in paper"} for i, (v, qq) in items.items()}}
        elif "COMPARE TWO REFERENCE SHEETS" in text:
            listed = re.findall(r"^(chk_\w+):$", text, flags=re.M)
            body = {"items": {i: {"same": i != "chk_primary_result", "reason": "x"} for i in listed}}
        else:
            raise AssertionError("unknown task")
        return FakeCompletions._resp(json.dumps(body))


def test_reference_sheet(tmp: Path):
    (tmp / "papers").mkdir()
    (tmp / "papers" / "paper01.pdf").write_bytes(b"")          # listed, text supplied below
    (tmp / "text").mkdir()
    (tmp / "text" / "paper01.txt").write_text(PAPER_TEXT)
    cfg = yaml.safe_load((HERE.parent.parent / "spec" / "config.example.yaml").read_text())
    (tmp / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    fake = FakeReference()
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    args = ["--config", str(tmp / "cfg.yaml"), "--papers-dir", str(tmp / "papers"),
            "--paper-text-dir", str(tmp / "text"), "--data-dir", str(tmp / "data")]
    reference_sheet.main(args, client=client)
    sheet = json.loads((tmp / "papers" / "paper01.reference.json").read_text())
    status = {i: e["status"] for i, e in sheet["items"].items()}
    print(json.dumps(status, indent=1))
    assert status == {"chk_problem": "accepted", "chk_method": "accepted", "chk_data": "uncertain",
                      "chk_setup": "accepted", "chk_primary_result": "uncertain",
                      "chk_secondary_result": "accepted", "chk_baseline": "accepted",
                      "chk_conclusion": "na", "chk_limitation": "uncertain"}, status
    assert "quote not found (openai.gpt-4o)" in sheet["items"]["chk_data"]["why"]
    assert "91.7%" in sheet["items"]["chk_primary_result"]["paper_excerpt"]
    assert sheet["items"]["chk_problem"]["value"] == "slow GNN inference"
    judge.check_reference(sheet, Path("sheet"))
    assert judge.reference_text(sheet, PAPER_TEXT, 100).count("UNCERTAIN") == 3
    review = list(csv.DictReader(open(tmp / "data" / "reference_review.csv")))
    assert sorted(r["item"] for r in review) == ["chk_data", "chk_limitation", "chk_primary_result"]
    calls = fake.calls
    reference_sheet.main(args, client=client)                    # existing sheet: skipped
    assert fake.calls == calls
    print("reference_sheet.py offline run: OK  (model calls:", calls, ")")


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    base.mkdir(parents=True, exist_ok=True)
    (base / "run").mkdir(exist_ok=True)
    (base / "pilot").mkdir(exist_ok=True)
    (base / "ref").mkdir(exist_ok=True)
    test_reference_sheet(base / "ref")
    test_judge_run(base / "run")
    test_pilot(base / "pilot")
