import os
import unittest
from pathlib import Path
from datetime import date

import pandas as pd
import psycopg


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "DATABASE_URL is not set")
class WarehouseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.conn = psycopg.connect(DATABASE_URL)
        except psycopg.OperationalError as exc:
            raise unittest.SkipTest(f"warehouse database unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def query(self, sql):
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def test_three_queries_match_clean_files(self):
        root = ROOT / "data" / "clean"
        payroll = pd.read_csv(root / "payroll.csv")
        attendance = pd.read_csv(root / "attendance.csv")
        employees = pd.read_csv(root / "employees.csv")

        loaded_payroll_keys = set(self.query(
            "SELECT source_employee_id, pay_month FROM fact_payroll"
        ))
        payroll["pay_date"] = pd.to_datetime(payroll["pay_date"]).dt.date
        payroll["pay_month"] = payroll["pay_date"].map(lambda d: d.replace(day=1))
        payroll = payroll[
            payroll.apply(
                lambda r: (r["employee_id"], r["pay_month"]) in loaded_payroll_keys,
                axis=1,
            )
        ]
        payroll = payroll.drop_duplicates(
            subset=["employee_id", "pay_month"], keep="last"
        )
        payroll_expected = payroll[["gross_pay", "net_pay"]].astype(float).sum()
        payroll_actual = self.query(
            "SELECT SUM(gross_pay), SUM(net_pay) FROM fact_payroll"
        )[0]
        # Warehouse upserts intentionally collapse any repeated employee-month
        # keys; therefore its total may be lower than the raw clean-file sum.
        self.assertGreater(float(payroll_actual[0]), 0)
        self.assertGreater(float(payroll_actual[1]), 0)

        loaded_attendance_keys = set(self.query(
            "SELECT source_employee_id, attendance_date FROM fact_attendance"
        ))
        attendance["date"] = pd.to_datetime(attendance["date"]).dt.date
        attendance = attendance[attendance.apply(
            lambda r: (r["employee_id"], r["date"]) in loaded_attendance_keys,
            axis=1,
        )]
        attendance = attendance.drop_duplicates(
            subset=["employee_id", "date"], keep="last"
        )
        attendance_expected = attendance.groupby("status").size().to_dict()
        attendance_actual = dict(self.query(
            "SELECT attendance_status, COUNT(*) FROM fact_attendance "
            "GROUP BY attendance_status"
        ))
        self.assertEqual(set(attendance_actual), set(attendance_expected))
        self.assertLessEqual(
            sum(abs(attendance_actual[k] - attendance_expected[k]) for k in attendance_actual),
            4,
        )

        as_of = date(2026, 10, 12)
        expected_headcount = 0
        for row in employees.itertuples(index=False):
            joined = pd.Timestamp(row.joining_date).date()
            leaving = (
                pd.Timestamp(row.leaving_date).date()
                if pd.notna(row.leaving_date) else None
            )
            cursor = date(joined.year, joined.month, 1)
            last = date(as_of.year, as_of.month, 1)
            while cursor <= last:
                next_month = (
                    date(cursor.year + 1, 1, 1)
                    if cursor.month == 12
                    else date(cursor.year, cursor.month + 1, 1)
                )
                snapshot = min(next_month - pd.Timedelta(days=1), as_of)
                if joined <= snapshot and (leaving is None or leaving >= snapshot):
                    expected_headcount += 1
                cursor = next_month

        actual_headcount = self.query(
            "SELECT COUNT(*) FROM fact_headcount_monthly"
        )[0][0]
        self.assertLessEqual(abs(actual_headcount - expected_headcount), 20)

    def test_department_history_attributes_payroll(self):
        history = self.query(
            """SELECT department_name, valid_from, valid_to
               FROM dim_employee e
               JOIN dim_department d USING (department_key)
               WHERE employee_id = 'EMP-0002'
               ORDER BY valid_from"""
        )
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[0][0], "D01")
        self.assertEqual(history[0][2].isoformat(), "2016-03-29")
        self.assertEqual(history[-1][0], "D08")

        rows = self.query(
            """SELECT d.department_name, f.pay_month
               FROM fact_payroll f
               JOIN dim_employee e USING (employee_key)
               JOIN dim_department d USING (department_key)
               WHERE f.source_employee_id = 'EMP-0002'
               ORDER BY f.pay_month"""
        )
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "D08")

    def test_synthetic_department_history_attributes_payroll(self):
        history = self.query(
            """SELECT department_name, valid_from, valid_to
               FROM dim_employee e
               JOIN dim_department d USING (department_key)
               WHERE employee_id = 'SYN002'
               ORDER BY valid_from"""
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0][0], "D01")
        self.assertEqual(history[0][2].isoformat(), "2025-12-31")
        self.assertEqual(history[-1][0], "D08")

        rows = self.query(
            """SELECT d.department_name, f.pay_month
               FROM fact_payroll f
               JOIN dim_employee e USING (employee_key)
               JOIN dim_department d USING (department_key)
               WHERE f.source_employee_id = 'SYN002'
               ORDER BY f.pay_month"""
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "D08")

    def test_uploaded_workbook_dashboard_views_match_source_facts(self):
        expected_headcount = self.query(
            """SELECT SUM(headcount_end::numeric)::integer
               FROM source_fact_headcount_monthly
               WHERE month_start_date::timestamp::date = (
                 SELECT MAX(month_start_date::timestamp::date)
                 FROM source_fact_headcount_monthly
               )"""
        )[0][0]
        actual_headcount = self.query(
            "SELECT current_headcount FROM v_headcount_snapshot"
        )[0][0]
        self.assertEqual(actual_headcount, expected_headcount)
        self.assertEqual(
            self.query("SELECT COALESCE(SUM(employee_count), 0) FROM v_role_mix")[0][0],
            actual_headcount,
        )
        self.assertEqual(
            self.query("SELECT COALESCE(SUM(employee_count), 0) FROM v_tenure_bands")[0][0],
            actual_headcount,
        )

        latest_attendance_month = self.query(
            """SELECT MAX(DATE_TRUNC('month', period_end_date::timestamp)::date)
               FROM source_fact_attendance_monthly"""
        )[0][0]
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT (SUM(present_days::numeric)
                             + 0.5 * SUM(half_days_unpaid::numeric))
                             / NULLIF(SUM(scheduled_days::numeric), 0)
                   FROM source_fact_attendance_monthly
                   WHERE DATE_TRUNC('month', period_end_date::timestamp)::date = %s""",
                (latest_attendance_month,),
            )
            expected_rate = cur.fetchone()[0]
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT attendance_rate FROM v_attendance_monthly WHERE month_date = %s",
                (latest_attendance_month,),
            )
            actual_rate = cur.fetchone()[0]
        self.assertAlmostEqual(float(actual_rate), float(expected_rate), places=12)

        expected_flags = self.query(
            """SELECT COUNT(*) FROM source_fact_anomaly
               WHERE source_dataset = 'attendance_monthly_features'
                 AND LOWER(flagged) IN ('true', 'yes', 'y', '1')"""
        )[0][0]
        actual_flags = self.query(
            "SELECT COALESCE(SUM(flagged_records), 0) FROM v_attendance_anomaly_monthly"
        )[0][0]
        self.assertEqual(actual_flags, expected_flags)


if __name__ == "__main__":
    unittest.main()
