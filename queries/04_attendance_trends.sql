-- Uses the uploaded workbook's monthly attendance facts, not a daily proxy.
SELECT month_date, attendance_records, present_records, attendance_rate,
       rolling_3_month_rate, late_arrivals, late_arrival_rate
FROM v_attendance_monthly
ORDER BY month_date;

-- Department-level monthly comparison.
SELECT month_date, department_name, attendance_records, present_records,
       attendance_rate, late_arrivals, late_arrival_rate
FROM v_attendance_department_monthly
ORDER BY month_date, department_name;

-- Leave by month and type; the view includes approved requests only.
SELECT month_date, leave_type, leave_days, leave_requests
FROM v_leave_monthly
ORDER BY month_date, leave_type;

-- Workbook anomaly output is monthly. These flagged counts do not identify
-- exact daily attendance events and are review signals, not decisions.
SELECT month_date, scored_records, flagged_records, avg_anomaly_score
FROM v_attendance_anomaly_monthly
ORDER BY month_date;

-- Weekday analysis is intentionally not fabricated: the uploaded attendance
-- fact is employee-month grain and has no daily attendance dates. A daily
-- Python-team attendance export is required for weekday/holiday analysis.
