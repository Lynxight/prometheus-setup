#!/usr/bin/env python3
"""Verify each generated dashboard matches its generator's output.

READ-ONLY: never writes into the dashboards directory. Each generator is run
with DASHBOARD_OUT_DIR pointed at a throwaway temp dir, and its output is
compared against the committed dashboard file. On any mismatch it fails and
tells you to regenerate — it does not rewrite your files.

Generators to run are discovered two ways: every helpers/gen_*.py, PLUS any
other script a dashboard's __generated_by marker points at. Off-convention
generators are allowed as long as a marker points at them, so they are still
run and drift-checked. Caveat: a generator discoverable ONLY via a marker
loses deletion detection — once its dashboard is deleted nothing points back
to it, so its being orphaned goes unnoticed. gen_*.py generators keep full
deletion detection via the glob, so the convention stays the safer choice.
A marker naming a missing file — or a path outside the repo or not ending in
.py, which is never executed — is a failure.

Generators must honor DASHBOARD_OUT_DIR (write there when set, else the
default dashboards dir) and write <name>.json directly into it. Stdlib-only
and idempotent, so it runs identically in pre-commit and CI. Exit 0 = in
sync, 1 = drift / deletion / orphan / bad-marker, 2 = a generator crashed.

Used by .pre-commit-config.yaml and .github/workflows/check-generated-dashboards.yml.
"""
import json
import os
import subprocess
import sys
import pathlib
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPERS = REPO_ROOT / "helpers"
DASH_DIR = REPO_ROOT / "grafana/provisioning/dashboards"


def main() -> int:
    problems = []

    # Generators to run = every helpers/gen_*.py, PLUS any other script named by
    # a dashboard's __generated_by marker (off-convention generators are fine as
    # long as a marker makes them discoverable and thus drift-checked). A set
    # dedups a script found both ways.
    to_run = {g.relative_to(REPO_ROOT).as_posix()
              for g in HELPERS.glob("gen_*.py")}

    for p in sorted(DASH_DIR.glob("*.json")):
        try:
            marker = json.loads(p.read_text()).get("__generated_by")
        except (json.JSONDecodeError, OSError):
            continue
        if not marker:
            continue
        # A marker is committed data, so a bad one is a defect to report — never
        # a path to blindly execute. Only run scripts that resolve inside the
        # repo and are Python; anything else fails without being run.
        target = (REPO_ROOT / marker).resolve()
        if not target.is_relative_to(REPO_ROOT) or target.suffix != ".py":
            problems.append(
                f"{p.name}: __generated_by '{marker}' must be a .py path "
                f"inside the repo"
            )
        elif not target.is_file():
            problems.append(f"{p.name}: references missing generator '{marker}'")
        else:
            to_run.add(target.relative_to(REPO_ROOT).as_posix())

    generators = sorted(to_run)

    # Generate into a temp dir (the real files are never touched) and compare.
    if generators:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DASHBOARD_OUT_DIR": tmp}
            for rel in generators:
                proc = subprocess.run([sys.executable, str(REPO_ROOT / rel)],
                                      cwd=REPO_ROOT, env=env,
                                      capture_output=True, text=True)
                if proc.returncode != 0:
                    print(f"ERROR: generator crashed: python3 {rel}")
                    if proc.stderr.strip():
                        print(proc.stderr.strip())
                    return 2

            for produced in sorted(pathlib.Path(tmp).glob("*.json")):
                committed = DASH_DIR / produced.name
                rel = committed.relative_to(REPO_ROOT).as_posix()
                if not committed.is_file():
                    problems.append(f"{rel}: generator produces this file but it is missing (deleted?)")
                elif committed.read_bytes() != produced.read_bytes():
                    problems.append(f"{rel}: file does not match its generator's output")

    if problems:
        print("ERROR: generated dashboard(s) out of sync with their generator:")
        for m in problems:
            print(f"  - {m}")
        if generators:
            print("\nRegenerate (this updates the file), then commit the result:")
            for rel in generators:
                print(f"  python3 {rel}")
        return 1

    if not generators:
        print("no generators (helpers/gen_*.py or a dashboard __generated_by) "
              "found — nothing to check")
        return 0

    print(f"OK: {len(generators)} generator(s); all generated dashboards match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
