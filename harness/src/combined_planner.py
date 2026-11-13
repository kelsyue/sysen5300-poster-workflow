"""Select relevant figures and assign them to existing sections in one model call."""
import json

SYSTEM_PROMPT = """Plan the figures for a scientific poster using the supplied section summaries
and figure/table captions. Select only informative, relevant scientific visuals;
exclude logos, decoration and redundant visuals. Preserve every existing section
and its exact title. Assign at most one image OR table to a section, and use each
visual at most once. Do not assign a visual to the poster title/authors section.
Prioritize evidence for the main findings and an informative method diagram.
Do not invent figures, IDs, claims or sections. Return only a JSON object mapping
exact section titles to {"image": "ID"} or {"table": "ID"}. Omit sections with no
suitable visual. Return {} if no supplied visual is useful. No reasons or layout
coordinates are needed: code computes layout and sizing."""

# latex-painter-v3 only (in PLAN_TASK): posters are read visually, so use the paper's figures.
# Upstream's rule (zero or one visual per section) is unchanged; v2 runs keep SYSTEM_PROMPT.
FILL_RULE = """
Give a visual to every section that has a relevant one; leave a section without a visual
only when none of the remaining visuals fits it."""

# The task is restated in the user turn: with only the system message, Llama 4 Maverick
# summarized the input instead of planning (first LaTeX dry run, P01). Same text for every model.
PLANNING_REQUEST = """Task: choose the figures for the poster sections below, following the rules in the system message.
Output: only a JSON object whose keys are section titles copied exactly and whose values are {"image": "ID"} or {"table": "ID"} with IDs from the lists below, for example {"Results": {"image": "2"}}. No other text.

Input:
"""


# latex-painter-v3: the Planner, Painter and overflow-shortening calls share one prefix
# (this system message + source_block) so a model with prompt caching reads it from the
# cache after the first call. The block must be byte-identical across calls: it is built
# only from raw_content.json, images.json and tables.json, with fixed JSON formatting.
SHARED_SYSTEM = """You help turn a scientific paper into a conference poster. The first part of
the user message is the source: the paper's section summaries and its figure and table
captions. Follow the task that comes after the source exactly, using only that source."""

PLAN_TASK = ("Task: plan the figures for the poster.\nRules: " + SYSTEM_PROMPT + FILL_RULE + """
Output: only a JSON object whose keys are section titles copied exactly from the source and whose values are {"image": "ID"} or {"table": "ID"} with IDs from the source, for example {"Results": {"image": "2"}}. No other text.""")


def source_block(document, images, tables):
    """The shared, cacheable prefix: summaries and captions, serialized deterministically."""
    payload = {'paper_title': (document.get('meta') or {}).get('poster_title', ''),
               **planning_input(document, images, tables)}
    return 'SOURCE\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def planning_input(document, images, tables):
    """Send scientific content once; leave paths and styling out of the prompt."""
    return {
        'sections': [{'title': s['title'], 'content': s.get('content', '')}
                     for s in document['sections']],
        'images': {str(k): {'caption': v.get('caption', '')} for k, v in images.items()},
        'tables': {str(k): {'caption': v.get('caption', '')} for k, v in tables.items()},
    }


def validate_plan(plan, document, images, tables):
    """Reject invalid selections locally; never spend tokens on automatic repairs."""
    if not isinstance(plan, dict):
        raise ValueError('Combined figure plan must be a JSON object')
    titles = {s['title'] for s in document['sections']}
    used, clean = set(), {}
    for title, selection in plan.items():
        if selection in ({}, None, ''):
            continue  # "no visual for this section", which some models state explicitly
        if title not in titles or title.lower().startswith('poster title'):
            raise ValueError(f'Invalid figure section: {title}')
        if not isinstance(selection, dict) or len(selection) != 1:
            raise ValueError(f'Expected one image OR table for {title}')
        kind = next(iter(selection))
        source = {'image': images, 'table': tables}.get(kind)
        identifier = str(selection[kind])
        if source is None or identifier not in source:
            raise ValueError(f'Unknown figure selection: {selection}')
        if (kind, identifier) in used:
            raise ValueError(f'Figure selected more than once: {selection}')
        used.add((kind, identifier))
        clean[title] = {kind: identifier}
    return clean


def make_panels(document, images, tables, plan):
    """Compute upstream tree-layout inputs locally, retaining all source sections."""
    total_text = sum(len(s.get('content', '')) for s in document['sections']) or 1
    selected = {}
    for title, selection in plan.items():
        kind, identifier = next(iter(selection.items()))
        selected[title] = (images if kind == 'image' else tables)[identifier]
    total_area = sum(v['figure_size'] for v in selected.values()) or 1
    panels = []
    for i, section in enumerate(document['sections']):
        visual = selected.get(section['title'])
        length = len(section.get('content', ''))
        panels.append({'panel_id': i, 'section_name': section['title'],
                       'tp': length / total_text, 'text_len': length,
                       'gp': visual['figure_size'] / total_area if visual else 0,
                       'figure_size': visual['figure_size'] if visual else 0,
                       'figure_aspect': visual['figure_aspect'] if visual else 1})
    return panels


FEEDBACK = ('\n\nRecovery of this same model\'s failed attempt. The previous response '
            'below was rejected. Return a corrected mapping using only the supplied '
            'IDs and exact section titles. Exclude title/authors sections entirely. '
            'Use each image/table at most once; leave sections without a suitable '
            'unused visual out. Return only the corrected JSON.\n')


def plan_figures(document, images, tables, actor_config, record_usage, raw_path=None, feedback=None,
                 ask=None):
    """One planning call. With ask (latex-painter-v3, gateway_chat) the shared cached
    source prefix is used and ask records usage; otherwise camel, as in latex-only-v2."""
    if ask is not None:
        from utils.src.utils import get_json_from_response
        task = PLAN_TASK + (FEEDBACK + json.dumps(feedback, ensure_ascii=False, separators=(',', ':'))
                            if feedback else '')
        text = ask('planning', SHARED_SYSTEM, [source_block(document, images, tables), task], cache=True)
        if raw_path is not None:
            raw_path.write_text(text)
        plan = validate_plan(get_json_from_response(text), document, images, tables)
        return make_panels(document, images, tables, plan), plan

    # Imports resolve in Paper2Poster's environment, not the harness environment.
    from camel.models import ModelFactory
    from camel.agents import ChatAgent
    from utils.src.utils import get_json_from_response
    from utils.wei_utils import account_token

    kwargs = {k: actor_config[k] for k in ('model_platform', 'model_type')}
    kwargs['model_config_dict'] = actor_config['model_config']
    if actor_config.get('url'):
        kwargs['url'] = actor_config['url']
    agent = ChatAgent(system_message=SYSTEM_PROMPT, model=ModelFactory.create(**kwargs),
                      message_window_size=1)
    prompt = PLANNING_REQUEST + json.dumps(planning_input(document, images, tables),
                                          ensure_ascii=False, separators=(',', ':'))
    if feedback:
        prompt += FEEDBACK + json.dumps(feedback, ensure_ascii=False, separators=(',', ':'))
    response = agent.step(prompt)
    record_usage(*account_token(response))  # record even if JSON validation fails
    if raw_path is not None:  # kept for audit, and to see why a plan was rejected
        raw_path.write_text(response.msgs[0].content or '')
    plan = validate_plan(get_json_from_response(response.msgs[0].content),
                         document, images, tables)
    return make_panels(document, images, tables, plan), plan
