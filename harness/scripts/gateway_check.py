"""Smoke test for the Cornell AI Gateway.

Checks that the gateway is reachable, every configured model ID is served,
each model answers a text prompt, vision models answer an image prompt, and
token usage is returned (needed for token_usage / generation_cost).

Usage:
    pip install openai pyyaml
    export CORNELL_AI_GATEWAY_URL="https://<host>/v1"   # from Cornell
    export CORNELL_AI_GATEWAY_KEY="<your key>"
    python scripts/gateway_check.py --config config/experiment.yaml
"""
import argparse
import base64
import os
import sys
import time
import zlib
import struct

import yaml
from openai import OpenAI

TEXT_ONLY: set[str] = set()  # models without image input (all current models accept images)


def tiny_png() -> str:
    """Return a data URL for a 2x2 red PNG, built without extra dependencies."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def call(client, model, content):
    t0 = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,  # reasoning models spend tokens thinking before they answer
        temperature=0,
    )
    dt = time.time() - t0
    u = r.usage
    return r.choices[0].message.content, dt, (u.prompt_tokens, u.completion_tokens) if u else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiment.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    g = cfg["gateway"]
    base_url = os.environ.get(g["base_url_env"])
    api_key = os.environ.get(g["api_key_env"])
    if not base_url or not api_key:
        sys.exit(f"Set {g['base_url_env']} and {g['api_key_env']} first.")

    # Fail fast: a listed model that never answers should show up as FAIL, not a hang.
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60, max_retries=0)

    models = [c["id"] for c in cfg["candidates"]] + [j["id"] for j in cfg["judges"]["models"]]
    vision = cfg.get("fixed", {}).get("paper2poster", {}).get("vision_model")
    if vision and vision not in ("TBD", "same_as_candidate") and vision not in models:
        models.append(vision)
    ok = True

    try:
        served = {m.id for m in client.models.list().data}
        print(f"Gateway serves {len(served)} models.")
    except Exception as e:  # some proxies disable /models
        served = None
        print(f"Could not list models ({e}); continuing with direct calls.")

    for m in models:
        print(f"\n== {m}")
        if served is not None and m not in served:
            print("  FAIL  not in gateway model list")
            close = [s for s in served if m.split(".")[-1].split("-")[0] in s]
            if close:
                print(f"  hint  similar IDs: {sorted(close)[:5]}")
            ok = False
            continue
        try:
            text, dt, usage = call(client, m, "Reply with the single word: ready")
            print(f"  text   ok  {dt:.1f}s  reply={text!r}")
            if usage is None:
                print("  WARN  no usage returned; token_usage/cost cannot be recorded")
                ok = False
            else:
                print(f"  usage  prompt={usage[0]} completion={usage[1]}")
        except Exception as e:
            print(f"  FAIL  text call: {e}")
            ok = False
            continue
        if m in TEXT_ONLY:
            print("  image  skipped (text-only model)")
            continue
        try:
            content = [
                {"type": "text", "text": "What color is this image? One word."},
                {"type": "image_url", "image_url": {"url": tiny_png()}},
            ]
            text, dt, _ = call(client, m, content)
            if text and text.strip():
                print(f"  image  ok  {dt:.1f}s  reply={text!r}")
            else:
                print(f"  FAIL  image call returned an empty reply ({dt:.1f}s); image input not confirmed")
                ok = False
        except Exception as e:
            print(f"  FAIL  image call: {e}")
            ok = False

    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
