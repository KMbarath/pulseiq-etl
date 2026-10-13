
import os
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = Path(os.getenv("CLEAN_DIR", ROOT / "data" / "clean"))
REFERENCE_FILE = ROOT / "data" / "reference" / "employee_org_history.csv"
SCHEMA_FILE = ROOT / "sql" / "warehouse.sql"
DATABASE_URL = os.environ["DATABASE_URL"]
AS_OF_DATE = date.fromisoformat(
    os.getenv("ETL_AS_OF_DATE", date.today().isoformat())
)


def read_csv(name, required):
    path = CLEAN_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing clean input: {path}")

    df = pd.read_csv(path, dtype={"employee_id": "string"})
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")

    df["employee_id"] = df["employee_id"].str.strip()
    if df["employee_id"].isna().any() or (df["employee_id"] == "").any():
        raise ValueError(f"{name} contains blank employee_id values")
    return df


def parse_date(value, field):
    if pd.isna(value) or str(value).strip() == "":
        return None
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date in {field}: {value!r}") from None


def month_start(value):
    return date(value.year, value.month, 1)


def ensure_date(cur, value):
    if value is None:
        return
    cur.execute(
        """
        INSERT INTO dim_date
            (date_key, full_date, day_number, month_number,
             month_name, quarter_number, year_number)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (full_date) DO NOTHING
        """,
        (
            int(value.strftime("%Y%m%d")), value, value.day, value.month,
            value.strftime("%B"), (value.month - 1) // 3 + 1, value.year,
        ),
    )


def main():
    employees = read_csv(
        "employees.csv", ["employee_id", "name", "joining_date", "leaving_date"]
    )
    attendance = read_csv(
        "attendance.csv", ["employee_id", "date", "status"]
    )
    payroll = read_csv(
        "payroll.csv", ["employee_id", "pay_date", "gross_pay", "net_pay"]
    )

    salaries = read_csv(
        "salaries.csv", ["employee_id", "salary", "effective_date"]
    )

    leave = read_csv(
        "leave.csv", ["employee_id", "start_date", "end_date"]
    )

    if not REFERENCE_FILE.exists():
        raise FileNotFoundError(
            f"Create the department/role mapping file first: {REFERENCE_FILE}"
        )

    org = pd.read_csv(REFERENCE_FILE, dtype={"employee_id": "string"})
    org_required = {
        "employee_id", "department", "role", "valid_from", "valid_to"
    }
    if not org_required.issubset(org.columns):
        raise ValueError(
            f"employee_org_history.csv needs columns: {sorted(org_required)}"
        )

    for df in (employees, attendance, payroll, leave, org):
        if df["employee_id"].duplicated().all() and df is employees:
            raise ValueError("employees.csv has duplicate employee IDs")

    employee_rows = {}
    for row in employees.to_dict("records"):
        eid = str(row["employee_id"])
        if eid in employee_rows:
            raise ValueError(f"Duplicate employee in employees.csv: {eid}")
        joined = parse_date(row["joining_date"], "joining_date")
        left = parse_date(row["leaving_date"], "leaving_date")
        if joined is None or (left and left < joined):
            raise ValueError(f"Invalid employment dates for {eid}")
        employee_rows[eid] = {
            "name": str(row["name"]),
            "joining": joined,
            "leaving": left,
        }

    org_rows = []
    for row in org.to_dict("records"):
        eid = str(row["employee_id"])
        start = parse_date(row["valid_from"], "valid_from")
        end = parse_date(row["valid_to"], "valid_to")
        if eid not in employee_rows:
            raise ValueError(f"Org mapping references unknown employee {eid}")
        if start is None or (end and end < start):
            raise ValueError(f"Invalid mapping dates for {eid}")
        if not str(row["department"]).strip() or not str(row["role"]).strip():
            raise ValueError(f"Blank department/role for {eid}")
        org_rows.append({
            "employee_id": eid,
            "department": str(row["department"]).strip(),
            "role": str(row["role"]).strip(),
            "start": start,
            "end": end,
        })

    org_rows.sort(key=lambda r: (r["employee_id"], r["start"]))
    for previous, current in zip(org_rows, org_rows[1:]):
        if previous["employee_id"] == current["employee_id"]:
            if previous["end"] is None or previous["end"] >= current["start"]:
                raise ValueError(
                    f"Overlapping org history for {current['employee_id']}"
                )

    skipped_out_of_employment = 0
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

            cur.execute(
                """
                INSERT INTO dim_leave_type(leave_type_name)
                VALUES ('Unspecified')
                ON CONFLICT (leave_type_name) DO NOTHING
                """
            )

            # Upsert department and role dimensions.
            for item in org_rows:
                cur.execute(
                    """
                    INSERT INTO dim_department(department_name)
                    VALUES (%s) ON CONFLICT (department_name) DO NOTHING
                    """,
                    (item["department"],),
                )
                cur.execute(
                    """
                    INSERT INTO dim_role(role_name)
                    VALUES (%s) ON CONFLICT (role_name) DO NOTHING
                    """,
                    (item["role"],),
                )

            # SCD Type 2 versions: identity is employee_id + valid_from.
            for item in org_rows:
                employee = employee_rows[item["employee_id"]]
                                # Retire any earlier current version before inserting a newer one.
                # This preserves the partial unique index on current employees.
                cur.execute(
                    """
                    UPDATE dim_employee
                    SET is_current = FALSE
                    WHERE employee_id = %s
                      AND valid_from < %s
                      AND is_current = TRUE
                    """,
                    (item["employee_id"], item["start"]),
                )
                cur.execute(
                    "SELECT department_key FROM dim_department WHERE department_name=%s",
                    (item["department"],),
                )
                department_key = cur.fetchone()["department_key"]
                cur.execute(
                    "SELECT role_key FROM dim_role WHERE role_name=%s",
                    (item["role"],),
                )
                role_key = cur.fetchone()["role_key"]

                cur.execute(
                    """
                    INSERT INTO dim_employee
                      (employee_id, employee_name, joining_date, leaving_date,
                       department_key, role_key, valid_from, valid_to, is_current)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (employee_id, valid_from) DO UPDATE SET
                      employee_name=EXCLUDED.employee_name,
                      joining_date=EXCLUDED.joining_date,
                      leaving_date=EXCLUDED.leaving_date,
                      department_key=EXCLUDED.department_key,
                      role_key=EXCLUDED.role_key,
                      valid_to=EXCLUDED.valid_to,
                      is_current=EXCLUDED.is_current
                    """,
                    (
                        item["employee_id"], employee["name"], employee["joining"],
                        employee["leaving"], department_key, role_key,
                        item["start"], item["end"], item["end"] is None,
                    ),
                )

            # Ensure no employee has multiple current versions.
            for eid in employee_rows:
                cur.execute(
                    """
                    SELECT employee_key FROM dim_employee
                    WHERE employee_id=%s AND is_current
                    """,
                    (eid,),
                )
                current = cur.fetchall()
                if len(current) > 1:
                    raise ValueError(f"Multiple current dimension rows for {eid}")

            def employee_key(eid, event_date):
                cur.execute(
                    """
                    SELECT employee_key FROM dim_employee
                    WHERE employee_id=%s
                      AND valid_from <= %s
                      AND (valid_to IS NULL OR valid_to >= %s)
                    ORDER BY valid_from DESC LIMIT 1
                    """,
                    (eid, event_date, event_date),
                )
                found = cur.fetchone()
                if not found:
                    raise ValueError(
                        f"No employee history version for {eid} on {event_date}"
                    )
                return found["employee_key"]

            # Load attendance.
            for row in attendance.to_dict("records"):
                eid = str(row["employee_id"])
                day = parse_date(row["date"], "attendance.date")
                if eid not in employee_rows or day is None:
                    skipped_out_of_employment += 1
                    continue
                ensure_date(cur, day)
                try:
                    fact_employee_key = employee_key(eid, day)
                except ValueError:
                    # The supplied workbook includes known attendance-after-exit
                    # issues. Do not invent an employee dimension version.
                    skipped_out_of_employment += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO fact_attendance
                      (employee_key, attendance_date, attendance_status,
                       source_employee_id)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (source_employee_id, attendance_date)
                    DO UPDATE SET employee_key=EXCLUDED.employee_key,
                                  attendance_status=EXCLUDED.attendance_status
                    """,
                    (fact_employee_key, day, str(row["status"]), eid),
                )

            # Load payroll. Grain is employee + pay month.
            for row in payroll.to_dict("records"):
                eid = str(row["employee_id"])
                pay_day = parse_date(row["pay_date"], "payroll.pay_date")
                if eid not in employee_rows or pay_day is None:
                    skipped_out_of_employment += 1
                    continue
                gross, net = float(row["gross_pay"]), float(row["net_pay"])
                if gross < 0 or net < 0:
                    raise ValueError(f"Negative payroll amount for {eid}")
                pay_month = month_start(pay_day)
                ensure_date(cur, pay_day)
                ensure_date(cur, pay_month)
                try:
                    fact_employee_key = employee_key(eid, pay_day)
                except ValueError:
                    skipped_out_of_employment += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO fact_payroll
                      (employee_key, pay_date, pay_month, gross_pay, net_pay,
                       source_employee_id)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (source_employee_id, pay_month)
                    DO UPDATE SET employee_key=EXCLUDED.employee_key,
                                  pay_date=EXCLUDED.pay_date,
                                  gross_pay=EXCLUDED.gross_pay,
                                  net_pay=EXCLUDED.net_pay
                    """,
                    (
                        fact_employee_key, pay_day, pay_month,
                        gross, net, eid,
                    ),
                )


            # Load salary history. Grain: employee + effective date.
            for row in salaries.to_dict("records"):
                eid = str(row["employee_id"])
                effective_date = parse_date(
                    row["effective_date"], "salaries.effective_date"
                )

                if eid not in employee_rows or effective_date is None:
                    skipped_out_of_employment += 1
                    continue

                salary = float(row["salary"])
                if salary < 0:
                    raise ValueError(f"Negative salary for {eid}")

                ensure_date(cur, effective_date)
                try:
                    key = employee_key(eid, effective_date)
                except ValueError:
                    skipped_out_of_employment += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO fact_salary
                        (employee_key, effective_date, salary, source_employee_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (source_employee_id, effective_date)
                    DO UPDATE SET
                        employee_key = EXCLUDED.employee_key,
                        salary = EXCLUDED.salary
                    """,
                    (key, effective_date, salary, eid),
                )


            # Load leave. Leave type defaults to Unspecified because the source
            # CSV does not provide a leave category.
            cur.execute(
                "SELECT leave_type_key FROM dim_leave_type WHERE leave_type_name='Unspecified'"
            )
            leave_type_key = cur.fetchone()["leave_type_key"]

            for row in leave.to_dict("records"):
                eid = str(row["employee_id"])
                start = parse_date(row["start_date"], "leave.start_date")
                end = parse_date(row["end_date"], "leave.end_date")
                if eid not in employee_rows or start is None or end is None or end < start:
                    skipped_out_of_employment += 1
                    continue
                ensure_date(cur, start)
                ensure_date(cur, end)
                try:
                    fact_employee_key = employee_key(eid, start)
                except ValueError:
                    skipped_out_of_employment += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO fact_leave
                      (employee_key, start_date, end_date, leave_type_key,
                       leave_days, source_employee_id)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (source_employee_id, start_date, end_date)
                    DO UPDATE SET employee_key=EXCLUDED.employee_key,
                                  leave_type_key=EXCLUDED.leave_type_key,
                                  leave_days=EXCLUDED.leave_days
                    """,
                    (
                        fact_employee_key, start, end, leave_type_key,
                        (end - start).days + 1, eid,
                    ),
                )

            # Headcount snapshot per employee/month, from joining through
            # the latest month represented in the clean input data.

            # Rebuild monthly snapshots so changed source data cannot leave
            # stale headcount rows behind.
            dates = []
            for df, column in (
                (attendance, "date"),
                (payroll, "pay_date"),
                (leave, "start_date"),
            ):
                dates.extend(
                    parse_date(v, column) for v in df[column].tolist()
                    if not pd.isna(v)
                )

            latest = max(dates + [AS_OF_DATE])
            cursor_month = min(
                e["joining"] for e in employee_rows.values()
            )
            cursor_month = month_start(cursor_month)
            last_month = month_start(latest)

            cur.execute("DELETE FROM fact_headcount_monthly")

            while cursor_month <= last_month:
                next_month = (
                    date(cursor_month.year + 1, 1, 1)
                    if cursor_month.month == 12
                    else date(cursor_month.year, cursor_month.month + 1, 1)
                )
                month_end = next_month - timedelta(days=1)

                # For the current, incomplete month, count employees as of
                # ETL_AS_OF_DATE rather than assuming the month has ended.
                snapshot_date = min(month_end, AS_OF_DATE)

                ensure_date(cur, cursor_month)

                for eid, employee in employee_rows.items():
                    active = (
                        employee["joining"] <= snapshot_date
                        and (
                            employee["leaving"] is None
                            or employee["leaving"] >= snapshot_date
                        )
                    )

                    if active:
                        try:
                            key = employee_key(eid, snapshot_date)
                        except ValueError:
                            skipped_out_of_employment += 1
                            continue
                        cur.execute(
                            """
                            INSERT INTO fact_headcount_monthly
                              (employee_key, month_date, headcount_value,
                               source_employee_id)
                            VALUES (%s, %s, 1, %s)
                            ON CONFLICT (source_employee_id, month_date)
                            DO UPDATE SET
                              employee_key = EXCLUDED.employee_key,
                              headcount_value = EXCLUDED.headcount_value
                            """,
                            (key, cursor_month, eid),
                        )

                cursor_month = next_month


        conn.commit()

    print(
        "Warehouse load completed successfully. "
        f"Skipped out-of-employment fact rows: {skipped_out_of_employment}."
    )


if __name__ == "__main__":
    main()
