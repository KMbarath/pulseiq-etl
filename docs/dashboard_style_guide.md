# PulseIQ dashboard style guide

## Visual system

- Palette: navy `#12355B`, blue `#2F6690`, teal `#3A7D7C`, orange `#D17A22`, and purple `#6C5B7B`. Use text labels as well as color; never encode good/bad status by color alone.
- Font: Arial or Superset's default sans-serif. Use sentence-case titles and readable labels.
- Number formats: counts `#,##0`; INR currency `₹#,##0`; rates `0.0%`; date labels `MMM YYYY`.
- Every chart has a metric-led title and a one-line takeaway in its description. Keep caveats visible for proxy metrics and small groups.
- Default layout: four headline KPI cards first, then trend charts, then department/role/leave detail. Superset's native filter bar stays visible above the dashboard; on narrow screens, cards and charts stack vertically.
- Use a small number of consistent series colors and avoid red/green-only semantics.

## AI-assisted design and review

The AI-assisted layout proposal was a header, four headline metrics, a trend row,
department/role detail, and persistent date/department filters. Review against
the uploaded data led to these changes before implementation:

1. Keep the four KPI cards first so the latest snapshot is immediately visible.
2. Use the workbook's month-end and scheduled-day measures rather than the
   derived ETL daily-grain sample tables.
3. Keep date filters limited to monthly charts and department filters limited
   to views that actually carry department labels.
4. Label attendance with the workbook formula and disclose that weekday
   analysis is unavailable at monthly grain.
5. Display anomaly output by month and explain it is a model review signal, not
   a daily incident or decision.

The Superset native filter controls render in its persistent top filter bar,
not a right-hand sidebar. On laptop and mobile widths this avoids squeezing
the chart canvas; mobile layout stacks controls and charts.
