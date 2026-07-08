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
Have the generator write into `$DASHBOARD_OUT_DIR` when that env var is set
(else the default dashboards dir) so the checker can regenerate into a temp
dir to compare without touching working files.

The `helpers/gen_<name>.py` → `<name>.json` naming is **recommended, not
required**: the checker verifies any script a dashboard's `"__generated_by"`
points at, so an off-convention generator is still drift-checked as long as
its marker names it. The convention buys one extra guarantee — a `gen_*.py`
script is discovered by the checker's glob independently of its output, so
deleting its dashboard is caught; an off-convention generator is discoverable
*only* through that marker, so if the dashboard is deleted its orphaning goes
unnoticed. Prefer the convention; reach for an off-convention name only when
you have a reason.

### Currently generated

| Dashboard JSON | Generator |
|----------------|-----------|
| `grafana/provisioning/dashboards/pool_health_metrics.json` | `helpers/gen_pool_health_dashboard.py` |

### Enforcement

`helpers/check_generated_dashboards.py` re-runs every generator (each
`helpers/gen_*.py`, plus any script named by a dashboard's `"__generated_by"`)
and fails if a committed dashboard has drifted from its generator's output, or
references a generator that is missing or outside the repo. CI runs it on
every PR
(`.github/workflows/check-generated-dashboards.yml`). To catch drift locally
before you push, install the commit hook once per clone:

```bash
pip install pre-commit && pre-commit install
```
