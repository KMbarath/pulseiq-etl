"""Provision PulseIQ datasets, charts, and dashboards through Superset's API."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
import urllib.error
import urllib.request
import http.cookiejar


BASE_URL = os.getenv("SUPERSET_URL", "http://127.0.0.1:8088").rstrip("/")
USERNAME = os.getenv("SUPERSET_USERNAME", "admin")
PASSWORD = os.getenv("SUPERSET_PASSWORD", "admin")
ROOT = Path(__file__).resolve().parents[1]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main() -> None:
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies)
    )
    token = ""
    csrf_token = ""

    def request(method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-CSRFToken"] = csrf_token
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}{path}", data=data, headers=headers, method=method
        )
        try:
            with opener.open(req, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Superset {method} {path} failed: {detail}") from exc
        return json.loads(body) if body else {}

    token = request("POST", "/api/v1/security/login", {
        "username": USERNAME, "password": PASSWORD,
        "provider": "db", "refresh": True,
    })["access_token"]
    csrf_token = request("GET", "/api/v1/security/csrf_token/")["result"]

    def get(path: str) -> dict:
        return request("GET", path)

    def post(path: str, payload: dict) -> dict:
        return request("POST", path, payload)

    def put(path: str, payload: dict) -> dict:
        return request("PUT", path, payload)

    datasets = get("/api/v1/dataset/")["result"]
    dataset_ids = {item["table_name"]: item["id"] for item in datasets}
    required_views = [
        "v_headcount_monthly", "v_headcount_department_monthly",
        "v_headcount_latest_department", "v_role_mix",
        "v_headcount_snapshot", "v_tenure_bands",
        "v_joiners_leavers_monthly", "v_attendance_monthly",
        "v_attendance_department_monthly", "v_leave_monthly",
        "v_attendance_anomaly_monthly",
    ]
    for name in required_views:
        if name not in dataset_ids:
            dataset = post("/api/v1/dataset/", {
                "database": 1, "schema": "public", "table_name": name
            })
            dataset_ids[name] = dataset["id"]
    for name in required_views:
        request("PUT", f"/api/v1/dataset/{dataset_ids[name]}/refresh")

    dashboard_specs = [
        {
            "title": "Headcount & Departments",
            "slug": "pulseiq-headcount-departments",
            "summary": "Current workforce, month-end trend, department and role mix, and employee movement.",
            "charts": [
                ("Current headcount", "v_headcount_snapshot", "big_number_total", ["current_headcount"], [], "The September 2026 workbook snapshot has 441 active employees.", "big_number"),
                ("Active departments", "v_headcount_snapshot", "big_number_total", ["active_departments"], [], "All 11 departments have non-zero headcount in September 2026.", "big_number"),
                ("Average tenure", "v_headcount_snapshot", "big_number_total", ["average_tenure_years"], [], "Average tenure is 3.3 years for active employees at the 2026-09-30 cutoff.", "big_number"),
                ("Joiners (latest month)", "v_headcount_snapshot", "big_number_total", ["joiners_latest_month"], [], "September 2026 recorded 17 hires; the source reports 3 exits.", "big_number"),
                ("Headcount trend", "v_headcount_monthly", "echarts_timeseries_line", ["month_date"], ["headcount"], "Headcount grew from 407 in April 2026 to 441 in September (+34).", "time"),
                ("Headcount by department", "v_headcount_latest_department", "echarts_timeseries_bar", ["department_name"], ["headcount"], "Engineering is largest (167); Customer Support has 59 and Data & AI 52.", "category"),
                ("Role mix", "v_role_mix", "pie", ["role_name"], ["employee_count"], "Software Engineer and QA Engineer are tied at 29 active employees each.", "category"),
                ("Joiners and leavers", "v_joiners_leavers_monthly", "echarts_timeseries_bar", ["month_date"], ["joiners", "leavers"], "September 2026 had 17 hires and 3 exits; transfers are excluded from hires.", "time"),
                ("Headcount by department over time", "v_headcount_department_monthly", "table", ["month_date", "department_name", "headcount"], [], "Compare monthly department counts; the latest snapshot totals 441 active employees.", "table"),
                ("Tenure bands", "v_tenure_bands", "table", ["tenure_band", "employee_count"], [], "The largest active tenure band is 1-2 years (123 of 441 employees).", "table"),
            ],
        },
        {
            "title": "Attendance & Leave",
            "slug": "pulseiq-attendance-leave",
            "summary": "Monthly attendance trends, department comparisons, leave volume, and AI/ML anomaly flags.",
            "charts": [
                ("Attendance rate trend", "v_attendance_monthly", "echarts_timeseries_line", ["month_date"], ["AVG:attendance_rate", "AVG:rolling_3_month_rate"], "Rate bottomed at 92.89% in May 2026 and recovered to 95.19% by September.", "time"),
                ("Attendance by department", "v_attendance_department_monthly", "table", ["month_date", "department_name", "scheduled_days", "present_days", "attendance_rate"], [], "In September, Finance & Accounts was 88.87% and Sales 97.54%; group sizes differ.", "table"),
                ("Leave days by type", "v_leave_monthly", "table", ["month_date", "leave_type", "leave_days", "leave_requests"], [], "Earned Leave leads at 2,336 approved days, followed by Casual Leave at 1,995.", "table"),
                ("Late-arrival rate", "v_attendance_monthly", "table", ["month_date", "late_arrivals", "late_arrival_rate"], [], "Late arrivals peaked at 7.53% of present days in March 2026.", "table"),
                ("Attendance anomaly flags", "v_attendance_anomaly_monthly", "echarts_timeseries_bar", ["month_date"], ["flagged_records"], "221 monthly anomaly flags appear in the workbook sample; these are review signals, not daily incidents.", "time"),
            ],
        },
    ]

    charts_existing = get("/api/v1/chart/")["result"]
    chart_by_name = {item["slice_name"]: item for item in charts_existing}
    dashboards_existing = get("/api/v1/dashboard/")["result"]
    dashboard_by_slug = {item.get("slug"): item for item in dashboards_existing}
    artifacts: list[dict] = []

    for spec in dashboard_specs:
        dashboard = dashboard_by_slug.get(spec["slug"])
        if dashboard is None and spec["slug"] == "pulseiq-headcount-departments":
            # Reuse the earlier API smoke-test dashboard instead of leaving a dummy behind.
            dashboard = dashboard_by_slug.get("pulseiq-test")
        position = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"], "parents": []},
            "GRID_ID": {"id": "GRID_ID", "type": "GRID", "children": [], "parents": ["ROOT_ID"]},
        }
        if dashboard is None:
            created = post("/api/v1/dashboard/", {
                "dashboard_title": spec["title"], "slug": spec["slug"],
                "published": True, "position_json": json.dumps(position),
                "json_metadata": "{}",
            })
            dashboard_id = created["id"]
        else:
            dashboard_id = dashboard["id"]

        chart_records = []
        chart_ids = []
        for title, view, viz, dimensions, metrics, takeaway, mode in spec["charts"]:
            datasource_id = dataset_ids[view]
            config: dict = {
                "datasource": f"{datasource_id}__table",
                "viz_type": viz,
                "query_mode": "raw" if mode == "table" else "aggregate",
                "row_limit": 10000,
                "adhoc_filters": [],
            }
            if mode == "table":
                config["all_columns"] = dimensions
            elif mode == "big_number":
                metric = dimensions[0]
                config["time_range"] = "No filter"
                config["metric"] = {
                    "expressionType": "SIMPLE",
                    "column": {"column_name": metric},
                    "aggregate": "MAX", "label": metric,
                    "optionName": f"metric_{metric}",
                }
            elif mode == "category":
                config["groupby"] = dimensions
                config["metrics"] = [
                    {"expressionType": "SIMPLE",
                     "column": {"column_name": metric},
                     "aggregate": "SUM", "label": metric,
                     "optionName": f"metric_{metric}"}
                    for metric in metrics
                ]
            else:
                config["x_axis"] = dimensions[0]
                config["granularity_sqla"] = dimensions[0]
                config["time_grain_sqla"] = "P1M"
                config["time_range"] = "No filter"
                config["groupby"] = []
                config["metrics"] = []
                for metric in metrics:
                    aggregate, column = metric.split(":", 1) if ":" in metric else ("SUM", metric)
                    config["metrics"].append({
                        "expressionType": "SIMPLE",
                        "column": {"column_name": column},
                        "aggregate": aggregate,
                        "label": column,
                        "optionName": f"metric_{column}",
                    })
            payload = {
                "slice_name": title,
                "datasource_id": datasource_id,
                "datasource_type": "table",
                "viz_type": viz,
                "params": json.dumps(config, separators=(",", ":")),
                "description": takeaway,
                "dashboards": [dashboard_id],
            }
            if mode == "table":
                query = {"columns": dimensions, "metrics": [], "groupby": [],
                         "granularity": None, "filters": [], "orderby": [],
                         "extras": {"time_grain_sqla": "P1M", "having": "", "where": ""},
                         "row_limit": 10000, "order_desc": True,
                         "annotation_layers": [], "post_processing": []}
            elif mode == "big_number":
                query = {"columns": [], "metrics": [config["metric"]],
                         "groupby": [], "granularity": None, "filters": [],
                         "orderby": [], "extras": {"time_grain_sqla": "P1M", "having": "", "where": ""},
                         "row_limit": 10000, "order_desc": True,
                         "annotation_layers": [], "post_processing": []}
            elif mode == "category":
                query = {"columns": [], "metrics": config["metrics"],
                         "groupby": config["groupby"], "granularity": None,
                         "filters": [], "orderby": [],
                         "extras": {"time_grain_sqla": "P1M", "having": "", "where": ""},
                         "row_limit": 10000, "order_desc": True,
                         "annotation_layers": [], "post_processing": []}
            else:
                query = {"columns": [], "metrics": config["metrics"],
                         "groupby": dimensions,
                         "is_timeseries": True,
                         "granularity": dimensions[0],
                         "granularity_sqla": dimensions[0], "filters": [],
                         "orderby": [],
                         "extras": {"time_grain_sqla": "P1M", "having": "", "where": ""},
                         "time_range": "No filter", "row_limit": 10000,
                         "order_desc": True, "annotation_layers": [],
                         "post_processing": []}
            query_context = {
                "datasource": {"id": datasource_id, "type": "table"},
                "force": True, "queries": [query],
                "result_format": "json", "result_type": "full",
                "form_data": config,
            }
            data_result = post("/api/v1/chart/data", query_context)
            query_output = data_result.get("result", [{}])[0]
            if query_output.get("status") != "success":
                raise RuntimeError(
                    f"Superset chart query failed for {title}: "
                    f"{query_output.get('error') or query_output.get('query')}"
                )
            payload["query_context"] = json.dumps(query_context, separators=(",", ":"))
            payload["query_context_generation"] = False
            existing = chart_by_name.get(title)
            if existing:
                chart_id = existing["id"]
                put(f"/api/v1/chart/{chart_id}", payload)
            else:
                created = post("/api/v1/chart/", payload)
                chart_id = created["id"]
                chart_by_name[title] = {"id": chart_id, "slice_name": title}
            chart_ids.append(chart_id)
            chart_records.append({"id": chart_id, "title": title,
                                  "dataset": view, "viz_type": viz,
                                  "takeaway": takeaway,
                                  "rows_returned": query_output.get("rowcount", 0),
                                  "query_status": query_output.get("status")})

        rows = []
        if spec["slug"] == "pulseiq-headcount-departments":
            chart_groups = [chart_ids[:4]] + [chart_ids[i:i + 2]
                                               for i in range(4, len(chart_ids), 2)]
        else:
            chart_groups = [chart_ids[i:i + 2]
                            for i in range(0, len(chart_ids), 2)]
        for row_charts in chart_groups:
            row_id = f"ROW-{uuid.uuid4()}"
            position["GRID_ID"]["children"].append(row_id)
            chart_nodes = []
            for chart_id in row_charts:
                chart_node_id = f"CHART-{chart_id}"
                chart_nodes.append(chart_node_id)
                record = next(x for x in chart_records if x["id"] == chart_id)
                position[chart_node_id] = {
                    "id": chart_node_id, "type": "CHART", "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "meta": {"chartId": chart_id, "height": 50,
                             "sliceName": record["title"],
                             "width": 12 // len(row_charts)},
                }
            position[row_id] = {
                "id": row_id, "type": "ROW", "children": chart_nodes,
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            rows.append(row_id)

        # Department/date filter definitions are native-filter metadata; date
        # filters apply to charts with a month_date column only.
        department_views = (
            ["v_headcount_department_monthly", "v_headcount_latest_department"]
            if spec["slug"] == "pulseiq-headcount-departments"
            else ["v_attendance_department_monthly"]
        )
        date_filter_datasets = [dataset_ids[chart[1]] for chart in spec["charts"]
                                if "month_date" in chart[3]]
        filters = [{
            "id": f"NATIVE_FILTER-{uuid.uuid4()}", "name": "Department",
            "filterType": "filter_select", "type": "NATIVE_FILTER",
            "targets": [{"datasetId": dataset_ids[view],
                         "column": {"name": "department_name"}}
                        for view in department_views],
            "chartsInScope": chart_ids, "tabsInScope": [],
            "cascadeParentIds": [],
            "controlValues": {"enableEmptyFilter": False,
                               "defaultToFirstItem": False,
                               "multiSelect": True, "searchAllOptions": True},
            "defaultDataMask": {"filterState": {"value": None, "label": None},
                                "extraFormData": {}},
        }]
        if date_filter_datasets:
            filters.append({
                "id": f"NATIVE_FILTER-{uuid.uuid4()}", "name": "Date range",
                "filterType": "filter_time", "type": "NATIVE_FILTER",
                "targets": [{"datasetId": dataset_id,
                             "column": {"name": "month_date"}}
                            for dataset_id in sorted(set(date_filter_datasets))],
                "chartsInScope": chart_ids, "tabsInScope": [],
                "cascadeParentIds": [],
                "defaultDataMask": {
                    "filterState": {"value": "No filter", "label": "No filter"},
                    "extraFormData": {"time_range": "No filter"},
                },
            })
        metadata = {"show_native_filters": True,
                    "native_filter_configuration": filters,
                    "timed_refresh_immune_slices": []}
        position["GRID_ID"]["children"] = rows
        put(f"/api/v1/dashboard/{dashboard_id}", {
            "dashboard_title": spec["title"], "slug": spec["slug"],
            "published": True, "position_json": json.dumps(position),
            "json_metadata": json.dumps(metadata),
        })
        artifacts.append({"dashboard_title": spec["title"], "slug": spec["slug"],
                          "dashboard_id": dashboard_id, "summary": spec["summary"],
                          "charts": chart_records, "filters": ["department", "date range"]})

    for artifact in artifacts:
        path = ROOT / "dashboards" / f"{artifact['slug']}.json"
        dashboard_detail = get(f"/api/v1/dashboard/{artifact['dashboard_id']}")["result"]
        artifact["superset_definition"] = {
            "dashboard": dashboard_detail,
            "charts": [get(f"/api/v1/chart/{chart['id']}")["result"]
                       for chart in artifact["charts"]],
        }
        path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dashboards": artifacts}, indent=2))


if __name__ == "__main__":
    main()
