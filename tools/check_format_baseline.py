"""Require formatted Python files unless unchanged since the existing baseline."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".github" / "format-baseline.json"


def main() -> int:
    result = subprocess.run(
        [
            "uvx",
            "ruff==0.17.4",
            "format",
            "--check",
            "--output-format",
            "json",
            "src",
            "tests",
            "tools",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        print(result.stdout + result.stderr, file=sys.stderr)
        return result.returncode
    try:
        diagnostics = json.loads(result.stdout)
        baseline = json.loads(BASELINE.read_text())
        unformatted = {Path(item["filename"]).relative_to(ROOT) for item in diagnostics}
        new = sorted(
            str(path)
            for path in unformatted
            if baseline.get(path.as_posix())
            != hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Could not check the format baseline: {error}", file=sys.stderr)
        return 1
    if new:
        print("Format these new or changed files with Ruff:", file=sys.stderr)
        for path in new:
            print(path, file=sys.stderr)
        return 1
    if result.returncode == 1 and not unformatted:
        print(
            result.stderr or "Ruff reported a failure without diagnostics",
            file=sys.stderr,
        )
        return 1
    print(
        f"Ruff format: no new formatting deviations ({len(unformatted)} existing files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
