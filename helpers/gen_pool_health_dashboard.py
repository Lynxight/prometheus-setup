#!/usr/bin/env python3
"""Generate grafana/provisioning/dashboards/pool_health_metrics.json.

The dashboard JSON is generated — edit this script and re-run it instead of
editing the JSON by hand.
"""
import json
import pathlib

DS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}
F = 'environment=~"$server", site_name=~"$site_name", pool_name=~"$pool_name", group=~"$deploy_group"'
SWF = F + ', pool_state=~"$pool_state", under_maintenance=~"$under_maintenance"'
# pool_state/under_maintenance exist only on swimmer_count; other metrics get
# those filters via this join (same convention as cvs_stability_metrics.json)
SW_JOIN = f" and on(site_name, pool_name, environment) swimmer_count{{{SWF}}}"
POOL_LEGEND = "{{site_name}} / {{pool_name}}"
CAM_LEGEND = "{{site_name}} / {{pool_name}} / cam {{camera_id}}"
OPS_LINK = {
    "title": "View in OPS Dashboard",
    "url": "/d/c2e10e40-2cbb-460d-91a0-83334f641194/ops-dashboard-per-site-support?var-site_name=${__field.labels.site_name}&var-server=${__field.labels.environment}&var-pool_name=${__field.labels.pool_name}&from=${__from}&to=${__to}",
    "targetBlank": True,
}

ids = iter(range(1, 100))


def variable(name, label, query, chain=""):
    q = f"label_values(swimmer_count{{{chain}}},{name if name not in ('server', 'deploy_group') else {'server': 'environment', 'deploy_group': 'group'}[name]})" if chain else f"label_values(swimmer_count,{name})"
    return {
        "name": name,
        "type": "query",
        "label": label,
        "datasource": DS,
        "definition": query,
        "query": {"query": query, "refId": "StandardVariableQuery"},
        "refresh": 2,
        "sort": 1,
        "includeAll": True,
        "allValue": ".*",
        "multi": True,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
    }


def row(title, y):
    return {"id": next(ids), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


def target(expr, legend, ref, instant=False):
    t = {"datasource": DS, "editorMode": "code", "expr": expr,
         "legendFormat": legend, "refId": ref}
    if instant:
        t["instant"] = True
    else:
        t["range"] = True
    return t


def timeseries(title, desc, y, targets, unit, steps, calcs, overrides=None, min_y=None):
    custom = {
        "drawStyle": "line",
        "lineWidth": 1,
        "fillOpacity": 5,
        "pointSize": 4,
        "showPoints": "never",
        "lineInterpolation": "linear",
        "spanNulls": False,
    }
    if steps is None:
        steps = [{"color": "green", "value": None}]
    else:
        custom["thresholdsStyle"] = {"mode": "line+area"}
    defaults = {
        "color": {"mode": "palette-classic"},
        "custom": custom,
        "unit": unit,
        "decimals": 2,
        "thresholds": {"mode": "absolute", "steps": steps},
    }
    if min_y is not None:
        defaults["min"] = min_y
    return {
        "id": next(ids),
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"h": 10, "w": 14, "x": 0, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom",
                       "showLegend": True, "calcs": calcs},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def bargauge(title, desc, y, inner, legend):
    """% of time `inner` (a bool expression body) held, per series + overall."""
    return {
        "id": next(ids),
        "type": "bargauge",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"h": 10, "w": 10, "x": 14, "y": y},
        "targets": [
            target(f"avg({inner})", "OVERALL AVERAGE", "A", instant=True),
            target(f"sort({inner})", legend, "B", instant=True),
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
            "overrides": [{
                "matcher": {"id": "byName", "options": "OVERALL AVERAGE"},
                "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "white"}}],
            }],
        },
        "options": {
            "orientation": "horizontal",
            "displayMode": "gradient",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showUnfilled": True,
            "minVizWidth": 8,
            "minVizHeight": 16,
        },
    }


def pct(cond_expr, rng="$__range:"):
    return f"avg_over_time(({cond_expr})[{rng}]) * 100"


panels = []
y = 0

# --- Row 1: Swimmer Count ---
panels.append(row("Swimmer Count", y)); y += 1
panels.append(timeseries(
    "Swimmer Count (red marks = -1, excluding nightly restart)",
    "Reported swimmer count per pool. Red points mark samples where the count "
    "is -1 (interrupted / invalid swimmer count) outside planned maintenance "
    "windows: the nightly restart and any other clean stop set "
    "cvs_maintenance_mode=1, which suppresses the red marks. The raw line "
    "still dips to -1 during those windows.",
    y,
    [
        target(f"swimmer_count{{{SWF}}}", POOL_LEGEND, "A"),
        target(f"(swimmer_count{{{SWF}}} == -1) and on(site_name, pool_name, environment) (cvs_maintenance_mode == 0)", "INTERRUPTED — " + POOL_LEGEND, "B"),
    ],
    unit="none", steps=None, calcs=["mean", "min", "lastNotNull"],
    overrides=[{
        "matcher": {"id": "byFrameRefID", "options": "B"},
        "properties": [
            {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}},
            {"id": "custom.drawStyle", "value": "points"},
            {"id": "custom.showPoints", "value": "always"},
            {"id": "custom.pointSize", "value": 6},
        ],
    }],
))
panels[-1]["fieldConfig"]["defaults"]["decimals"] = 0
panels.append(bargauge(
    "% Time with Valid Swimmer Count (excluding nightly restart)",
    "Percentage of the selected time range with a valid swimmer count "
    "(swimmer_count >= 0), per pool. Planned maintenance windows — the "
    "nightly restart and any other clean stop (cvs_maintenance_mode=1) — "
    "are excluded from the calculation via the cvs:swimmer_valid:bool "
    "recording rule, matching the red marks on the graph.",
    y,
    f"avg_over_time(cvs:swimmer_valid:bool{{{SWF}}}[$__range]) * 100",
    POOL_LEGEND,
)); y += 10

# --- Row 2: Detection FPS ---
panels.append(row("Detection FPS", y)); y += 1
panels.append(timeseries(
    "Detection FPS (threshold 0.9)",
    "Detection pipeline FPS per pool. Healthy: > 0.9 (target-normalized, ~1.0 when keeping up).",
    y,
    [target(f"detection_fps{{{F}}}{SW_JOIN}", POOL_LEGEND, "A")],
    unit="none", steps=[{"color": "red", "value": None}, {"color": "yellow", "value": 0.8}, {"color": "green", "value": 0.9}], calcs=["mean", "min", "lastNotNull"], min_y=0,
))
panels.append(bargauge(
    "% Time Detection FPS > 0.9 (per pool)",
    "Percentage of the selected time range with detection_fps above 0.9.",
    y,
    pct(f"(detection_fps{{{F}}} > bool 0.9){SW_JOIN}"),
    POOL_LEGEND,
)); y += 10

# --- Row 3: Decision FPS ---
panels.append(row("Decision FPS", y)); y += 1
panels.append(timeseries(
    "Decision FPS (threshold 0.9)",
    "Decision engine FPS per pool. Healthy: > 0.9.",
    y,
    [target(f"decisions_engine_fps{{{F}}}{SW_JOIN}", POOL_LEGEND, "A")],
    unit="none", steps=[{"color": "red", "value": None}, {"color": "yellow", "value": 0.8}, {"color": "green", "value": 0.9}], calcs=["mean", "min", "lastNotNull"], min_y=0,
))
panels.append(bargauge(
    "% Time Decision FPS > 0.9 (per pool)",
    "Percentage of the selected time range with decisions_engine_fps above 0.9.",
    y,
    pct(f"(decisions_engine_fps{{{F}}} > bool 0.9){SW_JOIN}"),
    POOL_LEGEND,
)); y += 10

# --- Row 4: Max Time Between Frames ---
panels.append(row("Max Time Between Frames (per camera)", y)); y += 1
panels.append(timeseries(
    "Max Time Between Frames per Camera (threshold 1s)",
    "Largest gap between consecutive frame arrivals per camera (FrameSource, "
    "upstream of the Synchronizer). Healthy: < 1s. Simultaneous spikes on all "
    "cameras of a server indicate a host/network pause rather than a camera issue.",
    y,
    [target(f"max_time_between_frames{{{F}}}{SW_JOIN}", CAM_LEGEND, "A")],
    unit="s", steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}], calcs=["mean", "max", "lastNotNull"], min_y=0,
))
panels.append(bargauge(
    "% Time Frame Gap < 1s (per camera)",
    "Percentage of the selected time range with max_time_between_frames below 1s, per camera.",
    y,
    pct(f"(max_time_between_frames{{{F}}} < bool 1){SW_JOIN}"),
    CAM_LEGEND,
)); y += 10

# --- Row 5: Mean Fuse Error ---
panels.append(row("Mean Fuse Error (per camera)", y)); y += 1
panels.append(timeseries(
    "Mean Fuse Error per Camera (threshold 1.5)",
    "GTM multi-camera fuse error per camera. Healthy: <= 1.5. A value of exactly "
    "1.5 is a sentinel meaning not enough multi-camera track overlap to measure "
    "and counts as healthy, so the red zone starts just above 1.5.",
    y,
    [target(f"mean_fuse_error{{{F}}}{SW_JOIN}", CAM_LEGEND, "A")],
    unit="none", steps=[{"color": "green", "value": None}, {"color": "red", "value": 1.501}], calcs=["mean", "max", "lastNotNull"], min_y=0,
))
panels.append(bargauge(
    "% Time Fuse Error <= 1.5 (per camera)",
    "Percentage of the selected time range with mean_fuse_error at or below 1.5, "
    "per camera. The sentinel value 1.5 (insufficient overlap samples) counts as healthy.",
    y,
    pct(f"(mean_fuse_error{{{F}}} <= bool 1.5){SW_JOIN}"),
    CAM_LEGEND,
)); y += 10

VAR_DEFS = [
    ("under_maintenance", "Under Maintenance", "label_values(swimmer_count,under_maintenance)"),
    ("pool_state", "Pool State", 'label_values(swimmer_count{under_maintenance=~"$under_maintenance"},pool_state)'),
    ("deploy_group", "Deploy Group", 'label_values(swimmer_count{pool_state=~"$pool_state"},group)'),
    ("server", "Server", 'label_values(swimmer_count{pool_state=~"$pool_state", group=~"$deploy_group"},environment)'),
    ("site_name", "Site", 'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group"},site_name)'),
    ("pool_name", "Pool", 'label_values(swimmer_count{pool_state=~"$pool_state", environment=~"$server", group=~"$deploy_group", site_name=~"$site_name"},pool_name)'),
]

dashboard = {
    "__inputs": [],
    "__requires": [
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"}
    ],
    "id": None,
    "uid": "pool-health-metrics",
    "title": "Pool Health Metrics",
    "description": "Per-pool health: uninterrupted swimmer count, detection/decision FPS, "
                   "per-camera frame gaps and fuse error, with % of time each metric was "
                   "within its threshold.",
    "tags": ["cvs", "pool-health", "algo"],
    "schemaVersion": 36,
    "version": 1,
    "links": [],
    "timezone": "browser",
    "editable": True,
    "refresh": "5m",
    "time": {"from": "now-3d", "to": "now"},
    "templating": {"list": [
        {
            "name": name,
            "type": "query",
            "label": label,
            "datasource": DS,
            "definition": query,
            "query": {"query": query, "refId": "StandardVariableQuery"},
            "refresh": 2,
            "sort": 1,
            "includeAll": True,
            "allValue": ".*",
            "multi": True,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        }
        for name, label, query in VAR_DEFS
    ]},
    "panels": panels,
}

out = str(pathlib.Path(__file__).resolve().parent.parent / "grafana/provisioning/dashboards/pool_health_metrics.json")
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print("wrote", out)
