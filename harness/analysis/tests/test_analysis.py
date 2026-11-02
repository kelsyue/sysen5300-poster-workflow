"""Offline test of build_dataset.py and analyze.py on synthetic data with known answers.

    python analysis/tests/test_analysis.py
"""
import math
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import analyze  # noqa: E402
import build_dataset  # noqa: E402

MODELS = ["claude-opus-5", "gpt-5.6-sol", "meta.llama-4-maverick-17b-instruct", "qwen.qwen3-vl-235b-a22b"]
PAPERS = [f"T{i:02d}" for i in range(1, 9)] + ["P06"]          # P06 is a calibration paper in the config
# per model: (first attempt succeeds, recovery succeeds, coverage, unsupported of 20 claims, quality)
PLAN = {"claude-opus-5": (True, None, 100.0, 0, 5),               # meets every content limit
        "gpt-5.6-sol": (True, None, 55.56, 4, 2),                 # fails coverage, hallucination and quality
        "meta.llama-4-maverick-17b-instruct": (False, True, 100.0, 0, 4),   # every poster from recovery
        "qwen.qwen3-vl-235b-a22b": (False, False, None, None, None)}        # never a poster


def make(tmp: Path) -> dict:
    runs, recov, key, judge, rid = [], [], [], [], 0
    common = dict(prompt_sha256="v1", started_at="2026-11-01T00:00:00+00:00", input_tokens=900, output_tokens=100)
    for order, paper in enumerate(PAPERS, 1):
        for model in MODELS:
            first_ok, rec_ok, cov, unsup, qual = PLAN[model]
            rid += 1
            runs.append(dict(run_id=rid, run_order=order, batch_id=1 + (order - 1) // 3, llm_model=model,
                             input_paper_id=paper, workflow_success=int(first_ok),
                             failure_reason="" if first_ok else "E_PIPELINE", poster_word_count=600 if first_ok else "",
                             latency=40.0, token_usage=1000, generation_cost=0.01, **common))
            poster = ("runs.csv", rid) if first_ok else None
            if rec_ok is not None:
                rec_id = 1000 + rid
                recov.append(dict(run_id=rec_id, original_run_id=rid, completion_attempt=2, run_order=order, batch_id=1,
                                  llm_model=model, input_paper_id=paper, workflow_success=int(rec_ok),
                                  failure_reason="" if rec_ok else "E_OVERFLOW", poster_word_count=500 if rec_ok else "",
                                  latency=10.0, token_usage=300, generation_cost=0.002, **{**common, "prompt_sha256": "v2"}))
                if rec_ok:
                    poster = ("recovery_attempts.csv", rec_id)
            if poster:
                code = f"P-{rid:04d}"
                key.append(dict(poster_code=code, runs_file=str(tmp / "data" / poster[0]), run_id=poster[1], llm_model=model))
                for judge_model, shift in (("judge-a", 0), ("judge-b", -1)):
                    judge.append(dict(poster_code=code, judge_model=judge_model, judge_repeat=1, judge_prompt_sha256="j1",
                                      coverage_pct=cov, n_claims_total=20, n_claims_unsupported=unsup,
                                      quality_score=max(1, qual + shift), failed_tasks=""))
    # judge-a's claims task failed on one claude poster: only its hallucination value is missing
    judge[0]["failed_tasks"], judge[0]["n_claims_unsupported"] = "claims", 0
    (tmp / "data").mkdir()
    for name, rows in (("runs.csv", runs), ("recovery_attempts.csv", recov), ("judge_scores.csv", judge)):
        pd.DataFrame(rows).to_csv(tmp / "data" / name, index=False)
    pd.DataFrame(key).to_csv(tmp / "key.csv", index=False)
    calib = [k for k in key if k["run_id"] in {r["run_id"] for r in runs if r["input_paper_id"] == "P06"}]
    pd.DataFrame([dict(poster_code=calib[0]["poster_code"], evaluator_id="e1", **{i: 1 for i in build_dataset.ITEMS},
                       n_claims_total=10, n_claims_unsupported=1, quality_score=3)]).to_csv(tmp / "data" / "human_scores.csv", index=False)
    return {"runs": runs, "judge": judge}


def test_pipeline(tmp: Path) -> None:
    made = make(tmp)
    args = ["--data-dir", str(tmp / "data"), "--key", str(tmp / "key.csv"), "--out", str(tmp / "out" / "dataset.csv"),
            "--judge-scores", str(tmp / "data" / "judge_scores.csv"), "--human-scores", str(tmp / "data" / "human_scores.csv")]
    build_dataset.main(args)
    d = pd.read_csv(tmp / "out" / "dataset.csv")
    assert len(d) == len(PAPERS) * len(MODELS) and (d.split == "calibration").sum() == len(MODELS)
    llama = d[d.llm_model == MODELS[2]].iloc[0]
    assert (llama.workflow_success, llama.from_recovery, llama.n_attempts) == (1, 1, 2)
    assert llama.latency == 50 and llama.token_usage == 1300 and math.isclose(llama.generation_cost, 0.012)
    assert llama.used_prompt_sha256 == "v2"
    claude0 = d[d.llm_model == MODELS[0]].iloc[0]
    assert (claude0.workflow_success, claude0.from_recovery, claude0.used_runs_file) == (1, 0, str(tmp / "data" / "runs.csv"))
    qwen = d[d.llm_model == MODELS[3]]
    assert qwen.workflow_success.sum() == 0 and qwen.poster_code.isna().all() and qwen.latency.eq(50).all()
    assert qwen.from_recovery.all()                                # used run = the last, failed recovery
    claude = d[d.llm_model == MODELS[0]].set_index("input_paper_id")
    assert pd.isna(claude.loc["T01", "halluc_pct__judge-a"]) and claude.loc["T01", "coverage_pct__judge-a"] == 100
    gpt = d[d.llm_model == MODELS[1]].iloc[0]
    assert gpt["halluc_pct__judge-a"] == 20.0                      # 4 of 20 claims
    assert d["quality_score__human"].notna().sum() == 1

    # a second prompt version for one judge must be chosen explicitly
    j = pd.read_csv(tmp / "data" / "judge_scores.csv")
    pd.concat([j, j.iloc[[0]].assign(judge_prompt_sha256="j2", quality_score=1)]).to_csv(tmp / "data" / "judge_scores.csv", index=False)
    try:
        build_dataset.main(args)
        raise AssertionError("mixed prompt versions were accepted")
    except SystemExit as e:
        assert "judge-a has 2 prompt versions" in str(e)
    build_dataset.main(args + ["--judge-prompt", "judge-a=j1"])

    analyze.main(["--dataset", str(tmp / "out" / "dataset.csv"), "--out-dir", str(tmp / "out" / "main")])
    out = tmp / "out" / "main"
    gate = pd.read_csv(out / "gate.csv").set_index(["source", "llm_model"])
    a = gate.loc[("judge-a", MODELS[0])]
    assert (a["GR-1"], a["GR-2"], a["GR-3"], a["GR-4"]) == ("pass", "pass", "pass", "inconclusive"), a
    assert a.recommendation == "Inconclusive"                     # 8/8 successes cannot show >= 95%
    b = gate.loc[("judge-a", MODELS[1])]
    assert (b["GR-1"], b["GR-2"], b["GR-3"]) == ("fail", "fail", "fail") and b.recommendation == "Reject"
    q = gate.loc[("judge-a", MODELS[3])]
    assert q["GR-1"] == "insufficient data" and q["GR-4"] == "fail" and q.recommendation == "Reject"
    succ = pd.read_csv(out / "success.csv").set_index(["llm_model", "measure"])
    assert math.isclose(succ.loc[(MODELS[0], "workflow_success"), "lower_95"], 0.05 ** (1 / 8), rel_tol=1e-9)
    assert succ.loc[(MODELS[2], "workflow_success"), "rate"] == 1          # failed first attempts not counted
    assert set(succ.index.get_level_values("measure")) == {"workflow_success"}
    cap = pd.read_csv(out / "capability.csv").set_index(["source", "measure", "llm_model"])
    assert cap.loc[("judge-a", "halluc_pct", MODELS[0]), "n_scored"] == 7    # failed claims task left out
    assert pd.isna(cap.loc[("judge-a", "coverage_pct", MODELS[0]), "ppk"])     # no spread: undefined, not infinite
    comp = pd.read_csv(out / "compare.csv")
    assert {"mixed model LR (log scale)", "Friedman (complete papers)", "Cochran's Q"} <= set(comp.test)
    assert (out / "report.md").read_text().count("not counted against the model") == 1
    assert (out / "figures" / "box_latency.png").exists()

    # share basis: 7/7 meeting has a 95% CI lower bound of about 0.59, below a 0.75 target
    cfg = (build_dataset.HARNESS / "config" / "experiment.yaml").read_text().replace("decision_basis: mean", "decision_basis: share")
    (tmp / "share.yaml").write_text(cfg)
    analyze.main(["--config", str(tmp / "share.yaml"), "--dataset", str(tmp / "out" / "dataset.csv"),
                  "--out-dir", str(tmp / "out" / "share")])
    g2 = pd.read_csv(tmp / "out" / "share" / "gate.csv").set_index(["source", "llm_model"])
    assert g2.loc[("judge-a", MODELS[0]), "GR-1"] == "inconclusive"
    print("analysis pipeline: OK")


if __name__ == "__main__":
    test_pipeline(Path(tempfile.mkdtemp()))
