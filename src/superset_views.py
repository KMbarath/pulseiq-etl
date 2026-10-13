"""Create the presentation views consumed by Superset dashboards."""
from pathlib import Path
import os

import psycopg


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "superset_views.sql"
    with psycopg.connect(database_url, autocommit=True) as connection:
        for view in (
            "v_headcount_latest_department", "v_headcount_department_monthly",
            "v_headcount_snapshot", "v_headcount_monthly", "v_role_mix",
            "v_joiners_leavers_monthly", "v_tenure_bands",
            "v_attendance_monthly", "v_attendance_department_monthly",
            "v_leave_monthly", "v_attendance_anomaly_monthly",
        ):
            connection.execute(f'DROP VIEW IF EXISTS "{view}" CASCADE')
        connection.execute(sql_path.read_text(encoding="utf-8"))
    print("Superset presentation views are ready.")


if __name__ == "__main__":
    main()
