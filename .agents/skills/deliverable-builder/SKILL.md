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
