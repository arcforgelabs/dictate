"""Version metadata."""

from __future__ import annotations

# Public app/release version. This is intentionally the requested CalVer form.
RELEASE_VERSION = "2026.9.25-1"

# Python package metadata uses the same PEP 440-compatible CalVer form.
PACKAGE_VERSION = "2026.9.25-1"

__version__ = PACKAGE_VERSION


def release_channel() -> str:
    """Beta and stable are different builds. The version string is the channel."""
    return "unstable" if "-unstable." in str(RELEASE_VERSION) else "stable"
