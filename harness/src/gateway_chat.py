"""One recorded chat call to the gateway (latex-painter-v3); replaces camel's ChatAgent.

The request is what camel sent at the pinned commit (model, messages, max_tokens and
temperature from the generation-params patch's environment variables, client timeout 180 s
and 3 SDK retries), without camel's hidden behaviour (message windows, context truncation,
token counting).

Every call is written to <calls_dir>/<NN>_<stage>.json: the full request (no credentials)
and the response text, finish reason, usage and the gateway's own record (LiteLLM version,
deployment ID, charged cost). With these files the rest of the pipeline is deterministic,
so a poster can be rebuilt byte for byte without calling a model.

Prompt caching: blocks are sent as one user message of text parts. With cache=True and a
model that needs explicit markers (config fixed.paper2poster.prompt_cache_models), the
first block ends with an Anthropic-style cache breakpoint ({"type": "ephemeral"}, 5-minute
lifetime). Calls that share that first block byte for byte read it from the cache.
Usage keys per stage in the usage log: <stage>_in_t (all prompt tokens, cached included),
<stage>_out_t, <stage>_cached_t (read from cache), <stage>_cachewrite_t, <stage>_cost_usd.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CLIENT_SETTINGS = {'timeout': 180, 'max_retries': 3}  # camel OpenAICompatibleModel, pinned commit
GATEWAY_HEADERS = ('x-litellm-version', 'x-litellm-model-id', 'x-litellm-model-group',
                   'x-litellm-response-cost', 'x-litellm-response-cost-input',
                   'x-litellm-response-cost-output', 'x-litellm-response-cost-cache-read',
                   'x-litellm-response-cost-cache-creation')


def generation_params(env=os.environ) -> dict:
    """max_tokens and temperature exactly as the generation-params patch sets them."""
    params = {}
    if env.get('P2P_MAX_OUTPUT_TOKENS'):
        params['max_tokens'] = int(env['P2P_MAX_OUTPUT_TOKENS'])
    if env.get('P2P_TEMPERATURE'):
        params['temperature'] = float(env['P2P_TEMPERATURE'])
    return params


def build_messages(system: str, blocks: list[str], cache: bool) -> list[dict]:
    content = [{'type': 'text', 'text': b} for b in blocks]
    if cache:
        content[0]['cache_control'] = {'type': 'ephemeral'}
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]


def usage_of(response) -> dict:
    """Prompt tokens include cache reads and writes (checked on the gateway, 2026-11-12)."""
    u = response.usage
    details = getattr(u, 'prompt_tokens_details', None)
    cached = (getattr(details, 'cached_tokens', None) or 0) if details else 0
    written = ((getattr(details, 'cache_write_tokens', None) if details else None)
               or getattr(u, 'cache_creation_input_tokens', None) or 0)
    return {'in': u.prompt_tokens or 0, 'out': u.completion_tokens or 0,
            'cached': cached, 'cachewrite': written}


class GatewayChat:
    def __init__(self, model: str, calls_dir: Path, usage: dict, save_usage, cache_markers: bool = False,
                 client=None, env=os.environ):
        self.model, self.calls_dir, self.usage, self.save_usage = model, Path(calls_dir), usage, save_usage
        self.cache_markers, self.params = cache_markers, generation_params(env)
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=env['OPENAI_API_KEY'], base_url=env['OPENAI_BASE_URL'], **CLIENT_SETTINGS)
        self.client = client

    def ask(self, stage: str, system: str, blocks: list[str], cache: bool = False) -> str:
        """One call; usage is recorded before the caller validates the reply."""
        request = {'model': self.model, 'messages': build_messages(system, blocks, cache and self.cache_markers),
                   **self.params}
        raw = self.client.chat.completions.with_raw_response.create(**request)
        response = raw.parse()
        choice = response.choices[0]
        text = choice.message.content or ''
        used = usage_of(response)
        gateway = {k: raw.headers.get(k) for k in GATEWAY_HEADERS if raw.headers.get(k) is not None}
        cost = float(gateway['x-litellm-response-cost']) if 'x-litellm-response-cost' in gateway else None
        for key, value in (('in_t', used['in']), ('out_t', used['out']), ('cached_t', used['cached']),
                           ('cachewrite_t', used['cachewrite'])):
            self.usage[f'{stage}_{key}'] = self.usage.get(f'{stage}_{key}', 0) + value
        if cost is not None:
            self.usage[f'{stage}_cost_usd'] = round(self.usage.get(f'{stage}_cost_usd', 0.0) + cost, 8)
        self.save_usage()
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        number = len(list(self.calls_dir.glob('*.json'))) + 1
        record = {'stage': stage, 'request': request,
                  'response': {'id': response.id, 'model': response.model, 'created': response.created,
                               'system_fingerprint': getattr(response, 'system_fingerprint', None),
                               'finish_reason': choice.finish_reason, 'text': text,
                               'usage': response.usage.model_dump() if hasattr(response.usage, 'model_dump') else used},
                  'gateway': gateway}
        (self.calls_dir / f'{number:02d}_{stage}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return text
