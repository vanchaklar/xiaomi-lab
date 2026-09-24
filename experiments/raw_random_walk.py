#!/usr/bin/env python3
"""Exercise the MIoT direct controller through raw miIO commands.

This deliberately bypasses G1Vacuum.set_property_by() and sends the underlying
set_properties request through raw_command(). The robot is stopped before the
sequence and again in a finally block.

Default mode is dry-run. Pass --apply to move the robot.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect


CONTROLLER_SIID = 8
DIRECTION_PIID = 1

DIRECTIONS = {
    "left": 0,
    "right": 1,
    "forward": 2,
    "backward": 3,
    "stop": 4,
}

MOVING_DIRECTIONS = ("left", "right", "forward", "backward")


def raw_direction(vac, direction: str):
    value = DIRECTIONS[direction]
    payload = [
        {
            "did": f"raw-set-{CONTROLLER_SIID}-{DIRECTION_PIID}",
            "siid": CONTROLLER_SIID,
            "piid": DIRECTION_PIID,
            "value": value,
        }
    ]
    return vac.raw_command("set_properties", payload)


def response_ok(response) -> bool:
    return (
        isinstance(response, list)
        and bool(response)
        and isinstance(response[0], dict)
        and response[0].get("code") == 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send random direct-controller commands through raw miIO."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually move the robot; without this flag the sequence is only printed",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=15.0,
        help="total random-walk duration in seconds (default: 15)",
    )
    parser.add_argument(
        "--min-pulse",
        type=float,
        default=0.20,
        help="minimum movement pulse in seconds (default: 0.20)",
    )
    parser.add_argument(
        "--max-pulse",
        type=float,
        default=0.65,
        help="maximum movement pulse in seconds (default: 0.65)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.08,
        help="stop/pause between movement pulses in seconds (default: 0.08)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="optional deterministic random seed for reproducing a sequence",
    )
    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("--duration must be positive")
    if args.min_pulse <= 0 or args.max_pulse <= 0:
        parser.error("pulse durations must be positive")
    if args.min_pulse > args.max_pulse:
        parser.error("--min-pulse cannot exceed --max-pulse")
    if args.pause < 0:
        parser.error("--pause must be non-negative")

    rng = random.Random(args.seed)

    if not args.apply:
        elapsed = 0.0
        step = 0
        print("dry_run=True")
        while elapsed < args.duration:
            direction = rng.choice(MOVING_DIRECTIONS)
            pulse = min(rng.uniform(args.min_pulse, args.max_pulse), args.duration - elapsed)
            step += 1
            print(f"step={step} direction={direction} value={DIRECTIONS[direction]} pulse={pulse:.3f}")
            elapsed += pulse + args.pause
        print("final=stop")
        print("Re-run with --apply only with the robot on open floor away from stairs.")
        return

    vac = connect()

    print("initial_stop_response=", raw_direction(vac, "stop"))

    started = time.monotonic()
    step = 0

    try:
        while True:
            elapsed = time.monotonic() - started
            remaining = args.duration - elapsed
            if remaining <= 0:
                break

            direction = rng.choice(MOVING_DIRECTIONS)
            pulse = min(rng.uniform(args.min_pulse, args.max_pulse), remaining)
            step += 1

            response = raw_direction(vac, direction)
            print(
                f"step={step} direction={direction} value={DIRECTIONS[direction]} "
                f"pulse={pulse:.3f} response={response!r}"
            )
            if not response_ok(response):
                raise RuntimeError(f"raw direction command failed: {response!r}")

            time.sleep(pulse)

            stop_response = raw_direction(vac, "stop")
            print(f"step={step} stop_response={stop_response!r}")
            if not response_ok(stop_response):
                raise RuntimeError(f"raw stop command failed: {stop_response!r}")

            if args.pause:
                time.sleep(args.pause)
    finally:
        try:
            print("final_stop_response=", raw_direction(vac, "stop"))
        except Exception as exc:
            print(f"final_stop_failed={type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
