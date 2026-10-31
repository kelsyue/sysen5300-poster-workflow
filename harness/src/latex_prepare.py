"""LaTeX preparation: upstream parsing, one combined planner and local tree layout.

Parsing/layout adapted from PosterAgent/new_pipeline.py at the pinned commit.
The harness-owned planner merges figure filtering and section assignment.
Completed generation stages are checkpointed per source PDF and candidate.
Stops after saving tree_split: no bullet JSON generation, vision critics or PPTX.
Run from the Paper2Poster working directory using its Python environment.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from PosterAgent.parse_raw import parse_raw, gen_image_and_table
from combined_planner import plan_figures, planning_input, SYSTEM_PROMPT
from preparation_cache import StageCache, file_digest
from utils.wei_utils import get_agent_config, scale_to_target_area, char_capacity
from PosterAgent.tree_split_layout import main_train, main_inference, get_arrangments_in_inches, split_textbox, to_inches

import argparse
import atexit
import json
import os
import shutil
import time

units_per_inch = 25

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Prepare summaries and figure layout for LaTeX')
    parser.add_argument('--poster_path', type=str, required=True)
    parser.add_argument('--usage_path', type=str, required=True)
    parser.add_argument('--checkpoint_dir', type=str, required=True)
    parser.add_argument('--intermediate_dir', type=str, required=True)
    parser.add_argument('--model_name_t', type=str, default='4o')
    parser.add_argument('--model_name_v', type=str, default='4o')
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--poster_name', type=str, default=None)
    parser.add_argument('--tmp_dir', type=str, default='tmp')
    parser.add_argument('--poster_width_inches', type=int, default=None)
    parser.add_argument('--poster_height_inches', type=int, default=None)

    args = parser.parse_args()

    start_time = time.time()

    os.makedirs(args.tmp_dir, exist_ok=True)

    usage_path = Path(args.usage_path)
    detail_log = json.loads(usage_path.read_text()) if usage_path.exists() else {}
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    def save_usage():
        temporary = usage_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(detail_log, indent=2))
        temporary.replace(usage_path)
    atexit.register(save_usage)
    identity = {
        'pdf_sha256': file_digest(args.poster_path), 'candidate': args.model_name_t,
        'artifact_model': args.model_name_v, 'paper': args.poster_name or Path(args.poster_path).parent.name,
        'parser_code': file_digest('PosterAgent/parse_raw.py'),
        'parser_prompt': file_digest('utils/prompts/gen_poster_raw_content_v2.txt'),
        'parser_utils': file_digest('utils/wei_utils.py'),
        'max_output_tokens': os.environ.get('P2P_MAX_OUTPUT_TOKENS'),
        'gateway': os.environ.get('OPENAI_BASE_URL'),
    }
    cache = StageCache(args.checkpoint_dir, identity)
    cache_hits = []

    agent_config_t = get_agent_config(args.model_name_t)
    poster_name = args.poster_path.split('/')[-2].replace(' ', '_')
    if args.poster_name is None:
        args.poster_name = poster_name
    else:
        poster_name = args.poster_name
    meta_json_path = args.poster_path.replace('paper.pdf', 'meta.json')
    if args.poster_width_inches is not None and args.poster_height_inches is not None:
        poster_width = args.poster_width_inches * units_per_inch
        poster_height = args.poster_height_inches * units_per_inch
    elif os.path.exists(meta_json_path):
        meta_json = json.load(open(meta_json_path, 'r'))
        poster_width = meta_json['width']
        poster_height = meta_json['height']
    else:
        poster_width = 48 * units_per_inch
        poster_height = 36 * units_per_inch

    poster_width, poster_height = scale_to_target_area(poster_width, poster_height)
    poster_width_inches = to_inches(poster_width, units_per_inch)
    poster_height_inches = to_inches(poster_height, units_per_inch)

    if poster_width_inches > 56 or poster_height_inches > 56:
        # Work out which side is longer, then compute a single scale factor
        if poster_width_inches >= poster_height_inches:
            scale_factor = 56 / poster_width_inches
        else:
            scale_factor = 56 / poster_height_inches

        poster_width_inches  *= scale_factor
        poster_height_inches *= scale_factor

        # convert back to internal units
        poster_width  = poster_width_inches  * units_per_inch
        poster_height = poster_height_inches * units_per_inch

    print(f'Poster size: {poster_width_inches} x {poster_height_inches} inches')

    tag = f'<{args.model_name_t}_{args.model_name_v}>'
    raw_path = Path(f'contents/{tag}_{poster_name}_raw_content.json')
    images_path = Path(f'{tag}_images_and_tables/{poster_name}_images.json')
    tables_path = Path(f'{tag}_images_and_tables/{poster_name}_tables.json')
    parsed = cache.load('parse', {}, destination=Path.cwd())
    if parsed is None:
        input_token, output_token, raw_result = parse_raw(args, agent_config_t, version=2)
        detail_log['parser_in_t'] = detail_log.get('parser_in_t', 0) + input_token
        detail_log['parser_out_t'] = detail_log.get('parser_out_t', 0) + output_token
        save_usage()
        _, _, images, tables = gen_image_and_table(args, raw_result)
        assets = [v['image_path'] for v in images.values()] + [v['table_path'] for v in tables.values()]
        parsed = {'input_tokens': input_token, 'output_tokens': output_token}
        cache.save('parse', {}, parsed, source=Path.cwd(),
                   files=[raw_path, images_path, tables_path, *assets])
    else:
        print('Reusing saved summaries and extracted figures; no parser API call.', flush=True)
        cache_hits.append('parse')
        detail_log.setdefault('parser_in_t', parsed['input_tokens'])
        detail_log.setdefault('parser_out_t', parsed['output_tokens'])
        images = json.loads(images_path.read_text())
        tables = json.loads(tables_path.read_text())
    # Export only artifacts produced/restored by this run, never stale vendor output.
    intermediate = Path(args.intermediate_dir)
    intermediate.mkdir(parents=True, exist_ok=True)
    for original, name in ((raw_path, 'raw_content.json'), (images_path, 'images.json'),
                           (tables_path, 'tables.json')):
        shutil.copyfile(original, intermediate / name)
    for visual in [*images.values(), *tables.values()]:
        rel = visual.get('image_path') or visual.get('table_path')
        target = intermediate / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rel, target)
    document = json.loads(raw_path.read_text())
    detail_log['parser_time'] = time.time() - start_time

    # One compact model request replaces filtering followed by planning.
    plan_inputs = {'content': planning_input(document, images, tables),
                   'prompt': SYSTEM_PROMPT,
                   'implementation': file_digest(Path(__file__).with_name('combined_planner.py'))}
    planned = cache.load('plan', plan_inputs)
    if planned is None:
        def record_usage(tin, tout):
            detail_log['planning_in_t'] = detail_log.get('planning_in_t', 0) + tin
            detail_log['planning_out_t'] = detail_log.get('planning_out_t', 0) + tout
            save_usage()
        panels, figures = plan_figures(document, images, tables, agent_config_t, record_usage)
        planned = {'panels': panels, 'figures': figures}
        cache.save('plan', plan_inputs, planned)
    else:
        print('Reusing saved figure selections and outline; no planning API call.', flush=True)
        cache_hits.append('plan')
        panels, figures = planned['panels'], planned['figures']
    usage_path.with_name('cache_usage.json').write_text(json.dumps({
        'reused_stages': cache_hits, 'candidate': args.model_name_t,
        'pdf_sha256': identity['pdf_sha256'],
        'token_accounting': 'detail_log includes cumulative generation usage, including earlier tries'
    }, indent=2))
    save_usage()
    outline_time = time.time()

    # Step 4: Learn and generate layout
    panel_model_params, figure_model_params = main_train()

    panel_arrangement, figure_arrangement, text_arrangement = main_inference(
        panels,
        panel_model_params,
        figure_model_params,
        poster_width,
        poster_height,
        shrink_margin=3
    )

    text_arrangement_title = text_arrangement[0]
    text_arrangement = text_arrangement[1:]
    # Split the title textbox into two parts
    text_arrangement_title_top, text_arrangement_title_bottom = split_textbox(
        text_arrangement_title,
        0.8
    )
    # Add the split textboxes back to the list
    text_arrangement = [text_arrangement_title_top, text_arrangement_title_bottom] + text_arrangement


    for i in range(len(figure_arrangement)):
        panel_id = figure_arrangement[i]['panel_id']
        panel_section_name = panels[panel_id]['section_name']
        figure_info = figures[panel_section_name]
        if 'image' in figure_info:
            figure_id = figure_info['image']
            if not figure_id in images:
                figure_path = images[str(figure_id)]['image_path']
            else:
                figure_path = images[figure_id]['image_path']
        elif 'table' in figure_info:
            figure_id = figure_info['table']
            if not figure_id in tables:
                figure_path = tables[str(figure_id)]['table_path']
            else:
                figure_path = tables[figure_id]['table_path']

        figure_arrangement[i]['figure_path'] = figure_path

    for text_arrangement_item in text_arrangement:
        num_chars = char_capacity(
            bbox=(text_arrangement_item['x'], text_arrangement_item['y'], text_arrangement_item['height'], text_arrangement_item['width'])
        )
        text_arrangement_item['num_chars'] = num_chars


    width_inch, height_inch, panel_arrangement_inches, figure_arrangement_inches, text_arrangement_inches = get_arrangments_in_inches(
        poster_width, poster_height, panel_arrangement, figure_arrangement, text_arrangement, 25
    )

    # Save to file
    tree_split_results = {
        'poster_width': poster_width,
        'poster_height': poster_height,
        'poster_width_inches': width_inch,
        'poster_height_inches': height_inch,
        'panels': panels,
        'panel_arrangement': panel_arrangement,
        'figure_arrangement': figure_arrangement,
        'text_arrangement': text_arrangement,
        'panel_arrangement_inches': panel_arrangement_inches,
        'figure_arrangement_inches': figure_arrangement_inches,
        'text_arrangement_inches': text_arrangement_inches,
    }
    os.makedirs('tree_splits', exist_ok=True)
    with open(f'tree_splits/<{args.model_name_t}_{args.model_name_v}>_{args.poster_name}_tree_split_{args.index}.json', 'w') as f:
        json.dump(tree_split_results, f, indent=4)

    (intermediate / 'tree_split.json').write_text(json.dumps(tree_split_results, indent=2))
    layout_time_taken = time.time() - outline_time
    print(f'Layout time: {layout_time_taken:.2f} seconds')
    detail_log['layout_time'] = layout_time_taken

    layout_time = time.time()

