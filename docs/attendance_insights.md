# Attendance and leave insights

These figures are computed from the uploaded workbook's `fact_attendance_monthly`,
`fact_leave`, `dim_department`, and `fact_anomaly` sheets (loaded into the
`source_*` tables). Attendance rate uses the workbook definition:
`(present_days + 0.5 × half_days_unpaid) / scheduled_days`.

## Findings

1. The lowest monthly weighted attendance rate in the workbook period was
   **92.89% in May 2026**. It recovered to **95.19% in September 2026**. The
   monthly pattern is not monotonic, so HR should review operational context
   (holidays, schedules, and staffing) before interpreting a dip as engagement.
2. In September 2026, **Finance & Accounts was 88.87%** across 355 scheduled
   employee-days, while **Sales was 97.54%** across 957. Executive Office was
   100% on only 21 records, so that apparent high is a small-group result and
   should not be ranked as a reliable department signal. Investigate patterns
   with managers and schedules, not named employees.
3. The late-arrival rate (late arrivals divided by present days) peaked at
   **7.53% in March 2026** and was **7.14% in September 2026**. It is a follow-up
   signal, not a performance conclusion.
4. Approved leave volume is led by Earned (Privilege) Leave (2,336 days),
   Casual Leave (1,995), and Sick Leave (1,769) over the workbook period.

## What is not known

- The uploaded attendance fact is employee-month grain. It has no individual
  attendance dates, so weekday, weekend, holiday, and exact daily anomaly
  overlays cannot be calculated from it. A daily attendance export is needed;
  month-end dates must not be treated as daily observations.
- The anomaly sample is monthly employee-level model output, not a record of
  verified attendance incidents. Its flags are displayed as monthly counts
  only and must not drive employment decisions.
- This is synthetic/sample data. May's low and September's recovery are
  descriptive of this workbook, not proof of a recurring business pattern.
- The workbook ends on 2026-09-30. Future approved leave is planned leave; it
  should not be confused with historical attendance.

## HR follow-up

Check Finance & Accounts' September schedule and leave mix, validate the
March late-arrival peak against source policy/calendar data, and compare with
several real periods before changing staffing or attendance policy. Request a
daily attendance feed for weekday and holiday analysis.

## Daily-grain follow-through

The workbook does not contain daily attendance rows. The project now includes
an optional validated loader and daily weekday summary query, but these remain
unpopulated until the Python team supplies its real daily feed. See
`docs/daily_attendance_contract.md` for the exact CSV fields and load command.
This avoids making up a daily distribution from monthly totals.
