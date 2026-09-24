#!/usr/bin/env python3
"""Run one docked re-anchoring trial.

This script does not try to create carpet drift. The operator first lets the robot
accumulate visible drift and returns it to the dock. The script then applies either
a control condition (no map change) or the map-toggle condition. Starting a new
cleaning run is a separate explicit flag.
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


MAP_SIID = 7
MAP_PIID = 2
CHARGING_SIID = 3
CHARGING_PIID = 2
STATE_SIID = 2
STATE_PIID = 1

CHARGING = 1
FULLY_CHARGED = 2


def get_value(vac, siid: int, piid: int):
    response = vac.get_property_by(siid, piid)
    if not response:
        raise RuntimeError(f"Empty response for property {siid}/{piid}")
    item = response[0]
    if item.get("code") != 0:
        raise RuntimeError(
            f"Property {siid}/{piid} failed with code {item.get('code')}: {response!r}"
        )
    return item.get("value")


def set_value(vac, siid: int, piid: int, value):
    response = vac.set_property_by(siid, piid, value)
    if not response:
        raise RuntimeError(f"Empty response while setting {siid}/{piid}")
    item = response[0]
    if item.get("code") != 0:
        raise RuntimeError(
            f"Setting {siid}/{piid}={value!r} failed with "
            f"code {item.get('code')}: {response!r}"
        )
    return response


def toggle_map(vac, hold_seconds: float) -> None:
    original = bool(get_value(vac, MAP_SIID, MAP_PIID))
    changed = False
    try:
        print(f"map_switch_before={original!r}")
        print("setting map_switch=False")
        print(set_value(vac, MAP_SIID, MAP_PIID, False))
        changed = True

        disabled = get_value(vac, MAP_SIID, MAP_PIID)
        print(f"map_switch_after_disable={disabled!r}")
        if disabled is not False:
            raise RuntimeError("map_switch did not read back as False")

        time.sleep(hold_seconds)

        print("setting map_switch=True")
        print(set_value(vac, MAP_SIID, MAP_PIID, True))
        enabled = get_value(vac, MAP_SIID, MAP_PIID)
        print(f"map_switch_after_enable={enabled!r}")
        if enabled is not True:
            raise RuntimeError("map_switch did not read back as True")
    finally:
        if changed:
            current = bool(get_value(vac, MAP_SIID, MAP_PIID))
            if current != original:
                print(f"restoring map_switch={original}")
                set_value(vac, MAP_SIID, MAP_PIID, original)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "condition",
        choices=("control", "toggle"),
        help="control leaves map state untouched; toggle performs False -> True",
    )
    parser.add_argument(
        "--start-clean",
        action="store_true",
        help="start a global cleaning run after applying the condition",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=2.0,
        help="map-off duration for the toggle condition (default: 2)",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=3.0,
        help="delay before starting cleaning when --start-clean is used (default: 3)",
    )
    args = parser.parse_args()

    if args.hold_seconds < 0 or args.start_delay < 0:
        parser.error("durations must be non-negative")

    vac = connect()

    charge_state = get_value(vac, CHARGING_SIID, CHARGING_PIID)
    robot_state = get_value(vac, STATE_SIID, STATE_PIID)
    print(f"condition={args.condition}")
    print(f"charging_state={charge_state}")
    print(f"robot_state={robot_state}")

    if charge_state not in (CHARGING, FULLY_CHARGED):
        raise RuntimeError(
            "Refusing the trial because the robot is not docked "
            f"(charging_state={charge_state!r})"
        )

    if args.condition == "toggle":
        toggle_map(vac, args.hold_seconds)
        print("condition_applied=toggle")
    else:
        print(f"map_switch={get_value(vac, MAP_SIID, MAP_PIID)!r}")
        print("condition_applied=control")

    if not args.start_clean:
        print("cleaning_not_started=True")
        print("Re-run with --start-clean when ready to observe the fresh trajectory.")
        return

    if args.start_delay:
        print(f"starting_clean_in={args.start_delay}")
        time.sleep(args.start_delay)

    print("start_response=", vac.start())
    print("state_after_start=", get_value(vac, STATE_SIID, STATE_PIID))


if __name__ == "__main__":
    main()
