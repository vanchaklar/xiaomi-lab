#!/usr/bin/env python3
"""Guarded direct movement control for mijia.vacuum.v2."""

from __future__ import annotations

import argparse
import time

from vacuum import connect


# Public MIoT direct-controller values for mijia.vacuum.v2.
DIRECTIONS = {
    "left": 0,
    "right": 1,
    "forward": 2,
    "backward": 3,
    "stop": 4,
}

CONTROLLER_SIID = 8
DIRECTION_PIID = 1


def set_direction(vac, direction: str):
    return vac.set_property_by(
        CONTROLLER_SIID,
        DIRECTION_PIID,
        DIRECTIONS[direction],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move the vacuum using the MIoT direct controller."
    )
    parser.add_argument("direction", choices=DIRECTIONS)
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.5,
        help="auto-stop after this many seconds; ignored for 'stop' (default: 0.5)",
    )
    args = parser.parse_args()

    if args.seconds < 0:
        parser.error("--seconds must be non-negative")

    vac = connect()
    print(set_direction(vac, args.direction))

    if args.direction != "stop":
        try:
            time.sleep(args.seconds)
        finally:
            print(set_direction(vac, "stop"))


if __name__ == "__main__":
    main()
