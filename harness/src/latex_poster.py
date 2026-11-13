"""Build the LaTeX version of a run's poster with Paper2Poster's own demo builder.

Paper2Poster's README poster comes from demo/posterbuilder, not from the PPTX that
new_pipeline writes: it typesets the parser's section summaries (raw_content) and the
panel/figure arrangement into the beamerposter "gemini" template. This script does
the same for a harness run, from the files the Runner saved in
outputs/<run_id>/intermediate/, without editing anything in vendor/.

Three fixes make the pinned demo build at all: real fonts from assets/fonts/ replace
the Git LFS pointers, the template's unterminated headline TikZ node is closed, and
the \\textpaddingtop/bottom lengths it sets (unused by the theme) are defined.

Rendering rules, identical for every run:
  - page size is fixed.paper2poster.poster_{width,height}_inches; no footer (the
    demo's footer advertises Paper2Poster, and a footer could break blinding);
  - the left logo is the configured institution logo; the right logo is removed;
  - the "Poster Title & Authors" section is dropped (the demo's filter misses the
    "Authors" spelling); table captions are used as well as figure captions, and
    captions are printed as written (they already start with "Fig. 1." / "Table 3.");
  - the section text is the Painter's bullets (intermediate/painted_content.json) when
    the run has them, otherwise the parser text (raw_content.json, latex-only-v2);
  - section text keeps its structure: Markdown table lines become tables, "•" or "-"
    lines become lists, blank lines start paragraphs (the demo joins everything);
    **key terms** become bold accent-coloured text;
  - sections are split into the three columns in reading order, balancing estimated
    height, then re-balanced with the block heights measured in the compiled PDF;
  - auto-fit: the beamerposter scale steps down from 1.5 to fixed.paper2poster.min_font_scale
    until no column runs into the bottom margin and no line sticks out of its column
    (LaTeX log and \pdfsavepos markers). Columns left with empty space get their figures
    enlarged (up to the column width). fit.json records the scale, the overflow in both
    directions and the figure widths; a poster that still does not fit fails (E_OVERFLOW)
    rather than being cut off.

Usage (from harness/):
    python src/latex_poster.py outputs/dry_run/1 [outputs/dry_run/2 ...]
Writes outputs/<run_id>/latex/<paper_id> x <model>.pdf and .png,
plus poster.tex, fit.json and build.log. Copies the PDF and PNG into
outputs/posters/<paper_id lowercase>/ alongside the other models' posters.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

from poster_naming import group_poster_exports, run_poster_stem

HARNESS = Path(__file__).resolve().parent.parent
SCALES = [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.95, 0.9, 0.85, 0.8, 0.76, 0.72, 0.68, 0.64, 0.6]
FIT_TOLERANCE_PT = 5.0
HBOX_TOLERANCE_PT = 10.0      # a line sticking out of its column by more than this is a cutoff
BOTTOM_MARGIN_FRAC = 0.015    # content must end this far above the page bottom
FILL_MIN_FRAC = 0.02          # a column with more empty space than this gets larger figures
FILL_SAFETY_PT = 12.0
FIG_MAX_WIDTH = 1.0           # of \linewidth
FIG_MAX_HEIGHT_FRAC = 0.4     # of the page height, so one figure never fills a column
TABLE_MAX_GROWTH = 1.2       # a table image grows at most this much (its text must stay near body size)
SHRINK_FIGURES = 0.8          # last local resort before failing: figures at 80% width
SP_PER_PT = 65536
SOURCE_DATE_EPOCH = "1767225600"  # 2026-01-01 UTC: fixed PDF dates and IDs, so rebuilds are byte-identical
# Height estimate for column balancing, in "characters of body text":
# one column-width of height is about 3000 characters, a block title about 150.
CHARS_PER_COLWIDTH = 3000
CHARS_PER_TITLE = 150
CHARS_PER_TABLE_ROW = 80


def configure_tex_path() -> None:
    """Use the project-local TinyTeX when TeX is absent from PATH."""
    if not shutil.which("xelatex"):
        for executable in sorted((HARNESS / "vendor/TinyTeX/bin").glob("*/xelatex")):
            os.environ["PATH"] = str(executable.parent) + os.pathsep + os.environ.get("PATH", "")
            break


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else HARNESS / path


LATIN_TWINS = {"ALPHA": "A", "BETA": "B", "EPSILON": "E", "ZETA": "Z", "ETA": "H", "IOTA": "I", "KAPPA": "K",
               "MU": "M", "NU": "N", "OMICRON": "O", "RHO": "P", "TAU": "T", "CHI": "X"}
GREEK_CAPITALS = {"GAMMA", "DELTA", "THETA", "LAMDA", "XI", "PI", "SIGMA", "UPSILON", "PHI", "PSI", "OMEGA"}
MATH_SYMBOLS = {"≈": r"\approx", "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "±": r"\pm", "×": r"\times",
                "÷": r"\div", "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
                "↑": r"\uparrow", "↓": r"\downarrow", "∼": r"\sim", "∞": r"\infty", "√": r"\surd",
                "∑": r"\sum", "∈": r"\in", "·": r"\cdot", "∝": r"\propto", "⊂": r"\subset",
                "≪": r"\ll", "≫": r"\gg", "∂": r"\partial", "∇": r"\nabla", "∆": r"\Delta"}
MISSING = re.compile(r"Missing character: There is no (.) \(U\+([0-9A-F]+)\)")


def math_glyph(ch: str) -> str | None:
    """LaTeX math for a Greek letter or math symbol the poster's text fonts lack (Lato has no Greek)."""
    import unicodedata
    if ch in MATH_SYMBOLS:
        return MATH_SYMBOLS[ch]
    name = unicodedata.name(ch, "")
    for prefix in ("GREEK SMALL LETTER ", "GREEK CAPITAL LETTER "):
        if name.startswith(prefix) and " " not in name[len(prefix):]:
            letter = name[len(prefix):]
            command = {"LAMDA": "lambda", "OMICRON": None}.get(letter, letter.lower())
            if prefix.startswith("GREEK SMALL"):
                return "o" if command is None else "\\" + command
            if letter in GREEK_CAPITALS:
                return "\\" + command.capitalize()
            return LATIN_TWINS.get(letter)  # capitals that look Latin: the Latin letter
    return None


def text_symbols(text: str) -> str:
    """Greek letters and math symbols in poster text -> \\ensuremath{...}; applied after escaping."""
    out = []
    for ch in text:
        glyph = math_glyph(ch) if ord(ch) > 127 else None
        out.append(f"\\ensuremath{{{glyph}}}" if glyph and glyph.startswith("\\") else glyph or ch)
    return "".join(out)


def keyterms(text: str) -> str:
    """**term** (Painter's emphasis) -> \\keyterm{term}; applied after LaTeX escaping."""
    return re.sub(r"\*\*(.+?)\*\*", r"\\keyterm{\1}", text)


def format_content(content: str, escape) -> str:
    """Section text to LaTeX, keeping tables, lists and paragraphs."""
    out, para, items, rows = [], [], [], []
    plain = escape
    escape = lambda text: keyterms(plain(text))

    def flush():
        if para:
            out.append(escape(" ".join(para)))
            para.clear()
        if items or rows:
            out.append("")  # end the paragraph so the list/table starts on its own line
        if items:
            out.append("\\begin{itemize}\n" + "\n".join(f"\\item {escape(i)}" for i in items) + "\n\\end{itemize}")
            items.clear()
        if rows:
            n = max(len(r) for r in rows)
            rows_ = [r + [""] * (n - len(r)) for r in rows]
            spec = r">{\raggedright\arraybackslash}X" + r" >{\centering\arraybackslash}X" * (n - 1)
            body = [" & ".join(f"\\textbf{{{escape(c)}}}" for c in rows_[0]) + r" \\ \midrule"]
            body += [" & ".join(escape(c) for c in r) + r" \\" for r in rows_[1:]]
            out.append("{\\begin{tabularx}{\\linewidth}{" + spec + "}\n\\toprule\n"
                       + "\n".join(body) + "\n\\bottomrule\n\\end{tabularx}}")
            out.append("")
            rows.clear()

    for line in content.splitlines():
        s = line.strip()
        if s.startswith("|"):
            if para or items:
                flush()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):  # skip |---| separator rows
                rows.append(cells)
        elif s.startswith(("•", "- ")):
            if para or rows:
                flush()
            items.append(s.lstrip("•-").strip())
        elif s:
            if items or rows:
                flush()
            para.append(s)
        else:
            flush()
            out.append("")
    flush()
    return "\n".join(r"\par" if x == "" else x for x in out).strip()


def block_weight(block: str, figures_dir: Path) -> float:
    w = CHARS_PER_TITLE + CHARS_PER_TABLE_ROW * block.count(r"\\")
    for m in re.finditer(r"\\includegraphics\[width=([\d.]+)\\linewidth\]\{figures/([^}]+)\}", block):
        try:
            with Image.open(figures_dir / m.group(2)) as im:
                w += float(m.group(1)) * im.height / im.width * CHARS_PER_COLWIDTH
        except OSError:
            w += 0.5 * CHARS_PER_COLWIDTH
    text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "", block, flags=re.S)
    return w + len(re.sub(r"\\[a-zA-Z]+(\[[^]]*\])?|[{}]", "", text))


def balanced_split(weights: list[float], n_cols: int) -> list[int]:
    """Contiguous split of blocks into n_cols columns minimizing the tallest column."""
    n, best = len(weights), (float("inf"), [])
    def rec(start, cols_left, sizes, worst):
        nonlocal best
        if cols_left == 1:
            worst = max(worst, sum(weights[start:]))
            if worst < best[0]:
                best = (worst, sizes + [n - start])
            return
        for end in range(start, n + 1):
            rec(end, cols_left - 1, sizes + [end - start], max(worst, sum(weights[start:end])))
    rec(0, n_cols, [], 0.0)
    return best[1]



MARK = re.compile(r"P2PB([SE]) (\d+) (-?\d+)")
TEXT_MARK = re.compile(r"P2PT([SE]) (\d+) (-?\d+)")
PAGE = re.compile(r"P2PPAGE ([\d.]+)pt ([\d.]+)pt ([\d.]+)pt")


def mark_block(i: int, block: str) -> str:
    """Wrap a block with position markers written to the log at shipout (y in sp from page bottom)."""
    return (f"\\par\\pdfsavepos\\write-1{{P2PBS {i} \\the\\pdflastypos}}\n{block}\n"
            f"\\par\\pdfsavepos\\write-1{{P2PBE {i} \\the\\pdflastypos}}")


def measure(log_text: str) -> dict:
    """Page size, block start/end heights (pt) and overflow figures from the LaTeX log."""
    page = PAGE.search(log_text)
    missing = sorted({f"{c} U+{code}" for c, code in MISSING.findall(log_text)})
    starts, ends = {}, {}
    for kind, i, y in MARK.findall(log_text):
        (starts if kind == "S" else ends)[int(i)] = int(y) / SP_PER_PT
    text_starts, text_ends = {}, {}
    for kind, i, y in TEXT_MARK.findall(log_text):
        (text_starts if kind == "S" else text_ends)[int(i)] = int(y) / SP_PER_PT
    vbox = re.findall(r"Overfull \\vbox \(([\d.]+)pt too high\)", log_text)
    hbox = re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)", log_text)
    return {"page_width_pt": float(page.group(1)) if page else None,
            "page_height_pt": float(page.group(2)) if page else None,
            "column_width_pt": float(page.group(3)) if page else None,
            "starts": starts, "ends": ends,
            "text_heights": {i: text_starts[i] - text_ends[i] for i in text_starts if i in text_ends},
            "vbox_pt": max(map(float, vbox), default=0.0), "hbox_pt": max(map(float, hbox), default=0.0),
            "missing_glyphs": missing}


def assess(m: dict, columns: list[list[int]]) -> dict:
    """Overflow in both directions and each column's bottom, from measure() and the split."""
    page_h = m["page_height_pt"] or 0.0
    margin = BOTTOM_MARGIN_FRAC * page_h
    bottoms = [min((m["ends"][i] for i in col if i in m["ends"]), default=page_h) for col in columns]
    below = max((margin - b for b in bottoms), default=0.0)
    overflow = max(m["vbox_pt"], below, 0.0)
    return {"overflow_pt": round(overflow, 1), "hbox_overflow_pt": round(m["hbox_pt"], 1),
            "missing_glyphs": m.get("missing_glyphs", []),
            "column_bottoms_pt": [round(b, 1) for b in bottoms], "bottom_margin_pt": round(margin, 1),
            "fits": overflow <= FIT_TOLERANCE_PT and m["hbox_pt"] <= HBOX_TOLERANCE_PT}


def measured_weights(m: dict, n: int) -> list[float] | None:
    """Block heights including the gap to the next block, or None if a marker is missing."""
    if any(i not in m["starts"] or i not in m["ends"] for i in range(n)):
        return None
    heights = [m["starts"][i] - m["ends"][i] for i in range(n)]
    gaps = [m["ends"][i] - m["starts"][i + 1] for i in range(n - 1)
            if 0 <= m["ends"][i] - m["starts"][i + 1] < 200]  # same column only
    gap = sum(gaps) / len(gaps) if gaps else 0.0
    return [h + gap for h in heights]


def grow_figures(widths: dict, aspects: dict, columns_figs: list[list[str]], bottoms: list[float],
                 margin: float, page_h: float, line_w: float, defaults: dict | None = None) -> dict:
    """Wider figures in columns that end well above the bottom margin; others unchanged.

    Tables (crops named *-table-*) grow at most TABLE_MAX_GROWTH x their planned width:
    a small table blown up to the column width has text far larger than the poster's
    (P03 v3 test, 2026-11-12). Plots and diagrams may grow to the column width.
    """
    new, defaults = dict(widths), defaults or widths
    for figs, bottom in zip(columns_figs, bottoms):
        gap = bottom - margin - FILL_SAFETY_PT
        if not figs or gap < FILL_MIN_FRAC * page_h:
            continue
        caps = {f: min(FIG_MAX_WIDTH, FIG_MAX_HEIGHT_FRAC * page_h * aspects[f] / line_w,
                       TABLE_MAX_GROWTH * defaults[f] if "-table-" in f else FIG_MAX_WIDTH) for f in figs}
        room = [f for f in figs if caps[f] > widths[f] + 0.01]
        if not room:
            continue
        # Height of a figure at width w is w * line_w / aspect; share the gap's height.
        delta = 0.9 * gap / sum(line_w / aspects[f] for f in room)
        for f in room:
            new[f] = round(min(caps[f], widths[f] + delta), 3)
    return new


def compile_once(work: Path) -> dict | None:
    """Compile poster.tex in one XeLaTeX pass; return measure() of its log, or None if it failed.

    One pass is enough: the poster has no references, and the headline TikZ nodes use only
    `current page` (checked 2026-11-12: identical page and markers to latexmk's 2-3 passes).
    A fixed SOURCE_DATE_EPOCH makes the PDF byte-identical on every rebuild.
    """
    for f in work.glob("poster.*"):
        if f.suffix not in (".tex",):
            f.unlink()
    env = dict(os.environ, SOURCE_DATE_EPOCH=SOURCE_DATE_EPOCH, FORCE_SOURCE_DATE="1")
    with open(work / "build.log", "a") as log:
        subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "poster.tex"],
                       cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    if not (work / "poster.pdf").exists():
        return None
    return measure((work / "poster.log").read_text(errors="replace"))


def build(run_dir: Path, demo: Path, logo: Path | None, size_in: tuple[float, float],
          min_scale: float = 0.6) -> dict:
    configure_tex_path()
    export_stem = run_poster_stem(run_dir)
    inter = run_dir / "intermediate"
    if not (inter / "raw_content.json").exists() or not (inter / "tree_split.json").exists():
        sys.exit(f"{inter} is missing raw_content.json or tree_split.json (run predates archiving?)")
    work = run_dir / "latex"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(demo / "template", work)
    # The checkout's fonts are Git LFS pointers; assets/fonts/ has the real files for the
    # pinned commit (sha256 checked against the pointers when downloaded).
    shutil.rmtree(work / "fonts")
    shutil.copytree(HARNESS / "assets" / "fonts", work / "fonts")

    painted = inter / "painted_content.json"
    content = json.loads((painted if painted.exists() else inter / "raw_content.json").read_text())
    content["sections"] = [s for s in content.get("sections", [])
                           if not s.get("title", "").lower().startswith("poster title")]
    (work / "poster_content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2))

    captions = {}
    for name, key in (("images.json", "image_path"), ("tables.json", "table_path")):
        if (inter / name).exists():
            for k, v in json.loads((inter / name).read_text()).items():
                captions[f"{name}:{k}"] = {"image_path": v.get(key, ""), "caption": v.get("caption", "")}
    (work / "figure_caption.json").write_text(json.dumps(captions, ensure_ascii=False, indent=2))

    t = (demo / "posterbuilder" / "cambridge_template.tex").read_text()
    t = t.replace("size=custom,width=120,height=72",
                  f"size=custom,width={size_in[0] * 2.54:.2f},height={size_in[1] * 2.54:.2f}")
    t = re.sub(r"\\footercontent\{.*?\n\s*\}\n", "", t, count=1, flags=re.S)
    t = t.replace(r"\logoright{\includegraphics[height=5cm]{logos/right_logo.png}}", r"\logoright{}")
    if logo:
        shutil.copyfile(logo, work / "logos" / "left_logo.png")
    else:
        t = t.replace(r"\logoleft{\includegraphics[height=4cm]{logos/left_logo.png}}", r"\logoleft{}")
    # The pinned template's headline node has no text and no ';', which TikZ rejects.
    node = r"\node [anchor=north west, inner sep=3cm] at ([xshift=0.0cm,yshift=1.0cm]current page.north west)"
    t = t.replace(node + "\n", node + " {};\n")
    # It also sets \textpaddingtop/bottom, which the pinned gemini theme never defines (or reads).
    t = t.replace(r"\addtobeamertemplate{block begin}{",
                  r"\ifdefined\textpaddingtop\else\newlength{\textpaddingtop}\newlength{\textpaddingbottom}\fi"
                  "\n" r"\addtobeamertemplate{block begin}{", 1)
    t = t.replace(r"\usepackage{anyfontsize}",
                  r"\usepackage{anyfontsize}" "\n" r"\usepackage{tabularx}" "\n"
                  r"\setbeamertemplate{caption}{\raggedright\insertcaption\par}" "\n"
                  r"\newcommand{\keyterm}[1]{\textbf{\textcolor{nipspurple}{#1}}}" "\n"
                  r"\setlength{\emergencystretch}{3em}", 1)
    # Page and column size for the fit measurements (see measure()).
    t = t.replace(r"\begin{document}",
                  r"\begin{document}" "\n" r"\typeout{P2PPAGE \the\paperwidth\space\the\paperheight\space\the\colwidth}", 1)
    (work / "template.tex").write_text(t)

    figures = json.loads((inter / "tree_split.json").read_text()).get("figure_arrangement", [])
    tag = next((Path(f["figure_path"]).parts[0] for f in figures if f.get("figure_path")), "")

    sys.path.insert(0, str(demo))
    # The package re-exports a build_poster() function under the module's name.
    bp = importlib.import_module("posterbuilder.build_poster")
    bp.JSON_PATH = work / "poster_content.json"
    bp.TEMPLATE_PATH = work / "template.tex"
    bp.ARRANGEMENT_PATH = inter / "tree_split.json"
    bp.CAPTION_PATH = work / "figure_caption.json"
    bp.OUTPUT_DIR = work
    bp.OUTPUT_PATH = work / "poster.tex"
    bp.IMAGES_PARENTS = [inter]
    bp.IMAGES_DIR_NAME = tag
    bp.ROOT_DIR = run_dir  # only used to print relative paths
    # Every text the builder escapes (titles, authors, block titles, captions, body) also gets
    # Greek letters and math symbols through the math font, so no character is silently dropped.
    upstream_escape = bp.__dict__.setdefault("_upstream_escape_text", bp.escape_text)
    bp.escape_text = lambda text: text_symbols(upstream_escape(text))

    def body(content):
        """Section text between markers, so its height (without title or figures) is measured."""
        i = state["text_index"]
        state["text_index"] += 1
        return (f"\\pdfsavepos\\write-1{{P2PTS {i} \\the\\pdflastypos}}\n"
                + format_content(content or "", bp.escape_text)
                + f"\n\\par\\pdfsavepos\\write-1{{P2PTE {i} \\the\\pdflastypos}}")
    bp.format_content_to_latex = body

    # State shared with the two builder hooks below; the fit loop changes weights and widths.
    state = {"weights": None, "widths": {}, "defaults": {}, "columns": [], "block_figs": [], "last": None}
    upstream_figures_to_latex = bp.figures_to_latex

    def figures_to_latex(fig_list, out_tex_path, images_parent):
        """Upstream's figure code, with each figure's width taken from the fit state."""
        for it in fig_list:
            state["defaults"].setdefault(Path(it["src"]).name, it["width_frac"])
        resized = [{**it, "width_frac": state["widths"].get(Path(it["src"]).name, it["width_frac"])}
                   for it in fig_list]
        return upstream_figures_to_latex(resized, out_tex_path, images_parent)
    bp.figures_to_latex = figures_to_latex

    def split(blocks, n_cols):
        weights = state["weights"] if state["weights"] and len(state["weights"]) == len(blocks) \
            else [block_weight(b, work / "figures") for b in blocks]
        sizes = balanced_split(weights, n_cols)
        out, columns, i = [], [], 0
        for sz in sizes:
            out.append([mark_block(j, blocks[j]) for j in range(i, i + sz)])
            columns.append(list(range(i, i + sz)))
            i += sz
        state["columns"] = columns
        state["block_figs"] = [re.findall(r"\{figures/([^}]+)\}", b) for b in blocks]
        return out
    bp.split_even_continuous = split

    def config(scale):
        return scale, tuple(state["weights"] or ()), tuple(sorted(state["widths"].items()))

    def render(scale):
        state["last"] = config(scale)
        state["text_index"] = 0
        bp.BEAMER_SCALE_TARGET = scale
        bp.main()
        m = compile_once(work)
        if m is None:
            sys.exit(f"LaTeX build failed; see {work / 'build.log'}")
        return m, assess(m, state["columns"])

    def lowest_bottom(a):  # higher is better: the tallest column ends further above the page bottom
        return min(a["column_bottoms_pt"], default=0.0)

    scales = [s for s in SCALES if s >= min_scale - 1e-9] or [min_scale]
    probes = {}  # scale -> (measure, assessment, measured weights used or None)

    def probe(scale):
        """Render with the estimated split, then with measured block heights if they split differently."""
        state["weights"] = None
        m, a = render(scale)
        used = None
        weights = measured_weights(m, len(state["block_figs"]))
        if weights and balanced_split(weights, 3) != [len(c) for c in state["columns"]]:
            state["weights"] = weights
            m2, a2 = render(scale)
            if (a2["fits"], -a2["overflow_pt"], lowest_bottom(a2)) >= (a["fits"], -a["overflow_pt"], lowest_bottom(a)):
                m, a, used = m2, a2, weights
        probes[scale] = (m, a, used)
        print(f"  scale {scale}: overflow {a['overflow_pt']:.1f}pt, line overflow {a['hbox_overflow_pt']:.1f}pt"
              f"{' (rebalanced)' if used else ''}", flush=True)
        return a["fits"]

    # Largest scale that fits: the top scale first (concise posters), then a binary search,
    # assuming a smaller font never makes a poster taller. About 4 probes instead of up to 15.
    if probe(scales[0]) or len(scales) == 1:
        scale = scales[0]
    elif not probe(scales[-1]):
        scale = scales[-1]
    else:
        lo, hi = 1, len(scales) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if probe(scales[mid]):
                hi = mid
            else:
                lo = mid + 1
        scale = scales[lo]
    m, a, used = probes[scale]
    rebalanced = used is not None
    state["weights"] = used
    if state["last"] != config(scale):  # the last compile was another probe: rebuild the chosen one
        m, a = render(scale)

    aspects = {}
    for name in state["defaults"]:
        with Image.open(work / "figures" / name) as im:
            aspects[name] = im.width / im.height
    shrunk = grown = False
    if not a["fits"] and state["defaults"] and a["hbox_overflow_pt"] <= HBOX_TOLERANCE_PT:
        # Last local step: smaller figures at the smallest font scale.
        state["widths"] = {n: round(max(0.45, w * SHRINK_FIGURES), 3) for n, w in state["defaults"].items()}
        m2, a2 = render(scale)
        if a2["overflow_pt"] < a["overflow_pt"]:
            m, a, shrunk = m2, a2, True
        else:
            state["widths"] = {}
            m, a = render(scale)
        print(f"  figures at {SHRINK_FIGURES:.0%}: overflow {a['overflow_pt']:.1f}pt", flush=True)
    if a["fits"] and state["defaults"] and m["column_width_pt"]:
        # Fill: columns that end well above the bottom margin get larger figures.
        for _ in range(2):
            current = {n: state["widths"].get(n, w) for n, w in state["defaults"].items()}
            column_figs = [[f for i in col for f in state["block_figs"][i]] for col in state["columns"]]
            proposal = grow_figures(current, aspects, column_figs, a["column_bottoms_pt"],
                                    a["bottom_margin_pt"], m["page_height_pt"], 0.95 * m["column_width_pt"],
                                    state["defaults"])
            if proposal == current:
                break
            previous = dict(state["widths"])
            state["widths"] = proposal
            m2, a2 = render(scale)
            if a2["fits"]:
                m, a, grown = m2, a2, True
                continue
            state["widths"] = previous
            m, a = render(scale)
            break
        if grown:
            print(f"  figures enlarged to fill columns: {a['column_bottoms_pt']}", flush=True)

    # Where the empty space is, per column, for the Painter's blank-space step (poster_painter.expand).
    titles = [s_["title"] for s_ in content["sections"]]
    layout = {"columns": [[titles[i] for i in col] for col in state["columns"]],
              "column_gap_pt": [round(b - a["bottom_margin_pt"], 1) for b in a["column_bottoms_pt"]],
              "text_height_pt": {titles[i]: round(h, 1) for i, h in m["text_heights"].items() if i < len(titles)}}
    result = {"scale": scale, **a, "layout": layout, "page_height_pt": m["page_height_pt"], "rebalanced": rebalanced,
              "figures_shrunk": shrunk, "figures_grown": grown,
              "figure_widths": {n: state["widths"].get(n, w) for n, w in state["defaults"].items()},
              "content": painted.name if painted.exists() else "raw_content.json"}
    (work / "fit.json").write_text(json.dumps(result, indent=2))
    subprocess.run(["pdftoppm", "-png", "-r", "40", "-singlefile", str(work / "poster.pdf"), str(work / "poster")],
                   check=True)
    for suffix in (".pdf", ".png"):
        (work / f"poster{suffix}").rename(work / f"{export_stem}{suffix}")
    print(f"  Poster exports: {group_poster_exports(run_dir)}", flush=True)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--config", default="config/experiment.yaml")
    args = ap.parse_args()

    p2c = yaml.safe_load(open(resolve(args.config)))["fixed"]["paper2poster"]
    demo = resolve(p2c["path"]) / "demo"
    logo = resolve(p2c["institution_logo_path"]) if p2c.get("institution_logo_path") else None
    size_in = (p2c["poster_width_inches"], p2c["poster_height_inches"])
    for d in args.run_dirs:
        print(f"{d}:")
        print(f"{d}: {build(resolve(d), demo, logo, size_in, p2c.get('min_font_scale', 0.6))}")


if __name__ == "__main__":
    main()
