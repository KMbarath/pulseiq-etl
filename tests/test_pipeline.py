import unittest

import pandas as pd

from src.pipeline import AS_OF_DATE, transform, validate


class PipelineQualityTests(unittest.TestCase):
    def test_negative_salary_is_rejected(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"], "salary": ["-10"],
            "effective_date": ["2026-01-01"],
        })
        clean, rejected, stats = transform("salaries", raw)
        self.assertEqual(len(clean), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("negative_salary", rejected.iloc[0]["_rejection_reason"])
        self.assertEqual(stats["rows_rejected"], 1)

    def test_invalid_date_is_rejected(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"], "salary": ["10"],
            "effective_date": ["not-a-date"],
        })
        clean, rejected, _ = transform("salaries", raw)
        self.assertEqual(len(clean), 0)
        self.assertIn("invalid_effective_date", rejected.iloc[0]["_rejection_reason"])

    def test_duplicate_employee_id_is_rejected(self):
        raw = pd.DataFrame({
            "employee_id": ["E1", "E1"],
            "name": ["A One", "A Uno"],
            "joining_date": ["2024-01-01", "2024-01-01"],
            "leaving_date": [None, None],
        })
        clean, rejected, _ = transform("employees", raw)
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected.iloc[0]["_rejection_reason"], "duplicate_employee_id")
        validate("employees", clean)

    def test_joining_after_leaving_is_quarantined(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"], "name": ["A One"],
            "joining_date": ["2026-02-01"],
            "leaving_date": ["2026-01-01"],
        })
        clean, rejected, _ = transform("employees", raw)
        self.assertEqual(len(clean), 0)
        self.assertIn("joining_after_leaving", rejected.iloc[0]["_rejection_reason"])

    def test_future_date_is_rejected(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"], "salary": ["10"],
            "effective_date": [(AS_OF_DATE + pd.Timedelta(days=1)).strftime("%Y-%m-%d")],
        })
        _, rejected, _ = transform("salaries", raw)
        self.assertIn("future_effective_date", rejected.iloc[0]["_rejection_reason"])

    def test_approved_future_leave_is_retained_as_planned_leave(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"],
            "start_date": [(AS_OF_DATE + pd.Timedelta(days=10)).strftime("%Y-%m-%d")],
            "end_date": [(AS_OF_DATE + pd.Timedelta(days=20)).strftime("%Y-%m-%d")],
            "status": ["Approved"],
        })
        clean, rejected, _ = transform("leave", raw)
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(rejected), 0)

    def test_reversed_leave_dates_are_quarantined(self):
        raw = pd.DataFrame({
            "employee_id": ["E1"],
            "start_date": ["2026-02-20"],
            "end_date": ["2026-02-19"],
            "status": ["Approved"],
        })
        clean, rejected, _ = transform("leave", raw)
        self.assertEqual(len(clean), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("leave_start_after_end", rejected.iloc[0]["_rejection_reason"])


if __name__ == "__main__":
    unittest.main()
