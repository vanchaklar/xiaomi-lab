"""Connection helpers for the Xiaomi vacuum lab."""

from __future__ import annotations

import os

from miio.integrations.vacuum.mijia import G1Vacuum


def connect() -> G1Vacuum:
    """Create a G1Vacuum from local environment variables."""
    ip = os.environ.get("VACUUM_IP")
    token = os.environ.get("VACUUM_TOKEN")

    if not ip:
        raise RuntimeError("VACUUM_IP is not set")
    if not token:
        raise RuntimeError("VACUUM_TOKEN is not set")

    return G1Vacuum(ip=ip, token=token)


def safe_info() -> str:
    """Return the normal miIO info representation."""
    return str(connect().info())
