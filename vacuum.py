"""Connection helpers for the Xiaomi vacuum lab."""

from __future__ import annotations

import os
import string
from pathlib import Path

from dotenv import load_dotenv
from miio.integrations.vacuum.mijia import G1Vacuum


load_dotenv(Path(__file__).with_name(".env"))


def _read_token() -> str:
    token = os.environ.get("VACUUM_TOKEN", "").strip()

    if not token:
        raise RuntimeError("VACUUM_TOKEN is not set")

    if token.startswith(("b'", 'b"')):
        raise RuntimeError(
            "VACUUM_TOKEN must be the raw 32-character hexadecimal token, "
            "without a leading b prefix or quotes"
        )

    if len(token) != 32 or any(ch not in string.hexdigits for ch in token):
        raise RuntimeError(
            "VACUUM_TOKEN must contain exactly 32 hexadecimal characters"
        )

    return token


def connect() -> G1Vacuum:
    """Create a G1Vacuum from .env or process environment variables."""
    ip = os.environ.get("VACUUM_IP", "").strip()
    if not ip:
        raise RuntimeError("VACUUM_IP is not set")

    return G1Vacuum(ip=ip, token=_read_token())


def safe_info() -> str:
    """Return the normal miIO info representation."""
    return str(connect().info())
