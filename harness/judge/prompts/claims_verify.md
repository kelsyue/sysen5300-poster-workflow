TASK: CLAIM VERIFICATION (step 2 of 2 for hallucination)

Verify each supplied atomic claim occurrence against the source paper. Treat repeated occurrences independently; do not combine or deduplicate them. Use exactly the claim ids supplied in this batch.

Labels:
- "supported": the paper states the claim, or it follows directly without an unstated assumption. Legitimate paraphrases and correctly rounded numerical values are acceptable when meaning and scope are preserved.
- "unsupported": the paper does not state this and it does not follow from the paper.
- "contradicted": the source explicitly conflicts with the claim under the same stated conditions, such as an incompatible numerical value, opposite direction, or different method or sample. A different result in a different evaluation setting is not by itself a contradiction.

Rules:
- Use only the paper below. A claim that is true in general but not in the paper is "unsupported".
- Match subject, metric, units, comparator, denominator, numerical scope, uncertainty and evaluation setting before assigning a verdict. Keep main test results, ablations, representative-fold results and clinical subsets distinct. Do not treat a subset result as a general result unless the source justifies that scope.
- Verify a printed mean and its ± spread as separate numerical occurrences while retaining their relationship and the type of spread stated in the source. Correct rounding must be consistent with printed precision; changed uncertainty, denominator, comparator or setting is not mere rounding.
- Inspect relevant body text, source table text, and captions supplied below. A claim can be supported by a table rather than a narrative sentence. Do not invent entries that are missing or unreadable in the supplied source.
- For "supported" and "contradicted", put a direct, exact source quotation in paper_evidence. Put the source location in reason when available: section, table/figure identifier and row/column, or an explicit page label. Do not invent a location. Explain briefly why the evidence supports or conflicts with this particular claim.
- For "unsupported", leave paper_evidence empty when there is no supporting passage and explain the specific unsupported part in reason. Use this verdict for lack of support in an accessible, relevant source, not for lack of access to the necessary evidence.
- If missing source access or unreadable/omitted evidence prevents verification of any claim, do not fabricate support, label it unsupported merely because it cannot be read, or return a partial audit as complete. Return {"verdicts": []} for this batch; the existing runner's missing-verdict check flags the claims task for review. This is a verification limitation, not evidence of a hallucination.
- Do not calculate or output a hallucination rate in this task. Claim-based percent is 100 × (unsupported + contradicted occurrences) / total audited claim occurrences. Flagged claims per 1,000 poster words is 1,000 × flagged occurrences / poster word count. These have different denominators and must not be substituted for each other. Application code performs its configured calculation.
- Keep quotations and reasons concise while sufficient to verify the judgement. Return one verdict for every supplied id unless the verification-limitation rule requires an empty batch; no extended analysis.

SOURCE PAPER:
<<<
{{paper_text}}
>>>

CLAIMS:
{{claims}}

Return JSON:
{
  "verdicts": [
    {"id": 1, "label": "supported|unsupported|contradicted", "paper_evidence": "<exact quote from paper, or empty>", "reason": "<source location when available and one short explanation>"},
    ...
  ]
}
Return verdicts in the same order as the supplied claim ids. The verification-limitation response is the empty verdicts array described above; do not add a new verdict label or output field.
