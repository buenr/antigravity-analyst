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

## Visualization for forecasting

### Essential time-series plots

| Visualization | Purpose |
|---|---|
| Time series line chart | Overall pattern, trend, volatility |
| Seasonal decomposition | Trend, seasonal, residual components |
| ACF/PACF plots | Autocorrelation structure, ARIMA order hints |
| Rolling statistics | Moving average, rolling std for stability checks |
| Forecast vs. actual | Backtest performance, prediction intervals |
| Faceted series | Multiple entities or subgroups |

### Forecast presentation

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 5))

# Historical data
ax.plot(history.index, history.values, label="Historical", color="black")

# Fitted values (optional, lighter style)
ax.plot(fitted.index, fitted.values, label="Fitted", 
        color="gray", linestyle="--", alpha=0.7)

# Forecast
ax.plot(forecast.index, forecast.values, label="Forecast", 
        color="blue", linewidth=2)

# Prediction intervals
ax.fill_between(forecast.index, lower, upper, 
                alpha=0.2, color="blue", label="95% PI")

# Mark forecast origin
ax.axvline(x=forecast_start, color="red", linestyle=":", 
           label="Forecast origin")

ax.legend()
ax.set_title("Sales Forecast with 95% Prediction Intervals")
ax.set_xlabel("Date")
ax.set_ylabel("Sales")
```

### Best practices

- **Distinguish clearly**: Use different colors, line styles, or shading to separate historical, fitted, and forecast values.
- **Prediction intervals**: Always show uncertainty bands; forecasts without intervals are incomplete.
- **Forecast origin**: Mark the point where forecasts begin with a vertical line.
- **Zoom appropriately**: Provide both full-series context and a zoomed view of the forecast horizon.
- **Multiple series**: Facet by entity or use small multiples rather than overlaying many lines.
- **Seasonality**: Use seasonal subseries plots or month/quarter box plots to reveal seasonal patterns.
- **Anomalies**: Highlight detected anomalies with distinct markers or colors.
