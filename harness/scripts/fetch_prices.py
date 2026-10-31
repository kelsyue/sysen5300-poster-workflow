"""Write config/prices.yaml from the Cornell AI Gateway's own price list.

The gateway is a LiteLLM proxy; GET /model/info returns each deployment's
input_cost_per_token and output_cost_per_token. generation_cost in runs.csv is
tokens x these prices, so re-running this script only changes cost for runs made after it.

Usage (from harness/, credentials loaded):
    python scripts/fetch_prices.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

HARNESS = Path(__file__).resolve().parent.parent


def main() -> None:
    cfg = yaml.safe_load(open(HARNESS / "config/experiment.yaml"))
    g = cfg["gateway"]
    base, key = os.environ.get(g["base_url_env"]), os.environ.get(g["api_key_env"])
    if not base or not key:
        sys.exit(f"Set {g['base_url_env']} and {g['api_key_env']} first.")
    url = base.rstrip("/").removesuffix("/v1") + "/model/info"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        info = {m["model_name"]: m.get("model_info") or {} for m in json.load(r)["data"]}

    models = [c["id"] for c in cfg["candidates"]] + [j["id"] for j in cfg["judges"]["models"]]
    prices, missing = {}, []
    for m in models:
        mi = info.get(m, {})
        pin, pout = mi.get("input_cost_per_token"), mi.get("output_cost_per_token")
        if pin is None or pout is None:
            missing.append(m)
        prices[m] = {"input_per_mtok": None if pin is None else round(pin * 1e6, 6),
                     "output_per_mtok": None if pout is None else round(pout * 1e6, 6)}

    out = HARNESS / cfg["fixed"].get("prices_file", "config/prices.yaml")
    header = ("# List prices (USD per million tokens), written by scripts/fetch_prices.py.\n"
              "# generation_cost = input_tokens x input price + output_tokens x output price.\n")
    out.write_text(header + yaml.safe_dump({"as_of": dt.date.today().isoformat(),
                                            "source": f"{url} (LiteLLM model_info)",
                                            "models": prices}, sort_keys=False))
    for m, p in prices.items():
        print(f"{m:40} in {p['input_per_mtok']}  out {p['output_per_mtok']}  per 1M tokens")
    if missing:
        sys.exit(f"No price from the gateway for {missing}; cost stays empty for them.")


if __name__ == "__main__":
    main()
