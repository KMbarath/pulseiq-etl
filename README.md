# PulseIQ ETL pipeline

This project extracts the five raw datasets, standardises them with pandas,
validates the accepted rows with Pandera, and writes deterministic CSV outputs.

## Run with Docker

1. Copy `.env.example` to `.env`.
2. Put exactly one file for each table (`employees`, `salaries`, `attendance`,
   `leave`, and `payroll`) in `data/raw/` as CSV or Excel.
3. Run:

```text
docker compose run --rm etl
```

Clean data is written to `data/clean/`, rejected rows to `data/rejected/`, and
one JSON run report to `logs/`.

The default `FAIL_ON_REJECTS=true` means rejected rows are saved for diagnosis,
then the run exits non-zero so bad data cannot be mistaken for a successful
refresh. Set it to `false` only for an explicitly quarantine-only workflow.

## Data-quality decisions

Rows with missing required fields, malformed or future dates, negative financial
values, invalid numbers, reversed leave dates, or `joining_date` after
`leaving_date` are quarantined. A joining date after a leaving date is not
silently corrected: the source dates are ambiguous, so retaining the row would
create misleading tenure; quarantining preserves evidence and requires the
source owner to fix it. Exact duplicates are removed deterministically, while
duplicate employee IDs are quarantined.

## Tests

The standard-library test suite runs without extra tooling:

```text
python -m unittest discover -s tests -v
```

The tests exercise negative salaries, malformed dates, duplicate employee IDs,
and reversed employment dates.
