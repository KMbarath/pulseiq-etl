-- Current workforce KPI cards (latest month in the uploaded workbook).
SELECT * FROM v_headcount_snapshot;

-- Month-end headcount trend.
SELECT month_date, headcount FROM v_headcount_monthly ORDER BY month_date;

-- Latest department snapshot and historical department trend.
SELECT department_name, headcount
FROM v_headcount_latest_department ORDER BY headcount DESC;

SELECT month_date, department_name, headcount
FROM v_headcount_department_monthly
ORDER BY month_date, department_name;

-- Current role mix, tenure bands, and monthly movement.
SELECT role_name, employee_count FROM v_role_mix ORDER BY employee_count DESC;
SELECT tenure_band, employee_count FROM v_tenure_bands ORDER BY tenure_band;
SELECT month_date, joiners, leavers
FROM v_joiners_leavers_monthly ORDER BY month_date;
