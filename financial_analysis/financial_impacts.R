#!/usr/bin/env Rscript
# Run from anywhere: Rscript /path/to/financial_analysis/financial_impacts.R
# Base R only. Reads logs without editing them. No credentials or API calls.
# Adapted conceptually from tim_example.R: define a financial statistic and
# resample its observational units. Here the unit is a whole paper, paired
# across models, not an attempt or an individual token.

argv <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", argv, value = TRUE)
stopifnot(length(script_arg) == 1)
analysis_dir <- dirname(normalizePath(sub("^--file=", "", script_arg)))
repo <- dirname(analysis_dir)
out <- file.path(analysis_dir, "results")
dir.create(out, showWarnings = FALSE, recursive = TRUE)
seed <- 5300L
replicates <- 10000L
projection_n <- 30L
# BLS OOH, Technical Writers: May 2025 median hourly wage, accessed 2026-11-01.
# Sensitivity proxy only: not this team's wage, loaded labor cost, or time saving.
hourly_wage <- 43.46
baseline_model <- "claude-opus-5"
comparison_model <- "qwen.qwen3-vl-235b-a22b"

read_log <- function(relative) {
  p <- file.path(repo, relative)
  stopifnot(file.exists(p))
  read.csv(p, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA"))
}
original <- read_log("harness/data/latex/runs.csv")
recovery <- read_log("harness/data/latex/recovery_attempts.csv")
prices <- read.csv(file.path(analysis_dir, "prices_snapshot.csv"), stringsAsFactors = FALSE)
stopifnot(!anyDuplicated(prices$model))
stopifnot(!anyDuplicated(original$run_id), !anyDuplicated(recovery$run_id))
stopifnot(!any(recovery$run_id %in% original$run_id))
stopifnot(all(recovery$original_run_id %in% original$run_id))
stopifnot(!anyDuplicated(paste(original$input_paper_id, original$llm_model)))
# Financial analysis of one configured initial experiment attempt per pair.
# A separate experiment with repeated initial attempts needs an explicit policy.
stopifnot(all(original$attempt == 1))

fields <- c(
  "run_id", "input_paper_id", "llm_model", "input_tokens", "output_tokens",
  "token_usage", "generation_cost", "workflow_success", "failure_reason"
)
initial <- original[, fields]
initial$original_run_id <- original$run_id
initial$completion_attempt <- 1L
initial$source <- "runs.csv"
later <- recovery[, fields]
later$original_run_id <- recovery$original_run_id
later$completion_attempt <- recovery$completion_attempt
later$source <- "recovery_attempts.csv"
attempts <- rbind(initial, later)
stopifnot(!anyNA(attempts[, c("input_tokens", "output_tokens", "token_usage", "generation_cost")]))
stopifnot(all(attempts$input_tokens >= 0), all(attempts$output_tokens >= 0))
stopifnot(all(attempts$token_usage == attempts$input_tokens + attempts$output_tokens))
stopifnot(all(attempts$workflow_success %in% c(0, 1)))
parent <- match(recovery$original_run_id, original$run_id)
stopifnot(
  all(recovery$input_paper_id == original$input_paper_id[parent]),
  all(recovery$llm_model == original$llm_model[parent])
)
rate <- prices[match(attempts$llm_model, prices$model), ]
stopifnot(!anyNA(rate$input_per_million), !anyNA(rate$output_per_million))
attempts$cost_recomputed_usd <- (attempts$input_tokens * rate$input_per_million +
  attempts$output_tokens * rate$output_per_million) / 1e6
# The workflow rounds each logged attempt to six decimals.
stopifnot(all(abs(attempts$cost_recomputed_usd - attempts$generation_cost) <= 0.000000501))
attempts$price_date <- rate$price_date
write.csv(attempts, file.path(out, "attempt_costs.csv"), row.names = FALSE, na = "")

paper_model <- do.call(rbind, lapply(seq_len(nrow(original)), function(i) {
  first <- original[i, ]
  records <- attempts[attempts$original_run_id == first$run_id, ]
  records <- records[order(records$completion_attempt), ]
  # Recovery rows contain new usage only. Do not use their cumulative counters
  # as additional spend and do not sum detail_log.json across copied folders.
  data.frame(
    paper = first$input_paper_id, model = first$llm_model,
    original_run_id = first$run_id, completion_attempts = nrow(records),
    first_attempt_success = first$workflow_success,
    workflow_success = as.integer(any(records$workflow_success == 1)),
    input_tokens = sum(records$input_tokens), output_tokens = sum(records$output_tokens),
    total_tokens = sum(records$token_usage),
    cost_usd = sum(records$generation_cost),
    cost_unrounded_usd = sum(records$cost_recomputed_usd)
  )
}))
stopifnot(abs(sum(paper_model$cost_usd) - sum(attempts$generation_cost)) < 1e-10)
stopifnot(sum(paper_model$total_tokens) == sum(attempts$token_usage))
write.csv(paper_model, file.path(out, "paper_model_costs.csv"), row.names = FALSE)
models <- unique(original$llm_model)
papers <- sort(unique(original$input_paper_id))
stopifnot(nrow(paper_model) == length(papers) * length(models))
cost_matrix <- vapply(models, function(model) {
  part <- paper_model[paper_model$model == model, ]
  stopifnot(setequal(part$paper, papers))
  part$cost_usd[match(papers, part$paper)]
}, numeric(length(papers)))
success_matrix <- vapply(models, function(model) {
  part <- paper_model[paper_model$model == model, ]
  part$workflow_success[match(papers, part$paper)]
}, numeric(length(papers)))
rownames(cost_matrix) <- rownames(success_matrix) <- papers
summary <- do.call(rbind, lapply(models, function(model) {
  part <- paper_model[paper_model$model == model, ]
  data.frame(
    model = model, papers_requested = nrow(part),
    first_attempt_successes = sum(part$first_attempt_success),
    eventual_workflow_successes = sum(part$workflow_success),
    eventual_workflow_success_rate = mean(part$workflow_success),
    recorded_completion_attempts = sum(part$completion_attempts),
    total_tokens = sum(part$total_tokens),
    total_generation_cost_usd = sum(part$cost_usd),
    mean_cost_per_requested_paper_usd = mean(part$cost_usd),
    # Allocate ALL spend to completed outputs, including failed work.
    # This is not cost per quality-qualified poster.
    spend_per_workflow_success_usd = if (sum(part$workflow_success) > 0) {
      sum(part$cost_usd) / sum(part$workflow_success)
    } else {
      NA_real_
    }
  )
}))
write.csv(summary, file.path(out, "model_summary.csv"), row.names = FALSE)

# Pair each resampled paper with all its candidate results. Identical indices
# are used for before/after and for each pricing sensitivity. Never bootstrap
# baseline and candidate independently or omit failed generation attempts.
set.seed(seed)
indices <- replicate(replicates, sample.int(length(papers), length(papers), replace = TRUE))
stopifnot(nrow(indices) == length(papers), ncol(indices) == replicates)
bootstrap_means <- t(apply(indices, 2, function(ids) colMeans(cost_matrix[ids, , drop = FALSE])))
colnames(bootstrap_means) <- models
interval <- function(x) unname(quantile(x, c(0.025, 0.975), type = 7))
savings <- do.call(rbind, lapply(setdiff(models, baseline_model), function(model) {
  delta <- cost_matrix[, baseline_model] - cost_matrix[, model]
  boot_delta <- bootstrap_means[, baseline_model] - bootstrap_means[, model]
  boot_pct <- 100 * boot_delta / bootstrap_means[, baseline_model]
  ci <- interval(boot_delta)
  pct_ci <- interval(boot_pct)
  before_ci <- interval(bootstrap_means[, baseline_model])
  after_ci <- interval(bootstrap_means[, model])
  data.frame(
    baseline = baseline_model, candidate = model, paired_papers = length(papers),
    before_mean_usd = mean(cost_matrix[, baseline_model]),
    after_mean_usd = mean(cost_matrix[, model]),
    before_mean_ci_low = before_ci[1], before_mean_ci_high = before_ci[2],
    after_mean_ci_low = after_ci[1], after_mean_ci_high = after_ci[2],
    savings_per_requested_paper_usd = mean(delta),
    savings_ci_low = ci[1], savings_ci_high = ci[2],
    relative_cost_reduction_pct = 100 * mean(delta) / mean(cost_matrix[, baseline_model]),
    reduction_pct_ci_low = pct_ci[1], reduction_pct_ci_high = pct_ci[2],
    observed_pilot_savings_usd = sum(delta),
    projected_n = projection_n,
    projected_before_usd = projection_n * mean(cost_matrix[, baseline_model]),
    projected_after_usd = projection_n * mean(cost_matrix[, model]),
    projected_savings_usd = projection_n * mean(delta),
    expected_savings_ci_low = projection_n * ci[1],
    expected_savings_ci_high = projection_n * ci[2],
    wage_proxy_usd_per_hour = hourly_wage,
    extra_review_break_even_seconds = mean(delta) / hourly_wage * 3600,
    break_even_seconds_ci_low = ci[1] / hourly_wage * 3600,
    break_even_seconds_ci_high = ci[2] / hourly_wage * 3600
  )
}))
write.csv(savings, file.path(out, "paired_savings.csv"), row.names = FALSE)
write.csv(data.frame(replicate = seq_len(replicates), bootstrap_means),
  file.path(out, "bootstrap_model_means.csv"),
  row.names = FALSE
)

# Optional, explicitly UNVERIFIED reprice using the user's draft candidate rates.
# These are not substituted for the observed historical costs.
draft_in <- c(5, 5, 0.24, 0.53)
draft_out <- c(25, 30, 0.97, 2.66)
names(draft_in) <- names(draft_out) <- c(
  "claude-opus-5", "gpt-5.6-sol",
  "meta.llama-4-maverick-17b-instruct", "qwen.qwen3-vl-235b-a22b"
)
sensitivity <- do.call(rbind, lapply(models, function(model) {
  part <- paper_model[paper_model$model == model, ]
  hypothetical <- (part$input_tokens * draft_in[model] + part$output_tokens * draft_out[model]) / 1e6
  data.frame(
    model = model, logged_historical_cost_usd = sum(part$cost_usd),
    repriced_draft_table_usd = sum(hypothetical),
    status = "Draft rates supplied by user; not verified gateway charges"
  )
}))
write.csv(sensitivity, file.path(out, "draft_price_sensitivity.csv"), row.names = FALSE)

# Reproduce the arithmetic of the user's illustrative fixed-token example only.
# Its token counts are an assumption, not measured counts from this workflow.
illustration <- data.frame(
  model = c("openai.gpt-4o", comparison_model),
  assumed_input_tokens = 98100, assumed_output_tokens = 3000,
  draft_input_rate = c(2.75, 0.53), draft_output_rate = c(11, 2.66)
)
illustration$assumed_cost_usd <- with(
  illustration,
  (assumed_input_tokens * draft_input_rate + assumed_output_tokens * draft_output_rate) / 1e6
)
write.csv(illustration, file.path(out, "draft_illustration_only.csv"), row.names = FALSE)

# A deterministic 15-paper spend has no sampling uncertainty once logged.
# These intervals concern expected mean savings for similar papers at fixed
# prices and the observed recovery policy. They are not future-total prediction
# intervals, invoice guarantees, or evidence that quality gates are met.
inputs <- c(
  file.path(repo, "harness/data/latex/runs.csv"),
  file.path(repo, "harness/data/latex/recovery_attempts.csv"),
  file.path(analysis_dir, "prices_snapshot.csv")
)
write.csv(data.frame(file = inputs, md5 = unname(tools::md5sum(inputs))),
  file.path(out, "input_fingerprints.csv"),
  row.names = FALSE
)
metadata <- data.frame(
  key = c(
    "bootstrap_replicates", "seed", "observed_papers",
    "projection_papers", "wage_proxy_usd_per_hour", "R_version", "interval_type", "excluded_costs"
  ),
  value = c(
    replicates, seed, length(papers), projection_n, hourly_wage,
    R.version.string, "Paired paper-level percentile 95%; quantile type 7",
    "Judge/reference-sheet calls, labor, local compute, credits and unreported provider usage"
  )
)
write.csv(metadata, file.path(out, "analysis_metadata.csv"), row.names = FALSE)
capture.output(sessionInfo(), file = file.path(out, "R_session.txt"))
cat("Validated", nrow(original), "original and", nrow(recovery), "recovery attempts.\n")
print(summary, row.names = FALSE)
cat("\nPaired cost comparison for the report:\n")
print(savings[savings$candidate == comparison_model, ], row.names = FALSE)
cat("\nOutputs:", out, "\n")
