# prometheus-setup

Config source-of-truth for the **cloud** Prometheus + Grafana stack (dockprom
fork): provisioned Grafana dashboards + datasource, and Prometheus scrape /
alert / recording rules. This repo is not itself deployed by any script — the
stack runs on a dedicated EC2 that applies these files manually. See
`README.md` for the dockprom stack itself.

## Generated dashboards — check before you edit

Some dashboards under `grafana/provisioning/dashboards/*.json` are **generated
by a script** and must not be hand-edited — a hand edit is silently clobbered
the next time the generator runs.

**Before editing any dashboard JSON:** look at the top of the file for a
`"__generated_by"` key.

- If it's present, it names the generator (e.g. `helpers/gen_pool_health_dashboard.py`).
  **Do not edit the JSON.** Edit that script and re-run it:
  `python3 helpers/gen_pool_health_dashboard.py`
- If it's absent, the dashboard is hand-authored — edit the JSON directly.

**If you create a dashboard programmatically:** commit the generator to
`helpers/` and make it emit `"__generated_by"` (and a `"__generated_warning"`)
as the first keys of the dashboard object, so the next person or AI finds it.
Follow the naming convention `helpers/gen_<name>.py` → `<name>.json`.

### Currently generated

| Dashboard JSON | Generator |
|----------------|-----------|
| `grafana/provisioning/dashboards/pool_health_metrics.json` | `helpers/gen_pool_health_dashboard.py` |
