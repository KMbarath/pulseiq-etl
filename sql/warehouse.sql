
CREATE TABLE IF NOT EXISTS dim_department (
    department_key BIGSERIAL PRIMARY KEY,
    department_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_role (
    role_key BIGSERIAL PRIMARY KEY,
    role_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_leave_type (
    leave_type_key BIGSERIAL PRIMARY KEY,
    leave_type_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    day_number INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    quarter_number INTEGER NOT NULL,
    year_number INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_employee (
    employee_key BIGSERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    joining_date DATE NOT NULL,
    leaving_date DATE,
    department_key BIGINT NOT NULL REFERENCES dim_department(department_key),
    role_key BIGINT NOT NULL REFERENCES dim_role(role_key),
    valid_from DATE NOT NULL,
    valid_to DATE,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (employee_id, valid_from),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_employee_current
    ON dim_employee(employee_id) WHERE is_current;

CREATE INDEX IF NOT EXISTS ix_dim_employee_dates
    ON dim_employee(valid_from, valid_to);

CREATE TABLE IF NOT EXISTS fact_attendance (
    attendance_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    attendance_date DATE NOT NULL REFERENCES dim_date(full_date),
    attendance_status TEXT NOT NULL,
    source_employee_id TEXT NOT NULL,
    UNIQUE (source_employee_id, attendance_date)
);

-- Optional Python-team daily feed. The workbook's monthly attendance facts
-- must not be expanded into synthetic daily observations.
CREATE TABLE IF NOT EXISTS fact_attendance_daily (
    daily_attendance_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    attendance_date DATE NOT NULL REFERENCES dim_date(full_date),
    department_key BIGINT NOT NULL REFERENCES dim_department(department_key),
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'half_day', 'leave', 'holiday', 'weekend')),
    scheduled_minutes INTEGER CHECK (scheduled_minutes IS NULL OR scheduled_minutes >= 0),
    worked_minutes INTEGER CHECK (worked_minutes IS NULL OR worked_minutes >= 0),
    late_minutes INTEGER CHECK (late_minutes IS NULL OR late_minutes >= 0),
    is_holiday BOOLEAN NOT NULL DEFAULT FALSE,
    source_employee_id TEXT NOT NULL,
    UNIQUE (source_employee_id, attendance_date)
);

CREATE INDEX IF NOT EXISTS ix_fact_attendance_daily_date
    ON fact_attendance_daily(attendance_date);
CREATE INDEX IF NOT EXISTS ix_fact_attendance_daily_department_date
    ON fact_attendance_daily(department_key, attendance_date);
CREATE INDEX IF NOT EXISTS ix_fact_attendance_daily_employee_date
    ON fact_attendance_daily(employee_key, attendance_date);

CREATE TABLE IF NOT EXISTS fact_payroll (
    payroll_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    pay_date DATE NOT NULL REFERENCES dim_date(full_date),
    pay_month DATE NOT NULL,
    gross_pay NUMERIC(14,2) NOT NULL CHECK (gross_pay >= 0),
    net_pay NUMERIC(14,2) NOT NULL CHECK (net_pay >= 0),
    source_employee_id TEXT NOT NULL,
    UNIQUE (source_employee_id, pay_month)
);


CREATE TABLE IF NOT EXISTS fact_salary (
    salary_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    effective_date DATE NOT NULL,
    salary NUMERIC(12, 2) NOT NULL CHECK (salary >= 0),
    source_employee_id VARCHAR(50) NOT NULL,
    UNIQUE (source_employee_id, effective_date)
);

CREATE INDEX IF NOT EXISTS idx_fact_salary_employee
    ON fact_salary(employee_key);

CREATE INDEX IF NOT EXISTS idx_fact_salary_effective_date
    ON fact_salary(effective_date);


CREATE TABLE IF NOT EXISTS fact_leave (
    leave_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    start_date DATE NOT NULL REFERENCES dim_date(full_date),
    end_date DATE NOT NULL REFERENCES dim_date(full_date),
    leave_type_key BIGINT NOT NULL REFERENCES dim_leave_type(leave_type_key),
    leave_days INTEGER NOT NULL CHECK (leave_days > 0),
    source_employee_id TEXT NOT NULL,
    UNIQUE (source_employee_id, start_date, end_date),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS fact_headcount_monthly (
    headcount_key BIGSERIAL PRIMARY KEY,
    employee_key BIGINT NOT NULL REFERENCES dim_employee(employee_key),
    month_date DATE NOT NULL REFERENCES dim_date(full_date),
    headcount_value SMALLINT NOT NULL DEFAULT 1 CHECK (headcount_value IN (0, 1)),
    source_employee_id TEXT NOT NULL,
    UNIQUE (source_employee_id, month_date)
);

CREATE INDEX IF NOT EXISTS ix_attendance_date
    ON fact_attendance(attendance_date);

CREATE INDEX IF NOT EXISTS ix_attendance_employee
    ON fact_attendance(employee_key);

CREATE INDEX IF NOT EXISTS ix_payroll_month
    ON fact_payroll(pay_month);

CREATE INDEX IF NOT EXISTS ix_payroll_employee
    ON fact_payroll(employee_key);

CREATE INDEX IF NOT EXISTS ix_leave_dates
    ON fact_leave(start_date, end_date);

CREATE INDEX IF NOT EXISTS ix_leave_employee
    ON fact_leave(employee_key);

CREATE INDEX IF NOT EXISTS ix_headcount_month
    ON fact_headcount_monthly(month_date);

CREATE INDEX IF NOT EXISTS ix_headcount_employee
    ON fact_headcount_monthly(employee_key);
