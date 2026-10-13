"""Import the supplied PulseIQ workbook into the Task 1/2 input contracts."""
from pathlib import Path
import os
import sys
import csv
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = Path(os.getenv(
    "PULSEIQ_DATASET_XLSX",
    str(ROOT / "data" / "03_PulseIQ_Analytics_Star_Schema_Dataset.xlsx"),
))
RAW = ROOT / "data" / "raw"
REF = ROOT / "data" / "reference"

def rows(wb, sheet):
    values = wb[sheet].values
    header = next(values)
    # README has leading blank columns; all analytical sheets have headers.
    while header and all(v is None for v in header):
        header = next(values)
    return [dict(zip(header, row)) for row in values if any(v is not None for v in row)]

def write(name, fields, records, folder=RAW):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("w", newline="", encoding="utf-8") as f:
        out = csv.DictWriter(f, fieldnames=fields)
        out.writeheader()
        out.writerows({k: ("" if r.get(k) is None else r.get(k)) for k in fields} for r in records)

def iso(value):
    return value.date().isoformat() if hasattr(value, "date") else ("" if value is None else str(value))

def main():
    if not WORKBOOK.exists():
        raise FileNotFoundError(WORKBOOK)
    try:
        wb = load_workbook(WORKBOOK, read_only=True, data_only=True)
    except PermissionError as exc:
        raise PermissionError(
            f"Python cannot read {WORKBOOK}. Close the workbook in Excel/OneDrive "
            "or copy it to the repository and set PULSEIQ_DATASET_XLSX to that copy."
        ) from exc

    employee_history = rows(wb, "dim_employee")
    current = [r for r in employee_history if r.get("is_current") == "Y"]
    write("employees.csv", ["employee_id", "name", "joining_date", "leaving_date"], [
        {"employee_id": r["employee_id"], "name": r["full_name"],
         "joining_date": iso(r["hire_date"]), "leaving_date": iso(r.get("exit_date"))}
        for r in current
    ])

    write("salaries.csv", ["employee_id", "salary", "effective_date"], [
        {"employee_id": r["employee_id"], "salary": r["monthly_fixed_gross"],
         "effective_date": iso(r["period_end_date"])}
        for r in rows(wb, "fact_payroll")
    ])

    write("payroll.csv", ["employee_id", "pay_date", "gross_pay", "net_pay"], [
        {"employee_id": r["employee_id"], "pay_date": iso(r["period_end_date"]),
         "gross_pay": r["gross_pay"], "net_pay": r["net_pay"]}
        for r in rows(wb, "fact_payroll")
    ])

    attendance = []
    for r in rows(wb, "fact_attendance_monthly"):
        rate = float(r["attendance_rate"] or 0)
        status = "Present" if rate >= 0.999 else ("Partial" if rate > 0 else "Absent")
        attendance.append({"employee_id": r["employee_id"], "date": iso(r["period_end_date"]), "status": status})
    write("attendance.csv", ["employee_id", "date", "status"], attendance)

    write("leave.csv", ["employee_id", "start_date", "end_date"], [
        {"employee_id": r["employee_id"], "start_date": iso(r["start_date"]), "end_date": iso(r["end_date"])}
        for r in rows(wb, "fact_leave")
    ])

    # Normalize overlapping source validity windows to contiguous SCD windows.
    history = sorted(employee_history, key=lambda r: (r["employee_id"], r["valid_from"]))
    org_history = []
    for i, r in enumerate(history):
        next_row = history[i + 1] if i + 1 < len(history) and history[i + 1]["employee_id"] == r["employee_id"] else None
        valid_to = next_row["valid_from"].date() if next_row else (r.get("valid_to").date() if r.get("valid_to") else None)
        if valid_to and valid_to > r["valid_from"].date():
            from datetime import timedelta
            valid_to = valid_to - timedelta(days=1)
        org_history.append({"employee_id": r["employee_id"], "department": r["department_id"],
                            "role": r["role_id"], "valid_from": iso(r["valid_from"]),
                            "valid_to": "" if valid_to is None else valid_to.isoformat()})
    write("employee_org_history.csv", ["employee_id", "department", "role", "valid_from", "valid_to"], org_history, REF)

    metrics = rows(wb, "metric_dictionary")
    if metrics:
        metric_fields = list(metrics[0].keys())
        write("metric_dictionary.csv", metric_fields, metrics, ROOT)

    print(f"Imported {len(current)} current employees, {len(rows(wb, 'fact_payroll'))} payroll rows, "
          f"{len(attendance)} attendance rows, and {len(rows(wb, 'fact_leave'))} leave rows.")

if __name__ == "__main__":
    main()
