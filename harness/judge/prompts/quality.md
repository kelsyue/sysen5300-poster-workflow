TASK: POSTER QUALITY (1–5)

Evaluate visual communication from the actual attached poster image. First record the observations below, then score the three existing criteria, then give one holistic score. The holistic score is the one that counts; it should be consistent with the criteria but is not required to be their average. There are no additional numerical weights or extra criteria.

The poster is printed at {{width_in}} × {{height_in}} inches. Use a consistent whole-poster viewing scale and assess text and figure sizes relative to the full canvas, as a viewer about 1–2 m from the printed poster would encounter them. The supplied image is downscaled: do not penalize raster blur alone, but do not assume unreadable details are legible in print. Identify resolution-related uncertainty in the relevant reason. Assess only visual details you can actually observe; extracted text or a reference summary cannot establish visual quality on their own.

Criteria (1–5 each):
- layout: information hierarchy, logical reading order and flow, section separation, balance and efficient use of the full canvas; no clipping, overlapping content or text outside boxes. Whitespace should guide reading and balance content. Canvas left unused is a layout weakness: a blank region covering a large share of the poster, such as an empty lower part or an empty column, means the poster does not use its space, however clean the remaining content looks, and the larger the unused share the more serious the weakness. Margins and the gaps between sections are not unused canvas. Judge unused canvas, not word count: a short poster whose text and figures fill the canvas is not penalized for being short.
- readability: text size and density, manageable paragraphs, figure/table size, readable axes, legends and table cells, and clear caption-to-figure/table correspondence. A clean heading system cannot compensate for illegible evidence or dense blocks that obstruct scanning.
- fidelity: the visual hierarchy emphasizes the source paper's main findings accurately, and the selected figures and captions support those findings in their correct setting. Do not infer scientific emphasis from section titles alone. Evaluate this existing criterion without replacing the separate coverage checklist or claim audit.

Holistic anchors:
- 1 = Severe communication problems. The reader cannot reliably follow or read essential content, or the presentation fundamentally misrepresents the work.
- 2 = Major weaknesses. Substantial rework is needed because flow, readability, visual evidence or emphasis obstructs communication.
- 3 = Usable with noticeable weaknesses. The main message can be understood, but several issues or a substantial local weakness reduce clarity or accessibility.
- 4 = Strong communication with minor weaknesses. Flow, balance, readability and faithful emphasis work well; remaining issues are limited and specific.
- 5 = Exceptional performance across the rubric. Clear hierarchy and flow, purposeful balance and density, legible visual evidence, and faithful emphasis work together with no consequential weakness. Support this rating with specific observations across all three criteria.

Use these same severity anchors for each criterion as well as the holistic assessment. A strong fidelity score must not hide a major layout or readability problem in the holistic rationale; explain how any observed weakness affects communication. Do not call a consequential weakness a minor edit merely because the template is polished.

A clean template, large blank areas, high coverage or zero flagged claims does not by itself justify a high quality score. Equally, dense content or spacing between elements is not automatically bad: assess its effect on communication. Do not mechanically copy a coverage or hallucination penalty into quality; only the existing fidelity dimension addresses how the presentation represents the source. Do not reward decoration or length. A plain, concise poster can score highly when the visual evidence supports it.

In each existing reason field, identify a concrete location or visual feature and its communication effect. Check the full canvas before claiming that space is well used or that no important text/figure is too small. Assess whether captions identify the correct visual and whether retained source numbering actually creates confusion; nonconsecutive source figure numbers alone are not a quality defect. Do not invent image details or infer a desired score from scientific accuracy.

MEASURED CANVAS (computed by code from the same image; more reliable than your view of the downscaled image for blank space):
Blank share of the canvas: {{blank_pct}}%
Map, top to bottom; each character is about {{cell_in}} inches; # = text or graphics, . = blank:
{{canvas_map}}

Use this measurement for empty_space and for the layout criterion's use of the canvas. Blank cells inside a section or at the end of a column are unused canvas; a narrow ring of blank cells around the edge or a thin row between sections is margin or spacing. Under the anchors above, unused canvas of about a quarter of the poster or more is a major layout weakness, and about a tenth is a noticeable one. Judge only the unused share, never the amount of text.

Observations (record before scoring; each is a check, not a score):
- empty_space: a blank region larger than about one tenth of the canvas, other than margins. Answer from the measured canvas map, and give its location in where.
- overflow: text or a visual that is clipped, overlaps other content, or runs outside its box.
- duplicate_visual: the same or a near-identical figure or table appears more than once, including a table typed out as text that is also shown as an image of the same table.
- small_visual_text: figure or table text (axes, legends, cells, labels) too small to read at 1–2 m.
- dense_text: a text block that is hard to scan, such as a long unbroken paragraph or small body text.
- caption_mismatch: a caption that does not describe its own visual, or a visual with no caption.
- unclear_order: no evident reading order between sections.
- main_result_hidden: the paper's main result is not visible as a prominent figure, table or statement.
For each, answer present true or false. When true, give where (which region) and the effect on a reader. Base each answer on what you can see; when the image cannot settle it, answer false and say so in where. Every observation marked true must be reflected in the reason of the criterion it affects; do not describe a criterion's weaknesses as minor while leaving its observed problems unmentioned.

PAPER SUMMARY (for judging fidelity):
{{reference}}

Return JSON:
{
  "observations": {
    "empty_space":        {"present": true|false, "where": "<region and effect; empty if false>"},
    "overflow":           {"present": true|false, "where": "..."},
    "duplicate_visual":   {"present": true|false, "where": "..."},
    "small_visual_text":  {"present": true|false, "where": "..."},
    "dense_text":         {"present": true|false, "where": "..."},
    "caption_mismatch":   {"present": true|false, "where": "..."},
    "unclear_order":      {"present": true|false, "where": "..."},
    "main_result_hidden": {"present": true|false, "where": "..."}
  },
  "layout":      {"score": 1-5, "reason": "<one sentence>"},
  "readability": {"score": 1-5, "reason": "<one sentence>"},
  "fidelity":    {"score": 1-5, "reason": "<one sentence>"},
  "holistic":    {"score": 1-5, "reason": "<two sentences max, naming the main issue if below 5>"}
}
