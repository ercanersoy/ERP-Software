"""ERP-Software: a small, customisable, web based ERP built on Tornado."""

import sys

if sys.version_info < (3, 13):  # pragma: no cover - checked before anything else runs
    raise SystemExit(
        "ERP-Software requires Python 3.13 or newer "
        f"(running {sys.version_info.major}.{sys.version_info.minor})."
    )

__version__ = "1.0.0"
APP_NAME = "ERP-Software"
