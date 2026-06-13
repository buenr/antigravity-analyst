---
name: ml-modeling
description: Build responsible baseline-first machine-learning analyses with leakage checks, appropriate splits, and task-specific metrics.
---

# ML Modeling

Use this skill for classification, regression, clustering, ranking, or model evaluation tasks.

## Procedure

1. Install Tier 1 and Tier 2 (`bash .agents/bootstrap_packages.sh 2`).
2. Identify the target, prediction unit, business decision, available features, and success metric.
3. Check for target leakage, duplicated entities across splits, temporal leakage, and post-outcome fields.
4. Build a simple baseline before more complex models, and compare improvements against a business-relevant benchmark.
5. Choose validation strategy based on data structure: random, stratified, grouped, or chronological.
6. Use appropriate metrics and connect them to consequences such as false positives, false negatives, forecast error, missed revenue, cost, or service risk.
7. Include confusion matrices, residual checks, feature importance, calibration, or segment performance when relevant.
8. Report limitations, likely failure modes, data drift risks, fairness or subgroup concerns when visible, and recommendations for production use only if requested.
9. Avoid implying deployment readiness from a notebook-style model; describe it as exploratory unless the user asks for production planning.

## Visualization for ML

### Model evaluation

| Visualization | Purpose |
|---|---|
| Confusion matrix heatmap | Classification errors by class |
| ROC/PR curves | Threshold trade-offs, class imbalance diagnostics |
| Residual plots | Regression fit diagnostics, heteroscedasticity |
| Prediction vs. actual scatter | Regression calibration |
| Calibration curve | Probability calibration for classifiers |
| Learning curves | Diagnose underfitting vs. overfitting |
| Feature importance bar chart | Model interpretation, feature selection |

### Residual diagnostics

```python
import matplotlib.pyplot as plt
import seaborn as sns

# Residuals vs. predicted
plt.scatter(y_pred, residuals, alpha=0.5)
plt.axhline(y=0, color='r', linestyle='--')
plt.xlabel("Predicted values")
plt.ylabel("Residuals")
plt.title("Residuals vs. Predicted")

# Distribution of residuals
sns.histplot(residuals, kde=True)
plt.title("Residual Distribution")
```

### Feature importance

- Use horizontal bar charts sorted by importance.
- For SHAP values, use summary plots (beeswarm) and dependence plots.
- Show top 10-15 features to avoid clutter; full importance can go in a table.

### Classification thresholds

- Plot precision, recall, and F1 against threshold values to help select operating points.
- Show class distribution to contextualize imbalance.
