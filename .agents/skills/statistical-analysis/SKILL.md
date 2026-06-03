---
name: statistical-analysis
description: Perform exploratory and statistical analysis with clear assumptions, uncertainty, and practical interpretation.
---

# Statistical Analysis

Use this skill for EDA, comparisons, hypothesis checks, segmentation, correlation analysis, and explanatory analytics.

## Procedure

1. Install Tier 1 (`bash .agents/bootstrap_packages.sh 1`); add Tier 2 when deeper profiling is needed.
2. Confirm analytical question, population, grain, and relevant filters.
3. Compute descriptive statistics and visualize important distributions or relationships.
4. Use statistical tests or intervals only when assumptions are reasonable; state those assumptions.
5. Avoid causal claims unless the data and design support them.
6. Quantify uncertainty, effect sizes, and practical significance when possible.
7. Summarize findings with caveats, limitations, and next analytical steps.

## Visualization for statistical analysis

Choose charts that match the analytical goal:

| Goal | Recommended visualizations |
|---|---|
| Compare groups | Box plots, violin plots, bar charts with confidence intervals |
| Show relationships | Scatter plots with regression lines, pair plots for multivariate |
| Display distributions | Histograms, density plots, ECDF plots |
| Correlation matrix | Annotated heatmap with diverging color scale |
| Time patterns | Line charts with trend indicators, seasonal decomposition plots |
| Segment comparison | Faceted small multiples, grouped bar charts |

### Best practices

- **Confidence intervals**: Always show uncertainty in bar charts and line plots (error bars, ribbons).
- **Effect size visualization**: Use forest plots or Cohen's d annotations for group comparisons.
- **Multivariate relationships**: Use `seaborn.pairplot()` or `seaborn.PairGrid()` for pairwise scatter matrices.
- **Faceting**: Small multiples (facet wrap/grid) compare patterns across subgroups without overloading a single chart.
- **Annotation**: Mark statistical significance with clear symbols or labels; explain test results in captions.
