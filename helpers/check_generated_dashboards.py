#!/usr/bin/env python3
"""Verify each generated dashboard matches its generator's output.

READ-ONLY: never writes into the dashboards directory. Each generator is run
with DASHBOARD_OUT_DIR pointed at a throwaway temp dir, and its output is
compared against the committed dashboard file. On any mismatch it fails and
tells you to regenerate — it does not rewrite your files. A generated file
that is missing (e.g. deleted while its generator was kept) also fails.

Generators must honor DASHBOARD_OUT_DIR (write there when set, else the
default dashboards dir) and write <name>.json directly into it. Stdlib-only
and idempotent, so it runs identically in pre-commit and CI. Exit 0 = in
sync, 1 = drift/deletion/orphan, 2 = a generator crashed.

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
    generators = sorted(HELPERS.glob("gen_*.py"))
    if not generators:
        print("no generator scripts (helpers/gen_*.py) found — nothing to check")
        return 0

    problems = []

    # A committed dashboard that names a generator which no longer exists.
    for p in sorted(DASH_DIR.glob("*.json")):
        try:
            marker = json.loads(p.read_text()).get("__generated_by")
        except (json.JSONDecodeError, OSError):
            continue
        if marker and not (REPO_ROOT / marker).is_file():
            problems.append(f"{p.name}: references missing generator '{marker}'")

    # Generate into a temp dir (the real files are never touched) and compare.
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DASHBOARD_OUT_DIR": tmp}
        for gen in generators:
            rel = gen.relative_to(REPO_ROOT).as_posix()
            proc = subprocess.run([sys.executable, str(gen)], cwd=REPO_ROOT,
                                  env=env, capture_output=True, text=True)
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
        print("\nRegenerate (this updates the file), then commit the result:")
        for gen in generators:
            print(f"  python3 {gen.relative_to(REPO_ROOT).as_posix()}")
        return 1

    print(f"OK: {len(generators)} generator(s); all generated dashboards match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
