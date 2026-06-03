---
name: ml-modeling
description: Build responsible baseline-first machine-learning analyses with leakage checks, appropriate splits, and task-specific metrics.
---

# ML Modeling

Use this skill for classification, regression, clustering, ranking, or model evaluation tasks.

## Procedure

1. Install Tier 1 and Tier 2 (`bash .agents/bootstrap_packages.sh 2`).
2. Identify the target, prediction unit, available features, and success metric.
3. Check for target leakage, duplicated entities across splits, temporal leakage, and post-outcome fields.
4. Build a simple baseline before more complex models.
5. Choose validation strategy based on data structure: random, stratified, grouped, or chronological.
6. Use appropriate metrics and include confusion matrices, residual checks, feature importance, or calibration when relevant.
7. Report limitations, likely failure modes, and recommendations for production use only if requested.
