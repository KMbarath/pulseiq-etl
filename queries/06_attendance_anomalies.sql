SELECT
    period_key AS month_key,
    employee_id,
    reason_code,
    reason_text,
    anomaly_score,
    flagged
FROM source_fact_anomaly
WHERE source_dataset = 'attendance_monthly_features'
ORDER BY month_key, anomaly_score DESC;
