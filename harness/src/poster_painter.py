"""Painter: rewrite the parser's section summaries into poster text (one model call).

Paper2Poster's PosterAgent is Parser -> Planner -> Painter -> Commenter. The Parser
keeps the paper's raw text ("keep as much raw text as possible", ~500 words per
section); the Painter (upstream bullet_point_agent, one call per section) turns it into
bullets with bold key terms; the Commenter (a vision model) flags overflow. The
pinned LaTeX demo skips the Painter and typesets the raw parser text, which is what
latex-only-v2 did. This module restores the Painter as one call for the whole poster,
using the copy-density defaults of upstream's own poster skill
(skills/references/poster-defaults.md: 250-500 words of body copy). The text style
follows the README poster ("Paper2Poster for Paper2Poster"): each section is a short
paragraph with highlighted key terms; only sections that list parallel items (results,
contributions, limitations) add a few bullets.

The Commenter's job (overflow) is done locally from the LaTeX log; only when a poster
still overflows at the smallest allowed font scale does `shorten` make one more call.

Calls go through gateway_chat.GatewayChat after the shared source prefix
(combined_planner.source_block), so with prompt caching they read it from the cache.
The Commenter's other job (too much blank space) is also measured locally: when a column
ends far above the page bottom, `expand` makes one call that lengthens that column's
sections with facts from the source that are not yet on the poster.

Usage (follow-up calls, run by the Runner from the Paper2Poster directory):
    python poster_painter.py --repair --intermediate_dir DIR --usage_path FILE \
        --model_name_t MODEL --factor 0.8 [--prompt_cache]
    python poster_painter.py --expand --intermediate_dir DIR --usage_path FILE \
        --model_name_t MODEL --targets '{"Results": 90}' [--prompt_cache]
"""
from __future__ import annotations

import json
import re

TITLE_PREFIX = 'poster title'

RULES = """Rules:
1. Keep every section listed below. Use its exact title as the JSON key.
2. Stay within each section's word budget ("budget" = maximum words for the paragraph and
   any bullets together).
3. Write each section as one short paragraph of 2-4 plain sentences, most under 20 words,
   that reads well on its own. When a section lists three or more parallel items, such as
   separate results, contributions or limitations, put those items in 2-4 bullets after a
   one-sentence paragraph instead. Most sections are paragraphs only.
4. Use only facts from that section's text in the source. Copy numbers exactly, with their
   units and the baseline or comparison they refer to. Never invent, round or combine numbers.
5. Keep the paper's main claim, what was proposed, how it works, every headline
   quantitative result and the takeaway. Drop background detail, citations and repetition:
   state each number once on the whole poster (only the conclusion may restate the
   headline result), and use the space saved for results that are not yet on the poster.
6. Mark key terms and key numbers with **double asterisks**: one to four words each
   (a term, a number or a short phrase), at most two per sentence or bullet, never a whole
   clause.
7. When a section shows a figure or table ("visual" gives its caption), do not copy its
   values row by row; state its main takeaway in one sentence.
8. Plain text only: no Markdown tables, headings, LaTeX, citations or emoji."""

FORMAT = """Output: only a JSON object whose keys are the section titles copied exactly and whose values are {"paragraph": "...", "bullets": [...]} ("bullets" is [] for most sections), for example {"Motivation": {"paragraph": "Posters must convey a paper at a glance. **Long text** hides the **main result**.", "bullets": []}, "Results": {"paragraph": "**Method X** beats every baseline.", "bullets": ["Error falls by **12%** versus baseline Y", "Runs **3x** faster"]}}. No other text."""

PAINT_TASK = """Task: you are the Painter. Rewrite each poster section of the source into short text
that a conference visitor can read in seconds.
""" + RULES + "\n" + FORMAT + """
Sections:
"""

SHORTEN_TASK = """Task: the poster made from the source still overflows the page. Shorten each section below so its paragraph and bullets together fit its new "budget" (maximum words). Keep the most important facts and every headline number exactly as written; drop the least important sentences, bullets or words first. Keep the **double asterisk** marks on key terms, keep each section a short paragraph (bullets only where it already has them), use only facts already in the text, and keep the exact section titles.
""" + FORMAT + """
Sections:
"""

EXPAND_TASK = """Task: the poster made from the source has empty space at the bottom of the column holding the sections listed under "expand". Expand each of those sections to about its "budget" (maximum words for its paragraph and bullets together) by adding facts from that section's text in the source that are not yet on the poster: further results with their numbers, method details, or what the result means. Keep the existing text and its **double asterisk** marks, keep each section a short paragraph (bullets only where it already has them or for three or more parallel items), never repeat a number that is already anywhere on the poster, and never invent anything. Return only the sections listed under "expand".
""" + FORMAT + """
Poster and sections to expand:
"""

DEFAULTS = {'total_words': 450, 'min_section_words': 35, 'max_section_words': 110,
            'max_bullets': 4, 'length_tolerance': 1.5, 'blank_min_frac': 0.10, 'blank_fill_share': 0.8}
NUMBER = re.compile(r'\d+(?:[.,]\d+)*')


def is_title_section(title: str) -> bool:
    return str(title).strip().lower().startswith(TITLE_PREFIX)


def body_sections(document: dict) -> list[dict]:
    return [s for s in document['sections'] if not is_title_section(s.get('title', ''))]


def word_count(text: str) -> int:
    return len(text.replace('**', '').split())


def word_budgets(document: dict, settings: dict | None = None) -> dict[str, int]:
    """Words per section, proportional to the parser's section length (upstream: important
    sections get longer content), within [min_section_words, max_section_words]."""
    s = {**DEFAULTS, **(settings or {})}
    sections = body_sections(document)
    lengths = {x['title']: max(1, word_count(x.get('content', ''))) for x in sections}
    total = sum(lengths.values()) or 1
    return {t: int(min(s['max_section_words'], max(s['min_section_words'], round(s['total_words'] * n / total))))
            for t, n in lengths.items()}


def visual_captions(plan: dict, images: dict, tables: dict) -> dict[str, str]:
    captions = {}
    for title, selection in (plan or {}).items():
        kind, identifier = next(iter(selection.items()))
        source = images if kind == 'image' else tables
        captions[title] = source.get(str(identifier), {}).get('caption', '')
    return captions


def paint_input(document, budgets, captions):
    """Budgets and visuals per section; the section text itself is in the shared source."""
    return [{'title': s['title'], 'budget': budgets[s['title']],
             **({'visual': captions[s['title']]} if captions.get(s['title']) else {})}
            for s in body_sections(document)]


def _norm(title: str) -> str:
    return ' '.join(str(title).casefold().replace('&', 'and').split())


def section_words(section: dict) -> int:
    return word_count(section['paragraph']) + sum(word_count(b) for b in section['bullets'])


def validate_sections(response, budgets: dict[str, int], settings: dict | None = None) -> dict[str, dict]:
    """Check the Painter's JSON locally; raise ValueError when it is unusable.

    Each section must have a paragraph (no section is bullets only) and at most
    max_bullets bullets. Returns {title: {"paragraph": str, "bullets": [str]}}.
    """
    s = {**DEFAULTS, **(settings or {})}
    if isinstance(response, dict) and set(response) == {'sections'} and isinstance(response['sections'], dict):
        response = response['sections']
    if not isinstance(response, dict):
        raise ValueError('Painter output must be a JSON object of section title -> {paragraph, bullets}')
    by_norm = {_norm(t): t for t in budgets}
    clean = {}
    for key, value in response.items():
        title = key if key in budgets else by_norm.get(_norm(key))
        if title is None:
            raise ValueError(f'Painter returned an unknown section: {key!r}')
        if title in clean:
            raise ValueError(f'Painter returned section twice: {title!r}')
        if isinstance(value, str):
            value = {'paragraph': value, 'bullets': []}
        if not isinstance(value, dict) or not isinstance(value.get('paragraph'), str):
            raise ValueError(f'Painter section {title!r} needs a "paragraph" string')
        paragraph = ' '.join(value['paragraph'].split())
        bullets = value.get('bullets') or []
        if not isinstance(bullets, list) or not all(isinstance(b, str) for b in bullets):
            raise ValueError(f'Painter bullets for {title!r} must be a list of strings')
        bullets = [b for b in (re.sub(r'^\s*(?:[-*•]|\d+[.)])\s+', '', x).strip() for x in bullets) if b]
        if not paragraph:
            raise ValueError(f'Painter section {title!r} has no paragraph')
        if len(bullets) > s['max_bullets']:
            raise ValueError(f'Painter gave {len(bullets)} bullets for {title!r} (at most {s["max_bullets"]})')
        if any(t.lstrip().startswith(('|', '#')) for t in [paragraph, *bullets]):
            raise ValueError(f'Painter used a table or heading in {title!r}')
        clean[title] = {'paragraph': paragraph, 'bullets': bullets}
    missing = [t for t in budgets if t not in clean]
    if missing:
        raise ValueError(f'Painter dropped sections: {missing}')
    words = sum(section_words(v) for v in clean.values())
    limit = s['length_tolerance'] * sum(budgets.values())
    if words > limit:
        raise ValueError(f'Painter wrote {words} words; budget {sum(budgets.values())} (limit {limit:.0f})')
    return clean


def unsupported_numbers(sections: dict[str, dict], document: dict, captions: dict[str, str]) -> dict:
    """Numbers in the poster text that appear nowhere in the parser text or captions (audit only)."""
    source = ' '.join([s.get('content', '') for s in document['sections']] + list(captions.values()))
    known = {n.replace(',', '') for n in NUMBER.findall(source)}
    found = {}
    for title, sec in sections.items():
        text = ' '.join([sec['paragraph'], *sec['bullets']])
        missing = sorted({n for n in NUMBER.findall(text) if n.replace(',', '') not in known})
        if missing:
            found[title] = missing
    return found


def painted_document(document: dict, sections: dict[str, dict]) -> dict:
    """The parser document with each body section's content replaced by its paragraph and bullets."""
    out = json.loads(json.dumps(document))
    for section in out['sections']:
        if section['title'] in sections:
            sec = sections[section['title']]
            section['content'] = '\n'.join([sec['paragraph'], *(f'• {b}' for b in sec['bullets'])])
    return out


def report_of(sections: dict[str, dict]) -> dict:
    return {'words': {t: section_words(v) for t, v in sections.items()},
            'sections_with_bullets': sorted(t for t, v in sections.items() if v['bullets'])}


def _ask_valid(ask, stage, blocks, budgets, settings, max_attempts, raw_path):
    """Up to max_attempts calls (ask records each one's usage); locally validated."""
    from utils.src.utils import get_json_from_response
    from combined_planner import SHARED_SYSTEM
    problem = None
    for attempt in range(1, max_attempts + 1):
        text = ask(stage, SHARED_SYSTEM, blocks, cache=True)
        if raw_path is not None:
            raw_path.write_text(text)
        try:
            return validate_sections(get_json_from_response(text), budgets, settings)
        except Exception as exc:  # unparseable or invalid output; transport errors are raised by ask()
            problem = exc
            print(f'Painter output unusable ({exc}); attempt {attempt} of {max_attempts}.', flush=True)
    raise ValueError(f'Painter output unusable after {max_attempts} attempts: {problem}')


def paint_sections(document, plan, images, tables, ask, settings=None, max_attempts=2, raw_path=None):
    """One Painter call (bounded retries) after the shared cached source. Returns (painted, report)."""
    from combined_planner import source_block
    budgets = word_budgets(document, settings)
    captions = visual_captions(plan, images, tables)
    task = PAINT_TASK + json.dumps(paint_input(document, budgets, captions), ensure_ascii=False,
                                   separators=(',', ':'))
    sections = _ask_valid(ask, 'painter', [source_block(document, images, tables), task], budgets,
                          settings, max_attempts, raw_path)
    report = {'budgets': budgets, **report_of(sections),
              'unsupported_numbers': unsupported_numbers(sections, document, captions)}
    return painted_document(document, sections), report


def current_sections(painted: dict) -> dict[str, dict]:
    """Paragraph and bullets of each body section of a painted document."""
    out = {}
    for section in body_sections(painted):
        lines = [l.strip() for l in section.get('content', '').splitlines() if l.strip()]
        out[section['title']] = {'paragraph': ' '.join(l for l in lines if not l.startswith('•')),
                                 'bullets': [l.lstrip('•').strip() for l in lines if l.startswith('•')]}
    return out


def shorten(painted, document, images, tables, ask, factor, settings=None, max_attempts=2, raw_path=None):
    """Overflow repair: one call that cuts every section to factor x its current length.
    It sends the same source prefix as the Planner and Painter, so it is read from the cache."""
    from combined_planner import source_block
    s = {**DEFAULTS, **(settings or {})}
    current = current_sections(painted)
    budgets = {t: max(15, int(factor * section_words(v))) for t, v in current.items()}
    payload = [{'title': t, 'budget': budgets[t], **v} for t, v in current.items()]
    task = SHORTEN_TASK + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    new = _ask_valid(ask, 'painter_repair', [source_block(document, images, tables), task], budgets,
                     {**s, 'length_tolerance': 1.2}, max_attempts, raw_path)
    return painted_document(painted, new), {'factor': factor, 'budgets': budgets, **report_of(new)}


def expansion_targets(fit: dict, painted: dict, settings: dict | None = None) -> dict[str, int]:
    """Word budgets for the sections of each column whose empty space exceeds blank_min_frac
    of the page; {} when no column needs it (the Commenter's "too much blank space").

    Words per point of text height come from the rendered poster itself (fit.json layout:
    section text heights measured between markers), so a column's gap converts to words at
    the poster's own font size. A share (blank_fill_share) of the gap is filled, so the
    expanded poster still fits; the gap is shared by the column's sections in proportion to
    their current length, and no section more than doubles.
    """
    s = {**DEFAULTS, **(settings or {})}
    layout, page_h = fit.get('layout') or {}, fit.get('page_height_pt') or 0.0
    heights = layout.get('text_height_pt') or {}
    if not heights or not page_h or not painted.get('sections'):
        return {}
    words = {t: section_words(v) for t, v in current_sections(painted).items()}
    measured = [t for t in words if heights.get(t, 0) > 0]
    if not measured:
        return {}
    density = sum(words[t] for t in measured) / sum(heights[t] for t in measured)  # words per pt
    targets = {}
    for column, gap in zip(layout.get('columns') or [], layout.get('column_gap_pt') or []):
        column = [t for t in column if t in words]
        if gap < s['blank_min_frac'] * page_h or not column:
            continue
        extra = s['blank_fill_share'] * gap * density
        total = sum(words[t] for t in column) or 1
        for t in column:
            targets[t] = min(2 * words[t], words[t] + int(extra * words[t] / total))
    return {t: n for t, n in targets.items() if n > words[t]}


def expand(painted, document, images, tables, ask, targets, settings=None, max_attempts=2, raw_path=None):
    """Blank-space step: one call that lengthens the sections of under-filled columns.
    It sends the same source prefix as the Planner and Painter, so it is read from the cache."""
    from combined_planner import source_block
    s = {**DEFAULTS, **(settings or {})}
    current = current_sections(painted)
    payload = {'poster': [{'title': t, **v} for t, v in current.items()],
               'expand': [{'title': t, 'budget': n} for t, n in targets.items()]}
    task = EXPAND_TASK + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    new = _ask_valid(ask, 'painter_expand', [source_block(document, images, tables), task], targets,
                     {**s, 'length_tolerance': 1.15}, max_attempts, raw_path)
    captions = {k: v.get('caption', '') for k, v in [*images.items(), *tables.items()]}
    return painted_document(painted, new), {'targets': targets, **report_of(new),
                                            'unsupported_numbers': unsupported_numbers(new, document, captions)}


def main():
    import argparse
    import os
    import sys
    from pathlib import Path
    from gateway_chat import GatewayChat
    ap = argparse.ArgumentParser(description='Painter follow-up call: shorten (overflow) or expand (blank space)')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--repair', action='store_true', help='shorten every section (poster overflows)')
    mode.add_argument('--expand', action='store_true', help='lengthen sections of under-filled columns')
    ap.add_argument('--intermediate_dir', required=True)
    ap.add_argument('--usage_path', required=True)
    ap.add_argument('--model_name_t', required=True)
    ap.add_argument('--factor', type=float, help='--repair: share of current words to keep')
    ap.add_argument('--targets', help='--expand: JSON {section title: word budget}')
    ap.add_argument('--max_attempts', type=int, default=2)
    ap.add_argument('--settings', default='{}')
    ap.add_argument('--prompt_cache', action='store_true', help='send cache breakpoints (model needs markers)')
    args = ap.parse_args()
    if args.repair and args.factor is None or args.expand and not args.targets:
        ap.error('--repair needs --factor; --expand needs --targets')
    sys.path.insert(0, os.getcwd())  # Paper2Poster's utils (JSON repair)

    inter, usage_path = Path(args.intermediate_dir), Path(args.usage_path)
    usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
    save = lambda: usage_path.write_text(json.dumps(usage, indent=2))
    chat = GatewayChat(args.model_name_t, inter / 'calls', usage, save, cache_markers=args.prompt_cache)
    load = lambda name: json.loads((inter / name).read_text())
    painted = load('painted_content.json')
    name = 'repair' if args.repair else 'expand'
    (inter / f'painted_content.before_{name}.json').write_text(json.dumps(painted, ensure_ascii=False, indent=2))
    inputs = (painted, load('raw_content.json'), load('images.json'), load('tables.json'), chat.ask)
    if args.repair:
        new, report = shorten(*inputs, args.factor, json.loads(args.settings), args.max_attempts,
                              inter / 'painter_repair_response.txt')
    else:
        new, report = expand(*inputs, json.loads(args.targets), json.loads(args.settings), args.max_attempts,
                             inter / 'painter_expand_response.txt')
    (inter / 'painted_content.json').write_text(json.dumps(new, ensure_ascii=False, indent=2))
    (inter / f'painter_{name}.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
