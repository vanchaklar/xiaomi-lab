#!/usr/bin/env python3
"""Exercise the MIoT direct controller through raw miIO commands.

This deliberately bypasses G1Vacuum.set_property_by() and sends the underlying
MIoT requests through raw_command(). The robot is stopped before the sequence,
stopped again on exit, and then sent to the dock by default.

Every command/response is persisted as a CSV table so the run can be analyzed
later with pandas or any spreadsheet tool.

Default mode is dry-run. Pass --apply to move the robot.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, timezone
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

FIELDNAMES = [
    "timestamp_utc",
    "elapsed_s",
    "step",
    "phase",
    "direction",
    "value",
    "requested_pulse_s",
    "response_code",
    "response_json",
]


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


def raw_dock(vac):
    return vac.raw_command(
        "action",
        {
            "did": "raw-call-2-3",
            "siid": 2,
            "aiid": 3,
            "in": [],
        },
    )


def response_code(response):
    if isinstance(response, dict):
        return response.get("code")
    if (
        isinstance(response, list)
        and response
        and isinstance(response[0], dict)
    ):
        return response[0].get("code")
    return None


def response_ok(response) -> bool:
    return response_code(response) == 0


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "data" / f"raw_random_walk_{stamp}.csv"


def pulse_for(direction: str, args) -> float:
    if direction == "forward":
        return args.forward_pulse
    if direction == "backward":
        return args.backward_pulse
    return args.side_pulse


def write_row(
    writer,
    *,
    started: float,
    step: int,
    phase: str,
    direction: str,
    pulse: float | None,
    response,
) -> None:
    writer.writerow(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": f"{time.monotonic() - started:.6f}",
            "step": step,
            "phase": phase,
            "direction": direction,
            "value": DIRECTIONS.get(direction, ""),
            "requested_pulse_s": "" if pulse is None else f"{pulse:.6f}",
            "response_code": response_code(response),
            "response_json": json.dumps(response, separators=(",", ":"), sort_keys=True),
        }
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
        default=30.0,
        help=(
            "soft total run duration in seconds (default: 30); an already-started "
            "movement pulse is allowed to finish"
        ),
    )
    parser.add_argument(
        "--forward-pulse",
        type=float,
        default=10.0,
        help="forward movement pulse in seconds (default: 10)",
    )
    parser.add_argument(
        "--backward-pulse",
        type=float,
        default=1.0,
        help="backward movement pulse in seconds (default: 1)",
    )
    parser.add_argument(
        "--side-pulse",
        type=float,
        default=1.5,
        help="left/right movement pulse in seconds (default: 1.5)",
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
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path; defaults to data/raw_random_walk_<timestamp>.csv",
    )
    parser.add_argument(
        "--no-dock",
        action="store_true",
        help="do not send the final return-to-dock action",
    )
    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("--duration must be positive")
    if args.forward_pulse <= 0:
        parser.error("--forward-pulse must be positive")
    if args.backward_pulse <= 0:
        parser.error("--backward-pulse must be positive")
    if args.side_pulse <= 0:
        parser.error("--side-pulse must be positive")
    if args.pause < 0:
        parser.error("--pause must be non-negative")

    rng = random.Random(args.seed)

    if not args.apply:
        elapsed = 0.0
        step = 0
        print("dry_run=True")
        while elapsed < args.duration:
            direction = rng.choice(MOVING_DIRECTIONS)
            pulse = pulse_for(direction, args)
            step += 1
            print(
                f"step={step} direction={direction} "
                f"value={DIRECTIONS[direction]} pulse={pulse:.3f}"
            )
            elapsed += pulse + args.pause
        print("final=stop")
        if not args.no_dock:
            print("final=dock")
        print("No CSV is written for dry-run mode.")
        print("Re-run with --apply only with the robot on open floor away from stairs.")
        return

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vac = connect()
    started = time.monotonic()
    step = 0

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        handle.flush()

        initial_stop = raw_direction(vac, "stop")
        print("initial_stop_response=", initial_stop)
        write_row(
            writer,
            started=started,
            step=0,
            phase="initial_stop",
            direction="stop",
            pulse=None,
            response=initial_stop,
        )
        handle.flush()

        try:
            while (time.monotonic() - started) < args.duration:
                direction = rng.choice(MOVING_DIRECTIONS)
                pulse = pulse_for(direction, args)
                step += 1

                response = raw_direction(vac, direction)
                print(
                    f"step={step} direction={direction} value={DIRECTIONS[direction]} "
                    f"pulse={pulse:.3f} response={response!r}"
                )
                write_row(
                    writer,
                    started=started,
                    step=step,
                    phase="move",
                    direction=direction,
                    pulse=pulse,
                    response=response,
                )
                handle.flush()

                if not response_ok(response):
                    raise RuntimeError(f"raw direction command failed: {response!r}")

                time.sleep(pulse)

                stop_response = raw_direction(vac, "stop")
                print(f"step={step} stop_response={stop_response!r}")
                write_row(
                    writer,
                    started=started,
                    step=step,
                    phase="stop",
                    direction="stop",
                    pulse=None,
                    response=stop_response,
                )
                handle.flush()

                if not response_ok(stop_response):
                    raise RuntimeError(f"raw stop command failed: {stop_response!r}")

                if args.pause:
                    time.sleep(args.pause)
        finally:
            try:
                final_stop = raw_direction(vac, "stop")
                print("final_stop_response=", final_stop)
                write_row(
                    writer,
                    started=started,
                    step=step,
                    phase="final_stop",
                    direction="stop",
                    pulse=None,
                    response=final_stop,
                )
                handle.flush()
            except Exception as exc:
                print(f"final_stop_failed={type(exc).__name__}: {exc}", file=sys.stderr)

            if not args.no_dock:
                try:
                    dock_response = raw_dock(vac)
                    print("dock_response=", dock_response)
                    write_row(
                        writer,
                        started=started,
                        step=step,
                        phase="dock",
                        direction="dock",
                        pulse=None,
                        response=dock_response,
                    )
                    handle.flush()
                except Exception as exc:
                    print(f"dock_failed={type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"csv={output_path}")


if __name__ == "__main__":
    main()
