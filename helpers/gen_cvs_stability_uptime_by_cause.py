#!/usr/bin/env python3
"""Generate grafana/provisioning/dashboards/cvs_stability_uptime_by_cause.json.

The dashboard JSON is generated — edit this script and re-run it instead of
editing the JSON by hand.

Panel ids are those of the hand-authored file this generator replaced, so
viewPanel= links keep working. Take the next free id when adding a panel;
never renumber existing ones.
"""
import json
import os
import pathlib

# The Prometheus datasource provisioned with a fixed uid in grafana/provisioning/datasources/datasource.yml.
DS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}

# Selectors for the dashboard variables. POOL works on any per-pool metric; FULL needs the labels that
# swimmer_count carries (and the cvs:swimmer_valid:bool recording rule keeps).
POOL = 'environment=~"$server", site_name=~"$site_name", pool_name=~"$pool_name"'
FULL = f'{POOL}, pool_state=~"$pool_state", group=~"$deploy_group", under_maintenance=~"$under_maintenance"'
ON_POOL = "on(pool_name, site_name, environment)"
BY_POOL = "by (pool_name, site_name, environment)"
# CVS-version filter: $cvs_version <= 0 means every version.
VERSION = "(docker_version_tag == $cvs_version or docker_version_tag * (1 - ($cvs_version > bool 0)) > 0)"

VALID = f"cvs:swimmer_valid:bool{{{FULL}}}"
SWIMMER_COUNT = f"swimmer_count{{{FULL}}}"
VALID_SAMPLES = f"({VALID} and {ON_POOL} {VERSION})"
POOL_COUNT = f"scalar(count(count {BY_POOL} ({SWIMMER_COUNT})))"

# Every camera of the pool above 0.5 fps: VideoStream's frame rate as a stand-in for camera health, used only for
# pools whose CVS image does not push cvs_camera_health_state.
CAMERAS_UP_FPS = f"(min {BY_POOL} (actual_fps{{{POOL}}}) > bool 0.5)"

EXCEPTIONS = (
    f'{POOL}, group=~"$deploy_group", under_maintenance=~"$under_maintenance", '
    'exception_name!~"NoneType|KeyboardInterrupt"'
)
EXCEPTION_POOLS = (
    'swimmer_count{environment=~"$server", pool_state=~"$pool_state", group=~"$deploy_group", '
    'under_maintenance=~"$under_maintenance"}'
)
ALGO_SERVICES = ["Detection", "Ctm", "Gtm", "DecisionEngine"]
ALGO_SERVICE_REGEX = "|".join(ALGO_SERVICES)

OPS_LINK = {
    "title": "View in OPS Dashboard",
    "url": "/d/c2e10e40-2cbb-460d-91a0-83334f641194/ops-dashboard-per-site-support"
           "?var-site_name=${__field.labels.site_name}&var-server=${__field.labels.environment}"
           "&var-pool_name=${__field.labels.pool_name}&from=${__from}&to=${__to}",
    "targetBlank": True,
}


def es_link(title, lucene_query):
    return {
        "title": title,
        "url": "https://lynxight-log-prod.kb.eu-central-1.aws.cloud.es.io/app/discover#/?"
               "_g=(time:(from:'${__from:date:iso}',to:'${__to:date:iso}'))"
               f"&_a=(query:(language:lucene,query:'{lucene_query}'))",
        "targetBlank": True,
    }


ES_ANY_LINK = es_link("Explore logs in Elasticsearch", "*")
ES_ALGO_LINK = es_link(
    "View algo service logs in Elasticsearch",
    "container.labels.com_docker_compose_service:(detection OR ctm OR gtm OR decision_engine)",
)
ES_VIDEO_STREAM_LINK = es_link(
    "View video_stream logs in Elasticsearch", "container.labels.com_docker_compose_service:video_stream")
ES_EXCEPTION_LINK = es_link(
    "View logs for this exception in Elasticsearch",
    'host.name:"${__data.fields.environment}" AND '
    "container.name:*_${__data.fields.site_name}_${__data.fields.pool_name}* "
    "AND json.level:ERROR AND json.message:*${__data.fields.exception_name}*",
)

RED_YELLOW_GREEN_80_95 = [("red", None), ("yellow", 80), ("green", 95)]


def grid(x, y, w, h):
    return {"h": h, "w": w, "x": x, "y": y}


def target(ref, expr, legend, **extra):
    return {"datasource": DS, "editorMode": "code", "expr": expr, "legendFormat": legend, "refId": ref, **extra}


def thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": color, "value": value} for color, value in steps]}


def hide(field_name):
    return {"matcher": {"id": "byName", "options": field_name}, "properties": [{"id": "custom.hidden", "value": True}]}


def rename(field_name, display_name, *properties):
    return {
        "matcher": {"id": "byName", "options": field_name},
        "properties": [{"id": "displayName", "value": display_name}, *properties],
    }


def fixed_color(field_name, color):
    return {
        "matcher": {"id": "byName", "options": field_name},
        "properties": [{"id": "color", "value": {"fixedColor": color, "mode": "fixed"}}],
    }


def row(pid, title, y, collapsed_panels=None):
    """A row; given collapsed_panels it starts collapsed, holding them, and Grafana queries them only when opened."""
    if collapsed_panels is None:
        return {"id": pid, "type": "row", "title": title, "gridPos": grid(0, y, 24, 1), "collapsed": False}
    return {"id": pid, "type": "row", "title": title, "gridPos": grid(0, y, 24, 1), "collapsed": True,
            "panels": collapsed_panels}


def per_pool_bargauge(pid, title, description, grid_pos, overall_expr, per_pool_expr, defaults, options=None):
    """A bar per pool, linking to the OPS dashboard of the clicked pool, plus a white OVERALL AVERAGE bar unless
    overall_expr is None."""
    overall_targets = [] if overall_expr is None else [target("A", overall_expr, "OVERALL AVERAGE", instant=True)]
    return {
        "id": pid, "type": "bargauge", "title": title, "description": description, "datasource": DS,
        "gridPos": grid_pos,
        "targets": [
            *overall_targets,
            target("B", per_pool_expr, "{{site_name}} / {{pool_name}}", instant=True),
        ],
        "fieldConfig": {
            "defaults": {**defaults, "links": [OPS_LINK]},
            "overrides": [] if overall_expr is None else [fixed_color("OVERALL AVERAGE", "white")],
        },
        "options": {
            "orientation": "horizontal", "displayMode": "gradient",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "showUnfilled": True,
            **(options or {}),
        },
    }


BAR_SIZES = {"minVizWidth": 8, "minVizHeight": 16}
TABLE_LEGEND = {"displayMode": "table", "placement": "bottom", "showLegend": True, "calcs": ["mean", "lastNotNull"]}
MULTI_TOOLTIP = {"mode": "multi", "sort": "desc"}


def daily_trend(pid, title, description, grid_pos, expr, legend, color, unit, link, minimum=None):
    """One daily point per day, drawn as a line with markers."""
    defaults = {
        "color": color,
        "custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 10, "pointSize": 8, "showPoints": "always",
                   "lineInterpolation": "linear"},
        "unit": unit,
    }
    if minimum is not None:
        defaults["min"] = minimum
    defaults["links"] = [link]
    return {
        "id": pid, "type": "timeseries", "title": title, "description": description, "datasource": DS,
        "gridPos": grid_pos,
        "targets": [target("A", expr, legend, range=True, interval="1d")],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": TABLE_LEGEND, "tooltip": MULTI_TOOLTIP},
    }


def exception_table(pid, title, description, grid_pos, expr, legend, hidden_label_names, column_order):
    return {
        "id": pid, "type": "table", "title": title, "description": description, "datasource": DS,
        "gridPos": grid_pos,
        "targets": [target("A", expr, legend, instant=True, format="table")],
        "fieldConfig": {
            "defaults": {"custom": {"filterable": True}, "links": [ES_EXCEPTION_LINK]},
            "overrides": [
                *[hide(label_name) for label_name in
                  ["Time", "__name__", "job", "name", "group", "under_maintenance", *hidden_label_names]],
                rename("environment", "server"),
                rename("Value", "Count"),
            ],
        },
        "transformations": [{"id": "organize", "options": {"indexByName": {
            column_name: index for index, column_name in enumerate(column_order)}}}],
        "options": {"showHeader": True, "sortBy": [
            {"displayName": "Count", "desc": True},
            {"displayName": "site_name", "desc": False},
            {"displayName": "pool_name", "desc": False},
        ]},
    }


# --- Uptime by cause: camera/LAN, host absence, heat (AT-1667) -----------------------------------------------
# https://lynxight.atlassian.net/browse/AT-1667

ON_CAMERA = "on(pool_name, site_name, environment, camera_id)"
# SystemHealthService pushes it once a minute: 0 fine, 1 ping but no video, 2 no ping.
CAMERA_HEALTH = f"cvs_camera_health_state{{{POOL}}}"
CAMERA_HEALTH_PUSH_TIME = f'push_time_seconds{{name="cvs_camera_health_state", {POOL}}}'

# The camera reports 1 or 2 between one minute before and three minutes after the sample, in a report that was
# renewed in that window: the first probe comes a minute or two after the pool stops, and the pushgateway keeps a
# stopped health service's last value, which is unknown, not a camera fault.
CAMERA_FAULT_REPORTED = (
    f"((max_over_time({CAMERA_HEALTH}[4m] offset -3m) > 0) "
    f"and {ON_CAMERA} (changes({CAMERA_HEALTH_PUSH_TIME}[6m] offset -3m) > 0))"
)
POOL_CAMERA_FAULT_REPORTED = f"max {BY_POOL} ({CAMERA_FAULT_REPORTED})"
# Pools whose CVS image has no camera health gauge: a camera below 0.5 fps.
POOL_CAMERA_FAULT_BY_FPS = f"({CAMERAS_UP_FPS} == 0) unless {ON_POOL} {CAMERA_HEALTH}"
POOL_CAMERA_FAULT = f"({POOL_CAMERA_FAULT_REPORTED} or {POOL_CAMERA_FAULT_BY_FPS})"
# The validity samples that remain once the invalid ones with a camera/LAN fault are taken out.
VALID_WITHOUT_CAMERA_TIME = (
    f"(({VALID} unless {ON_POOL} ({POOL_CAMERA_FAULT} and {ON_POOL} ({VALID} == 0))) and {ON_POOL} {VERSION})"
)
# 1 for an invalid sample with a camera/LAN fault, 0 for every other validity sample.
CAMERA_DOWNTIME = (
    f"(((({VALID} == bool 0) and {ON_POOL} {POOL_CAMERA_FAULT}) or ({VALID} * 0)) and {ON_POOL} {VERSION})"
)

HOST = 'environment=~"$server", group=~"$deploy_group"'
BOOT_TIME = f'node_boot_time_seconds{{job="nodeexporter", {HOST}}}'
# Absence is counted against the 5-minute steps in which the cloud had a sample from any host, not against the
# length of the range: a range that ends in the future, or a gap in the cloud's own data, would otherwise count as
# absence of every host. The fleet count ignores the dashboard's filters, so a filter that selects only an absent
# host still has steps to count against. The 5-minute grid keeps the nightly monitoring restart and other gaps
# under 5 minutes out. A host's presence is counted per host, not per series: when a label of its boot-time series
# changes, each series covers only part of the range, and taking the worst series would read as near-total absence.
FLEET_BOOT_TIME = 'node_boot_time_seconds{job="nodeexporter"}'
HOST_ABSENT = (
    f"clamp_min(1 - count_over_time((count by (environment) ({BOOT_TIME}))[$__range:5m]) "
    f"/ scalar(count_over_time(count({FLEET_BOOT_TIME})[$__range:5m])), 0) * 100"
)
# The boot time also moves by seconds when the clock is stepped; a reboot moves it by more than 2 minutes.
HOST_REBOOTS = (
    f"max by (environment) (sum_over_time((({BOOT_TIME} - last_over_time({BOOT_TIME}[1d] offset 5m)) > bool 120)"
    f"[$__range:5m]))"
)
CPU_SENSOR_TEMPERATURE = f'node_hwmon_temp_celsius{{job="nodeexporter", chip=~"platform_coretemp_.*", {HOST}}}'
CPU_TEMPERATURE = f"max by (environment) ({CPU_SENSOR_TEMPERATURE})"
# Each CPU sensor's own over-limit flag (1 at or above the chip's critical temperature). A share of time at the limit
# separates a host that runs hot from a busy one: the hottest reading of a week reaches the limit on any busy host,
# and limits differ between chips.
CPU_CRIT_ALARM = f'node_hwmon_temp_crit_alarm_celsius{{job="nodeexporter", chip=~"platform_coretemp_.*", {HOST}}}'
CPU_AT_LIMIT_PERCENT = f"avg_over_time((max by (environment) ({CPU_CRIT_ALARM}))[$__range:5m]) * 100"
THROTTLES = f'node_cpu_package_throttles_total{{job="nodeexporter_lowfreq", {HOST}}}'
# The share of 5-minute steps in which the package throttle counter rose. A count of throttle events runs into the
# millions on a hot host and cannot be compared between hosts.
CPU_THROTTLING_PERCENT = (
    f"avg_over_time((sum by (environment) (increase({THROTTLES}[5m])) > bool 0)[$__range:5m]) * 100"
)
# The host panels show the servers that had a pool passing the dashboard's filters in some hour of the range, so a
# host that went silent before the end of the range keeps its row; joining on the current sample would drop it.
SELECTED_POOL_HOSTS = f"group by (environment) (max_over_time({SWIMMER_COUNT}[$__range:1h]))"
# The same for each point of a time series, over the day before it: the set of pools passing the filters changes
# during the day, and joining on each point's own sample would cut a host's line whenever it shrinks.
SELECTED_POOL_HOSTS_DAY = f"group by (environment) (max_over_time({SWIMMER_COUNT}[1d:1h]))"


validity_without_camera_time = per_pool_bargauge(
    23, "% Time with Valid Swimmer Count, camera/LAN time removed (per pool)",
    "The validity number of the 'Swimmer Count Validity' row with camera/LAN time taken out: invalid time during "
    "which a camera of the pool reported 'ping but no video' or 'no ping' (cvs_camera_health_state 1 or 2) is "
    "removed from the range, and validity is the valid share of what remains. Read it next to '% Time with Valid "
    "Swimmer Count', which counts every cause; the gap between the two is camera/LAN downtime. "
    "A camera report counts when it was renewed between one minute before and three minutes after the sample, "
    "because the first probe comes a minute or two after the pool stops; a frozen report is unknown and removes "
    "nothing. Outages shorter than 45 s are never probed and stay in the number. Validity is read on a 5-minute "
    "grid, so an outage shorter than 5 minutes can be missed in both directions. Pools whose CVS image does not "
    "push the gauge use the frame-rate rule instead (a camera below 0.5 fps). No bar = the pool was camera/LAN-down "
    "for the whole range. The newest three minutes are not yet attributed. The fleet average is the 'Validity % "
    "(camera/LAN time removed)' line of the daily trend beside this panel; it has no bar here because each "
    "query of this expression is slow on the production Prometheus.",
    grid(0, 1, 12, 12),
    None,
    f"sort(avg_over_time({VALID_WITHOUT_CAMERA_TIME}[$__range:5m]) * 100)",
    {"color": {"mode": "continuous-RdYlGr"}, "thresholds": thresholds(RED_YELLOW_GREEN_80_95), "unit": "percent",
     "decimals": 1, "min": 0, "max": 100},
    BAR_SIZES,
)

validity_by_cause_trend = {
    "id": 24, "type": "timeseries",
    "title": "Daily Trend: Validity counting every cause vs camera/LAN time removed (overall avg)",
    "description": "Daily overall averages. 'Validity % (every cause)' is the swimmer-count validity. 'Validity % "
                   "(camera/LAN time removed)' is the same number once invalid time with a camera/LAN fault is taken "
                   "out of the day. 'Camera/LAN downtime %' is the share of the day that was taken out.",
    "datasource": DS, "gridPos": grid(12, 1, 12, 12),
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "line", "fillOpacity": 0, "lineInterpolation": "linear", "lineWidth": 2,
                       "pointSize": 6, "showPoints": "always"},
            "unit": "percent",
        },
        "overrides": [
            fixed_color("Validity % (every cause)", "green"),
            fixed_color("Validity % (camera/LAN time removed)", "blue"),
            fixed_color("Camera/LAN downtime %", "orange"),
        ],
    },
    "options": {"legend": TABLE_LEGEND, "tooltip": MULTI_TOOLTIP},
    "targets": [
        target("A", f"avg(avg_over_time({VALID_SAMPLES}[1d:5m]) * 100)", "Validity % (every cause)",
               interval="1d", range=True),
        target("B", f"avg(avg_over_time({VALID_WITHOUT_CAMERA_TIME}[1d:5m]) * 100)",
               "Validity % (camera/LAN time removed)", interval="1d", range=True),
        target("C", f"avg(avg_over_time({CAMERA_DOWNTIME}[1d:5m]) * 100)", "Camera/LAN downtime %",
               interval="1d", range=True),
    ],
}

hosts_table = {
    "id": 26, "type": "table", "title": "Hosts: absence, reboots, heat (per server)",
    "description": "Per server with a pool that passes the dashboard's filters in some hour of the selected range, over that range. 'absent %' = share of the 5-minute steps of the range in which "
                   "the cloud had node-exporter samples from some host but none from this one (so the future part "
                   "of the range and gaps in the cloud's own data do not count, nor do the nightly monitoring "
                   "restart and gaps under 5 minutes; internet and power/host outages are not told apart here, and "
                   "a host silent for the whole range has no row). 'reboots' = times the boot time moved by more "
                   "than 2 minutes. '% time at CPU limit' = share of the range in which a CPU sensor was at or "
                   "above its chip's critical temperature (the sensor's own alarm flag; blank = the host does not "
                   "report it). '% time throttling' = share of the range in which the CPU package was "
                   "thermal-throttled. Both are read on a 5-minute grid. 'lowest pool validity %' = the "
                   "swimmer-count validity of the host's worst selected pool. Sort by heat or throttling to see "
                   "whether downtime follows heat.",
    "datasource": DS, "gridPos": grid(0, 13, 24, 11),
    "fieldConfig": {
        "defaults": {"custom": {"filterable": True}, "decimals": 1},
        "overrides": [
            hide("Time"),
            rename("environment", "server"),
            rename("Value #A", "absent %", {"id": "unit", "value": "percent"}),
            rename("Value #B", "reboots", {"id": "decimals", "value": 0}),
            rename("Value #C", "% time at CPU limit", {"id": "unit", "value": "percent"}),
            rename("Value #D", "% time throttling", {"id": "unit", "value": "percent"}),
            rename("Value #E", "lowest pool validity %", {"id": "unit", "value": "percent"}),
        ],
    },
    "options": {"showHeader": True, "sortBy": [{"desc": True, "displayName": "absent %"}]},
    "targets": [
        target("A", f"{HOST_ABSENT} and on(environment) {SELECTED_POOL_HOSTS}", "", format="table", instant=True),
        target("B", f"{HOST_REBOOTS} and on(environment) {SELECTED_POOL_HOSTS}", "", format="table", instant=True),
        target("C", f"{CPU_AT_LIMIT_PERCENT} and on(environment) {SELECTED_POOL_HOSTS}", "", format="table",
               instant=True),
        target("D", f"{CPU_THROTTLING_PERCENT} and on(environment) {SELECTED_POOL_HOSTS}", "", format="table",
               instant=True),
        target("E", f"min by (environment) (avg_over_time({VALID_SAMPLES}[$__range:5m]) * 100)", "",
               format="table", instant=True),
    ],
    "transformations": [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {"indexByName": {
            "environment": 0, "Value #A": 1, "Value #B": 2, "Value #C": 3, "Value #D": 4, "Value #E": 5}}},
    ],
}

LINES_NO_POINTS = {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "never"}

host_heat = {
    "id": 27, "type": "timeseries",
    "title": "Host heat over time: hottest CPU sensor and throttling (per server)",
    "description": "Hottest CPU sensor of each selected server (left axis) and its CPU package thermal-throttle "
                   "events per 10 minutes (right axis, bars). Narrow the Server filter and compare with the validity "
                   "panel beside it.",
    "datasource": DS, "gridPos": grid(0, 25, 12, 9),
    "fieldConfig": {
        "defaults": {"color": {"mode": "palette-classic"}, "custom": LINES_NO_POINTS, "unit": "celsius"},
        "overrides": [{
            "matcher": {"id": "byFrameRefID", "options": "B"},
            "properties": [
                {"id": "unit", "value": "short"},
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "custom.drawStyle", "value": "bars"},
                {"id": "custom.fillOpacity", "value": 40},
            ],
        }],
    },
    "options": {"legend": {"calcs": ["max"], "displayMode": "table", "placement": "bottom", "showLegend": True},
                "tooltip": MULTI_TOOLTIP},
    "targets": [
        target("A", f"{CPU_TEMPERATURE} and on(environment) {SELECTED_POOL_HOSTS_DAY}", "{{environment}} \u00b0C",
               range=True),
        target("B", f"sum by (environment) (increase({THROTTLES}[10m])) and on(environment) {SELECTED_POOL_HOSTS_DAY}",
               "{{environment}} throttle events",
               interval="10m", range=True),
    ],
}

pool_validity_over_time = {
    "id": 28, "type": "timeseries", "title": "Pool validity over time (per pool, 15-minute average)",
    "description": "Swimmer-count validity of each selected pool, averaged over 15 minutes, on the same time axis as "
                   "the heat panel beside it. A gap = the pool was under maintenance or its host was absent.",
    "datasource": DS, "gridPos": grid(12, 25, 12, 9),
    "fieldConfig": {
        "defaults": {"color": {"mode": "palette-classic"}, "custom": LINES_NO_POINTS, "unit": "percent",
                     "min": 0, "max": 100},
        "overrides": [],
    },
    "options": {"legend": {"calcs": ["mean"], "displayMode": "table", "placement": "bottom", "showLegend": True},
                "tooltip": {"mode": "multi", "sort": "asc"}},
    "targets": [target("A", f"avg_over_time({VALID}[15m]) * 100 and {ON_POOL} {VERSION}",
                       "{{site_name}} / {{pool_name}}", interval="15m", range=True)],
}

UPTIME_BY_CAUSE_ROW_HEIGHT = 25
# The Cameras vs Software row is collapsed, so the rows below it start right after its header.
SWIMMER_COUNT_VALIDITY_Y = UPTIME_BY_CAUSE_ROW_HEIGHT + 1

# --- Availability Breakdown: Cameras vs Software --------------------------------------------------------------
# A camera counts as down by the same rule as in the panels above (POOL_CAMERA_FAULT), so the dashboard has one
# definition of a camera/LAN fault. A camera that delivers no frames because our software is down is not down.

# 1 for a pool with no camera/LAN fault, 0 for a pool with one.
POOL_CAMERAS_UP = (
    f"(((count {BY_POOL} ({SWIMMER_COUNT}) * 0 + 1) unless {ON_POOL} {POOL_CAMERA_FAULT}) "
    f"or (count {BY_POOL} ({SWIMMER_COUNT}) * 0))"
)
CAMERAS_UP_SAMPLES = (
    f"(({POOL_CAMERAS_UP} and {ON_POOL} (cvs_maintenance_mode == 0)) and {ON_POOL} {SWIMMER_COUNT} "
    f"and {ON_POOL} {VERSION})"
)
VALID_WHILE_CAMERAS_UP = f"(({VALID} and {ON_POOL} ({POOL_CAMERAS_UP} == 1)) and {ON_POOL} {VERSION})"


def software_uptime(aggregation, subquery):
    """Valid samples while every camera was up, as a share of the samples in which every camera was up."""
    return (
        f"clamp_max({aggregation}(sum_over_time({VALID_WHILE_CAMERAS_UP}[{subquery}])) "
        f"/ {aggregation}(sum_over_time({CAMERAS_UP_SAMPLES}[{subquery}])) * 100, 100)"
    )


camera_availability = per_pool_bargauge(
    16, "% Camera Availability (per pool, no camera/LAN fault, excluding nightly restart)",
    "Percentage of the selected range during which no camera of the pool had a camera/LAN fault, by the same rule "
    "as the panels above: a camera reported 'ping but no video' or 'no ping' (cvs_camera_health_state 1 or 2), or, "
    "for pools whose CVS image does not push the gauge, a camera below 0.5 fps. Evaluated on a 15m grid; any single "
    "faulty camera counts the whole pool as down, because the synchronizer cannot form frame sets without it. A "
    "camera that delivers no frames because our software is down is not a camera fault. Planned maintenance "
    "windows (cvs_maintenance_mode=1) are excluded. Compare with the validity gauge below: when the two match, the "
    "invalid time is camera connectivity, not software.",
    grid(0, UPTIME_BY_CAUSE_ROW_HEIGHT + 1, 12, 10),
    f"avg(avg_over_time({CAMERAS_UP_SAMPLES}[$__range:15m]) * 100)",
    f"sort(avg_over_time({CAMERAS_UP_SAMPLES}[$__range:15m]) * 100)",
    {"color": {"mode": "continuous-RdYlGr"}, "decimals": 2, "max": 100, "min": 0,
     "thresholds": thresholds(RED_YELLOW_GREEN_80_95), "unit": "percent"},
    BAR_SIZES,
)

software_uptime_gauge = per_pool_bargauge(
    17, "% Software Uptime excluding camera issues (per pool)",
    "Of the time no camera of the pool had a camera/LAN fault (see the camera availability gauge), the percentage "
    "during which the pipeline produced a valid swimmer count (validity samples taken only while the cameras were "
    "up, divided by the cameras-up samples, both on a 15m grid). This isolates software / host faults (algo "
    "container crashes, GPU, stalls) from camera connectivity. Blank or NaN = the cameras were never all up in the "
    "selected range, so software uptime is undefined for that pool. Planned maintenance windows are excluded.",
    grid(12, UPTIME_BY_CAUSE_ROW_HEIGHT + 1, 12, 10),
    software_uptime("sum", "$__range:15m"),
    f"sort({software_uptime(f'sum {BY_POOL} ', '$__range:15m')})",
    {"color": {"mode": "continuous-RdYlGr"}, "decimals": 2, "max": 100, "min": 0,
     "thresholds": thresholds([("red", None), ("yellow", 98), ("green", 99.5)]), "unit": "percent",
     "mappings": [{"type": "special", "options": {
         "match": "nan", "result": {"text": "cameras never all up in range", "color": "transparent"}}}]},
    BAR_SIZES,
)

VALIDITY_DAILY = f"avg(avg_over_time({VALID}[1d]) * 100 and on(pool_name, site_name) {VERSION})"

availability_trend = {
    "id": 18, "type": "timeseries",
    "title": "Daily Trend: Validity vs Camera Availability vs Software Uptime (overall avg)",
    "description": "Daily overall averages, side by side: swimmer-count validity (share of the day with a valid "
                   "swimmer count), camera availability (no camera/LAN fault, by the rule of the panels above), and "
                   "software uptime measured only while the cameras were up. The gap between validity and camera availability is camera "
                   "connectivity; the gap between 100% and software uptime is ours.",
    "datasource": DS, "gridPos": grid(0, UPTIME_BY_CAUSE_ROW_HEIGHT + 11, 24, 8),
    "targets": [
        target("A", VALIDITY_DAILY, "Validity %", interval="1d", range=True),
        target("B", f"avg(avg_over_time({CAMERAS_UP_SAMPLES}[1d:15m]) * 100)", "Camera availability %",
               interval="1d", range=True),
        target("C", software_uptime("sum", "1d:15m"), "Software uptime % (cameras up)", interval="1d", range=True),
    ],
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "line", "fillOpacity": 0, "lineInterpolation": "linear", "lineWidth": 2,
                       "pointSize": 6, "showPoints": "always"},
            "unit": "percent",
        },
        "overrides": [
            fixed_color("Validity %", "green"),
            fixed_color("Camera availability %", "orange"),
            fixed_color("Software uptime % (cameras up)", "blue"),
        ],
    },
    "options": {"legend": TABLE_LEGEND, "tooltip": MULTI_TOOLTIP},
}

ACTUAL_FPS = f"actual_fps{{{POOL}}}"
# Cameras whose CVS image has no health gauge: below 0.5 fps.
CAMERA_FAULT_BY_FPS = f"(({ACTUAL_FPS} <= 0.5) unless {ON_CAMERA} {CAMERA_HEALTH})"
# 1 for a camera with no camera/LAN fault, 0 for one with a fault; one row per camera VideoStream reports.
CAMERA_UP = (
    f"((({ACTUAL_FPS} * 0 + 1) unless {ON_CAMERA} ({CAMERA_FAULT_REPORTED} or {CAMERA_FAULT_BY_FPS})) "
    f"or ({ACTUAL_FPS} * 0))"
)
CAMERA_UP_SAMPLES = f"({CAMERA_UP} and {ON_POOL} {SWIMMER_COUNT} and {ON_POOL} {VERSION})"
cameras_below_99 = {
    "id": 19, "type": "table", "title": "Cameras below 99% availability (per camera)",
    "description": "Individual cameras without a camera/LAN fault for less than 99% of the selected range, by the "
                   "rule of the camera availability gauge applied to each camera (raw per-camera availability, not "
                   "maintenance-gated, 15m grid). Use it to find WHICH camera is dragging a pool down in the gauges "
                   "above.",
    "datasource": DS, "gridPos": grid(0, UPTIME_BY_CAUSE_ROW_HEIGHT + 19, 24, 8),
    "targets": [target(
        "A", f"sort(avg_over_time({CAMERA_UP_SAMPLES}[$__range:15m]) * 100) < 99",
        "{{site_name}} / {{pool_name}} / cam {{camera_id}}", format="table", instant=True)],
    "fieldConfig": {
        "defaults": {"custom": {"filterable": True}, "decimals": 1, "unit": "percent",
                     "thresholds": thresholds(RED_YELLOW_GREEN_80_95)},
        "overrides": [
            *[hide(label_name) for label_name in ["Time", "__name__", "job", "name", "group"]],
            rename("environment", "server"),
            rename("Value", "% time without camera/LAN fault", {"id": "custom.cellOptions", "value": {"type": "color-background"}}),
        ],
    },
    "transformations": [{"id": "organize", "options": {"indexByName": {
        "site_name": 0, "pool_name": 1, "environment": 2, "camera_id": 3, "Value": 4}}}],
    "options": {"showHeader": True, "sortBy": [{"desc": False, "displayName": "% time without camera/LAN fault"}]},
}

# --- Swimmer Count Validity -----------------------------------------------------------------------------------

validity_gauge = per_pool_bargauge(
    3, "% Time with Valid Swimmer Count (per pool, excluding nightly restart)",
    "Percentage of time each pool had a valid swimmer count over the selected time range. Planned maintenance "
    "windows (nightly restart / clean stop, cvs_maintenance_mode=1) are excluded via the cvs:swimmer_valid:bool "
    "recording rule. Lower = less stable.",
    grid(0, SWIMMER_COUNT_VALIDITY_Y + 1, 12, 10),
    f"avg(avg_over_time({VALID_SAMPLES}[$__range:5m]) * 100)",
    f"sort(avg_over_time({VALID_SAMPLES}[$__range:5m]) * 100)",
    {"color": {"mode": "continuous-RdYlGr"}, "thresholds": thresholds(RED_YELLOW_GREEN_80_95), "unit": "percent",
     "decimals": 1, "min": 0, "max": 100},
    BAR_SIZES,
)

validity_trend = daily_trend(
    4, "Daily Trend: Validity % (overall avg)", "Daily overall average of swimmer count validity percentage.",
    grid(12, SWIMMER_COUNT_VALIDITY_Y + 1, 12, 10), VALIDITY_DAILY, "Validity %", {"mode": "fixed", "fixedColor": "green"}, "percent",
    ES_ANY_LINK,
)

# --- Invalid Swimmer Count Incidents --------------------------------------------------------------------------

INCIDENTS = f"ceil(sum_over_time((changes({VALID}[5m]) and {ON_POOL} {VERSION})[$__range:5m]) / 2)"
incidents_gauge = per_pool_bargauge(
    6, "Estimated Incidents (per pool)",
    "Estimated number of validity state transitions per pool (valid↔invalid) over the selected range, divided "
    "by 2. Excludes non-operational pools (under_maintenance) and nightly clean restarts (cvs_maintenance_mode).",
    grid(0, SWIMMER_COUNT_VALIDITY_Y + 12, 12, 8),
    f"avg({INCIDENTS})",
    f"sort_desc({INCIDENTS})",
    {"color": {"mode": "continuous-BlYlRd"},
     "thresholds": thresholds([("green", None), ("yellow", 10), ("red", 50)]), "unit": "short"},
)

incidents_trend = daily_trend(
    7, "Daily Trend: Avg Incidents per Pool (overall avg)",
    "Daily overall average of invalid swimmer count incidents per pool. Excludes non-operational pools "
    "(under_maintenance) and nightly clean restarts (cvs_maintenance_mode).",
    grid(12, SWIMMER_COUNT_VALIDITY_Y + 12, 12, 8),
    f"avg(ceil(changes({VALID}[1d]) / 2) and on(pool_name, site_name) {VERSION})",
    "Incidents", {"mode": "fixed", "fixedColor": "orange"}, "short", ES_ANY_LINK, minimum=0,
)

# --- Algo Container Exceptions --------------------------------------------------------------------------------


def service_exceptions_per_pool(service_name):
    """Average exceptions of one algo service per pool, or 0 so the service keeps its bar."""
    exceptions = f'cvs_exc_per_service{{{EXCEPTIONS}, service="{service_name}"}}'
    return (
        f"(sum by (service) (sum_over_time((increase({exceptions}[1h]) and {ON_POOL} {VERSION})[$__range:1h]) "
        f"and {ON_POOL} {EXCEPTION_POOLS}) / {POOL_COUNT} "
        f'or label_replace(vector(0), "service", "{service_name}", "", ""))'
    )


ALGO_EXCEPTIONS = f'cvs_exc_per_service{{{EXCEPTIONS}, service=~"{ALGO_SERVICE_REGEX}"}}'

algo_exceptions_per_container = {
    "id": 11, "type": "barchart", "title": "Avg Exceptions per Pool by Algo Container",
    "description": "Average exception count per pool, grouped by algo container. Shows the mean across all matching "
                   "pools.",
    "datasource": DS, "gridPos": grid(0, SWIMMER_COUNT_VALIDITY_Y + 21, 12, 8),
    "targets": [target("A", " or ".join(service_exceptions_per_pool(service_name) for service_name in ALGO_SERVICES),
                       "{{service}}", instant=True)],
    "fieldConfig": {
        "defaults": {"color": {"mode": "palette-classic"}, "unit": "short", "links": [ES_ALGO_LINK]},
        "overrides": [{"matcher": {"id": "byName", "options": "Time"}, "properties": [
            {"id": "custom.hideFrom", "value": {"legend": True, "tooltip": True, "viz": True}}]}],
    },
    "options": {"orientation": "horizontal", "showValue": "always", "barWidth": 0.8, "groupWidth": 0.7},
}

algo_exceptions_trend = {
    **daily_trend(
        12, "Daily Trend: Avg Exceptions per Pool by Container",
        "Daily overall average of algo container exception counts per pool, grouped by service.",
        grid(12, SWIMMER_COUNT_VALIDITY_Y + 21, 12, 8),
        f"sum by (service) (increase({ALGO_EXCEPTIONS}[1d]) and {ON_POOL} {EXCEPTION_POOLS} "
        f"and on(pool_name, site_name) {VERSION}) / {POOL_COUNT}",
        "{{service}}", {"mode": "palette-classic"}, "short", ES_ALGO_LINK,
    ),
}


def exception_counts(exceptions):
    return (
        f"(round(sum_over_time((increase({exceptions}[1h]) and {ON_POOL} {VERSION})[$__range:1h])) "
        f"and {ON_POOL} {EXCEPTION_POOLS}) > 0"
    )


algo_exceptions_table = exception_table(
    9, "Algo Exceptions (detailed counts)",
    "Exception counts for algo containers (Detection, Ctm, Gtm, DecisionEngine) over the selected time range. "
    "Detailed breakdown by pool, service, and exception type.",
    grid(0, SWIMMER_COUNT_VALIDITY_Y + 29, 24, 10), exception_counts(ALGO_EXCEPTIONS),
    "{{site_name}} / {{pool_name}} / {{service}} ({{exception_name}})",
    [], ["site_name", "pool_name", "environment", "service", "exception_name", "Value"],
)

# --- VideoStream Exceptions -----------------------------------------------------------------------------------

VIDEO_STREAM_EXCEPTIONS = f'cvs_exc_per_service{{{EXCEPTIONS}, service="VideoStream"}}'

video_stream_exceptions_trend = daily_trend(
    14, "Daily Trend: Avg VideoStream Exceptions per Pool",
    "Daily overall average of VideoStream exception counts per pool. Tracked separately from algo containers "
    "because volume differs by orders of magnitude.",
    grid(0, SWIMMER_COUNT_VALIDITY_Y + 40, 24, 8),
    f"sum(increase({VIDEO_STREAM_EXCEPTIONS}[1d]) and {ON_POOL} {EXCEPTION_POOLS} "
    f"and on(pool_name, site_name) {VERSION}) / {POOL_COUNT}",
    "VideoStream", {"mode": "fixed", "fixedColor": "purple"}, "short", ES_VIDEO_STREAM_LINK, minimum=0,
)

video_stream_exceptions_table = exception_table(
    15, "VideoStream Exceptions (detailed counts)",
    "VideoStream exception counts over the selected time range. Detailed breakdown by pool and exception type.",
    grid(0, SWIMMER_COUNT_VALIDITY_Y + 48, 24, 10), exception_counts(VIDEO_STREAM_EXCEPTIONS),
    "{{site_name}} / {{pool_name}} ({{exception_name}})",
    ["service"], ["site_name", "pool_name", "environment", "exception_name", "Value"],
)

PANELS = [
    row(22, "Uptime by cause: camera/LAN, host absence, heat", 0),
    validity_without_camera_time, validity_by_cause_trend, hosts_table,
    row(29, "Heat and pool validity over time", 24, [host_heat, pool_validity_over_time]),
    row(20, "Availability Breakdown: Cameras vs Software", UPTIME_BY_CAUSE_ROW_HEIGHT + 0,
        [camera_availability, software_uptime_gauge, availability_trend, cameras_below_99]),
    row(1, "Swimmer Count Validity", SWIMMER_COUNT_VALIDITY_Y),
    validity_gauge, validity_trend,
    row(5, "Invalid Swimmer Count Incidents", SWIMMER_COUNT_VALIDITY_Y + 11),
    incidents_gauge, incidents_trend,
    row(8, "Algo Container Exceptions", SWIMMER_COUNT_VALIDITY_Y + 20),
    algo_exceptions_per_container, algo_exceptions_trend, algo_exceptions_table,
    row(13, "VideoStream Exceptions", SWIMMER_COUNT_VALIDITY_Y + 39),
    video_stream_exceptions_trend, video_stream_exceptions_table,
]

# --- Variables ------------------------------------------------------------------------------------------------

ALL = {"selected": True, "text": ["All"], "value": ["$__all"]}


def query_variable(name, label, query, current, refresh, description=None):
    variable = {"name": name, "type": "query", "label": label}
    if description is not None:
        variable["description"] = description
    variable.update({
        "datasource": DS, "definition": query, "query": {"query": query, "refId": "StandardVariableQuery"},
        "refresh": refresh, "sort": 1, "includeAll": True, "allValue": ".*", "multi": True, "current": current,
    })
    return variable


TEMPLATING = {"list": [
    query_variable(
        "under_maintenance", "Under Maintenance", "label_values(swimmer_count,under_maintenance)",
        {"selected": True, "text": ["False"], "value": ["False"]}, 1,
        description="Filters non-operational pools (label on swimmer_count, no join needed). Validity and incident "
                    "panels also join on cvs_maintenance_mode metric to exclude nightly clean restarts."),
    query_variable(
        "pool_state", "Pool State", 'label_values(swimmer_count{under_maintenance=~"$under_maintenance"},pool_state)',
        {"selected": True, "text": ["LIVE", "SOFT_LAUNCH"], "value": ["LIVE", "SOFT_LAUNCH"]}, 1),
    query_variable(
        "deploy_group", "Deploy Group", 'label_values(swimmer_count{pool_state=~"$pool_state"},group)', ALL, 2),
    query_variable(
        "server", "Server",
        'label_values(swimmer_count{pool_state=~"$pool_state", group=~"$deploy_group"},environment)', ALL, 2),
    query_variable(
        "site_name", "Site",
        'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group"},'
        'site_name)', ALL, 2),
    query_variable(
        "pool_name", "Pool",
        'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group", '
        'site_name=~"$site_name"},pool_name)', ALL, 2),
    {"name": "cvs_version", "type": "textbox", "label": "CVS Version (e.g. 303 = Mar 3, -1 = all)",
     "current": {"selected": False, "text": "-1", "value": "-1"},
     "options": [{"selected": True, "text": "-1", "value": "-1"}]},
]}

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATOR_REL = pathlib.Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

dashboard = {
    "__generated_by": GENERATOR_REL,
    "__generated_warning": f"GENERATED FILE — do not edit by hand. Edit the generator and re-run: python3 {GENERATOR_REL}",
    "__inputs": [],
    "__requires": [{"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"}],
    "id": None,
    "uid": "cvs-stability-uptime-by-cause",
    "title": "CVS Stability Metrics — Uptime by Cause",
    "description": "Monitor swimmer count validity counting every cause and with camera/LAN time removed, camera "
                   "health tested on the camera itself, host absence, reboots and heat, incidents, and algo "
                   "container exceptions",
    "tags": ["cvs", "stability", "algo"],
    "schemaVersion": 36,
    "version": 1,
    "links": [],
    "timezone": "browser",
    "editable": True,
    "refresh": "1h",
    "time": {"from": "now-7d", "to": "now"},
    "templating": TEMPLATING,
    "panels": PANELS,
}

# Output dir is overridable via DASHBOARD_OUT_DIR so tooling
# (helpers/check_generated_dashboards.py) can regenerate into a temp dir to
# compare, without touching the committed file.
out_dir = pathlib.Path(
    os.environ.get("DASHBOARD_OUT_DIR", REPO_ROOT / "grafana/provisioning/dashboards")
)
out_dir.mkdir(parents=True, exist_ok=True)
out = str(out_dir / "cvs_stability_uptime_by_cause.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print("wrote", out)
