TASK: KEY-INFORMATION COVERAGE

Check whether the poster correctly represents each required item from the source paper.

For each item, choose one label:
- "accurate": the poster states this item and it matches the paper.
- "wrong": the poster states this item but it is incorrect, distorted, or contradicts the paper (wrong number, wrong method, wrong direction of a result).
- "missing": the poster does not state this item, or states it too vaguely to identify.
- "na": the paper itself has no such item (use only if the reference says "not applicable").

Items:
1. chk_problem: research problem / background
2. chk_method: method / approach
3. chk_data: dataset or sample
4. chk_setup: experimental setup
5. chk_primary_result: primary quantitative result (the number must match)
6. chk_secondary_result: secondary result
7. chk_baseline: baseline / comparison
8. chk_conclusion: main conclusion
9. chk_limitation: limitation / implication

Content shown only inside a figure or table on the poster counts if it is legible in the poster image. The poster text below is extracted from the poster file, so it includes table cells and captions but not text drawn inside figure images.

Items marked UNCERTAIN in the reference have two drafts, (a) and (b), that did not match, usually because the paper has more than one valid answer (for example, several limitations). Count such an item as "accurate" if the poster correctly states what either draft describes, checked against the paper text given for that item. Use "na" for it only if the paper has no such item.

REFERENCE (what the paper says for each item):
{{reference}}

POSTER TEXT (extracted):
<<<
{{poster_text}}
>>>

The poster image is attached.

Return JSON:
{
  "items": {
    "chk_problem":          {"label": "accurate|wrong|missing|na", "poster_evidence": "<exact quote from poster, or empty>", "reason": "<one sentence>"},
    "chk_method":           {...},
    "chk_data":             {...},
    "chk_setup":            {...},
    "chk_primary_result":   {...},
    "chk_secondary_result": {...},
    "chk_baseline":         {...},
    "chk_conclusion":       {...},
    "chk_limitation":       {...}
  }
}
