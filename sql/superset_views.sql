-- Read-only presentation views used by the Superset dashboards.
CREATE OR REPLACE VIEW v_headcount_monthly AS
SELECT month_start_date::timestamp::date AS month_date,
       SUM(headcount_end::numeric)::integer AS headcount,
       SUM(hires::numeric)::integer AS joiners,
       SUM(exits::numeric)::integer AS leavers
FROM source_fact_headcount_monthly
GROUP BY month_start_date::timestamp::date;

CREATE OR REPLACE VIEW v_headcount_department_monthly AS
SELECT h.month_start_date::timestamp::date AS month_date,
       COALESCE(d.department_name, h.department_id, 'Unknown') AS department_name,
       SUM(h.headcount_end::numeric)::integer AS headcount
FROM source_fact_headcount_monthly h
LEFT JOIN source_dim_department d ON d.department_id = h.department_id
GROUP BY h.month_start_date::timestamp::date,
         COALESCE(d.department_name, h.department_id, 'Unknown');

CREATE OR REPLACE VIEW v_headcount_latest_department AS
SELECT department_name, headcount
FROM v_headcount_department_monthly
WHERE month_date = (SELECT MAX(month_date) FROM v_headcount_department_monthly);

CREATE OR REPLACE VIEW v_headcount_snapshot AS
WITH latest_month AS (
  SELECT MAX(month_start_date::timestamp::date) AS month_date
  FROM source_fact_headcount_monthly
), headcount AS (
  SELECT SUM(f.headcount_end::numeric)::integer AS current_headcount,
         COUNT(*) FILTER (WHERE f.headcount_end::numeric > 0)::integer AS active_departments,
         SUM(f.hires::numeric)::integer AS joiners,
         SUM(f.exits::numeric)::integer AS leavers
  FROM source_fact_headcount_monthly f
  JOIN latest_month m ON f.month_start_date::timestamp::date = m.month_date
), tenure AS (
  SELECT AVG(EXTRACT(YEAR FROM AGE(DATE '2026-09-30', hire_date::timestamp))) AS average_tenure_years
  FROM source_dim_employee
  WHERE UPPER(is_current) IN ('Y', 'YES', 'TRUE', '1')
    AND LOWER(employment_status) = 'active'
)
SELECT h.current_headcount, h.active_departments,
       ROUND(t.average_tenure_years::numeric, 1) AS average_tenure_years,
       h.joiners AS joiners_latest_month, h.leavers AS leavers_latest_month,
       (SELECT month_date FROM latest_month) AS latest_month
FROM headcount h CROSS JOIN tenure t;

CREATE OR REPLACE VIEW v_role_mix AS
SELECT COALESCE(e.role_title, 'Unknown') AS role_name,
       COUNT(DISTINCT e.employee_id)::integer AS employee_count
FROM source_dim_employee e
WHERE UPPER(e.is_current) IN ('Y', 'YES', 'TRUE', '1')
  AND LOWER(e.employment_status) = 'active'
GROUP BY COALESCE(e.role_title, 'Unknown');

CREATE OR REPLACE VIEW v_joiners_leavers_monthly AS
SELECT month_start_date::timestamp::date AS month_date,
       SUM(hires::numeric)::integer AS joiners,
       SUM(exits::numeric)::integer AS leavers
FROM source_fact_headcount_monthly
GROUP BY month_start_date::timestamp::date;

CREATE OR REPLACE VIEW v_attendance_monthly AS
WITH monthly AS (
  SELECT DATE_TRUNC('month', period_end_date::timestamp)::date AS month_date,
         SUM(scheduled_days::numeric) AS scheduled_days,
         SUM(present_days::numeric) AS present_days,
         SUM(half_days_unpaid::numeric) AS half_days_unpaid,
         SUM(late_arrivals::numeric) AS late_arrivals
  FROM source_fact_attendance_monthly
  GROUP BY 1
)
SELECT month_date, scheduled_days::integer AS scheduled_days,
       present_days::integer AS present_days,
       (present_days + 0.5 * half_days_unpaid) / NULLIF(scheduled_days, 0) AS attendance_rate,
       late_arrivals::integer AS late_arrivals,
       late_arrivals / NULLIF(present_days, 0) AS late_arrival_rate,
       AVG((present_days + 0.5 * half_days_unpaid) / NULLIF(scheduled_days, 0))
         OVER (ORDER BY month_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3_month_rate
FROM monthly;

CREATE OR REPLACE VIEW v_attendance_department_monthly AS
SELECT DATE_TRUNC('month', f.period_end_date::timestamp)::date AS month_date,
       COALESCE(d.department_name, f.department_id, 'Unknown') AS department_name,
       SUM(f.scheduled_days::numeric)::integer AS scheduled_days,
       SUM(f.present_days::numeric)::integer AS present_days,
       (SUM(f.present_days::numeric) + 0.5 * SUM(f.half_days_unpaid::numeric))
         / NULLIF(SUM(f.scheduled_days::numeric), 0) AS attendance_rate,
       SUM(f.late_arrivals::numeric)::integer AS late_arrivals,
       SUM(f.late_arrivals::numeric) / NULLIF(SUM(f.present_days::numeric), 0) AS late_arrival_rate
FROM source_fact_attendance_monthly f
LEFT JOIN source_dim_department d ON d.department_id = f.department_id
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_leave_monthly AS
SELECT DATE_TRUNC('month', f.start_date::timestamp)::date AS month_date,
       COALESCE(t.leave_type_name, f.leave_type_code, 'Unknown') AS leave_type,
       SUM(f.days::numeric)::integer AS leave_days,
       COUNT(*)::integer AS leave_requests
FROM source_fact_leave f
LEFT JOIN source_dim_leave_type t ON t.leave_type_code = f.leave_type_code
WHERE LOWER(f.status) = 'approved'
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_attendance_anomaly_monthly AS
SELECT TO_DATE(SUBSTRING(period_key, 1, 6) || '01', 'YYYYMMDD') AS month_date,
       COUNT(*)::integer AS scored_records,
       COUNT(*) FILTER (WHERE LOWER(flagged) IN ('true', 'yes', 'y', '1'))::integer AS flagged_records,
       AVG(NULLIF(anomaly_score, '')::numeric) AS avg_anomaly_score
FROM source_fact_anomaly
WHERE source_dataset = 'attendance_monthly_features'
  AND period_key ~ '^[0-9]{6,8}$'
GROUP BY 1;

CREATE OR REPLACE VIEW v_tenure_bands AS
WITH active AS (
  SELECT DISTINCT employee_id,
         GREATEST(0, EXTRACT(YEAR FROM AGE(DATE '2026-09-30', hire_date::timestamp)))::numeric AS tenure_years
  FROM source_dim_employee
  WHERE UPPER(is_current) IN ('Y', 'YES', 'TRUE', '1')
    AND LOWER(employment_status) = 'active'
), banded AS (
  SELECT CASE WHEN tenure_years < 1 THEN 'Under 1 year'
              WHEN tenure_years < 3 THEN '1-2 years'
              WHEN tenure_years < 5 THEN '3-4 years'
              ELSE '5+ years' END AS tenure_band,
         employee_id
  FROM active
)
SELECT tenure_band, COUNT(DISTINCT employee_id)::integer AS employee_count
FROM banded GROUP BY tenure_band;
