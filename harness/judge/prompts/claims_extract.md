TASK: CLAIM EXTRACTION (step 1 of 2 for hallucination)

Enumerate independently checkable atomic factual claim occurrences in the supplied poster text before any verification. One occurrence states one fact that could be checked against the paper. This is an occurrence audit, not a list of unique facts.

Rules:
- Split compound statements into separately checkable facts. A sentence that gives values for several items (for example, "A improved by x, B by y, and C by z") gives one claim per value. A numerical claim retains enough surrounding context to identify its metric, subject, comparator, sample or population denominator, and evaluation setting.
- Count repeated occurrences separately, even when they repeat the same fact in body text, a caption, or a table. Do not deduplicate semantically identical occurrences.
- A printed mean and its accompanying ± spread are separate numerical claims. Preserve which value is the mean and which is the stated uncertainty or spread; do not assume the spread is a standard deviation if the poster does not say so.
- Include substantive table entries and captions present in the input. For each table entry retain its row/column labels and units as context. Header labels provide context but are not extra factual occurrences by themselves. Do not treat an entire numerical table as a single claim.
- Keep numerical values, units, qualifiers, model or method names, comparisons, direction, uncertainty, and evaluation setting as printed. Preserve whether a result is a main test result, an ablation, a representative fold, or a subgroup result; do not silently promote one setting to another.
- Include checkable assertions about method, data, setup, results, comparisons, conclusions, limitations, and implications.
- Skip non-factual text: titles, author names, affiliations, section headings, acknowledgements, references, QR-code captions, and generic statements with no checkable content ("Results are shown below").
- Do not add, fix, or infer anything that is not written on the poster.
- Audit only evidence actually supplied. Text inside a raster figure/table may be absent from this extraction; do not invent its contents or claim that unseen entries were audited.
- Give consecutive ids to all occurrences. Use a short exact poster_quote for each, retaining sufficient text to locate the occurrence. Return every occurrence, with concise claim text and no verification commentary or summary.

POSTER TEXT (extracted):
<<<
{{poster_text}}
>>>

Return JSON:
{
  "claims": [
    {"id": 1, "text": "<atomic claim>", "poster_quote": "<exact span from the poster text it came from>"},
    ...
  ]
}
