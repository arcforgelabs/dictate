"""Version metadata."""

from __future__ import annotations

# Public app/release version. This is intentionally the requested CalVer form.
RELEASE_VERSION = "2026.10.3"

# Python package metadata uses the same PEP 440-compatible CalVer form.
PACKAGE_VERSION = "2026.10.3"

__version__ = PACKAGE_VERSION


def release_channel() -> str:
    """Beta and stable are different builds. The version string is the channel.

    A beta is YYYY.M.N-beta.B. A build from the old unstable lane
    (YYYY.M.N-unstable.R.A) is on the beta channel too.
    """
    version = str(RELEASE_VERSION)
    return "beta" if "-beta." in version or "-unstable." in version else "stable"
