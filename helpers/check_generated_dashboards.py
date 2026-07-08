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

    # Committed dashboard name -> its generator, so we can later catch a
    # generator that stops producing that filename (renamed output / stale file).
    marked = {}
    for p in sorted(DASH_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except OSError as e:
            problems.append(f"{p.name}: cannot read ({e})")
            continue
        except json.JSONDecodeError as e:
            problems.append(f"{p.name}: invalid JSON ({e})")
            continue
        marker = data.get("__generated_by") if isinstance(data, dict) else None
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
            marked[p.name] = marker

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
                    print(f"ERROR: generator crashed (exit {proc.returncode}): "
                          f"python3 {rel}")
                    output = (proc.stdout + proc.stderr).strip()
                    if output:
                        print(output)
                    return 2

            produced_names = {q.name for q in pathlib.Path(tmp).glob("*.json")}
            for produced in sorted(pathlib.Path(tmp).glob("*.json")):
                committed = DASH_DIR / produced.name
                rel = committed.relative_to(REPO_ROOT).as_posix()
                if not committed.is_file():
                    problems.append(f"{rel}: generator produces this file but it is missing (deleted?)")
                elif committed.read_bytes() != produced.read_bytes():
                    problems.append(f"{rel}: file does not match its generator's output")

            # A committed dashboard that still claims a generator, but which no
            # generator produced this run, is stale — e.g. the generator was
            # changed to emit a different filename, leaving this one behind.
            for name, marker in sorted(marked.items()):
                if name not in produced_names:
                    problems.append(
                        f"{name}: claims generator '{marker}', but it no longer "
                        f"produces this file (renamed output? stale file?)"
                    )

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
