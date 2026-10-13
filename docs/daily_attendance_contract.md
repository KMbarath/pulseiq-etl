# Daily attendance source contract

The uploaded workbook's `fact_attendance_monthly` sheet has one employee-month
record per row. It cannot support weekday, holiday, or daily incident analysis.
Do not expand its monthly totals into fabricated dates.

To enable those Task 4 analyses, first initialize/refresh the warehouse (this
also creates `fact_attendance_daily`), then place the Python team's verified
daily export at `data/raw/attendance_daily.csv` and run:

```powershell
docker compose run --rm warehouse-load
docker compose run --rm warehouse-load python -m src.daily_attendance_loader
```

Required CSV columns:

| Column | Rule |
| --- | --- |
| `employee_id` | Non-empty; must map to an employee SCD history row on the attendance date |
| `attendance_date` | Parseable date at actual daily grain |
| `status` | `present`, `absent`, `half_day`, `leave`, `holiday`, or `weekend` |

Optional: `scheduled_minutes`, `worked_minutes`, `late_minutes` (non-negative
numbers) and `is_holiday` (true/false, yes/no, y/n, or 1/0). One row per
employee/date is required. Re-running upserts the same employee/date key.

Weekday summary SQL is in `queries/07_attendance_by_weekday.sql`. It calculates
attendance only across present/half-day/absent records, excluding holidays and
weekends. It should be reviewed against the source team's schedule and leave
coding conventions before operational use. Until the real feed is supplied,
the existing dashboard remains monthly and no weekday chart should imply daily
observations.
