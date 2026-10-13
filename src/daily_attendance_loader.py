"""Validate and idempotently load an optional real daily attendance export.

Required columns: employee_id, attendance_date, status.
Optional columns: scheduled_minutes, worked_minutes, late_minutes, is_holiday.
This loader intentionally does not derive daily rows from monthly aggregates.
"""
import os
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = Path(os.getenv("DAILY_ATTENDANCE_CSV", ROOT / "data" / "raw" / "attendance_daily.csv"))
DATABASE_URL = os.getenv("DATABASE_URL")
REQUIRED = {"employee_id", "attendance_date", "status"}
OPTIONAL = {"scheduled_minutes", "worked_minutes", "late_minutes", "is_holiday"}
STATUSES = {"present", "absent", "half_day", "leave", "holiday", "weekend"}


def load_frame(path=CSV_PATH):
    if not path.exists():
        raise FileNotFoundError(
            f"Daily attendance feed not found: {path}. Required columns: "
            "employee_id, attendance_date, status. No daily records were synthesized."
        )
    frame = pd.read_csv(path, dtype={"employee_id": "string"})
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"Daily attendance feed missing required columns: {sorted(missing)}")
    frame = frame[[*sorted(REQUIRED), *sorted(OPTIONAL & set(frame.columns))]].copy()
    frame["employee_id"] = frame["employee_id"].str.strip()
    if frame["employee_id"].isna().any() or frame["employee_id"].eq("").any():
        raise ValueError("Daily attendance feed contains blank employee_id")
    dates = pd.to_datetime(frame["attendance_date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("Daily attendance feed contains invalid attendance_date")
    frame["attendance_date"] = dates.dt.date
    frame["status"] = frame["status"].astype("string").str.strip().str.lower().str.replace(" ", "_", regex=False)
    invalid = sorted(set(frame["status"].dropna()) - STATUSES)
    if frame["status"].isna().any() or invalid:
        raise ValueError(f"Invalid daily attendance status value(s): {invalid}")
    if frame.duplicated(["employee_id", "attendance_date"]).any():
        raise ValueError("Daily attendance feed has duplicate employee_id/attendance_date keys")
    for column in ("scheduled_minutes", "worked_minutes", "late_minutes"):
        if column not in frame:
            frame[column] = None
        else:
            values = pd.to_numeric(frame[column], errors="coerce")
            if (frame[column].notna() & values.isna()).any() or (values.dropna() < 0).any():
                raise ValueError(f"{column} must contain non-negative numbers or blanks")
            frame[column] = values
    if "is_holiday" not in frame:
        frame["is_holiday"] = False
    else:
        mapped = frame["is_holiday"].astype("string").str.strip().str.lower().map(
            {"true": True, "false": False, "yes": True, "no": False, "y": True, "n": False, "1": True, "0": False}
        )
        if mapped.isna().any():
            raise ValueError("is_holiday must be a boolean (true/false, yes/no, y/n, 1/0)")
        frame["is_holiday"] = mapped
    return frame


def load_to_warehouse(frame, database_url=DATABASE_URL):
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to load daily attendance into PostgreSQL")
    if frame.empty:
        print("Daily attendance feed has no records; no rows loaded.")
        return 0
    count = 0
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for row in frame.to_dict("records"):
            employee_id = str(row["employee_id"])
            day = row["attendance_date"]
            cur.execute(
                "SELECT employee_key, department_key FROM dim_employee "
                "WHERE employee_id = %s AND valid_from <= %s "
                "AND (valid_to IS NULL OR valid_to >= %s) "
                "ORDER BY is_current DESC LIMIT 1",
                (employee_id, day, day),
            )
            employee = cur.fetchone()
            if employee is None:
                raise ValueError(f"No employee history version for {employee_id} on {day}")
            employee_key, department_key = employee
            cur.execute(
                "INSERT INTO dim_date(date_key, full_date, day_number, month_number, "
                "month_name, quarter_number, year_number) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(full_date) DO NOTHING",
                (int(day.strftime("%Y%m%d")), day, day.day, day.month,
                 day.strftime("%B"), (day.month - 1) // 3 + 1, day.year),
            )
            cur.execute(
                "INSERT INTO fact_attendance_daily "
                "(employee_key, attendance_date, department_key, status, scheduled_minutes, "
                "worked_minutes, late_minutes, is_holiday, source_employee_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(source_employee_id, attendance_date) DO UPDATE SET "
                "employee_key=EXCLUDED.employee_key, department_key=EXCLUDED.department_key, "
                "status=EXCLUDED.status, scheduled_minutes=EXCLUDED.scheduled_minutes, "
                "worked_minutes=EXCLUDED.worked_minutes, late_minutes=EXCLUDED.late_minutes, "
                "is_holiday=EXCLUDED.is_holiday",
                (employee_key, day, department_key, row["status"], row["scheduled_minutes"],
                 row["worked_minutes"], row["late_minutes"], row["is_holiday"], employee_id),
            )
            count += 1
    print(f"Daily attendance loaded/upserted: {count} rows from {CSV_PATH.name}")
    return count


def main():
    load_to_warehouse(load_frame())


if __name__ == "__main__":
    main()
