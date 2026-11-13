"""Re-crop extracted figures and tables so their edges are not clipped (no model calls).

docling's picture/table boxes sometimes stop inside the figure: an axis label or legend
is cut at the crop edge (P01 Fig. 2 lost the second line of "Cancer baseline"). Upstream
saves the crop as is. Here, after upstream has written its crops, each side whose edge
cuts through ink is pushed outwards on the page image until a strip of blank page is
reached, so a clipped label is completed but neighbouring paper text is not captured.
If no blank strip is found within MAX_GROW_PT the side is left where docling put it.

Runs inside Paper2Poster's environment (docling result), but grow_box is plain
numpy/PIL so it can be tested in the harness environment.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

INK = 235            # grey level below which a pixel counts as ink (0 black, 255 white)
BLANK_RUN_PT = 4.0   # blank strip that ends a figure: wider than gaps inside a label
MAX_GROW_PT = 40.0   # never move a side further than this
PAD_PT = 2.0         # white margin kept around a grown side


def _blank(line: np.ndarray) -> bool:
    return bool((line >= INK).all())


def grow_box(page: np.ndarray, box: tuple[int, int, int, int], px_per_pt: float) -> tuple[int, int, int, int]:
    """Grow (left, top, right, bottom) on a greyscale page array until each side is in blank page."""
    height, width = page.shape
    left, top, right, bottom = (int(round(v)) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    run = max(1, int(round(BLANK_RUN_PT * px_per_pt)))
    limit = max(1, int(round(MAX_GROW_PT * px_per_pt)))
    pad = int(round(PAD_PT * px_per_pt))

    def side(edge_inside, step, bound, line):
        """New position of one side; edge_inside is the last pixel row/column inside the box."""
        if _blank(line(edge_inside)):
            return None  # the crop already ends in blank page
        blank, pos = 0, edge_inside
        for k in range(1, limit + 1):
            pos = edge_inside + step * k
            if not 0 <= pos < bound:
                return pos - step  # reached the page edge
            if _blank(line(pos)):
                blank += 1
                if blank >= run:
                    first_blank = pos - step * (run - 1)
                    return first_blank + step * min(pad, run - 1)
            else:
                blank = 0
        return None  # no blank strip nearby: keep docling's edge

    for _ in range(2):  # a second pass sees the sides widened by the first
        changed = False
        rows = lambda y: page[y, left:right]
        cols = lambda x: page[top:bottom, x]
        new = side(bottom - 1, 1, height, rows)
        if new is not None and new + 1 > bottom:
            bottom, changed = new + 1, True
        new = side(top, -1, height, rows)
        if new is not None and new < top:
            top, changed = new, True
        new = side(right - 1, 1, width, cols)
        if new is not None and new + 1 > right:
            right, changed = new + 1, True
        new = side(left, -1, width, cols)
        if new is not None and new < left:
            left, changed = new, True
        if not changed:
            break
    return left, top, right, bottom


def _element_crop(element, document):
    """Page image and docling's crop box for an element, as upstream DocItem.get_image computes it."""
    if not element.prov:
        return None
    prov = element.prov[0]
    page = document.pages.get(prov.page_no)
    if page is None or page.size is None or page.image is None or page.image.pil_image is None:
        return None
    image = page.image.pil_image
    box = prov.bbox.to_top_left_origin(page_height=page.size.height).scale_to_size(
        old_size=page.size, new_size=page.image.size).as_tuple()
    return image, box, image.width / page.size.width


def regrow_crops(conv_res, images: dict, tables: dict, out_dir: Path, poster_name: str) -> dict:
    """Rewrite upstream's crop files with grown boxes; update sizes in images/tables in place.

    Files are numbered the way upstream's gen_image_and_table numbers them
    (document order of iterate_items), so each file keeps the same figure.
    """
    from docling_core.types.doc import PictureItem, TableItem

    report, counters = {}, {'picture': 0, 'table': 0}
    for element, _ in conv_res.document.iterate_items():
        kind = 'table' if isinstance(element, TableItem) else 'picture' if isinstance(element, PictureItem) else None
        if kind is None:
            continue
        counters[kind] += 1
        path = out_dir / f'{poster_name}-{kind}-{counters[kind]}.png'
        found = _element_crop(element, conv_res.document)
        if found is None or not path.exists():
            continue
        page_image, box, px_per_pt = found
        grey = np.asarray(page_image.convert('L'))
        grown = grow_box(grey, box, px_per_pt)
        original = tuple(int(round(v)) for v in box)
        if grown != original:
            page_image.crop(grown).save(path, 'PNG')
            report[path.name] = {'docling_box': original, 'grown_box': list(grown)}
    for entries, key in ((images, 'image_path'), (tables, 'table_path')):
        for entry in entries.values():
            if Path(entry[key]).name in report:
                from PIL import Image
                with Image.open(entry[key]) as im:
                    entry.update(width=im.width, height=im.height, figure_size=im.width * im.height,
                                 figure_aspect=im.width / im.height)
    return report
