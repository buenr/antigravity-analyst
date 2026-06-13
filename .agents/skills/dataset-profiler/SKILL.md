---
name: dataset-profiler
description: Inspect uploaded datasets for structure, quality, missingness, duplicates, suspicious values, and profiling summaries before analysis.
---

# Dataset Profiler

Use this skill whenever a task depends on uploaded data or asks for an analyst brief.

## Procedure

1. Install Tier 1 (`bash .agents/bootstrap_packages.sh 1`); add Tier 2 for `missingno` or large-file profiling with `pyarrow`.
2. List files under `/workspace/data` and identify readable formats.
3. Load each dataset with safe, format-aware readers.
4. Identify the apparent business grain of each dataset, such as one row per customer, order, transaction, account, product, date, or event.
5. Report shape, columns, inferred types, sample rows, missingness, duplicate counts, and obvious parsing issues.
6. Flag suspicious values, inconsistent categories, impossible dates, high-cardinality identifiers, likely keys, and potential outliers.
7. Identify likely measures, dimensions, dates, IDs, KPI candidates, and join keys, labeling inferred meanings as guesses.
8. Summarize data readiness: what can be analyzed now, what needs cleaning, and which quality risks could change business conclusions.
9. Recommend practical cleaning or validation steps, such as standardizing categories, handling missing values, deduplicating records, or confirming definitions.
10. Distinguish verified observations from inferred meanings.
11. If a file cannot be read, state the filename and the error or limitation.

## Visualization for profiling

When profiling, use these visual checks:

- **Missingness patterns**: Use `missingno.matrix()` or `missingno.heatmap()` to visualize missing data structure (requires Tier 2).
- **Distributions**: Plot histograms or density plots for numeric columns to identify skew, multimodality, and outliers.
- **Cardinality**: Bar charts of value counts for categorical columns to spot high-cardinality fields or dominant categories.
- **Correlations**: Heatmap of pairwise correlations for numeric fields to detect relationships and potential redundancies.
- **Outliers**: Box plots or violin plots for key numeric fields to visualize spread and extreme values.
