#!/usr/bin/env python3
"""Probe event-backing MIoT properties without changing device state.

The public mijia.vacuum.v2 specification marks these payload properties as
notify/event data rather than normally readable properties. Some firmware still
returns useful values to get_properties, so we test that before building an
event-subscription/capture path.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect


PROBES = [
    ("map_points", 7, 1),
    ("current_clean_record", 9, 6),
    ("temp_log", 16, 2),
]

CONTROLS = [
    ("status", 2, 1),
    ("map_switch", 7, 2),
]


def read_raw(vac, name: str, siid: int, piid: int, retries: int = 1) -> None:
    for attempt in range(retries + 1):
        try:
            response = vac.get_property_by(siid, piid)
            print(f"{name:22} ({siid},{piid}) => {response!r}")
            return
        except Exception as exc:
            if attempt >= retries:
                print(
                    f"{name:22} ({siid},{piid}) => "
                    f"EXCEPTION: {type(exc).__name__}: {exc}"
                )
                return
            time.sleep(0.25)


def sample(vac) -> None:
    print("controls:")
    for item in CONTROLS:
        read_raw(vac, *item)

    print("event-backing properties:")
    for item in PROBES:
        read_raw(vac, *item)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="number of read-only samples to take (default: 1)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="seconds between samples when --samples > 1 (default: 2)",
    )
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.interval < 0:
        parser.error("--interval must be non-negative")

    vac = connect()

    # Prime miIO discovery/session state before the first property query. This avoids
    # treating a transient first-packet discovery failure as a property result.
    try:
        info = vac.info()
        print(f"device={info.model} firmware={info.firmware_version}")
    except Exception as exc:
        print(f"initial_info=EXCEPTION: {type(exc).__name__}: {exc}")

    for index in range(args.samples):
        if args.samples > 1:
            print(f"\n=== sample {index + 1}/{args.samples} ===")
        sample(vac)
        if index + 1 < args.samples:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
