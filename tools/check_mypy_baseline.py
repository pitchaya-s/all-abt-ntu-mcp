"""Reject new mypy diagnostics while existing typing debt is retired."""

from collections import Counter
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".github" / "mypy-baseline.txt"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--follow-imports=silent",
            "--no-error-summary",
            "--no-pretty",
            "--no-color-output",
            "src",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        print(result.stdout + result.stderr, file=sys.stderr)
        return result.returncode
    current = Counter(
        re.sub(r":\d+(?::\d+)?: error:", ": error:", line)
        for line in result.stdout.splitlines()
        if ": error:" in line
    )
    unexpected = current - Counter(BASELINE.read_text().splitlines())
    if unexpected:
        print("New mypy diagnostics:", file=sys.stderr)
        for diagnostic, count in sorted(unexpected.items()):
            print(f"{count}x {diagnostic}", file=sys.stderr)
        return 1
    if result.returncode == 1 and not current:
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    print(f"mypy: no new diagnostics ({sum(current.values())} existing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
