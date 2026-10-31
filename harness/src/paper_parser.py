"""The paper-summary call of the LaTeX workflow: upstream parse_raw(version=2), bounded.

Runs inside Paper2Poster's environment, from its working directory (see latex_prepare.py).
"""
import json
import os
import re


def parser_output_problem(content):
    """Upstream parse_raw's validity checks; returns None when the output is usable."""
    sections = content.get('sections') if isinstance(content, dict) else None
    if not isinstance(sections, list) or not sections:
        return 'no sections'
    if any(not isinstance(s, dict) or 'title' not in s or 'content' not in s for s in sections):
        return 'a section lacks title or content'
    if not any('title' in str(s['title']).lower() for s in sections):
        return 'no poster title section'
    return None


def parse_paper(args, actor_config, record_usage, max_attempts, rng):
    """parse_raw(version=2) at the pinned commit, without its token leaks.

    Upstream retries the whole function up to 5 times (re-converting the PDF each time),
    loops without limit on an empty reply, reports only the last call's tokens, and drops
    sections with an unseeded random.sample. Here: one PDF conversion, at most
    max_attempts model calls, each one recorded, and the same selection rule with a
    seeded generator.
    """
    # Imports resolve in Paper2Poster's environment, not the harness environment.
    import PosterAgent.parse_raw as upstream_parse
    from camel.agents import ChatAgent
    from camel.models import ModelFactory
    from jinja2 import Template
    from utils.src.utils import get_json_from_response
    from utils.wei_utils import account_token

    raw_result = upstream_parse.doc_converter.convert(args.poster_path)
    text_content = re.sub(r"<!--[\s\S]*?-->", "", raw_result.document.export_to_markdown())
    if len(text_content) < 500:
        print('\nParsing with docling failed, using marker instead\n')
        parser_model = upstream_parse.create_model_dict(device='cuda', dtype=upstream_parse.torch.float16)
        text_content, _ = upstream_parse.parse_pdf(args.poster_path, model_lst=parser_model, save_file=False)
    prompt = Template(open('utils/prompts/gen_poster_raw_content_v2.txt').read()).render(
        markdown_document=text_content)

    kwargs = {k: actor_config[k] for k in ('model_platform', 'model_type')}
    kwargs['model_config_dict'] = actor_config['model_config']
    if actor_config.get('url'):
        kwargs['url'] = actor_config['url']
    agent = ChatAgent(system_message='You are the author of the paper, and you will create a poster for the paper.',
                      model=ModelFactory.create(**kwargs), message_window_size=10,
                      token_limit=actor_config.get('token_limit', None))
    for attempt in range(1, max_attempts + 1):
        agent.reset()
        response = agent.step(prompt)
        record_usage(*account_token(response))
        content = get_json_from_response(response.msgs[0].content)
        problem = parser_output_problem(content)
        if problem is None:
            break
        print(f'Parser output unusable ({problem}); attempt {attempt} of {max_attempts}.', flush=True)
    else:
        raise RuntimeError(f'Parser output unusable after {max_attempts} attempts: {problem}')

    if len(content['sections']) > 9:
        # Upstream rule: first 2 + 5 random middle sections + last 2.
        content['sections'] = (content['sections'][:2] + rng.sample(content['sections'][2:-2], 5)
                               + content['sections'][-2:])
    os.makedirs('contents', exist_ok=True)
    with open(f'contents/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_raw_content.json', 'w') as f:
        json.dump(content, f, indent=4)
    return raw_result
