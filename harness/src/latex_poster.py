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
  - section text keeps its structure: Markdown table lines become tables, "•" or "-"
    lines become lists, blank lines start paragraphs (the demo joins everything);
  - sections are split into the three columns in reading order, balancing estimated
    height instead of section count;
  - auto-fit: the beamerposter scale steps down from 1.1 until nothing runs off the
    page. fit.json records the final scale and any remaining overflow, so a model that
    writes longer summaries shows up as smaller text rather than lost content.

Usage (from harness/):
    python src/latex_poster.py outputs/dry_run/1 [outputs/dry_run/2 ...]
Writes outputs/<run_id>/latex/<paper_id> x <model>.pdf and .png,
plus poster.tex, fit.json and build.log.
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

from poster_naming import run_poster_stem

HARNESS = Path(__file__).resolve().parent.parent
SCALES = [1.1, 1.0, 0.95, 0.9, 0.85, 0.8, 0.76, 0.72, 0.68, 0.64, 0.6]
FIT_TOLERANCE_PT = 5.0
# Height estimate for column balancing, in "characters of body text":
# one column-width of height is about 3000 characters, a block title about 150.
CHARS_PER_COLWIDTH = 3000
CHARS_PER_TITLE = 150
CHARS_PER_TABLE_ROW = 80


def configure_tex_path() -> None:
    """Use the project-local TinyTeX when TeX is absent from PATH."""
    if not shutil.which("latexmk"):
        for executable in sorted((HARNESS / "vendor/TinyTeX/bin").glob("*/latexmk")):
            os.environ["PATH"] = str(executable.parent) + os.pathsep + os.environ.get("PATH", "")
            break


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else HARNESS / path


def format_content(content: str, escape) -> str:
    """Section text to LaTeX, keeping tables, lists and paragraphs."""
    out, para, items, rows = [], [], [], []

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


def compile_once(work: Path) -> float | None:
    """Compile poster.tex; return how far the frame overflows (pt), or None if it failed."""
    for f in work.glob("poster.*"):
        if f.suffix not in (".tex",):
            f.unlink()
    with open(work / "build.log", "a") as log:
        subprocess.run(["latexmk", "-xelatex", "-interaction=nonstopmode", "-halt-on-error", "poster.tex"],
                       cwd=work, stdout=log, stderr=subprocess.STDOUT, check=False)
    if not (work / "poster.pdf").exists():
        return None
    over = re.findall(r"Overfull \\vbox \(([\d.]+)pt too high\)", (work / "poster.log").read_text(errors="replace"))
    return max(map(float, over), default=0.0)


def build(run_dir: Path, demo: Path, logo: Path | None, size_in: tuple[float, float]) -> dict:
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

    content = json.loads((inter / "raw_content.json").read_text())
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
                  r"\setbeamertemplate{caption}{\raggedright\insertcaption\par}", 1)
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
    bp.format_content_to_latex = lambda c: format_content(c or "", bp.escape_text)

    def split(blocks, n_cols):
        sizes = balanced_split([block_weight(b, work / "figures") for b in blocks], n_cols)
        out, i = [], 0
        for sz in sizes:
            out.append(blocks[i:i + sz])
            i += sz
        return out
    bp.split_even_continuous = split

    result = {}
    for scale in SCALES:
        bp.BEAMER_SCALE_TARGET = scale
        bp.main()
        over = compile_once(work)
        if over is None:
            sys.exit(f"LaTeX build failed; see {work / 'build.log'}")
        result = {"scale": scale, "overflow_pt": round(over, 1), "fits": over <= FIT_TOLERANCE_PT}
        print(f"  scale {scale}: overflow {over:.1f}pt", flush=True)
        if result["fits"]:
            break
    (work / "fit.json").write_text(json.dumps(result, indent=2))
    subprocess.run(["pdftoppm", "-png", "-r", "40", "-singlefile", str(work / "poster.pdf"), str(work / "poster")],
                   check=True)
    for suffix in (".pdf", ".png"):
        (work / f"poster{suffix}").rename(work / f"{export_stem}{suffix}")
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
        print(f"{d}: {build(resolve(d), demo, logo, size_in)}")


if __name__ == "__main__":
    main()
