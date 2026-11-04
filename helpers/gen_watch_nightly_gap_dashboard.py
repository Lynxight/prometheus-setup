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
ANY_STATE = 'name="watch_ping", site_name="$site_name"'
OFF_CHARGER = ANY_STATE + ', is_charging="False"'
# A watch counts as reporting if its last push is younger than this.
REPORTING_WINDOW_SEC = 900
# The restart marker covers this long after the pushgateway starts, widened by one query step so a
# coarse step on a long time range still lands inside it.
RESTART_MARKER_SEC = 600
# Validated categorical slots 1-3 plus a neutral for the restart marker.
BLUE, ORANGE, GREEN, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8986"

IN_GRAFANA = "In Grafana (held by pushgateway)"
REPORTING_ANY = "Reporting, on or off the charger"
REPORTING_OFF = "Reporting off the charger"
RESTART = "Nightly restart (pushgateway)"
RESTART_TIMES = "the CVS stack stops at 03:16 and starts again at 03:20 site-local"


def target(ref, expr, legend, interval=None):
    t = {"refId": ref, "datasource": DS, "editorMode": "code", "expr": expr,
         "legendFormat": legend, "range": True}
    if interval:
        t["interval"] = interval
    return t


def fixed_color(name, color, extra=()):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}, *extra]}


def timeseries(pid, title, desc, y, h, targets, custom, overrides, unit="none", decimals=0, stack=False):
    custom_all = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "showPoints": "never",
                  "spanNulls": False, "axisSoftMin": 0, "lineInterpolation": "stepAfter",
                  "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    custom_all.update(custom)
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals,
                                     "color": {"mode": "palette-classic"}, "custom": custom_all},
                        "overrides": overrides},
        "options": {"legend": {"displayMode": "list", "placement": "right", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "none"}},
        "targets": targets,
    }


in_grafana_vs_reporting = timeseries(
    1, "Watches off the charger: in Grafana vs. actually reporting",
    "Counts watches whose last off-the-charger status is still held by the pushgateway on the CVS, so Grafana "
    "(e.g. the Watch Dashboard) still draws it. The pushgateway keeps the last value until the nightly restart "
    f"clears it ({RESTART_TIMES}). Reporting = the watch sent a status in the last "
    f"{REPORTING_WINDOW_SEC // 60} minutes (push_time_seconds). Blue shading = drawn in Grafana but silent. "
    "Green shading = put on the charger: its off-the-charger value is frozen in Grafana, but it is still "
    "reporting, as on the charger. The gray block marks the pushgateway restart on this site's CVS servers.",
    0, 10,
    [target("A", f"count(count by (watch) (push_time_seconds{{{OFF_CHARGER}}})) or vector(0)", IN_GRAFANA),
     target("B", f"count(count by (watch) (push_time_seconds{{{OFF_CHARGER}}}) and on (watch) "
                 f"(min by (watch) (time() - push_time_seconds{{{ANY_STATE}}}) < {REPORTING_WINDOW_SEC})) "
                 "or vector(0)", REPORTING_ANY),
     target("C", f"count(count by (watch) ((time() - push_time_seconds{{{OFF_CHARGER}}}) "
                 f"< {REPORTING_WINDOW_SEC})) or vector(0)", REPORTING_OFF),
     # 1 shortly after a pushgateway (re)start on any of the site's CVS servers.
     target("D", 'max((time() - container_start_time_seconds{name="pushgateway", environment=~"$environment"}) '
                 f'< ({RESTART_MARKER_SEC} + $__interval_ms / 1000)) * 0 + 1', RESTART)],
    {},
    [fixed_color(IN_GRAFANA, BLUE, [{"id": "custom.fillBelowTo", "value": REPORTING_ANY},
                                    {"id": "custom.fillOpacity", "value": 12}]),
     fixed_color(REPORTING_ANY, GREEN, [{"id": "custom.fillBelowTo", "value": REPORTING_OFF},
                                        {"id": "custom.fillOpacity", "value": 15},
                                        {"id": "custom.lineWidth", "value": 1}]),
     fixed_color(REPORTING_OFF, ORANGE),
     # A filled step line instead of bars: bars are drawn per step with gaps between them.
     fixed_color(RESTART, GRAY, [{"id": "custom.fillOpacity", "value": 30},
                                 {"id": "custom.lineWidth", "value": 0},
                                 {"id": "custom.axisPlacement", "value": "hidden"},
                                 {"id": "custom.hideFrom", "value": {"tooltip": True, "viz": False, "legend": False}},
                                 {"id": "min", "value": 0},
                                 {"id": "max", "value": 1}])],
)

reports_received = timeseries(
    2, "Watch reports received",
    "Status messages from watches (watch_ping increase) per bar: 15 minutes, wider on long time ranges. "
    "A watch left on its charger keeps reporting through the night, including across the nightly restart. "
    "The first report after a series appears (e.g. a watch's first report after the restart) is not counted, "
    "because increase() needs an earlier sample.",
    10, 8,
    [target("A", 'sum by (state) (label_replace(label_replace('
                 'increase(watch_ping{site_name="$site_name"}[$__interval]), '
                 '"state", "On the charger", "is_charging", "True"), '
                 '"state", "Off the charger", "is_charging", "False"))',
            "{{state}}", interval="15m")],
    {"drawStyle": "bars", "fillOpacity": 85, "lineWidth": 1, "lineInterpolation": "linear"},
    [fixed_color("Off the charger", ORANGE), fixed_color("On the charger", GREEN)],
    stack=True,
)

hours_since_report = timeseries(
    3, "Hours since each watch's last report",
    "For each watch whose off-the-charger value is held in Grafana: hours since its latest status, on or off "
    "the charger (push_time_seconds). A watch put on the charger stays near 0 while it reports; a rising line "
    "= the watch is silent but still drawn in Grafana. The line ends when the nightly restart clears the "
    "pushgateway.",
    18, 9,
    [target("A", f"min by (watch) ((time() - push_time_seconds{{{ANY_STATE}}}) / 3600) "
                 f"and on (watch) push_time_seconds{{{OFF_CHARGER}}}", "{{watch}}")],
    {"lineInterpolation": "linear"},
    [],
    unit="h",
    decimals=1,
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
    "description": "Why watch metrics disappear from Grafana at night and return in the morning: the "
                   "pushgateway on the CVS keeps a silent watch's last value until the nightly restart clears "
                   f"it ({RESTART_TIMES}). One site at a time. Times are in your browser's time zone. AT-1914.",
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
        # The site's CVS servers, for the restart marker: container metrics carry environment, not site_name.
        {"name": "environment", "label": "CVS", "type": "query", "datasource": DS, "hide": 2,
         "definition": 'label_values(watch_ping{site_name="$site_name"}, environment)',
         "query": {"query": 'label_values(watch_ping{site_name="$site_name"}, environment)', "refId": "environment"},
         "refresh": 2, "sort": 1, "includeAll": True, "multi": True,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
    ]},
    "panels": [in_grafana_vs_reporting, reports_received, hours_since_report],
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
