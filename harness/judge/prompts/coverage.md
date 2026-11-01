TASK: KEY-INFORMATION COVERAGE

Check whether the poster correctly represents each required item using the paper-derived reference below as the answer key. Evaluate each item independently; do not grade visual attractiveness here.

For each item, choose one label:
- "accurate": identifiable, specific poster evidence correctly covers the reference item with its required scope.
- "wrong": the poster states this item but it is incorrect, distorted, or contradicts the paper (wrong number, wrong method, wrong direction of a result).
- "missing": the poster does not state this item, or a heading, keyword, or vague mention does not establish the required information.
- "na": the paper itself has no such item (use only if the reference says "not applicable").

Items:
1. chk_problem: the specific research problem / background and motivation, not just a topic name.
2. chk_method: the identifiable method / approach and what it does, not just a method heading.
3. chk_data: the dataset or sample actually studied, with identifying information required by the reference. This may be a study population, measured material, or collected observations; a named benchmark is not always required.
4. chk_setup: how evaluation was performed, with the essential protocol or conditions in the reference. Naming the dataset alone does not describe the experimental setup; listing hardware alone is not automatically sufficient or necessary.
5. chk_primary_result: the primary quantitative finding in the reference, including the reported metric and the evaluation setting that makes the number meaningful.
6. chk_secondary_result: a distinct secondary finding that matches the reference and its setting; do not substitute the primary finding or an unrelated number.
7. chk_baseline: the identifiable baseline / comparison and the relationship or contrast required by the reference. A generic claim of superiority is insufficient.
8. chk_conclusion: the paper's substantive take-home conclusion, not a heading or a generic statement that the method is useful.
9. chk_limitation: a specific limitation OR a specific implication supported by the source. Either can satisfy this item; an implication need not be phrased as a weakness. Generic future work alone is insufficient.

Evidence rules:
- Inspect the whole poster: body text, readable table cells, figures, legends and captions can all establish coverage, regardless of section heading or position. Do not require a dedicated section or a particular wording.
- The extracted text may interleave columns or omit text inside image-based figures/tables. Consult the attached image and its row/column labels before declaring an item absent. Do not guess values that are unreadable.
- Dataset/sample and setup are separate questions. A passage may support both only if it actually supplies evidence for both; do not award or deny both from a keyword alone.
- For results, preserve the metric, numerical value, comparator when required, population or sample denominator, and evaluation setting. Correctly rounded equivalents are acceptable; a different metric, split, task, or population is not an equivalent result.
- Distinguish main test results from component ablations, representative-fold results, and clinical subsets. Credit them only for the reference item and setting they actually establish. A high number or a statement of improvement does not replace the requested main result.
- Require the identifying evidence needed for the reference item, without demanding every incidental implementation detail or every number appearing anywhere in the paper.
- Additional incorrect claims belong in the separate hallucination audit. They do not automatically erase specific, otherwise correct evidence for a coverage item.
- In poster_evidence, quote the smallest sufficient exact passage or transcribe the relevant readable table/figure text. In reason, briefly identify its location, the matched reference item/setting, and why it is accurate, wrong, missing or not applicable. Empty evidence is appropriate when the item is absent, not as a substitute for citing credited content.

Items marked UNCERTAIN have alternative drafts whose agreement is unresolved. Check the supplied source excerpt rather than assuming the drafts are equivalent or both correct. Credit either draft when the excerpt supports it and the poster matches its substantive answer and setting. Do not require every alternative simultaneously. If the supplied evidence does not resolve the item, state that limitation in reason rather than claiming certainty. Use "na" only when source evidence establishes non-applicability, never because the poster omitted the item.

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
