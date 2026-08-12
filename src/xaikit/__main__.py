"""Allow ``python -m xaikit`` to show package help; gaps CLI is ``python -m xaikit.gaps``."""

from __future__ import annotations

import sys


def main() -> int:
    sys.stdout.write(
        "XaiKit — use python -m xaikit.gaps for the optional gap-log review CLI.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
