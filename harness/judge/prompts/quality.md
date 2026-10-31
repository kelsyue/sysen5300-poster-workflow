TASK: POSTER QUALITY (1–5)

Rate the attached poster image. First score three criteria, then give one holistic score. The holistic score is the one that counts; it should be consistent with the criteria but is not required to be their average.

The poster is printed at {{width_in}} × {{height_in}} inches. The image is a downscaled render, so small text may look blurry here even when it is easy to read on the printed poster. Judge readability by text size relative to the whole poster, density of text, and size of figures, as a viewer standing about 1–2 m from the printed poster would see it. Do not lower a score only because text is blurry at this image resolution.

Criteria (1–5 each):
- layout: logical reading order, sections clearly separated, efficient use of space, no large empty areas, no text running outside boxes, nothing cut off at the edges.
- readability: text legible at poster size, no large walls of text, figures and tables labeled and readable.
- fidelity: the poster emphasizes what the paper emphasizes; the main findings are clear and are represented faithfully, and figures support the findings.

Holistic anchors:
- 5 = Ready to present. Logical flow, efficient use of space, readable text, labeled figures that carry the main findings, content faithful to the paper.
- 4 = Presentable with minor edits. One small issue in layout, readability, or emphasis.
- 3 = Usable draft. Several issues, or one major issue (for example, key result under-emphasized, crowded text block).
- 2 = Needs substantial rework. Poor structure or misleading representation of the paper.
- 1 = Not usable. Unreadable, missing core content, or misrepresents the work.

Do not reward length or decoration. A plain poster that communicates the paper clearly can score 5.

PAPER SUMMARY (for judging fidelity):
{{reference}}

Return JSON:
{
  "layout":      {"score": 1-5, "reason": "<one sentence>"},
  "readability": {"score": 1-5, "reason": "<one sentence>"},
  "fidelity":    {"score": 1-5, "reason": "<one sentence>"},
  "holistic":    {"score": 1-5, "reason": "<two sentences max, naming the main issue if below 5>"}
}
