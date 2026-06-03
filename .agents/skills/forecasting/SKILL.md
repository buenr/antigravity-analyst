---
name: forecasting
description: Analyze and forecast time-series data with chronological validation, backtesting, trend, seasonality, and uncertainty caveats.
---

# Forecasting

Use this skill for time-series diagnostics, forecasting, trend analysis, seasonality, anomaly detection, and forecast evaluation.

## Procedure

1. Install Tier 1 and Tier 3 (`bash .agents/bootstrap_packages.sh 3`); use `statsmodels` baselines from Tier 1 first.
2. Identify the timestamp column, target measure, entity grain, frequency, and forecast horizon.
3. Sort chronologically, inspect missing periods, duplicated timestamps, and calendar effects.
4. Never use random splits for forecasting. Use chronological holdouts or rolling-origin backtests.
5. Establish naive baselines such as last value, moving average, or seasonal naive before advanced models.
6. Report forecast accuracy with scale-appropriate metrics and include uncertainty where feasible.
7. Clearly separate historical observations, fitted values, and future forecasts.
