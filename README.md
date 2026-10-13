# PulseIQ ETL pipeline

This project extracts the five raw datasets, standardises them with pandas,
validates the accepted rows with Pandera, and writes deterministic CSV outputs.

## Quick start (Windows PowerShell)

Run these commands from the repository root (`D:\pulseiq-etl\pulseiq-etl`).
Docker Desktop must be running. The optional Python environment is used for
the workbook importer, tests, and Superset provisioning script.

```powershell
# One-time: create the local Python environment and install dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# One-time: create .env without overwriting an existing local configuration
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# Import the uploaded workbook into the Task 1 CSV inputs
python scripts\import_provided_dataset.py

# Run the ETL. This dataset has two known reversed leave-date rows;
# quarantine them and let the run finish with an explicit report.
docker compose run --rm -e FAIL_ON_REJECTS=false etl

# Start PostgreSQL and load/refresh the warehouse from the workbook
docker compose up -d warehouse-db
docker compose run --rm warehouse-load

# Verify all workbook sheets against PostgreSQL (headers/order and row counts)
docker compose run --rm warehouse-load python scripts/verify_workbook_counts.py

# Start Superset and provision the dashboards
docker compose up -d superset
python scripts\provision_superset_dashboards.py
```

Open the dashboards at:

- `http://localhost:8088/superset/dashboard/pulseiq-headcount-departments/`
- `http://localhost:8088/superset/dashboard/pulseiq-attendance-leave/`

Local Superset credentials are `admin` / `admin`. Change these before any
non-local deployment. If the strict ETL policy is preferred, omit
`-e FAIL_ON_REJECTS=false`; the run will save rejected rows and exit non-zero.

## Run with Docker

1. Copy `.env.example` to `.env`.
2. Put exactly one file for each table (`employees`, `salaries`, `attendance`,
   `leave`, and `payroll`) in `data/raw/` as CSV or Excel.
3. Run:

```text
docker compose run --rm etl
```

To replace the bundled sample inputs with the supplied workbook, run the
importer from the repository root (the workbook remains in its original
location):

```text
python scripts/import_provided_dataset.py
docker compose run --rm etl
```

If OneDrive blocks Python from reading the workbook, copy it into the project
and point the importer at the copy:

```powershell
Copy-Item "$env:USERPROFILE\OneDrive\Documents\Desktop\03_PulseIQ_Analytics_Star_Schema_Dataset.xlsx" .\input_dataset.xlsx
$env:PULSEIQ_DATASET_XLSX = (Resolve-Path .\input_dataset.xlsx).Path
python scripts\import_provided_dataset.py
```

The importer maps the workbook's `dim_employee`, `fact_payroll`,
`fact_attendance_monthly`, and `fact_leave` sheets into the five ETL input
contracts and derives employee organization history from `dim_employee`.

Clean data is written to `data/clean/`, rejected rows to `data/rejected/`, and
one JSON run report to `logs/`.

The default `FAIL_ON_REJECTS=true` means rejected rows are saved for diagnosis,
then the run exits non-zero so bad data cannot be mistaken for a successful
refresh. Set it to `false` only for an explicitly quarantine-only workflow.

## Data-quality decisions

Rows with missing required fields, malformed dates, future non-leave event
dates, negative financial values, invalid numbers, reversed leave dates, or `joining_date` after
`leaving_date` are quarantined. A joining date after a leaving date is not
silently corrected: the source dates are ambiguous, so retaining the row would
create misleading tenure; quarantining preserves evidence and requires the
source owner to fix it. Exact duplicates are removed deterministically, while
duplicate employee IDs are quarantined. Future leave dates are retained because
approved leave may be planned beyond the source data cutoff; reversed leave
ranges remain quarantined (the uploaded workbook documents two planted date
errors of this kind).

## Tests

Run unit tests with the project environment:

```text
\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

To include PostgreSQL integration tests, start/load the warehouse and set the
local database URL in the same PowerShell session first:

```powershell
docker compose up -d warehouse-db
docker compose run --rm warehouse-load
$env:DATABASE_URL = "postgresql://pulseiq:pulseiq_local_dev@localhost:5433/pulseiq_warehouse"
python -m unittest discover -s tests -v
Remove-Item Env:DATABASE_URL
```

The suite covers cleaning and quarantine rules, daily-feed validation, SCD
department history, dashboard view parity, and SQL answers compared with
expected values. PostgreSQL tests are skipped if `DATABASE_URL` is unset.

## Dashboards (Tasks 3–4)

Load the workbook-backed warehouse and presentation views, then start Superset
and provision the dashboards:

```text
docker compose up -d warehouse-db
docker compose run --rm warehouse-load
docker compose up -d superset
python scripts/provision_superset_dashboards.py
```

Open `http://localhost:8088/superset/dashboard/pulseiq-headcount-departments/`
or `http://localhost:8088/superset/dashboard/pulseiq-attendance-leave/`.
Local development credentials are `admin` / `admin`; change them before any
non-local deployment. The provisioning script registers workbook-derived views,
creates real charts and native filters, executes every chart query, and writes
the Superset API definitions into `dashboards/`.

Dashboard aggregates read the full uploaded workbook's `source_fact_*` sheets.
Attendance facts are monthly, so weekday/holiday and exact daily anomaly
analysis are unavailable; a daily attendance export is needed for those
questions. See `docs/attendance_insights.md` for findings and limitations and
`docs/dashboard_style_guide.md` for reviewed visual rules.

To enable real weekday/daily attendance analysis when the Python team provides
the daily export, use the contract in `docs/daily_attendance_contract.md` and
the summary query in `queries/07_attendance_by_weekday.sql`. Monthly workbook
rows are never expanded into invented daily records.

After the warehouse has been initialized with the commands above, put the
verified Python-team file at `data/raw/attendance_daily.csv`, then run:

```powershell
docker compose run --rm warehouse-load python -m src.daily_attendance_loader
```

The feed must have `employee_id`, `attendance_date`, and `status`; optional
minute and holiday fields are listed in the contract. The weekday query can
then be run in Superset SQL Lab or with `psql` against the warehouse. No daily
data or weekday chart is populated until that real feed is supplied.

## Stop services

Stop containers but keep warehouse and Superset data volumes:

```powershell
docker compose down
```

To see service status or logs:

```powershell
docker compose ps
docker compose logs --tail 100 warehouse-db
docker compose logs --tail 100 superset
```

Avoid `docker compose down -v` unless you intentionally want to delete the
warehouse database and Superset's saved state.
