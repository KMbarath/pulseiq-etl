SELECT
    month_date,
    SUM(headcount_value) AS headcount
FROM fact_headcount_monthly
GROUP BY month_date
ORDER BY month_date;