import tempfile
import unittest
from pathlib import Path

from src.daily_attendance_loader import load_frame


class DailyAttendanceLoaderTests(unittest.TestCase):
    def read_csv(self, content):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "attendance_daily.csv"
        path.write_text(content, encoding="utf-8")
        return load_frame(path)

    def test_normalizes_and_accepts_valid_daily_feed(self):
        frame = self.read_csv(
            "employee_id,attendance_date,status,late_minutes,is_holiday\n"
            " EMP-1 ,2026-09-01,Present,5,false\n"
        )
        self.assertEqual(frame.loc[0, "employee_id"], "EMP-1")
        self.assertEqual(frame.loc[0, "status"], "present")
        self.assertEqual(frame.loc[0, "attendance_date"].isoformat(), "2026-09-01")
        self.assertEqual(float(frame.loc[0, "late_minutes"]), 5.0)
        self.assertFalse(frame.loc[0, "is_holiday"])

    def test_rejects_duplicate_employee_day(self):
        with self.assertRaisesRegex(ValueError, "duplicate employee_id/attendance_date"):
            self.read_csv(
                "employee_id,attendance_date,status\n"
                "EMP-1,2026-09-01,present\nEMP-1,2026-09-01,absent\n"
            )

    def test_rejects_invalid_date_and_status(self):
        with self.assertRaisesRegex(ValueError, "invalid attendance_date"):
            self.read_csv("employee_id,attendance_date,status\nEMP-1,nope,present\n")
        with self.assertRaisesRegex(ValueError, "Invalid daily attendance status"):
            self.read_csv("employee_id,attendance_date,status\nEMP-1,2026-09-01,unknown\n")

    def test_rejects_negative_minutes(self):
        with self.assertRaisesRegex(ValueError, "late_minutes must contain non-negative"):
            self.read_csv(
                "employee_id,attendance_date,status,late_minutes\n"
                "EMP-1,2026-09-01,present,-1\n"
            )


if __name__ == "__main__":
    unittest.main()
