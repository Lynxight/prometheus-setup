#!/usr/bin/env python3
"""Generate grafana/provisioning/dashboards/cvs_stability_metrics.json.

The dashboard JSON is generated — edit this script and re-run it instead of
editing the JSON by hand.

Panel ids are stable (chosen to match the pre-generator hand-authored file),
so bookmarked viewPanel= links keep working. Take the next free id when
adding a panel; never renumber existing ones.
"""
import json
import os
import pathlib

DS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}

# Filters on metrics that carry the full label set (swimmer_count and the
# cvs:swimmer_valid:bool recording rule, which keeps swimmer_count's labels).
FULL = ('environment=~"$server", site_name=~"$site_name", '
        'pool_name=~"$pool_name", pool_state=~"$pool_state", '
        'group=~"$deploy_group", under_maintenance=~"$under_maintenance"')
# cvs:software_up:bool aggregates per-camera actual_fps with
# min by (pool_name, site_name, environment), so only those labels survive —
# pool_state / group / under_maintenance filtering happens via SW_GATE below.
POOL = ('environment=~"$server", site_name=~"$site_name", '
        'pool_name=~"$pool_name"')
# Carries the pool_state / deploy-group / under_maintenance selectors over to
# metrics that lack those labels, via a join on swimmer_count.
SW_GATE = (' and on(pool_name, site_name, environment) swimmer_count{'
           'pool_state=~"$pool_state", group=~"$deploy_group", '
           'under_maintenance=~"$under_maintenance"}')
# CVS-version filter: $cvs_version <= 0 means "all versions".
VERSION = ('docker_version_tag == $cvs_version or '
           'docker_version_tag * (1 - ($cvs_version > bool 0)) > 0')


def version_gate(on):
    return f" and on({on}) ({VERSION})"


EXC_F = ('environment=~"$server", site_name=~"$site_name", '
         'pool_name=~"$pool_name", group=~"$deploy_group", '
         'under_maintenance=~"$under_maintenance", '
         'exception_name!~"NoneType|KeyboardInterrupt"')
EXC_SW_GATE = (' and on(pool_name, site_name, environment) swimmer_count{'
               'environment=~"$server", pool_state=~"$pool_state", '
               'group=~"$deploy_group", under_maintenance=~"$under_maintenance"}')
POOL_COUNT = ('scalar(count(count by (pool_name, site_name, environment) '
              f'(swimmer_count{{{FULL}}})))')
ALGO_SERVICES = ["Detection", "Ctm", "Gtm", "DecisionEngine"]

OPS_LINK = {
    "title": "View in OPS Dashboard",
    "url": "/d/c2e10e40-2cbb-460d-91a0-83334f641194/ops-dashboard-per-site-support?var-site_name=${__field.labels.site_name}&var-server=${__field.labels.environment}&var-pool_name=${__field.labels.pool_name}&from=${__from}&to=${__to}",
    "targetBlank": True,
}
ES_TIME = "_g=(time:(from:'${__from:date:iso}',to:'${__to:date:iso}'))"


def es_link(title, lucene_query):
    return {
        "title": title,
        "url": ("https://lynxight-log-prod.kb.eu-central-1.aws.cloud.es.io/app/discover#/?"
                f"{ES_TIME}&_a=(query:(language:lucene,query:'{lucene_query}'))"),
        "targetBlank": True,
    }


ES_ANY_LINK = es_link("Explore logs in Elasticsearch", "*")
ES_ALGO_LINK = es_link(
    "View algo service logs in Elasticsearch",
    "container.labels.com_docker_compose_service:(detection OR ctm OR gtm OR decision_engine)")
ES_VS_LINK = es_link("View video_stream logs in Elasticsearch",
                     "container.labels.com_docker_compose_service:video_stream")
ES_EXC_LINK = es_link(
    "View logs for this exception in Elasticsearch",
    'host.name:"${__data.fields.environment}" AND '
    "container.name:*_${__data.fields.site_name}_${__data.fields.pool_name}* "
    "AND json.level:ERROR AND json.message:*${__data.fields.exception_name}*")


def row(pid, title, y):
    return {"id": pid, "type": "row", "title": title,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "collapsed": False}


def target(expr, legend, ref, instant=False, interval=None, fmt=None):
    t = {"datasource": DS, "editorMode": "code", "expr": expr,
         "legendFormat": legend}
    if instant:
        t["instant"] = True
    else:
        t["range"] = True
    if interval:
        t["interval"] = interval
    if fmt:
        t["format"] = fmt
    t["refId"] = ref
    return t


def pct_bargauge(pid, title, desc, y, inner):
    """Left-half bargauge: overall average + sorted per-pool values of a
    0-100 percentage expression."""
    return {
        "id": pid,
        "type": "bargauge",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"h": 10, "w": 12, "x": 0, "y": y},
        "targets": [
            target(f"avg({inner})", "OVERALL AVERAGE", "A", instant=True),
            target(f"sort({inner})", "{{site_name}} / {{pool_name}}", "B",
                   instant=True),
        ],
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "continuous-RdYlGr"},
                "thresholds": {"mode": "absolute", "steps": [
                    {"color": "red", "value": None},
                    {"color": "yellow", "value": 80},
                    {"color": "green", "value": 95},
                ]},
                "unit": "percent",
                "decimals": 1,
                "min": 0,
                "max": 100,
                "links": [OPS_LINK],
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "OVERALL AVERAGE"},
                    "properties": [
                        {"id": "color",
                         "value": {"mode": "fixed", "fixedColor": "white"}},
                    ],
                },
            ],
        },
        "options": {
            "orientation": "horizontal",
            "displayMode": "gradient",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                              "values": False},
            "showUnfilled": True,
            "minVizWidth": 8,
            "minVizHeight": 16,
        },
    }


def daily_trend(pid, title, desc, y, expr, legend, color, unit, link,
                min_y=None, h=10, x=12, w=12):
    defaults = {
        "color": ({"mode": "fixed", "fixedColor": color} if color
                  else {"mode": "palette-classic"}),
        "custom": {
            "drawStyle": "line",
            "lineWidth": 2,
            "fillOpacity": 10,
            "pointSize": 8,
            "showPoints": "always",
            "lineInterpolation": "linear",
        },
        "unit": unit,
    }
    if min_y is not None:
        defaults["min"] = min_y
    defaults["links"] = [link]
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(expr, legend, "A", interval="1d")],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom",
                       "showLegend": True, "calcs": ["mean", "lastNotNull"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def hide_col(name):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "custom.hidden", "value": True}]}


def exc_table(pid, title, desc, y, expr, extra_hidden, index_by):
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "targets": [
            target(expr,
                   "{{site_name}} / {{pool_name}}"
                   + (" / {{service}}" if "service" in index_by else "")
                   + " ({{exception_name}})",
                   "A", instant=True, fmt="table"),
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"filterable": True},
                "links": [ES_EXC_LINK],
            },
            "overrides": [
                hide_col(c) for c in
                ["Time", "__name__", "job", "name", "group",
                 "under_maintenance"] + extra_hidden
            ] + [
                {"matcher": {"id": "byName", "options": "environment"},
                 "properties": [{"id": "displayName", "value": "server"}]},
                {"matcher": {"id": "byName", "options": "Value"},
                 "properties": [{"id": "displayName", "value": "Count"}]},
            ],
        },
        "transformations": [
            {"id": "organize",
             "options": {"indexByName": {c: i for i, c in enumerate(index_by)}}},
        ],
        "options": {
            "showHeader": True,
            "sortBy": [
                {"displayName": "Count", "desc": True},
                {"displayName": "site_name", "desc": False},
                {"displayName": "pool_name", "desc": False},
            ],
        },
    }


# --- Percentage expressions (bargauge inner / daily trend) ---

# % software uptime per pool: every camera producing frames. 5m subquery step
# to match the validity panels — 1m over a 30d range exceeds Prometheus's
# query sample limit ("would load too many samples into memory"). The rule
# still evaluates every 15s; 5m sampling of the bool only costs precision on
# sub-5m outages, negligible in a long-range average.
UP_PCT = (f"avg_over_time((cvs:software_up:bool{{{POOL}}}{SW_GATE}"
          f"{version_gate('pool_name, site_name, environment')})"
          f"[$__range:5m]) * 100")
UP_DAILY = (f"avg(avg_over_time(cvs:software_up:bool{{{POOL}}}[1d]) * 100"
            f"{SW_GATE.replace('on(pool_name, site_name, environment)', 'on(pool_name, site_name)')}"
            f"{version_gate('pool_name, site_name')})")

VALID_PCT = (f"avg_over_time((cvs:swimmer_valid:bool{{{FULL}}}"
             f"{version_gate('pool_name, site_name, environment')})"
             f"[$__range:5m]) * 100")
VALID_DAILY = (f"avg(avg_over_time(cvs:swimmer_valid:bool{{{FULL}}}[1d]) * 100"
               f"{version_gate('pool_name, site_name')})")

INCIDENTS = (f"ceil(sum_over_time((changes(cvs:swimmer_valid:bool{{{FULL}}}[5m])"
             f"{version_gate('pool_name, site_name, environment')})"
             f"[$__range:5m]) / 2)")
INCIDENTS_DAILY = (f"avg(ceil(changes(cvs:swimmer_valid:bool{{{FULL}}}[1d]) / 2)"
                   f"{version_gate('pool_name, site_name')})")


def per_service_avg_exc(svc):
    """Avg exception count per pool for one algo service over the range,
    falling back to 0 so a service with no exceptions still shows a bar."""
    return (
        f"(sum by (service) (sum_over_time((increase(cvs_exc_per_service{{"
        f'{EXC_F}, service="{svc}"}}[1h])'
        f"{version_gate('pool_name, site_name, environment')})[$__range:1h])"
        f"{EXC_SW_GATE}) / {POOL_COUNT}"
        f' or label_replace(vector(0), "service", "{svc}", "", ""))'
    )


ALGO_EXC_AVG = " or ".join(per_service_avg_exc(s) for s in ALGO_SERVICES)
ALGO_EXC_DAILY = (
    f"sum by (service) (increase(cvs_exc_per_service{{{EXC_F}, "
    f'service=~"{"|".join(ALGO_SERVICES)}"}}[1d]){EXC_SW_GATE}'
    f"{version_gate('pool_name, site_name')}) / {POOL_COUNT}"
)
ALGO_EXC_TABLE = (
    f"(round(sum_over_time((increase(cvs_exc_per_service{{{EXC_F}, "
    f'service=~"{"|".join(ALGO_SERVICES)}"}}[1h])'
    f"{version_gate('pool_name, site_name, environment')})[$__range:1h]))"
    f"{EXC_SW_GATE}) > 0"
)
VS_EXC_DAILY = (
    f'sum(increase(cvs_exc_per_service{{{EXC_F}, service="VideoStream"}}[1d])'
    f"{EXC_SW_GATE}{version_gate('pool_name, site_name')}) / {POOL_COUNT}"
)
VS_EXC_TABLE = (
    f"(round(sum_over_time((increase(cvs_exc_per_service{{{EXC_F}, "
    f'service="VideoStream"}}[1h])'
    f"{version_gate('pool_name, site_name, environment')})[$__range:1h]))"
    f"{EXC_SW_GATE}) > 0"
)


panels = []
y = 0

# --- Row: Software Uptime (AT-697) ---
panels.append(row(16, "Software Uptime", y)); y += 1
panels.append(pct_bargauge(
    17,
    "% Software Uptime (per pool, excluding nightly restart)",
    "Percentage of time every camera on the pool was producing frames "
    "(per-pool min of actual_fps > 0.5, via the cvs:software_up:bool "
    "recording rule) over the selected time range. Any single dead camera "
    "counts the whole pool as down. Planned maintenance windows (nightly "
    "restart / clean stop, cvs_maintenance_mode=1) are excluded. Isolates "
    "'basic plumbing is working' from swimmer count validity, which also "
    "depends on the algo pipeline.",
    y,
    UP_PCT,
))
panels.append(daily_trend(
    18,
    "Daily Trend: Software Uptime % (overall avg)",
    "Daily overall average of software uptime percentage (every camera on "
    "the pool producing frames).",
    y,
    UP_DAILY, "Software Uptime %", "blue", "percent", ES_VS_LINK,
)); y += 10

# --- Row: Swimmer Count Validity ---
panels.append(row(1, "Swimmer Count Validity", y)); y += 1
panels.append(pct_bargauge(
    3,
    "% Time with Valid Swimmer Count (per pool, excluding nightly restart)",
    "Percentage of time each pool had a valid swimmer count over the "
    "selected time range. Planned maintenance windows (nightly restart / "
    "clean stop, cvs_maintenance_mode=1) are excluded via the "
    "cvs:swimmer_valid:bool recording rule. Lower = less stable.",
    y,
    VALID_PCT,
))
panels.append(daily_trend(
    4,
    "Daily Trend: Validity % (overall avg)",
    "Daily overall average of swimmer count validity percentage.",
    y,
    VALID_DAILY, "Validity %", "green", "percent", ES_ANY_LINK,
)); y += 10

# --- Row: Invalid Swimmer Count Incidents ---
panels.append(row(5, "Invalid Swimmer Count Incidents", y)); y += 1
panels.append({
    "id": 6,
    "type": "bargauge",
    "title": "Estimated Incidents (per pool)",
    "description": "Estimated number of validity state transitions per pool "
    "(valid↔invalid) over the selected range, divided by 2. Excludes "
    "non-operational pools (under_maintenance) and nightly clean restarts "
    "(cvs_maintenance_mode).",
    "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
    "targets": [
        target(f"avg({INCIDENTS})", "OVERALL AVERAGE", "A", instant=True),
        target(f"sort_desc({INCIDENTS})", "{{site_name}} / {{pool_name}}",
               "B", instant=True),
    ],
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "continuous-BlYlRd"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 10},
                {"color": "red", "value": 50},
            ]},
            "unit": "short",
            "links": [OPS_LINK],
        },
        "overrides": [
            {
                "matcher": {"id": "byName", "options": "OVERALL AVERAGE"},
                "properties": [
                    {"id": "color",
                     "value": {"mode": "fixed", "fixedColor": "white"}},
                ],
            },
        ],
    },
    "options": {
        "orientation": "horizontal",
        "displayMode": "gradient",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                          "values": False},
        "showUnfilled": True,
    },
})
panels.append(daily_trend(
    7,
    "Daily Trend: Avg Incidents per Pool (overall avg)",
    "Daily overall average of invalid swimmer count incidents per pool. "
    "Excludes non-operational pools (under_maintenance) and nightly clean "
    "restarts (cvs_maintenance_mode).",
    y,
    INCIDENTS_DAILY, "Incidents", "orange", "short", ES_ANY_LINK, min_y=0,
    h=8,
)); y += 8

# --- Row: Algo Container Exceptions ---
panels.append(row(8, "Algo Container Exceptions", y)); y += 1
panels.append({
    "id": 11,
    "type": "barchart",
    "title": "Avg Exceptions per Pool by Algo Container",
    "description": "Average exception count per pool, grouped by algo "
    "container. Shows the mean across all matching pools.",
    "datasource": DS,
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
    "targets": [target(ALGO_EXC_AVG, "{{service}}", "A", instant=True)],
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "unit": "short",
            "links": [ES_ALGO_LINK],
        },
        "overrides": [
            {
                "matcher": {"id": "byName", "options": "Time"},
                "properties": [
                    {"id": "custom.hideFrom",
                     "value": {"legend": True, "tooltip": True, "viz": True}},
                ],
            },
        ],
    },
    "options": {
        "orientation": "horizontal",
        "showValue": "always",
        "barWidth": 0.8,
        "groupWidth": 0.7,
    },
})
panels.append(daily_trend(
    12,
    "Daily Trend: Avg Exceptions per Pool by Container",
    "Daily overall average of algo container exception counts per pool, "
    "grouped by service.",
    y,
    ALGO_EXC_DAILY, "{{service}}", None, "short", ES_ALGO_LINK, h=8,
)); y += 8

panels.append(exc_table(
    9,
    "Algo Exceptions (detailed counts)",
    "Exception counts for algo containers (Detection, Ctm, Gtm, "
    "DecisionEngine) over the selected time range. Detailed breakdown by "
    "pool, service, and exception type.",
    y,
    ALGO_EXC_TABLE,
    extra_hidden=[],
    index_by=["site_name", "pool_name", "environment", "service",
              "exception_name", "Value"],
)); y += 10

# --- Row: VideoStream Exceptions ---
panels.append(row(13, "VideoStream Exceptions", y)); y += 1
panels.append(daily_trend(
    14,
    "Daily Trend: Avg VideoStream Exceptions per Pool",
    "Daily overall average of VideoStream exception counts per pool. Tracked "
    "separately from algo containers because volume differs by orders of "
    "magnitude.",
    y,
    VS_EXC_DAILY, "VideoStream", "purple", "short", ES_VS_LINK, min_y=0,
    h=8, x=0, w=24,
)); y += 8
panels.append(exc_table(
    15,
    "VideoStream Exceptions (detailed counts)",
    "VideoStream exception counts over the selected time range. Detailed "
    "breakdown by pool and exception type.",
    y,
    VS_EXC_TABLE,
    extra_hidden=["service"],
    index_by=["site_name", "pool_name", "environment", "exception_name",
              "Value"],
)); y += 10


def query_var(name, label, query, current, description=None, refresh=1):
    v = {"name": name, "type": "query", "label": label}
    if description:
        v["description"] = description
    v.update({
        "datasource": DS,
        "definition": query,
        "query": {"query": query, "refId": "StandardVariableQuery"},
        "refresh": refresh,
        "sort": 1,
        "includeAll": True,
        "allValue": ".*",
        "multi": True,
        "current": current,
    })
    return v


ALL = {"selected": True, "text": ["All"], "value": ["$__all"]}
TEMPLATING = [
    query_var(
        "under_maintenance", "Under Maintenance",
        "label_values(swimmer_count,under_maintenance)",
        {"selected": True, "text": ["False"], "value": ["False"]},
        description="Filters non-operational pools (label on swimmer_count, "
        "no join needed). Validity and incident panels also join on "
        "cvs_maintenance_mode metric to exclude nightly clean restarts.",
    ),
    query_var(
        "pool_state", "Pool State",
        'label_values(swimmer_count{under_maintenance=~"$under_maintenance"},pool_state)',
        {"selected": True, "text": ["LIVE", "SOFT_LAUNCH"],
         "value": ["LIVE", "SOFT_LAUNCH"]},
    ),
    query_var(
        "deploy_group", "Deploy Group",
        'label_values(swimmer_count{pool_state=~"$pool_state"},group)',
        ALL, refresh=2,
    ),
    query_var(
        "server", "Server",
        'label_values(swimmer_count{pool_state=~"$pool_state", group=~"$deploy_group"},environment)',
        ALL, refresh=2,
    ),
    query_var(
        "site_name", "Site",
        'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group"},site_name)',
        ALL, refresh=2,
    ),
    query_var(
        "pool_name", "Pool",
        'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group", site_name=~"$site_name"},pool_name)',
        ALL, refresh=2,
    ),
    {
        "name": "cvs_version",
        "type": "textbox",
        "label": "CVS Version (e.g. 303 = Mar 3, -1 = all)",
        "current": {"selected": False, "text": "-1", "value": "-1"},
        "options": [{"selected": True, "text": "-1", "value": "-1"}],
    },
]

# Paths derived from this file's location so the marker + output path track
# the script if it's renamed or moved, instead of being hardcoded.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATOR_REL = pathlib.Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

dashboard = {
    "__generated_by": GENERATOR_REL,
    "__generated_warning": (
        "GENERATED FILE — do not edit by hand. Edit the generator and re-run: "
        f"python3 {GENERATOR_REL}"
    ),
    "__inputs": [],
    "__requires": [
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"}
    ],
    "id": None,
    "uid": "cvs-stability-metrics",
    "title": "CVS Stability Metrics",
    "description": "Monitor software uptime, swimmer count validity, "
                   "incidents, and algo container exceptions",
    "tags": ["cvs", "stability", "algo"],
    "schemaVersion": 36,
    "version": 1,
    "links": [],
    "timezone": "browser",
    "editable": True,
    "refresh": "1h",
    "time": {"from": "now-30d", "to": "now"},
    "templating": {"list": TEMPLATING},
    "panels": panels,
}

# Output dir is overridable via DASHBOARD_OUT_DIR so tooling
# (helpers/check_generated_dashboards.py) can regenerate into a temp dir to
# compare, without touching the committed file.
out_dir = pathlib.Path(
    os.environ.get("DASHBOARD_OUT_DIR", REPO_ROOT / "grafana/provisioning/dashboards")
)
out_dir.mkdir(parents=True, exist_ok=True)
out = str(out_dir / "cvs_stability_metrics.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print("wrote", out)
