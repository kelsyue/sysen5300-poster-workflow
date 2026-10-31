TASK: CLAIM EXTRACTION (step 1 of 2 for hallucination)

Break the poster text into atomic factual claims. An atomic claim states one fact that could be checked against the paper.

Rules:
- One fact per claim. Split "We used X and achieved 92% accuracy" into two claims.
- Keep numbers, units, model names, and comparisons exactly as written on the poster.
- Include claims about the method, data, setup, results, comparisons, conclusions, and limitations.
- Skip non-factual text: titles, author names, affiliations, section headings, acknowledgements, references, QR-code captions, and generic statements with no checkable content ("Results are shown below").
- Do not add, fix, or infer anything that is not written on the poster.

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
