SELECT
    d.department_name,
    DATE_TRUNC('month', f.pay_month)::date AS payroll_month,
    SUM(f.gross_pay) AS gross_pay_total,
    SUM(f.net_pay) AS net_pay_total
FROM fact_payroll f
JOIN dim_employee e ON e.employee_key = f.employee_key
JOIN dim_department d ON d.department_key = e.department_key
GROUP BY d.department_name, DATE_TRUNC('month', f.pay_month)
ORDER BY payroll_month, d.department_name;