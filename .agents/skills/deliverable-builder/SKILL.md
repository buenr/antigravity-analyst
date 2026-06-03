---
name: deliverable-builder
description: Create final user-facing analytical artifacts and save only final deliverables in ./outputs/.
---

# Deliverable Builder

Use this skill when the user asks for a downloadable report, chart, table, export, slide deck, or summary file.

## Procedure

1. Install Tier 1; add Tier 4 when building PDF, PowerPoint, Word, or templated HTML deliverables (`bash .agents/bootstrap_packages.sh 4`).
2. Create `./outputs/` before writing final deliverables.
3. Save only final user-facing files in `./outputs/`.
4. Keep temporary files, intermediate chart components, cleaned working files, and scratch notebooks outside `./outputs/`.
5. Use clear, stable basenames such as `analysis_report.pdf`, `summary_table.csv`, or `forecast_chart.png`.
6. Validate that each final file exists and is readable.
7. In the final response, mention each deliverable by basename only and do not invent download links.

## Visualization export checklist

Before exporting a chart as a deliverable, verify:

### Content quality
- [ ] Descriptive title that states the main insight
- [ ] Axis labels with units (e.g., "Revenue ($M)", "Time (months)")
- [ ] Legend present and positioned to avoid overlap
- [ ] Data source noted in caption or footer
- [ ] Key takeaways annotated directly on the chart

### Visual quality
- [ ] Font sizes readable at export size (≥10pt labels, ≥12pt title)
- [ ] Colorblind-friendly palette used
- [ ] Sufficient contrast for print (test grayscale if printing)
- [ ] No overlapping labels or legend items
- [ ] Appropriate aspect ratio for content

### Technical quality
- [ ] Resolution sufficient for medium (300 DPI for print, 150 DPI for screens)
- [ ] Vector format (PDF/SVG) for reports and slides when possible
- [ ] PNG with transparent background if overlaying on colored slides
- [ ] Reasonable file size for email/attachment limits

### Export commands

```python
# High-quality static export with Plotly
fig.write_image("./outputs/chart.png", scale=2)  # 2x for retina
fig.write_image("./outputs/chart.pdf")  # vector format

# Matplotlib/Seaborn
plt.savefig("./outputs/chart.png", dpi=300, bbox_inches="tight")
plt.savefig("./outputs/chart.pdf", bbox_inches="tight")  # vector

# Interactive HTML (optional supplement)
fig.write_html("./outputs/chart.html", include_plotlyjs="cdn")
```

### Multi-chart deliverables

For reports with multiple charts:
- Use consistent color palettes and styling across all figures.
- Number figures (Figure 1, Figure 2) and reference them in text.
- Include a summary dashboard or key insights overview at the beginning.
- Consider small multiples or faceted layouts instead of many separate charts.

### Tables

For tabular deliverables:
- Round numbers appropriately (2-3 significant figures for reports).
- Use conditional formatting (heatmaps, bar sparklines) for large tables.
- Include totals, averages, or summary rows where helpful.
- Export as CSV for data, styled HTML or PDF for presentation tables.
