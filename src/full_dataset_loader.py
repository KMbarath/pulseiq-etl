"""Preserve every supplied workbook sheet as a PostgreSQL source table."""
import os, re
from pathlib import Path
from datetime import date, datetime
from openpyxl import load_workbook
import psycopg

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "data" / "03_PulseIQ_Analytics_Star_Schema_Dataset.xlsx"
DB = os.environ["DATABASE_URL"]
PRESENTATION_VIEWS = (
    "v_headcount_latest_department", "v_headcount_department_monthly",
    "v_headcount_snapshot", "v_headcount_monthly", "v_role_mix",
    "v_joiners_leavers_monthly", "v_tenure_bands",
    "v_attendance_monthly", "v_attendance_department_monthly",
    "v_leave_monthly", "v_attendance_anomaly_monthly",
)

def ident(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

def scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)

def main():
    wb = load_workbook(BOOK, read_only=True, data_only=True)
    with psycopg.connect(DB) as conn:
        with conn.cursor() as cur:
            # Workbook source tables are replaced below. Remove only our
            # dependent presentation views first; the compose command recreates
            # them from sql/superset_views.sql immediately after this loader.
            for view in PRESENTATION_VIEWS:
                cur.execute(f'DROP VIEW IF EXISTS "{view}" CASCADE')
            for sheet in wb.sheetnames:
                values = wb[sheet].values
                header = next(values)
                while header and all(v is None for v in header):
                    header = next(values)
                if not header or all(v is None for v in header):
                    continue
                columns = []
                seen = set()
                for i, name in enumerate(header):
                    col = ident(name or f"column_{i+1}") or f"column_{i+1}"
                    if col in seen:
                        col = f"{col}_{i+1}"
                    seen.add(col); columns.append(col)
                table = f"source_{ident(sheet)}"
                cur.execute(f'DROP TABLE IF EXISTS "{table}"')
                cur.execute(
                    f'CREATE TABLE "{table}" (' + ', '.join(f'"{c}" TEXT' for c in columns) + ')'
                )
                rows = []
                for row in values:
                    if any(v is not None for v in row):
                        rows.append([scalar(row[i] if i < len(row) else None) for i in range(len(columns))])
                if rows:
                    placeholders = ",".join(["%s"] * len(columns))
                    cur.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
                print(f"Loaded {table}: {len(rows)} rows")
        conn.commit()

if __name__ == "__main__":
    main()
