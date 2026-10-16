"""tools/coverage.py: fail under the floor — the lcov line-coverage gate for the Rust side of a binding.

Stdlib only. Reads an lcov info file, sums DA hits per SF line block, prints the percentage and exits
non-zero below the floor. Usage: coverage.py <lcov.info> <floor>."""

import sys
from pathlib import Path


def percent(info: Path) -> float:
    """Lines hit over lines instrumented, summed across every file block."""
    found = hit = 0
    for line in info.read_text().splitlines():
        if line.startswith("DA:"):
            found += 1
            hit += int(line.rsplit(",", 1)[1] != "0")
    return 100.0 * hit / found if found else 100.0


def main() -> int:
    path, floor = Path(sys.argv[1]), float(sys.argv[2])
    score = percent(path)
    print(f"rust line coverage: {score:.1f}% (floor {floor:.0f}%)")
    return 0 if score >= floor else 1


if __name__ == "__main__":
    sys.exit(main())
