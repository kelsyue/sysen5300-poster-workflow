TASK: REFERENCE SHEET FOR A RESEARCH PAPER

A poster made from this paper will later be checked against your sheet, item by item. For each item, state in one short phrase (at most 40 words) what this paper's item is, and copy one sentence from the paper that supports it.

Items:
1. chk_problem: research problem / background
2. chk_method: method / approach
3. chk_data: dataset or sample
4. chk_setup: experimental setup
5. chk_primary_result: primary quantitative result (the paper's headline number or numbers, written exactly as in the paper, with what they measure)
6. chk_secondary_result: secondary result (the next most important finding)
7. chk_baseline: baseline / comparison (what the method is compared against)
8. chk_conclusion: main conclusion
9. chk_limitation: limitation / implication

Rules:
- "value": the item in your own words, specific to this paper (name the method, dataset, numbers). Not a generic description.
- "paper_quote": one sentence copied character for character from the paper text below. Do not paraphrase, shorten, or join sentences.
- If the paper has no such item (for example, no baseline), set "value" and "paper_quote" to null and say why in "reason".
- "summary": two or three sentences on what the paper does and finds.

PAPER:
<<<
{{paper_text}}
>>>

Return JSON:
{
  "summary": "<two or three sentences>",
  "items": {
    "chk_problem":          {"value": "<phrase or null>", "paper_quote": "<exact sentence or null>", "reason": "<only if null>"},
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
