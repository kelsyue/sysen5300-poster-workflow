TASK: COMPARE TWO REFERENCE SHEETS FOR THE SAME PAPER

Two drafts (A and B) state what each checklist item is in the same research paper. For each item, decide whether A and B identify the same content.

- "same": both name the same thing (same method, same dataset, same result with the same numbers, same conclusion). Different wording, more or less detail, or one quoting a different sentence about the same thing still counts as the same. If one draft is a more detailed version of the other (A: "linear probes with 70/30 patient-level splits and kNN purity", B: "linear probing and kNN analysis"), or names one more element (A: "ResNet-50 baseline and a DINOv3 control", B: "ResNet-50 baseline"), answer same.
- "different": they name different things (a different result as the primary one, a different number, a different dataset or baseline), or one says the item does not apply and the other does not.

ITEMS:
{{pairs}}

Return JSON:
{
  "items": {
    "chk_problem": {"same": true, "reason": "<one sentence>"},
    ...
  }
}
Return one entry for every item listed.
