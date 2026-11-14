# Paper2Poster financial impact analysis
# Adapted to the structure of Tim Fraser's ZZ_financial_analysis.R example.
# Uses base R only. No observations or financial results are fabricated.
#
# HOW TO USE
# 1. source("financial_analysis/financial.R") # from repository root
# 2. write_poster_template("poster_results.csv")  # creates an EMPTY template
# 3. Fill it with your measured experiment results, then save the CSV.
# 4. results <- read.csv("poster_results.csv", stringsAsFactors = FALSE)
# 5. out <- qi(results)
# 6. out$financial_estimates
#    out$performance
#    out$observed_spending
#
# ANALYSIS UNIT: one completed experimental workflow per paper and candidate
# model, under the SAME retry policy. Sum all billed attempts inside that
# workflow. Do not put individual API calls or retries in separate rows here.
# If you independently repeat complete workflows, adapt the analysis to that
# repeated-run design rather than treating all repeats as independent papers.
#
# REQUIRED COLUMNS
# paper_id: same paper ID across candidate models
# model: exact candidate/generator model ID (not the judge model)
# generation_cost_usd: measured total generation API cost, including internal
#   LLM/VLM calls, failed attempts, repairs, and reruns for this workflow
# judge_cost_usd: separate final evaluation charges; do NOT double-count charges
#   already included in generation_cost_usd
# workflow_success: 1 if a poster was produced, 0 otherwise
# acceptable: 1 if the final poster met your PREDEFINED performance criteria,
#   0 otherwise; an unsuccessful workflow must have acceptable = 0
#
# Keep raw API request logs (tokens, billed models, prices, caching, and fees)
# as the evidence behind each cost. Prefer the gateway's itemized cost when
# available. Do not substitute a literature average for actual usage.
#
# COST SCOPE
# Default: generation API cost only. include_judging = TRUE adds final judging
# costs when judging will also be part of the deployed production workflow.
# All judging costs are still shown in the observed experiment spending table.
# This script does not price staff time, hardware, or switching costs.
#
# INTERPRETATION
# The CI describes expected mean savings for comparable papers, conditional on
# the selected models, prices, retry policy, and cost scope. Observed spending
# is a known total once billed; its bootstrap-scaled counterpart is an estimate
# of expected spending on a future workload, NOT a prediction interval.
# Keep the baseline/candidate comparison fixed before inspecting the results.
# If selecting a winning model from several alternatives, validate that choice
# on new papers or use an analysis that accounts for model selection.
# Report performance alongside cost; low cost alone does not establish value.
#
# METHOD REFERENCES
# https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.html
# https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.ci.html

write_poster_template <- function(file = "poster_results.csv") {
    if (file.exists(file)) {
        stop("Template destination already exists; choose another filename.")
    }
    template <- data.frame(
        paper_id = character(), model = character(),
        generation_cost_usd = numeric(), judge_cost_usd = numeric(),
        workflow_success = integer(), acceptable = integer()
    )
    write.csv(template, file, row.names = FALSE)
    invisible(template)
}

# Only for ordinary uncached token billing with no extra fees.
# For caching, separately priced modalities, tools, or other billing rules,
# price every charge category correctly or use the itemized gateway cost.
api_cost_usd <- function(input_tokens, output_tokens,
                         input_rate_per_million, output_rate_per_million) {
    inputs <- list(
        input_tokens, output_tokens,
        input_rate_per_million, output_rate_per_million
    )
    valid <- vapply(inputs, function(x) {
        is.numeric(x) && length(x) > 0L && all(is.finite(x)) && all(x >= 0)
    }, logical(1))
    if (!all(valid)) stop("Tokens and rates must be finite, nonnegative numbers.")
    lengths <- vapply(inputs, length, integer(1))
    if (any(lengths != 1L & lengths != max(lengths))) {
        stop("Arguments must have length one or a common length.")
    }
    (input_tokens * input_rate_per_million +
        output_tokens * output_rate_per_million) / 1000000
}

.flag01 <- function(x, label) {
    if (is.logical(x) && !anyNA(x)) {
        return(as.integer(x))
    }
    if (is.numeric(x) && all(is.finite(x)) && all(x %in% c(0, 1))) {
        return(as.integer(x))
    }
    stop(paste(label, "must contain measured 0/1 or TRUE/FALSE values without NA."))
}

# STEP 1: One statistic function, like f() in the instructor's example.
# Adapted from tim_version.R and the subgroup/percentile approach in
# functions_process_control.R::get_index(). Do not source those scripts here:
# Tim's example executes an unrelated onsen analysis and requires absent data.
.paired <- function(data, baseline, candidate, include_judging) {
    required <- c("paper_id", "model", "generation_cost_usd", "judge_cost_usd",
                  "workflow_success", "acceptable")
    if (!all(required %in% names(data))) stop("Missing required columns.")
    if (length(baseline) != 1L || length(candidate) != 1L ||
        is.na(baseline) || is.na(candidate) || baseline == candidate)
        stop("Choose two distinct model IDs.")
    if (!is.logical(include_judging) || length(include_judging) != 1L ||
        is.na(include_judging)) stop("include_judging must be TRUE or FALSE.")
    if (anyNA(data$paper_id) || anyNA(data$model) ||
        any(!nzchar(as.character(data$paper_id))) || any(!nzchar(data$model)))
        stop("Paper and model IDs must be nonempty.")
    d <- data[data$model %in% c(baseline, candidate), required, drop = FALSE]
    if (anyDuplicated(d[c("paper_id", "model")]))
        stop("Aggregate all workflow charges first: one row per paper/model.")
    for (col in c("generation_cost_usd", "judge_cost_usd")) {
        if (!is.numeric(d[[col]]) || any(!is.finite(d[[col]])) || any(d[[col]] < 0))
            stop(paste(col, "must be finite nonnegative measured costs."))
    }
    d$workflow_success <- .flag01(d$workflow_success, "workflow_success")
    d$acceptable <- .flag01(d$acceptable, "acceptable")
    if (any(d$acceptable > d$workflow_success))
        stop("Unsuccessful workflows cannot be acceptable.")
    b <- d[d$model == baseline, , drop = FALSE]
    c <- d[d$model == candidate, , drop = FALSE]
    if (nrow(b) < 2L || !setequal(b$paper_id, c$paper_id))
        stop("Need at least two matched papers, with both models for every paper.")
    c <- c[match(b$paper_id, c$paper_id), , drop = FALSE]
    cost <- function(x) x$generation_cost_usd +
        if (include_judging) x$judge_cost_usd else 0
    list(pairs = data.frame(paper_id = b$paper_id,
                           baseline_cost = cost(b), candidate_cost = cost(c),
                           baseline_acceptable = b$acceptable,
                           candidate_acceptable = c$acceptable), data = d)
}

# Before/after quantities from one paired dataset. Positive savings favors
# the candidate. Cost per acceptable output includes spending on failures.
f <- function(pairs) {
    ratio <- function(cost, acceptable) {
        if (sum(acceptable) == 0) return(NA_real_)
        sum(cost) / sum(acceptable)
    }
    c(baseline_mean_cost = mean(pairs$baseline_cost),
      candidate_mean_cost = mean(pairs$candidate_cost),
      mean_savings = mean(pairs$baseline_cost - pairs$candidate_cost),
      baseline_cost_per_acceptable = ratio(pairs$baseline_cost, pairs$baseline_acceptable),
      candidate_cost_per_acceptable = ratio(pairs$candidate_cost, pairs$candidate_acceptable))
}

# STEPS 2-6: paired resampling, percentile intervals, and reusable qi().
qi <- function(data, baseline = "openai.gpt-4o",
               candidate = "qwen.qwen3-vl-235b-a22b", B = 10000L,
               seed = 5300L, future_n = 30L, include_judging = FALSE) {
    if (length(B) != 1L || !is.finite(B) || B < 1000 || B != floor(B))
        stop("B must be an integer of at least 1000.")
    if (length(future_n) != 1L || !is.finite(future_n) ||
        future_n < 1 || future_n != floor(future_n)) stop("Invalid future_n.")
    paired <- .paired(data, baseline, candidate, include_judging)
    p <- paired$pairs
    estimate <- f(p)
    set.seed(seed)
    boot <- replicate(B, {
        idx <- sample.int(nrow(p), nrow(p), replace = TRUE)
        f(p[idx, , drop = FALSE])
    })
    intervals <- t(vapply(seq_along(estimate), function(j) {
        values <- boot[j, ]
        # Dropping undefined ratio replicates would condition on successes
        # and misrepresent uncertainty; leave that interval unavailable.
        if (any(!is.finite(values))) return(c(se = NA, lower = NA, upper = NA))
        c(se = sd(values), lower = unname(quantile(values, .025)),
          upper = unname(quantile(values, .975)))
    }, c(se = 0, lower = 0, upper = 0)))
    fin <- data.frame(term = names(estimate), estimate = unname(estimate),
                      intervals, row.names = NULL)
    future <- fin[fin$term == "mean_savings", , drop = FALSE]
    future$term <- paste0("expected_savings_for_", future_n, "_future_papers")
    future[c("estimate", "se", "lower", "upper")] <-
        future[c("estimate", "se", "lower", "upper")] * future_n
    d <- paired$data
    performance <- do.call(rbind, lapply(c(baseline, candidate), function(m) {
        x <- d[d$model == m, , drop = FALSE]
        data.frame(model = m, n = nrow(x), successes = sum(x$workflow_success),
                   acceptable = sum(x$acceptable),
                   success_rate = mean(x$workflow_success),
                   acceptable_rate = mean(x$acceptable))
    }))
    spending <- aggregate(d[c("generation_cost_usd", "judge_cost_usd")],
                           by = list(model = d$model), FUN = sum)
    spending$total_experiment_cost_usd <- spending$generation_cost_usd + spending$judge_cost_usd
    if (any(!is.finite(boot))) warning("A cost-per-acceptable interval is unavailable: zero acceptable outputs in some samples.")
    list(financial_estimates = rbind(fin, future), performance = performance,
         observed_spending = spending, bootstrap = boot, paired_data = p,
         settings = list(B = B, seed = seed, n_papers = nrow(p),
                         include_judging = include_judging, future_n = future_n))
}

# STEP 7: Rough estimate using literature usage and the user's quoted rates.
# GPT-4o gateway rates remain unverified. Qwen matches AWS US on-demand rates
# checked 2026-10-29 (https://aws.amazon.com/bedrock/pricing/).
# Usage: Pang et al. (2025), Appendix E.2:
# https://arxiv.org/html/2505.21497v2#A5.SS2
# These are deterministic scenarios, NOT measured results or confidence limits.
rough_estimate <- function(n_posters = 30L) {
    if (length(n_posters) != 1L || !is.finite(n_posters) ||
        n_posters < 1 || n_posters != floor(n_posters)) stop("Invalid n_posters.")
    baseline <- api_cost_usd(98100, 3000, 2.75, 11)
    multiplier <- c(0.5, 1, 2)
    candidate <- api_cost_usd(98100 * multiplier, 3000 * multiplier, .53, 2.66)
    data.frame(qwen_usage_multiplier = multiplier,
               baseline_per_poster_usd = baseline,
               candidate_per_poster_usd = candidate,
               baseline_total_usd = n_posters * baseline,
               candidate_total_usd = n_posters * candidate,
               savings_total_usd = n_posters * (baseline - candidate),
               savings_percent = 100 * (baseline - candidate) / baseline)
}
