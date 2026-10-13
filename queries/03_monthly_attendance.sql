SELECT
    DATE_TRUNC('month', attendance_date)::date AS attendance_month,
    attendance_status,
    COUNT(*) AS attendance_records
FROM fact_attendance
GROUP BY DATE_TRUNC('month', attendance_date), attendance_status
ORDER BY attendance_month, attendance_status;