# Financial impact analysis

Run from the repository root:

```bash
Rscript financial_analysis/financial_impacts.R
```

The script needs only base R and does not run poster generation or judging. It
reads the recorded attempts and produces auditable CSV results under `results/`.
The existing `tim_example.R` and `process_control.R` are preserved. The example's
idea of defining a financial statistic and bootstrapping it is retained, but
control limits are not appropriate cost or quality acceptance limits here.

## What is calculated

For every initial attempt or recovery:

```text
API cost = (input tokens * input USD per million
          + output tokens * output USD per million) / 1,000,000

Paper/model cost = initial cost + every recorded incremental recovery cost
Paired saving for paper i = Claude cost_i - candidate cost_i
Average saving = mean(paired savings over the same papers)
Projected expected saving at volume N = N * average saving
```

The script validates the entire recorded 15-paper by four-model grid, links each
recovery to its original paper/model, and checks recomputed token prices against
each logged cost to the workflow's six-decimal rounding precision. It includes
failed attempts and the interrupted attempt, and counts recovery increments only.
It deliberately does not sum copied `detail_log.json` cumulative counters.

The default before/after scenario is replacing Claude with Qwen for generation.
The output also compares the other candidates with Claude. GPT-4o is an evaluation
judge in this experiment, not a candidate generator; the earlier fixed-token
GPT-4o example cannot stand in for observed before/after generation costs.

There are currently 15 observed papers, not 30. All 15 are used for the financial
pilot budget, including the development papers. This is not an independent
quality evaluation. A 30-paper result is a projection of expected spend at a
similar paper mix, not an observed 30-paper experiment or a prediction interval
for the realized cost of 30 future papers.

## Bootstrap and uncertainty

The code resamples 15 paper IDs with replacement, 10,000 times, with seed 5300.
Every selected paper brings all four model costs and their recorded recovery
histories together. The 2.5th and 97.5th percentiles of the mean paired differences
give an approximate 95% percentile bootstrap confidence interval. The same index
matrix is used for all candidate comparisons. The point estimate is the observed
mean, not the median of the bootstrap replicates.

This is uncertainty about expected average savings across similar papers under
fixed prices and the recorded retry policy. The historical pilot spend is already
known; it does not need a confidence interval. The interval does not include
future price changes, provider usage not returned after an interrupted call,
different recovery policies, or uncertainty about labor, quality, taxes, local
compute, credits or support overhead. The small convenience pilot limits
generalization; multiple cost comparisons are exploratory and unadjusted.

## Pricing and corrections to the draft

`prices_snapshot.csv` transcribes `harness/config/prices.yaml`, dated 2026-10-31,
whose stated source is the Cornell gateway `/model/info` endpoint. These rates
reproduce the historical logs. No authenticated price refresh was made and they
are not represented as a current price quotation or invoice.

- Claude input is $5/M and output $25/M, not the reverse.
- Qwen input is $0.53/M and output $2.66/M; the draft's $0.83 conflicts with its table.
- The saved snapshot lists GPT-5.6 at $4/M input and $20/M output, rather than
  $5/$30 in the draft. Judge rates also differ. Keep rates, route and dates explicit.
- The client makes ordinary chat-completion requests; do not label these rates
  “Batch” or apply a batch discount without evidence of that billing route.
- The draft's illustrative $0.302775 and $0.059973 arithmetic is correct for its
  assumed 98,100/3,000 token counts and quoted rates. Its workload and price
  provenance are not established for this workflow. `draft_illustration_only.csv`
  reproduces the arithmetic without treating it as empirical evidence.
- `draft_price_sensitivity.csv` separately reprices observed token counts using
  the candidate prices supplied in the draft; these are unverified scenarios.

Cornell's public page says charges depend on token consumption and directs users
to login-protected model pricing. It does not independently verify the exact
model rates in the draft. Retain the saved snapshot and compare against gateway
billing records before submission. Cornell also describes a $10 monthly team
allowance; gross token-cost savings need not equal cash savings after credits.

## Decision and labor sensitivity

The script reports spend per requested paper and, separately, all spend divided
by automatic workflow successes. The latter allocates failed-work expense but
is not cost per poster meeting every coverage, hallucination and quality gate.
Failures are never dropped to make a cheap model look financially superior.

Qwen passed the automatic workflow check on 10/15 papers, Claude 8/15, GPT-5.6
14/15, and Llama 15/15. These are not complete quality-qualified counts. Do not
recommend deployment solely on token cost or treat development judge scores as
independent acceptance evidence. Further retries could change costs and success.

Net benefit requires measured differences in review/correction time, recurring
judge costs if deployed, local compute and implementation costs. The analysis
does not invent those measurements. For a sensitivity check only, BLS lists a
May 2025 technical-writer median wage of $43.46/hour. This is not the team's actual
or fully loaded labor cost. Extra review seconds that consume the API savings are:

```text
break-even extra review seconds = mean API saving / hourly wage * 3,600
net saving = API saving - hourly wage * additional review minutes / 60
```

The point estimate is about 28 seconds for the Claude-to-Qwen comparison. Benefits
would shorten that time. BLS wage uncertainty is not estimated; the interval on
break-even time transforms only the bootstrap cost interval at that fixed proxy.

## Files and provenance

- `results/attempt_costs.csv`: each observed attempt and cost reconstruction.
- `results/paper_model_costs.csv`: one row per matched paper/model.
- `results/model_summary.csv`: tokens, costs, attempts and workflow outcomes.
- `results/paired_savings.csv`: before/after comparisons and bootstrap intervals.
- `results/bootstrap_model_means.csv`: 10,000 replicates, all model costs paired.
- `results/input_fingerprints.csv`: input hashes for reproducing this run.
- `results/analysis_metadata.csv` and `R_session.txt`: settings and runtime.
- `Financial_Impacts.docx`: 300–500 word report section plus references.

Rebuild the document after running R with the bundled document-runtime Python:

```bash
/Users/jellies/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python financial_analysis/build_report.py
```

Render and visually verify after document changes using the documents skill's
`render_docx.py --renderer artifact-tool` before submitting it.

## Sources checked online

1. Cornell Information Technologies. *AI Platform*, Cost section.
   https://it.cornell.edu/aiplatform (accessed 2026-11-01).
2. U.S. Bureau of Labor Statistics. *Technical Writers*, Occupational Outlook
   Handbook. May 2025 median wage: $90,390/year, $43.46/hour.
   https://www.bls.gov/ooh/media-and-communication/technical-writers.htm
   (accessed 2026-11-01).
3. R Core/boot documentation. *Bootstrap Resampling* and *Nonparametric Bootstrap
   Confidence Intervals*.
   https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.html
   and https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.ci.html
   (accessed 2026-11-01). Base R implements the paper-level percentile calculation
   directly; the `boot` package is not a dependency of this script.
4. Project records: `harness/config/prices.yaml`, `harness/data/latex/runs.csv`,
   `harness/data/latex/recovery_attempts.csv`. Price snapshot dated 2026-10-31.

The broad generative-AI adoption statistic and the upstream fixed-token estimate
are unnecessary to the measured pilot cost argument and are omitted from the
report rather than retaining unverified or financially indirect claims.
