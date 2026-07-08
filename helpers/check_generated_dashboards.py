#!/usr/bin/env python3
"""Fail if any generated dashboard is out of sync with its generator.

Run every `helpers/gen_*.py`, then check whether that changed any tracked file
under the dashboards directory. A non-empty diff means the committed JSON
drifted from its generator — someone hand-edited the JSON, or changed the
generator without re-running it. Also flags a JSON that advertises a
`__generated_by` generator which no longer exists.

Generators are expected to be stdlib-only and idempotent, so this needs no
dependencies and can run identically in pre-commit and CI. Exit 0 = in sync,
1 = drift/orphan, 2 = a generator crashed.

Used by .pre-commit-config.yaml and .github/workflows/check-generated-dashboards.yml.
"""
import json
import subprocess
import sys
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPERS = REPO_ROOT / "helpers"
DASH_REL = "grafana/provisioning/dashboards"
DASH_DIR = REPO_ROOT / DASH_REL


def main() -> int:
    generators = sorted(HELPERS.glob("gen_*.py"))
    if not generators:
        print("no generator scripts (helpers/gen_*.py) found — nothing to check")
        return 0

    # 1. Every JSON that claims a generator must point at one that still exists.
    orphans = []
    for jf in sorted(DASH_DIR.glob("*.json")):
        try:
            marker = json.loads(jf.read_text()).get("__generated_by")
        except (json.JSONDecodeError, OSError):
            continue
        if marker and not (REPO_ROOT / marker).is_file():
            orphans.append((jf.relative_to(REPO_ROOT).as_posix(), marker))
    if orphans:
        print("ERROR: generated dashboard(s) reference a missing generator:")
        for jf, marker in orphans:
            print(f"  - {jf}  ->  {marker} (not found)")
        print("\nCommit the generator, or remove the stale __generated_by marker.")
        return 1

    # 2. Regenerate everything and see if any committed output changed.
    for gen in generators:
        rel = gen.relative_to(REPO_ROOT).as_posix()
        proc = subprocess.run([sys.executable, str(gen)], cwd=REPO_ROOT)
        if proc.returncode != 0:
            print(f"ERROR: generator failed: python3 {rel}")
            return 2

    diff = subprocess.run(
        ["git", "diff", "--name-only", "--", DASH_REL],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    if changed:
        print("ERROR: generated dashboard(s) are out of date with their generator:")
        for f in changed:
            print(f"  - {f}")
        print("\nA committed dashboard JSON does not match its generator's output.")
        print("Regenerate and commit the result:")
        for gen in generators:
            print(f"  python3 {gen.relative_to(REPO_ROOT).as_posix()}")
        return 1

    print(f"OK: {len(generators)} generator(s), all dashboards in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
