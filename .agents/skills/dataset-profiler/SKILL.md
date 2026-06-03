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
4. Report shape, columns, inferred types, sample rows, missingness, duplicate counts, and obvious parsing issues.
5. Flag suspicious values, inconsistent categories, impossible dates, high-cardinality identifiers, likely keys, and potential outliers.
6. Distinguish verified observations from inferred meanings.
7. If a file cannot be read, state the filename and the error or limitation.
