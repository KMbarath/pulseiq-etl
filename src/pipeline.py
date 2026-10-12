
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))
CLEAN_DIR = Path(os.getenv("CLEAN_DIR", "data/clean"))
REJECTED_DIR = Path(os.getenv("REJECTED_DIR", "data/rejected"))
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))

AS_OF_DATE = pd.Timestamp(
    os.getenv("ETL_AS_OF_DATE", "2026-10-12")
).normalize()

FAIL_ON_REJECTS = (
    os.getenv("FAIL_ON_REJECTS", "true").lower() == "true"
)

# Paths are relative to the project root when configured that way.
def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


RAW_DIR = resolve_path(RAW_DIR)
CLEAN_DIR = resolve_path(CLEAN_DIR)
REJECTED_DIR = resolve_path(REJECTED_DIR)
LOG_DIR = resolve_path(LOG_DIR)

TABLES = {
    "employees": {
        "required": ["employee_id", "name", "joining_date"],
        "dates": ["joining_date", "leaving_date"],
        "numbers": [],
        "primary_date": "joining_date",
    },
    "salaries": {
        "required": ["employee_id", "salary", "effective_date"],
        "dates": ["effective_date"],
        "numbers": ["salary"],
        "primary_date": "effective_date",
    },
    "attendance": {
        "required": ["employee_id", "date", "status"],
        "dates": ["date"],
        "numbers": [],
        "primary_date": "date",
    },
    "leave": {
        "required": ["employee_id", "start_date", "end_date"],
        "dates": ["start_date", "end_date"],
        "numbers": [],
        "primary_date": "start_date",
    },
    "payroll": {
        "required": [
            "employee_id", "pay_date", "gross_pay", "net_pay"
        ],
        "dates": ["pay_date"],
        "numbers": ["gross_pay", "net_pay"],
        "primary_date": "pay_date",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("pulseiq.etl")


def normalize_column(name: str) -> str:
    """Convert Employee ID, employee-id, etc. to employee_id."""
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def find_input(table: str) -> Path:
    """Find exactly one supported file for a logical table."""
    matches = [
        path for path in RAW_DIR.iterdir()
        if path.is_file()
        and path.stem.lower() == table
        and path.suffix.lower() in {".csv", ".xlsx", ".xls"}
    ] if RAW_DIR.exists() else []

    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one CSV/Excel file for '{table}' "
            f"in {RAW_DIR}; found {len(matches)}: "
            f"{[p.name for p in matches]}"
        )

    return matches[0]


def extract(path: Path) -> pd.DataFrame:
    """Read raw data without silently discarding source rows."""
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype="string")
    else:
        df = pd.read_excel(path, dtype=object)

    df.columns = [normalize_column(c) for c in df.columns]

    if df.columns.duplicated().any():
        raise ValueError(
            f"{path.name} has duplicate columns after normalization"
        )

    logger.info("EXTRACT | %s | rows_in=%d", path.name, len(df))
    return df


def reject_rows(
    df: pd.DataFrame,
    reasons: pd.Series,
    table: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split accepted rows from rejected rows, preserving source values."""
    bad = reasons.fillna("").ne("")
    rejected = df.loc[bad].copy()
    rejected["_source_table"] = table
    rejected["_rejection_reason"] = reasons.loc[bad].values

    accepted = df.loc[~bad].copy()
    return accepted, rejected


def transform(
    table: str, original: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cfg = TABLES[table]
    df = original.copy()
    rows_in = len(df)

    missing = [c for c in cfg["required"] if c not in df.columns]
    if missing:
        raise ValueError(
            f"{table}: missing required columns {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    # Strip surrounding whitespace; blank strings become missing values.
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace("", pd.NA)

    # Standardize employee IDs while preserving leading zeros.
    df["employee_id"] = df["employee_id"].astype("string").str.strip()

    # Standardize names consistently.
    if "name" in df.columns:
        df["name"] = (
            df["name"].astype("string")
            .str.replace(r"\s+", " ", regex=True)
            .str.title()
        )

    # Parse date columns. Invalid non-empty values become NaT.
    invalid_dates = {}
    for col in cfg["dates"]:
        if col not in df.columns:
            continue

        raw = df[col].copy()
        parsed = pd.to_datetime(raw, errors="coerce")
        invalid_dates[col] = raw.notna() & parsed.isna()
        df[col] = parsed.dt.normalize()

    # Convert known financial columns to numbers.
    invalid_numbers = {}
    for col in cfg["numbers"]:
        raw = df[col].copy()
        parsed = pd.to_numeric(raw, errors="coerce")
        invalid_numbers[col] = raw.notna() & parsed.isna()
        df[col] = parsed

    reasons = pd.Series("", index=df.index, dtype="string")

    def add_reason(mask: pd.Series, message: str) -> None:
        nonlocal reasons
        mask = mask.fillna(False)
        reasons.loc[mask] = reasons.loc[mask].map(
            lambda old: f"{old}; {message}" if old else message
        )

    # Reject rows missing critical fields.
    for col in cfg["required"]:
        add_reason(df[col].isna(), f"missing_{col}")

    # Reject malformed dates and numbers instead of guessing replacements.
    for col, mask in invalid_dates.items():
        add_reason(mask, f"invalid_{col}")

    for col, mask in invalid_numbers.items():
        add_reason(mask, f"invalid_{col}")

    # Negative salary/pay values are not allowed.
    for col in cfg["numbers"]:
        add_reason(df[col].lt(0), f"negative_{col}")

    # Dates cannot be in the future relative to the fixed as-of date.
    for col in cfg["dates"]:
        if col in df.columns:
            add_reason(df[col].gt(AS_OF_DATE), f"future_{col}")

    # Employee joining date must not be after leaving date.
    if {"joining_date", "leaving_date"}.issubset(df.columns):
        add_reason(
            df["leaving_date"].notna()
            & df["joining_date"].notna()
            & df["joining_date"].gt(df["leaving_date"]),
            "joining_after_leaving",
        )

    # Leave end must not precede leave start.
    if {"start_date", "end_date"}.issubset(df.columns):
        add_reason(
            df["start_date"].notna()
            & df["end_date"].notna()
            & df["start_date"].gt(df["end_date"]),
            "leave_start_after_end",
        )

    # Drop exact duplicates deterministically; keep the first occurrence.
    duplicate_mask = df.duplicated(keep="first")
    duplicate_count = int(duplicate_mask.sum())
    df = df.loc[~duplicate_mask].copy()
    reasons = reasons.loc[df.index]

    accepted, rejected = reject_rows(df, reasons, table)

    # Employees must have unique employee IDs.
    if table == "employees":
        duplicate_ids = accepted["employee_id"].duplicated(keep="first")
        if duplicate_ids.any():
            extra = accepted.loc[duplicate_ids].copy()
            extra["_source_table"] = table
            extra["_rejection_reason"] = "duplicate_employee_id"

            rejected = pd.concat(
                [rejected, extra], ignore_index=True
            )
            accepted = accepted.loc[~duplicate_ids].copy()

    # Add deterministic helper columns.
    date_col = cfg["primary_date"]
    accepted["month"] = accepted[date_col].dt.month.astype("Int64")
    accepted["year"] = accepted[date_col].dt.year.astype("Int64")

    if table == "employees":
        end_date = accepted["leaving_date"].fillna(AS_OF_DATE)
        tenure_days = (end_date - accepted["joining_date"]).dt.days
        accepted["tenure_years"] = (
            tenure_days.clip(lower=0) / 365.25
        ).round(2)

    stats = {
        "rows_in": rows_in,
        "exact_duplicates_removed": duplicate_count,
        "rows_clean": len(accepted),
        "rows_rejected": len(rejected),
    }

    return accepted, rejected, stats


def validate(table: str, df: pd.DataFrame) -> None:
    """Pandera schema validation. Any failure stops the ETL run."""
    cfg = TABLES[table]

    columns = {
        "employee_id": pa.Column(
            str, nullable=False, checks=pa.Check(
                lambda s: s.str.strip().ne("")
            )
        )
    }

    for col in cfg["dates"]:
        if col in df.columns:
            columns[col] = pa.Column(
                "datetime64[ns]", nullable=(col == "leaving_date")
            )

    for col in cfg["numbers"]:
        columns[col] = pa.Column(
            float,
            nullable=False,
            checks=pa.Check.ge(0),
            coerce=True,
        )

    if table == "employees":
        columns["name"] = pa.Column(str, nullable=False)
        columns["employee_id"] = pa.Column(
            str, nullable=False, unique=True
        )
        columns["joining_date"] = pa.Column(
            "datetime64[ns]", nullable=False
        )

    schema = pa.DataFrameSchema(
        columns,
        strict=False,
        coerce=False,
    )

    # Raises a SchemaError when any rule fails.
    schema.validate(df, lazy=True)

    if (
        table == "employees"
        and "leaving_date" in df.columns
    ):
        invalid = (
            df["leaving_date"].notna()
            & df["joining_date"].gt(df["leaving_date"])
        )
        if invalid.any():
            raise ValueError(
                "Pandera validation failed: joining_date "
                "must not be after leaving_date"
            )

    if table == "leave":
        invalid = df["start_date"].gt(df["end_date"])
        if invalid.any():
            raise ValueError(
                "Pandera validation failed: leave start is after end"
            )


def file_hash(path: Path) -> str:
    """Hash raw input bytes for reproducibility/audit tracking."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")

    for directory in (CLEAN_DIR, REJECTED_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    report = {
        "run_id": run_id,
        "started_at_utc": started.isoformat(),
        "as_of_date": str(AS_OF_DATE.date()),
        "tables": {},
        "status": "running",
    }

    all_rejected = []
    failed = False

    try:
        for table in TABLES:
            source = find_input(table)
            raw = extract(source)
            clean, rejected, stats = transform(table, raw)

            # Validate before writing accepted output.
            validate(table, clean)

            # Stable row order helps produce repeatable output files.
            clean = clean.sort_values(
                by=list(clean.columns),
                kind="mergesort",
                na_position="last",
            ).reset_index(drop=True)

            clean.to_csv(
                CLEAN_DIR / f"{table}.csv",
                index=False,
                date_format="%Y-%m-%d",
                na_rep="",
                lineterminator="\n",
            )

            rejected.to_csv(
                REJECTED_DIR / f"{table}_rejected.csv",
                index=False,
                date_format="%Y-%m-%d",
                na_rep="",
                lineterminator="\n",
            )

            all_rejected.append(rejected)

            report["tables"][table] = {
                **stats,
                "source_file": source.name,
                "source_sha256": file_hash(source),
            }

            logger.info(
                "LOAD | %s | rows_clean=%d | rows_rejected=%d",
                table, len(clean), len(rejected)
            )

        total_rejected = sum(
            item["rows_rejected"]
            for item in report["tables"].values()
        )

        report["total_rows_rejected"] = total_rejected
        report["status"] = (
            "completed_with_rejections"
            if total_rejected
            else "completed"
        )

        if FAIL_ON_REJECTS and total_rejected:
            report["status"] = "failed_due_to_rejections"
            failed = True

    except Exception as exc:
        logger.exception("ETL failed")
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        failed = True

    finally:
        report["finished_at_utc"] = datetime.now(
            timezone.utc
        ).isoformat()

        report_path = LOG_DIR / f"run_{run_id}.json"
        report_path.write_text(
            json.dumps(report, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

        logger.info("Run report saved to %s", report_path)
        print(json.dumps(report, indent=2, default=str))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
