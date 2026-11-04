#!/usr/bin/env python3
"""Generate grafana/provisioning/dashboards/watch_nightly_gap.json.

The dashboard JSON is generated — edit this script and re-run it instead of
editing the JSON by hand.

Explains the nightly gap in the Grafana watch metrics (AT-1914): each watch
status is pushed to the pushgateway on the CVS host, which keeps a watch's last
value until the nightly 03:20 restart clears it. "In Grafana" below means the
pushgateway still holds a value for the watch, so Grafana draws it; it is not
the Customer Dashboard, whose watch figures come from the cloud.
"""
import json
import os
import pathlib

# The Prometheus datasource provisioned with a fixed uid in grafana/provisioning/datasources/datasource.yml.
DS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}
OFF_CHARGER = 'name="watch_ping", site_name="$site_name", is_charging="False"'
# Validated categorical slots 1-3 plus a neutral for the restart marker.
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8986"

IN_GRAFANA = "In Grafana (held by pushgateway)"
REPORTING = "Reporting (last 15 min)"
RESTART = "Nightly restart (pushgateway)"


def target(ref, expr, legend, interval=None):
    t = {"refId": ref, "datasource": DS, "editorMode": "code", "expr": expr,
         "legendFormat": legend, "range": True}
    if interval:
        t["interval"] = interval
    return t


def fixed_color(name, color, extra=()):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}, *extra]}


def timeseries(pid, title, desc, y, h, targets, custom, overrides, unit="none", stack=False):
    custom_all = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "showPoints": "never",
                  "spanNulls": False, "axisSoftMin": 0, "lineInterpolation": "stepAfter",
                  "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    custom_all.update(custom)
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 0 if unit == "none" else 1,
                                     "color": {"mode": "palette-classic"}, "custom": custom_all},
                        "overrides": overrides},
        "options": {"legend": {"displayMode": "list", "placement": "right", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "none"}},
        "targets": targets,
    }


in_grafana_vs_reporting = timeseries(
    1, "Watches off the charger: in Grafana vs. actually reporting",
    "In Grafana = the pushgateway on the CVS still holds a value for the watch, so Grafana (e.g. the Watch "
    "Dashboard) still draws it; the pushgateway keeps the last value until the nightly restart (03:20 site-local) clears "
    "it. Reporting = the watch sent a status in the last 15 minutes (push_time_seconds). The shaded area is "
    "stale: drawn in Grafana, but silent. The gray bar marks the pushgateway restart on this site's CVS "
    "(nightly 03:20 site-local; first 10 minutes after the restart).",
    0, 10,
    [target("A", f"count(count by (watch) (push_time_seconds{{{OFF_CHARGER}}})) or vector(0)", IN_GRAFANA),
     target("B", f"count(count by (watch) ((time() - push_time_seconds{{{OFF_CHARGER}}}) < 900)) or vector(0)",
            REPORTING),
     # 1 for the first 10 min after a pushgateway restart on any CVS of the site. The 1d lookback finds the
     # site's servers even when no watch series is live at restart time.
     target("C", 'max(((time() - max by (environment) (container_start_time_seconds{name="pushgateway"})) < 600) '
                 'and on (environment) group by (environment) (max_over_time(watch_ping{site_name="$site_name"}[1d]))) '
                 '* 0 + 1', RESTART)],
    {},
    [fixed_color(IN_GRAFANA, BLUE, [{"id": "custom.fillBelowTo", "value": REPORTING},
                                    {"id": "custom.fillOpacity", "value": 12}]),
     fixed_color(REPORTING, ORANGE),
     fixed_color(RESTART, GRAY, [{"id": "custom.drawStyle", "value": "bars"},
                                 {"id": "custom.fillOpacity", "value": 100},
                                 {"id": "custom.lineWidth", "value": 0},
                                 {"id": "custom.axisPlacement", "value": "hidden"},
                                 {"id": "min", "value": 0},
                                 {"id": "max", "value": 1}])],
)

reports_per_15m = timeseries(
    2, "Watch reports received per 15 min",
    "Status messages from watches (watch_ping increase). A watch left on its charger keeps reporting through "
    "the night, including across the nightly restart.",
    10, 8,
    [target("A", 'sum by (state) (label_replace(label_replace('
                 'increase(watch_ping{site_name="$site_name"}[15m]), '
                 '"state", "On the charger", "is_charging", "True"), '
                 '"state", "Off the charger", "is_charging", "False"))',
            "{{state}}", interval="15m")],
    {"drawStyle": "bars", "fillOpacity": 85, "lineWidth": 1, "lineInterpolation": "linear"},
    [fixed_color("Off the charger", ORANGE), fixed_color("On the charger", AQUA)],
    stack=True,
)

hours_since_report = timeseries(
    3, "Hours since each watch's last report (off the charger)",
    "time() - push_time_seconds per watch. A rising line = the watch is silent but still drawn in Grafana. "
    "The line ends when the nightly restart clears the pushgateway.",
    18, 9,
    [target("A", f"min by (watch) ((time() - push_time_seconds{{{OFF_CHARGER}}}) / 3600)", "{{watch}}")],
    {"lineInterpolation": "linear"},
    [],
    unit="h",
)

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
    "title": "Watch metrics: nightly gap explained",
    "uid": "watch-nightly-gap",
    "id": None,
    "description": "Why watch metrics disappear from Grafana at 03:20 local and return in the morning: the "
                   "pushgateway on the CVS keeps a silent watch's last value until the nightly restart clears "
                   "it. One site at a time. Times are in your browser's time zone; the restart is at 03:20 site-local time. AT-1914.",
    "tags": ["watch", "pushgateway"],
    "timezone": "browser",
    "editable": True,
    "schemaVersion": 38,
    "time": {"from": "now-24h", "to": "now"},
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
         "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
    ]},
    "templating": {"list": [
        {"name": "site_name", "label": "site", "type": "query", "datasource": DS,
         "definition": "label_values(watch_ping, site_name)",
         "query": {"query": "label_values(watch_ping, site_name)", "refId": "site"},
         # One site at a time: the panels count watches per site, so a second site would add into the same
         # series. No saved default: Grafana opens on the first site; links pick one via var-site_name.
         "refresh": 2, "sort": 1, "includeAll": False, "multi": False, "current": {}},
    ]},
    "panels": [in_grafana_vs_reporting, reports_per_15m, hours_since_report],
}

# Output dir is overridable via DASHBOARD_OUT_DIR so tooling
# (helpers/check_generated_dashboards.py) can regenerate into a temp dir to
# compare, without touching the committed file.
out_dir = pathlib.Path(
    os.environ.get("DASHBOARD_OUT_DIR", REPO_ROOT / "grafana/provisioning/dashboards")
)
out_dir.mkdir(parents=True, exist_ok=True)
out = str(out_dir / "watch_nightly_gap.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print("wrote", out)
