#!/usr/bin/env python3
"""Entry point. Works from any folder on macOS, Linux and Windows:

    python weekly_review.py --help
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wr.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
