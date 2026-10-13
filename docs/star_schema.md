
# PulseIQ Analytics Warehouse — Star Schema

## Fact table grains

- fact_attendance: one row per employee per attendance date.
- fact_payroll: one row per employee per payroll month.
- fact_leave: one row per source leave record.
- fact_headcount_monthly: one row per active employee per month.

## Dimensions

- dim_employee: SCD Type 2 employee history, using employee_key,
  employee_id, valid_from, valid_to and is_current.
- dim_department: department lookup.
- dim_role: role lookup.
- dim_date: calendar date lookup.
- dim_leave_type: leave category lookup.

## Questions this warehouse answers

- What is payroll cost by department and month?
- How does headcount trend by month?
- What is attendance by month and status?
- What is monthly attrition (employees leaving during the month)?
- What invoices are outstanding by month and department?

Attrition can be derived from `dim_employee.leaving_date`. Invoice reporting
is currently out of scope because no invoice source file is included in Task 1;
add an invoice source and `fact_invoice` before publishing that metric.

## Relationships

- fact_attendance.employee_key -> dim_employee.employee_key
- fact_attendance.attendance_date -> dim_date.full_date
- fact_payroll.employee_key -> dim_employee.employee_key
- fact_payroll.pay_date -> dim_date.full_date
- fact_leave.employee_key -> dim_employee.employee_key
- fact_leave.start_date/end_date -> dim_date.full_date
- fact_leave.leave_type_key -> dim_leave_type.leave_type_key
- fact_headcount_monthly.employee_key -> dim_employee.employee_key
- fact_headcount_monthly.month_date -> dim_date.full_date
- dim_employee.department_key -> dim_department.department_key
- dim_employee.role_key -> dim_role.role_key

## Historical department and role changes

When an employee changes department or role, close the previous
dimension version by setting valid_to to the day before the new version
starts. Insert the new version with a new valid_from date.

Facts link to the employee version valid on the business event date,
preserving historical department attribution.

The sample history demonstrates this: SYN001 is in Sales through 2026-05-31 and
Support from 2026-06-01. May payroll joins to the Sales version; July payroll
joins to the Support version.

## Source limitations

The current clean CSVs do not include department, role or leave type.
Department and role come from data/reference/employee_org_history.csv.
Leave type is loaded as "Unspecified" until the source provides a category.

Invoice reporting requires an invoice source and is outside the current
five-file input dataset.
