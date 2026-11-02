# Frozen judge-prompt revision: evidence and visual communication

This is an author-facing development note, never a judge input. It is outside
`prompts/`; `judge.py` loads named Markdown files only from that directory.
No calibration rows, paper identifiers, poster codes, generator identities,
paper-specific facts, expected individual scores, or worked examples are copied
into this note or the revised runtime prompts. Only aggregate diagnostics appear
here. Human-assisted labels remain provisional and unchanged.

## Scope and freeze

One general revision of five runtime files: `prompts/system.md`,
`prompts/coverage.md`, `prompts/claims_extract.md`, `prompts/claims_verify.md`,
and `prompts/quality.md`. The reference-sheet prompts are unchanged. No papers,
posters, reference files, human labels, recorded judge outputs, application code,
output keys, score formulas, rubric dimensions or acceptance thresholds are edited.

Original `judge_prompt_sha256`:
`8efb4293473e225672f28f1c88ed5aca4cd298f6224f91d7d937da5a8f63e76b`.

Frozen revision `judge_prompt_sha256`:
`b869632da1ad4b55ac22113283e19f071d648950b15ea1524b071b8280f5a11f`.

All supplied examples are development data; none can retrospectively become an
untouched holdout. No predeclared split file was found. No holdout content or
scores were inspected. Keep the revised hash fixed before any holdout evaluation;
do not iterate on holdout results or select a split based on these disagreements.
No paid rerun was performed, and improved agreement has not been measured.

## Pipeline inspected before editing

`JudgeClient` in `judge.py` loads `prompts/system.md` for each metric call.
`task_coverage`, `task_claims`, and `task_quality` load the four task files named
above, with extraction and verification being separate calls. The nested
`prompts/reference/` files are used by `reference_sheet.py`, not as the metric
judge's system prompt, and were not changed.

| Task | Actual input | Consequence |
|---|---|---|
| Coverage | Attached rendered poster image, extracted poster text, and paper-derived reference answers | Correct content can be found outside a named section. Accepted reference answers and uncertain drafts/excerpts are supplied. |
| Quality | Attached rendered poster image, printed dimensions, and reference summary/values; uncertain source excerpts are omitted when a reference sheet exists | This is a visual call, not a text-only quality call. The reference can still be insufficient to adjudicate unresolved scientific emphasis. |
| Claim extraction | Extracted poster text only | Text inside raster figures/tables is unavailable unless separately transcribed into the input. |
| Claim verification | Atomic claims, numbered within each batch, and source-paper text | Source text is extracted/cached and can omit raster tables or be truncated. It is not the source PDF image. |

Rendering uses a configured common maximum image dimension, currently a
2,000-pixel long side. Cached images may predate a changed rendering setting.
The revised prompt asks for consistent whole-canvas judgement and disclosure of
resolution uncertainty. Prompt wording cannot recover unreadable pixels.
If a deployment supplies only text to quality, reliable visual calibration is
impossible: the minimum input fix is to attach the actual same-scale poster PNG
to the quality call, as this repository already does. Do not infer layout from
extracted text alone. Higher-resolution evidence or deterministic detail crops
may be needed for small tables; that input change is outside this revision.

## Recurring problems and general changes

| Behavior | Evidence available in development data | Revision and limits |
|---|---|---|
| Quality inflation and template-based ratings | Quality MAE exceeds one scale point for both judges. Inspected sparse development images contain large unused lower-canvas regions, yet some raw layout reasons claim no large empty areas. Other top holistic ratings acknowledge dense figures or text. | `quality.md` requires concrete full-canvas evidence, purposeful whitespace/density, and communication effects; a strong fidelity judgement cannot conceal major visual weaknesses. A score of five requires exceptional performance across the existing rubric. A sparse design is not automatically poor. |
| Vague evidence credited for quantitative results | One development raw coverage response credits a qualitative claim of improvement as a quantitative primary result. | `coverage.md` requires an identifiable metric, value and reference-matched setting; headings and vague mentions do not establish coverage. This does not imply every lower human score is correct. |
| Main-result versus ablation scope | Development raw coverage responses disagree about whether component-study figures establish the reference's main/secondary test results. The reference itself has unresolved alternatives. | Coverage and verification distinguish main tests, component ablations, representative folds and subsets. Alternatives must be checked against supplied source evidence, not all required simultaneously or assumed equivalent. The proper item-level label still needs human review. |
| Dataset/setup conflation | Some raw reasons use data-collection apparatus as dataset evidence, while other reasons demand the same apparatus and protocol details for multiple items. Aggregate human coverage labels cannot identify which individual decision differs. | `coverage.md` separates what was studied from how it was evaluated, permits non-benchmark samples, and requires essential rather than incidental details. It does not force a desired checklist total. |
| Limitation-only interpretation of the final item | Raw missing-item reasons focus on absent limitations even where development images contain specific implications or future directions. | `coverage.md` explicitly permits a supported, specific limitation OR implication. Generic future work remains insufficient. Without nine human decisions, the actual final-item disagreement is unconfirmed. |
| Claim unit and counting inconsistencies | Supplied human labels are claim percentages; the application reports a word-normalized rate. The raw audits also differ in extracted claim counts. | Extraction now counts repeated occurrences, individual substantive table entries, and means/spreads separately, retaining scope. Verification requests source quotations and locations in existing fields. The application formula is unchanged; this is not a unit conversion. |
| Asymmetric uncertainty and metric spillover | The previous system prompt instructed a conservative label whenever uncertain; raw quality reasons sometimes use scientific faithfulness to justify top overall scores despite communication weaknesses. | `system.md` distinguishes uncertainty from demonstrated error and keeps metrics separate, with fidelity retained as the existing scientific-emphasis dimension. No target distribution or individual expected score is provided. |

Repeated-count, rounding and numerical-scope changes clarify the requested audit
convention. Their effect on hallucination agreement is not established by the
available labels. Representative-fold and clinical-subset rules are safeguards;
their error frequency has not been measured here.

## Baseline agreement, before the revision

Calculated only from the supplied development table, using per-metric available
labels. These are descriptive comparisons to provisional human-assisted labels,
not a declaration that a judge or a human is necessarily correct. Completed
coverage and quality subtasks are assessed separately even when the claims task
failed. The supplied dagger marker's semantics were not assumed; raw task error
records independently establish the claims failures.

| Measure | Gemini Flash | GPT-4o |
|---|---:|---:|
| Coverage labels available | 11 | 11 |
| Coverage MAE, percentage points | 8.08 | 6.06 |
| Coverage mean signed error, judge minus human, percentage points | -8.08 | -6.06 |
| Coverage matching within 0.02 percentage points of rounding | 5/11 | 7/11 |
| Coverage ICC(2,1), absolute agreement | 0.625 | 0.562 |
| Quality labels available | 12 | 12 |
| Quality MAE, scale points | 1.17 | 1.58 |
| Quality mean signed error, judge minus human | +0.83 | +1.58 |
| Quality exact agreement | 3/12 | 2/12 |
| Quality within one point | 8/12 | 7/12 |
| Quality quadratic-weighted kappa | -0.147 | -0.156 |

One coverage label is missing and is excluded from coverage only. All quality
labels remain usable. One hallucination label is missing and another is
conflicting; exclude those only from hallucination comparisons until resolved.
No missing value is replaced by zero. Do not infer the conflicting label from
the displayed latest value or from judge agreement.

Coverage labels are aggregate percentages: nine per-item human decisions are
missing, so item accuracy and item kappa cannot be computed. No repeat human
labels or new-version judge scores were supplied. Do not infer an item vector
from an aggregate percentage. No claim-based hallucination agreement is reported:
the supplied judge table has no compatible hallucination outcomes, and raw human
audited/flagged occurrence counts are unavailable. Remaining substantive
disagreements and reference ambiguities require review, not automatic relabelling.

## Metric and review blockers left unchanged

`judge_poster` currently calculates:

```text
verified = extracted claims that have a returned verdict
n_claims_total = len(verified)
n_claims_unsupported = unsupported + contradicted, among verified claims
halluc_per1k = 1,000 * n_claims_unsupported / poster_word_count
```

The requested human measure is different:

```text
claim_hallucination_pct = 100 * flagged claim occurrences / total audited claim occurrences
```

Neither percentage nor its missing denominator can be recovered from a
per-word rate alone. A future code change should preserve `halluc_per1k`, add
explicit occurrence/audit-completeness counts and a separately named claim-based
percentage, and compare only identically counted, complete human/judge audits.
Do not reinterpret the existing acceptance threshold as a percentage.

Seven development claims tasks were truncated at the configured output limit.
Some incomplete rows currently display zero or a partial hallucination rate
despite `failed_tasks=claims`. Do not treat these as complete zero-hallucination
audits. Missing verdicts must invalidate the affected claim-rate comparison,
without invalidating otherwise completed coverage or quality subtasks.
`pilot_agreement.py` currently does not mask failed subtasks before computing
metrics, and its human loader derives coverage from nine item columns rather than
the supplied aggregate label. `results.py` instead excludes entire `parse_ok=0`
rows. Neither behavior implements per-metric availability reliably for this task.

The verifier's revised empty-verdict response uses the existing array shape and
missing-verdict error path; no new label or field is introduced. It cannot retain
a structured per-claim abstention reason with the current schema. The code may
still print a misleading zero on that flagged row. Future code should record
explicit verification limitations, mask incomplete rates, retain all extracted
occurrences in the audit denominator, and gate agreement on task-level validity.
Coverage and quality likewise have no structured abstention field for unresolved
source/image evidence; a reason alone does not trigger application review.

Prompts cannot recover raster table cells absent from text-only extraction or
source verification. Minimum input improvement: verified OCR/transcription with
row/column and caption context, or source/poster image evidence attached to those
calls. Complete occurrence enumeration can increase output size; smaller chunks
and verification batches need a later code/config revision rather than discarding
claims or deduplicating to fit the limit. No such changes are made here.

## Selective rerun and agreement commands, not executed

From `harness/`, after loading the usual environment and credentials, set
`CALIBRATION_CODES` to the supplied development-code list, checked against
`data/latex/judge_manifest.csv`. No frozen split file exists locally. Do not derive
holdout membership from observed scores or treat any supplied example as holdout.

Keep the new run in a separate data directory: the current raw-response filenames
do not include the prompt hash, so rerunning in the original data directory would
overwrite prior raw audit files even though CSV scores are versioned.

```bash
# Verify the frozen runtime hash before calibration or any future holdout run.
python -c 'import sys; sys.path.insert(0, "judge"); import judge; assert judge.prompt_sha256() == "b869632da1ad4b55ac22113283e19f071d648950b15ea1524b071b8280f5a11f"'

# Paid command: prepared only, not launched by this task.
caffeinate -i python judge/judge.py \
  --manifest data/latex/judge_manifest.csv \
  --only-codes "${CALIBRATION_CODES:?Set the approved development codes first}" --repeats 2 \
  --data-dir data/latex/calibration_revision_1

# Offline agreement command: conditional on the missing human input and validity
# blockers being resolved. CALIBRATION_HUMAN_SCORES must be a reviewed file in the
# existing human schema, with actual item decisions and appropriate raw counts.
# Do not substitute the supplied claim percentages into n_claims_unsupported.
python judge/pilot_agreement.py \
  --manifest data/latex/judge_manifest.csv \
  --human "${CALIBRATION_HUMAN_SCORES:?Set the reviewed human scores file first}" \
  --judge data/latex/calibration_revision_1/judge_scores.csv \
  --raw-dir data/latex/calibration_revision_1/judge_raw \
  --only-codes "${CALIBRATION_CODES:?Set the approved development codes first}" \
  --out-dir reports/calibration_revision_1
```

The agreement command is not directly usable on the supplied aggregate-only
table. Its hallucination output remains word-normalized, not the requested
claim-based comparison, even after compatible human counts are supplied. Until
task-level validity is handled, review failed-task rows separately rather than
accepting its printed agreement as a complete validated result.

After an independent holdout split is approved, freeze its membership without
opening content/scores. The following commands are templates only; their variables
must come from that predeclared split and reviewed human inputs, not score-based
selection. The same frozen hash and agreement blockers above apply.

```bash
caffeinate -i python judge/judge.py \
  --manifest data/latex/judge_manifest.csv \
  --only-codes "${HOLDOUT_CODES:?Set the predeclared holdout codes first}" --repeats 2 \
  --data-dir data/latex/holdout_revision_1

python judge/pilot_agreement.py \
  --manifest data/latex/judge_manifest.csv \
  --human "${HOLDOUT_HUMAN_SCORES:?Set the reviewed holdout scores file first}" \
  --judge data/latex/holdout_revision_1/judge_scores.csv \
  --raw-dir data/latex/holdout_revision_1/judge_raw \
  --only-codes "${HOLDOUT_CODES:?Set the predeclared holdout codes first}" \
  --out-dir reports/holdout_revision_1
```

Do not run, revise, or inspect that evaluation in this task. New-version
development agreement and independent holdout agreement remain unmeasured.

## Validation

Passed `python judge/tests/test_offline.py` with output under
`/tmp/poster-judge-prompt-revision-offline`: reference-sheet, fake-gateway judge,
real poster rendering, JSON repair, schema/CSV output, prompt-hash resume, and
synthetic pilot-agreement checks. These are software compatibility tests, not
evidence that the revised rubric agrees with humans. No real judge was called.

Checked that output field names and template-placeholder sets match the original
runtime prompts, and scanned them for development identifiers, generator names,
paper-specific numbers and calibration/holdout references. None are present.
The source reference-generation prompts are unchanged. The five runtime prompts
were revised once, without fitting successive versions to development scores.

Inspect the complete source diff with:

```bash
git diff -- harness/judge/prompts/system.md harness/judge/prompts/coverage.md \
  harness/judge/prompts/claims_extract.md harness/judge/prompts/claims_verify.md \
  harness/judge/prompts/quality.md
```

## Revision 2 (2026-11-01)

Prompt hash: `2436aa149d86bdcca81859577dce3c270efe6604190a60499f8513ffea4f0e02` (revision 1 was `b869632d…`).
No variable definition or formula changed; every CSV column is computed as before.

What changed:
1. **Quality checklist** (`quality.md`). Before scoring, the judge records eight yes/no
   observations with locations: empty space, overflow, duplicated visual, small figure/table
   text, dense text, caption mismatch, unclear order, hidden main result. Each problem found
   must appear in the matching criterion's reason. Kept in `judge_raw/` only.
2. **Unused canvas** (`quality.md`). The old wording excused large blank areas unless content
   was compressed elsewhere. Now unused canvas is a layout weakness, judged by blank space and
   not word count, so a short poster that fills its canvas is not penalized.
3. **Typed table plus table image** (`quality.md`). The duplicated-visual check names a table
   typed as text and also shown as an image of the same table (seen on P01).
4. **Derived numbers** (`claims_extract.md`, `claims_verify.md`). A sentence with several
   values becomes one claim per value; differences, gains and ratios are recomputed from the
   paper's numbers, with the computation in the reason.
5. **Blank instead of 0** (`judge.py`). A claims task that did not finish leaves `n_claims_*`
   and `halluc_per1k` blank instead of writing partial counts. Five recorded rows were blanked
   (four Gemini rows in `data/latex/judge_scores.csv`, P-KXPT in `gpt4o_calibration_revision_1/`).

Why (from the team's hand scores on the 12 development posters):
- GPT-4o (revision 1) gave every poster quality 4, with near-identical reasons.
- Humans scored the three short Llama posters 1-2 and the rest 3-4. Both judges scored the Llama
  posters highest (GPT-4o 5.0 mean on the original prompt). These posters leave much of the
  canvas blank.
- On P-BZ7R GPT-4o accepted "OCA added 2.7%, REG 2.4%"; the paper's Table IV gives 3.67 and 2.33.

Tested (few cents, single calls, not an agreement measurement):
- Change 4 works: GPT-4o now flags the P-BZ7R claim.
- Change 2 does not fix GPT-4o: on the dry-run P01 Llama poster (bottom half blank) it still
  answered "no empty space" and scored 4. Asked directly outside the scoring task, it did say
  the bottom is mostly blank. A code measurement of blank canvas would fix this; the team chose
  not to add one, so expect GPT-4o to keep overrating sparse posters.
- Change 3 is untested.

Tried and dropped: sending four zoomed quarters of the poster (about 4,000 more tokens per
poster per judge; did not help GPT-4o see the layout); asking the judge to describe the top,
middle and bottom of the poster first (it listed section names instead of seeing blank space).

Not done, because they would change a variable's definition or calculation: computing the
holistic score from the sub-scores; removing fidelity from quality.

Bias checks for the re-run:
- The hand scores in `manual_scoring.pdf` name the model next to each poster, so they were not
  blind. Score the holdout posters by code only.
- No worked examples from the 12 development posters were added to any prompt.
- After the re-run, compare the judge-minus-human gap per candidate model; a gap that stands out
  for one model means the judge is biased for or against it.

Protocol: spec/08 allows one revision per judge. Revision 2 was made on the same development
posters before any holdout result; the team should record whether it counts as the second.

Re-run GPT-4o on the 12 development posters (about $1.80; separate folder so revision 1 raw
files are kept):

```bash
caffeinate -i python judge/judge.py --judges openai.gpt-4o --manifest data/latex/judge_manifest.csv \
  --only-codes P-9C6K,P-A4AR,P-BZ7R,P-C2FT,P-K9BT,P-KXPT,P-PST6,P-QQS9,P-SH4A,P-YB63,P-Z35D,P-Z8KP \
  --data-dir data/latex/gpt4o_calibration_revision_2
```
