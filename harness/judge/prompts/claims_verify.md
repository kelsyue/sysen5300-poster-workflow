TASK: CLAIM VERIFICATION (step 2 of 2 for hallucination)

Check each claim against the source paper.

Labels:
- "supported": the paper states this, or it follows directly from what the paper states. Reasonable paraphrase and rounding (91.7% → 92%) are fine.
- "unsupported": the paper does not state this and it does not follow from the paper.
- "contradicted": the paper states something different (different number, opposite direction, different method or dataset).

Rules:
- Use only the paper below. A claim that is true in general but not in the paper is "unsupported".
- For "supported" and "contradicted", quote the paper sentence you relied on.
- For "unsupported", leave paper_evidence empty and explain briefly what is missing.

SOURCE PAPER:
<<<
{{paper_text}}
>>>

CLAIMS:
{{claims}}

Return JSON:
{
  "verdicts": [
    {"id": 1, "label": "supported|unsupported|contradicted", "paper_evidence": "<exact quote from paper, or empty>", "reason": "<one sentence>"},
    ...
  ]
}
Return one verdict for every claim id, in the same order.
