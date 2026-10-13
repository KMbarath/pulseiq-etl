-- Requires the optional real daily feed loaded into fact_attendance_daily.
-- Attendance rate denominator includes scheduled workdays only; exclude
-- holidays/weekends and exclude approved leave from absence classification.
SELECT
    TO_CHAR(attendance_date, 'FMDay') AS weekday,
    EXTRACT(ISODOW FROM attendance_date)::integer AS weekday_number,
    d.department_name,
    COUNT(*) FILTER (WHERE status IN ('present', 'half_day', 'absent')) AS scheduled_records,
    COUNT(*) FILTER (WHERE status IN ('present', 'half_day')) AS attended_records,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status IN ('present', 'half_day'))
        / NULLIF(COUNT(*) FILTER (WHERE status IN ('present', 'half_day', 'absent')), 0),
        2
    ) AS attendance_rate_pct,
    ROUND(AVG(late_minutes) FILTER (WHERE late_minutes > 0), 2) AS avg_late_minutes
FROM fact_attendance_daily a
JOIN dim_department d USING (department_key)
WHERE NOT is_holiday AND status <> 'weekend'
GROUP BY weekday, weekday_number, d.department_name
ORDER BY weekday_number, d.department_name;
