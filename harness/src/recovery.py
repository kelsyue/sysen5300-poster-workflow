"""Audited checkpoint recovery. Original experiment attempts are never overwritten."""
from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path

import yaml

import runner

TOKEN_COLUMNS = ('input_tokens', 'output_tokens', 'vision_input_tokens',
                 'vision_output_tokens', 'token_usage')
RECOVERY_COLUMNS = runner.RUN_COLUMNS + [
    'original_run_id', 'parent_run_id', 'completion_attempt', 'recovery_mode',
    'previous_failure_reason', 'failure_detail', 'checkpoint_source',
    'checkpoint_used', 'reused_stages', 'prior_token_usage', 'cumulative_token_usage',
    'cumulative_generation_cost', 'original_prompt_sha256', 'feedback_sha256',
    'checkpoint_fallback_reason',
]


def locations(harness, dry_run=False):
    sub = Path('latex') / ('dry_run' if dry_run else '')
    return harness / 'data' / sub, harness / 'outputs' / sub, harness / 'results' / sub


def write_csv(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def number(row, key):
    return float(row.get(key) or 0)


def selected_rows(data, papers=None, models=None):
    original = runner.read_runs(data / 'runs.csv')
    if not original:
        raise ValueError(f'No original attempts recorded in {data / "runs.csv"}')
    for values, key in ((papers, 'input_paper_id'), (models, 'llm_model')):
        unknown = set(values or []) - {r[key] for r in original}
        if unknown:
            raise ValueError(f'No recorded attempts for {key}: {sorted(unknown)}')
    original = [r for r in original if (not papers or r['input_paper_id'] in papers)
                and (not models or r['llm_model'] in models)]
    ids = {r['run_id'] for r in original}
    recoveries = [r for r in runner.read_runs(data / 'recovery_attempts.csv')
                  if r['original_run_id'] in ids]
    return original, recoveries


def failure_detail(directory, code):
    log = directory / 'run.log'
    lines = log.read_text(errors='replace').splitlines() if log.exists() else []
    for line in reversed(lines):
        if line.startswith(('ValueError:', 'RuntimeError:', 'TypeError:', 'KeyError:',
                            'FileNotFoundError:', 'IndexError:', 'openai.', '=== harness:')):
            return line
    if code == 'E_OVERFLOW' and (directory / 'latex/fit.json').exists():
        return 'Poster overflow after fitting: ' + (directory / 'latex/fit.json').read_text()
    return code or ''


def write_summary(harness, *, dry_run=False, papers=None, models=None):
    data, outputs, results = locations(harness, dry_run)
    original, recoveries = selected_rows(data, papers, models)
    grouped = {}
    for row in recoveries:
        grouped.setdefault(row['original_run_id'], []).append(row)
    posters = []
    for first in original:
        later = sorted(grouped.get(first['run_id'], []), key=lambda r: int(r['completion_attempt']))
        attempts = [first, *later]
        successful = next((r for r in attempts if str(r['workflow_success']) == '1'), None)
        latest = attempts[-1]
        success_on = (1 if successful is first else int(successful['completion_attempt'])) if successful else ''
        failures = [{'completion_attempt': 1 if r is first else int(r['completion_attempt']),
                     'run_id': r['run_id'], 'failure_reason': r.get('failure_reason', ''),
                     'failure_detail': r.get('failure_detail') or failure_detail(
                         outputs / r['run_id'], r.get('failure_reason', ''))}
                    for r in attempts if str(r['workflow_success']) != '1']
        posters.append({
            'original_run_id': first['run_id'], 'input_paper_id': first['input_paper_id'],
            'llm_model': first['llm_model'], 'experiment_attempt': first['attempt'],
            'first_attempt_success': int(str(first['workflow_success']) == '1'),
            'workflow_success': int(successful is not None),
            'completion_attempts': len(attempts), 'success_on_attempt': success_on,
            'needed_checkpoint_recovery': int(bool(later)),
            'checkpoint_used': int(any(str(r.get('checkpoint_used')) == '1' for r in later)),
            'checkpoint_runs': ','.join(r['run_id'] for r in later if str(r.get('checkpoint_used')) == '1'),
            'first_attempt_tokens': int(number(first, 'token_usage')),
            'recovery_tokens': int(sum(number(r, 'token_usage') for r in later)),
            'total_input_tokens': int(sum(number(r, 'input_tokens') for r in attempts)),
            'total_output_tokens': int(sum(number(r, 'output_tokens') for r in attempts)),
            'total_token_usage': int(sum(number(r, 'token_usage') for r in attempts)),
            'token_records_missing': sum(r.get('token_usage') in (None, '') for r in attempts),
            'total_generation_cost_usd': round(sum(number(r, 'generation_cost') for r in attempts), 6)
                if all(r.get('generation_cost') not in (None, '') for r in attempts) else '',
            'latest_run_id': latest['run_id'],
            'final_failure_reason': '' if successful else latest.get('failure_reason', ''),
            'final_failure_detail': '' if successful else failures[-1]['failure_detail'],
            'failure_history': json.dumps(failures, ensure_ascii=False),
            'poster_path': successful.get('poster_path', '') if successful else '',
        })
    summary = {
        'generated_at': runner.now_utc(), 'posters': len(posters),
        'first_attempt_successes': sum(p['first_attempt_success'] for p in posters),
        'first_attempt_failures': sum(not p['first_attempt_success'] for p in posters),
        'recovery_attempts': len(recoveries),
        'finished_after_recovery': sum(p['workflow_success'] and not p['first_attempt_success'] for p in posters),
        'still_failed': sum(not p['workflow_success'] for p in posters),
        'posters_requiring_recovery': sum(p['needed_checkpoint_recovery'] for p in posters),
        'posters_using_checkpoints': sum(p['checkpoint_used'] for p in posters),
        'first_attempt_tokens': sum(p['first_attempt_tokens'] for p in posters),
        'recovery_tokens': sum(p['recovery_tokens'] for p in posters),
        'total_token_usage': sum(p['total_token_usage'] for p in posters),
        'token_records_missing': sum(p['token_records_missing'] for p in posters),
        'total_generation_cost_usd': round(sum(p['total_generation_cost_usd'] for p in posters), 6)
            if all(p['total_generation_cost_usd'] != '' for p in posters) else None,
        'scope': {'papers': papers, 'models': models, 'dry_run': dry_run},
        'accounting': 'Recorded tokens only; recovery rows contain increments, not reused historical tokens. '
                      'Interrupted requests without provider usage can be undercounted. '
                      'Workflow success covers automatic checks; human visual review is separate.',
    }
    results.mkdir(parents=True, exist_ok=True)
    attempt_rows = []
    for first in original:
        attempt_rows.append({**first, 'original_run_id': first['run_id'],
            'parent_run_id': '', 'completion_attempt': 1, 'recovery_mode': 'initial_generation',
            'checkpoint_used': 0, 'reused_stages': '[]',
            'failure_detail': failure_detail(outputs / first['run_id'], first.get('failure_reason'))
                if str(first['workflow_success']) != '1' else ''})
    attempt_rows.extend(recoveries)
    write_csv(results / 'completion_attempts.csv',
              [{key: row.get(key, '') for key in RECOVERY_COLUMNS} for row in attempt_rows], RECOVERY_COLUMNS)
    write_csv(results / 'completion_by_poster.csv', posters)
    (results / 'completion_summary.json').write_text(json.dumps(summary, indent=2))
    lines = ['# Poster generation and checkpoint recovery', '',
             f"Generated: {summary['generated_at']}", '',
             f"- Posters: {len(posters)}",
             f"- Finished on first attempt: {summary['first_attempt_successes']}",
             f"- Finished after recovery: {summary['finished_after_recovery']}",
             f"- Still failed: {summary['still_failed']}",
             f"- Recovery attempts: {len(recoveries)}",
             f"- Posters using checkpoints: {summary['posters_using_checkpoints']}",
             f"- First-attempt tokens: {summary['first_attempt_tokens']:,}",
             f"- Additional recovery tokens: {summary['recovery_tokens']:,}",
             f"- Combined tokens: {summary['total_token_usage']:,}",
             f"- Combined generation cost (USD): {summary['total_generation_cost_usd']}", '',
             '| Paper | Model | Outcome | Completion attempts | Checkpoint used | Total tokens |',
             '|---|---|---|---:|---|---:|']
    for p in posters:
        outcome = (f"Finished on attempt {p['success_on_attempt']}" if p['workflow_success']
                   else f"Failed: {p['final_failure_reason']}")
        lines.append(f"| {p['input_paper_id']} | {p['llm_model']} | {outcome} | "
                     f"{p['completion_attempts']} | {'yes' if p['checkpoint_used'] else 'no'} | "
                     f"{p['total_token_usage']:,} |")
    lines.extend(['', 'Detailed failure reasons, checkpoint run IDs and all per-poster totals: '
                  '[completion_by_poster.csv](completion_by_poster.csv).', '', summary['accounting'], ''])
    (results / 'completion_summary.md').write_text('\n'.join(lines))
    print(f"Summary: {summary['first_attempt_successes']} first-attempt successes, "
          f"{summary['finished_after_recovery']} recovered, {summary['still_failed']} failed; "
          f"tokens {summary['first_attempt_tokens']:,} + {summary['recovery_tokens']:,} "
          f"= {summary['total_token_usage']:,}. Reports: {results}", flush=True)
    return summary


def recovery_environment(cfg):
    """Use the same gateway and generation settings as the archived attempt."""
    import os
    gateway, p2c = cfg['gateway'], cfg['fixed']['paper2poster']
    key, url = os.environ.get(gateway['api_key_env']), os.environ.get(gateway['base_url_env'])
    if not key or not url:
        raise ValueError('Load gateway credentials before --retry-failed (same as generation).')
    env = dict(os.environ, OPENAI_API_KEY=key, OPENAI_BASE_URL=url,
               OPENAI_COMPATIBILIY_API_KEY=key, OPENAI_COMPATIBILIY_API_BASE_URL=url)
    env.setdefault('HF_HUB_DISABLE_XET', '1')
    env.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '120')
    if p2c.get('max_output_tokens'):
        env['P2P_MAX_OUTPUT_TOKENS'] = str(p2c['max_output_tokens'])
    temperature = cfg['fixed'].get('generation', {}).get('temperature')
    if temperature is not None:
        env['P2P_TEMPERATURE'] = str(temperature)
    return env


def checkpoint_source(outputs, first, history):
    """Use the latest surviving archive within this original run's lineage."""
    candidates = [first, *sorted(history, key=lambda r: int(r['completion_attempt']))]
    for record in reversed(candidates):
        directory = outputs / str(record['run_id'])
        if all((directory / name).is_file() for name in ('run_config.yaml', 'run_metadata.json')):
            return record
    raise ValueError(f"No saved configuration/metadata survives for original run {first['run_id']}. "
                     'Restore an archive for this paper/model before checkpoint recovery.')


def recover_one(harness, first, parent, history, cfg, outputs, run_id, prices, as_of, env):
    source_record = checkpoint_source(outputs, first, history)
    source, target = outputs / str(source_record['run_id']), outputs / str(run_id)
    metadata = json.loads((source / 'run_metadata.json').read_text())
    if (metadata['input_paper_id'], metadata['llm_model']) != (first['input_paper_id'], first['llm_model']):
        raise ValueError('Recovery source paper/model does not match the original attempt')
    target.mkdir()  # never overwrite another attempt
    for name in ('preparation', 'intermediate'):
        if (source / name).exists():
            shutil.copytree(source / name, target / name)
    # detail_log stays cumulative for checkpoint accounting. Only its delta is billed
    # to this recovery attempt in recovery_attempts.csv.
    if (source / 'detail_log.json').exists():
        shutil.copyfile(source / 'detail_log.json', target / 'detail_log.json')
    baseline = runner.read_tokens(target)
    prior_tokens = int(number(first, 'token_usage') + sum(number(r, 'token_usage') for r in history))
    completion_attempt = 2 + len(history)
    render_only = (target / 'intermediate/tree_split.json').exists()
    previous_error = source_record.get('failure_detail') or failure_detail(source, source_record.get('failure_reason'))
    row = {**first, 'run_id': run_id, 'original_run_id': first['run_id'],
           'parent_run_id': parent['run_id'], 'completion_attempt': completion_attempt,
           'previous_failure_reason': parent.get('failure_reason', ''),
           'checkpoint_source': str(source.relative_to(harness)),
           'checkpoint_fallback_reason': (f"Latest attempt {parent['run_id']} archive missing or incomplete; "
                                          f"using surviving run {source_record['run_id']}"
                                          if str(source_record['run_id']) != str(parent['run_id']) else ''),
           'recovery_mode': 'local_render' if render_only else 'checkpoint_generation',
           'original_prompt_sha256': first['prompt_sha256'], 'started_at': runner.now_utc(),
           'workflow_success': 0, 'poster_path': '', 'poster_word_count': '',
           'failure_reason': '', 'visual_check': '', 'failure_detail': '',
           'prior_token_usage': prior_tokens, 'retries': 0}
    row['prompt_sha256'] = runner.prompt_sha256(runner.resolve(cfg['fixed']['paper2poster']['path']))
    row['config_sha256'] = runner.config_sha256(cfg)
    feedback_path = None
    rejected = source / 'intermediate/planner_response.txt'
    if not render_only and rejected.exists():
        feedback_path = target / 'planning_feedback.json'
        feedback_path.write_text(json.dumps({'failure': previous_error,
                                              'previous_response': rejected.read_text()}, indent=2))
        row['feedback_sha256'] = runner.hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    (target / 'run_metadata.json').write_text(json.dumps(metadata, indent=2))
    (target / 'run_config.yaml').write_text(yaml.safe_dump(cfg))
    audit = target / 'recovery_attempt.json'
    audit.write_text(json.dumps({'status': 'running', 'record': row,
                                'baseline_tokens': baseline}, indent=2))
    start = time.monotonic()
    interrupted = False
    try:
        if render_only:
            with (target / 'run.log').open('a') as log:
                log.write(f"Recovery attempt {completion_attempt}: local render from {source}\n")
            result = runner.rebuild_saved(target)
            row.update(workflow_success=result['workflow_success'],
                       failure_reason=result.get('failure_reason', ''),
                       poster_word_count=result.get('poster_word_count', ''),
                       failure_detail=result.get('error', ''))
            if row['workflow_success']:
                name = runner.poster_stem(first['input_paper_id'], first['llm_model'])
                row['poster_path'] = str((target / 'latex' / f'{name}.pdf').relative_to(harness))
        else:
            result = runner.run_attempt(run_id=run_id, model=first['llm_model'],
                paper_id=first['input_paper_id'],
                pdf=runner.resolve(cfg['fixed']['papers_dir']) / f"{first['input_paper_id']}.pdf",
                cfg=cfg, out_root=outputs, env=env, planning_feedback=feedback_path)
            row.update(result)
    except (Exception, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        row.update(workflow_success=0, failure_reason='E_INTERRUPTED' if interrupted else 'E_PIPELINE',
                   failure_detail=f'{type(exc).__name__}: {exc}')
        with (target / 'run.log').open('a') as log:
            log.write(f"\n=== harness: recovery failed: {row['failure_detail']}\n")
    row['finished_at'] = runner.now_utc()
    row['latency'] = round(time.monotonic() - start, 2)
    after = runner.read_tokens(target)
    for key in TOKEN_COLUMNS:
        delta = after.get(key, 0) - baseline.get(key, 0)
        if delta < 0:
            raise ValueError('Token accounting decreased during recovery')
        row[key] = delta
    row['generation_cost'] = runner.token_cost(prices, first['llm_model'], row['input_tokens'], row['output_tokens'])
    row['vision_cost'] = 0
    row['price_table_as_of'] = as_of
    row['cumulative_token_usage'] = prior_tokens + row['token_usage']
    costs = [first, *history, row]
    row['cumulative_generation_cost'] = round(sum(number(r, 'generation_cost') for r in costs), 6) \
        if all(r.get('generation_cost') not in (None, '') for r in costs) else ''
    cache_report = target / 'cache_usage.json'
    reused = json.loads(cache_report.read_text()).get('reused_stages', []) if cache_report.exists() else []
    if render_only:
        reused = ['saved_layout', 'saved_summaries', 'saved_figures']
    row['reused_stages'] = json.dumps(reused)
    row['checkpoint_used'] = int(bool(reused))
    if not row['workflow_success']:
        row['failure_detail'] = row['failure_detail'] or failure_detail(target, row['failure_reason'])
        row['poster_path'] = ''
    audit.write_text(json.dumps({'status': 'complete', 'record': row,
                                'baseline_tokens': baseline, 'cumulative_detail_tokens': after}, indent=2))
    return row, interrupted


def recover_batch(harness, *, dry_run=False, papers=None, models=None, config_path=None):
    data, outputs, _ = locations(harness, dry_run)
    lock = runner.acquire_run_lock(data)
    original, recoveries = selected_rows(data, papers, models)
    runner.configure_tex_path()
    if any(not shutil.which(name) for name in ('latexmk', 'xelatex', 'pdftoppm', 'pdftotext')):
        raise ValueError('Required LaTeX/Poppler executables are missing')
    # Do not overlap an unfinished normal generation attempt or an abruptly killed
    # recovery: its accounting must be resolved before allocating more attempts.
    known = {r['run_id'] for r in runner.read_runs(data / 'runs.csv')}
    known.update(r['run_id'] for r in runner.read_runs(data / 'recovery_attempts.csv'))
    orphaned = [p.name for p in outputs.iterdir() if p.is_dir() and p.name.isdigit() and p.name not in known]
    if orphaned:
        raise ValueError(f'Unrecorded/in-progress output runs {orphaned}; resolve these before recovery')
    next_id = max(map(int, known), default=0) + 1
    attempted = 0
    for first in original:
        history = sorted([r for r in recoveries if r['original_run_id'] == first['run_id']],
                         key=lambda r: int(r['completion_attempt']))
        if any(str(r['workflow_success']) == '1' for r in [first, *history]):
            continue
        parent = history[-1] if history else first
        source_record = checkpoint_source(outputs, first, history)
        saved = outputs / str(source_record['run_id']) / 'run_config.yaml'
        if str(source_record['run_id']) != str(parent['run_id']):
            print(f"Original run {first['run_id']}: latest archive {parent['run_id']} is missing/incomplete; "
                  f"reusing saved run {source_record['run_id']}. Interrupted attempt history is preserved.", flush=True)
        cfg = yaml.safe_load((config_path or saved).read_text())
        # Recovery keeps the generation settings that produced these checkpoints.
        if runner.config_sha256(cfg) != first['config_sha256']:
            raise ValueError('Recovery configuration differs from original fixed settings')
        p2c = cfg['fixed']['paper2poster']
        runner.check_p2p_commit(runner.resolve(p2c['path']), p2c['commit'], runner.resolve(p2c['patch']))
        prices, as_of = runner.load_prices(runner.resolve(cfg['fixed'].get('prices_file', 'config/prices.yaml')))
        cap = cfg['experiment'].get('spend_cap_usd')
        all_rows = runner.read_runs(data / 'runs.csv') + runner.read_runs(data / 'recovery_attempts.csv')
        if cap is not None and (any(r.get('generation_cost') in (None, '') for r in all_rows)
                                or sum(runner.run_cost(r) for r in all_rows) >= cap):
            print('Recovery stopped: spend cap reached or cost accounting incomplete.', flush=True)
            break
        env = recovery_environment(cfg)
        print(f"[recovery run {next_id}] original {first['run_id']}: {first['llm_model']} × "
              f"{first['input_paper_id']} (completion attempt {len(history) + 2}) ...", flush=True)
        row, interrupted = recover_one(harness, first, parent, history, cfg, outputs, next_id, prices, as_of, env)
        existing = runner.read_runs(data / 'recovery_attempts.csv')
        write_csv(data / 'recovery_attempts.csv', [*existing, row], RECOVERY_COLUMNS)
        recoveries.append(row)
        attempted += 1
        print(f"[recovery run {next_id}] {'ok' if row['workflow_success'] else row['failure_reason']} "
              f"new tokens={row['token_usage']} cumulative={row['cumulative_token_usage']} "
              f"checkpoint={row['reused_stages']}", flush=True)
        write_summary(harness, dry_run=dry_run, papers=papers, models=models)
        next_id += 1
        if interrupted or row.get('failure_reason') == 'E_BUDGET':
            break
    if not attempted:
        write_summary(harness, dry_run=dry_run, papers=papers, models=models)
    # Keep the advisory lock alive throughout the batch.
    lock.close()
