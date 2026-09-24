#!/usr/bin/env python3
"""Guarded map-switch experiment for mijia.vacuum.v2.

Default mode is read-only. Pass --apply to toggle the map switch off and back on.
The experiment requires the robot to report that it is charging or fully charged,
so the dock provides a known physical pose.
"""

from __future__ import annotations

import argparse
import time

from vacuum import connect


MAP_SIID = 7
MAP_PIID = 2
CHARGING_SIID = 3
CHARGING_PIID = 2

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
    return item.get("value"), response


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read or briefly toggle the map switch while the robot is docked."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually set map_switch false then true; otherwise read only",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=2.0,
        help="seconds to keep map_switch disabled before restoring it (default: 2)",
    )
    args = parser.parse_args()

    if args.hold_seconds < 0:
        parser.error("--hold-seconds must be non-negative")

    vac = connect()

    charge_state, _ = get_value(vac, CHARGING_SIID, CHARGING_PIID)
    map_before, _ = get_value(vac, MAP_SIID, MAP_PIID)

    print(f"charging_state={charge_state}")
    print(f"map_switch_before={map_before!r}")

    if not args.apply:
        print("read-only mode; pass --apply to perform the reversible toggle")
        return

    if charge_state not in (CHARGING, FULLY_CHARGED):
        raise RuntimeError(
            "Refusing to modify map_switch because the robot is not docked "
            f"(charging_state={charge_state!r})"
        )

    original = bool(map_before)
    changed = False

    try:
        print("setting map_switch=False")
        print(set_value(vac, MAP_SIID, MAP_PIID, False))
        changed = True

        map_off, _ = get_value(vac, MAP_SIID, MAP_PIID)
        print(f"map_switch_after_disable={map_off!r}")
        if map_off is not False:
            raise RuntimeError("Device accepted the write but did not report map_switch=False")

        time.sleep(args.hold_seconds)

        print("setting map_switch=True")
        print(set_value(vac, MAP_SIID, MAP_PIID, True))

        map_on, _ = get_value(vac, MAP_SIID, MAP_PIID)
        print(f"map_switch_after_enable={map_on!r}")
        if map_on is not True:
            raise RuntimeError("Device accepted the write but did not report map_switch=True")

        print("toggle_completed=True")
    finally:
        # Restore the user's starting state if the experiment exits early.
        if changed:
            current, _ = get_value(vac, MAP_SIID, MAP_PIID)
            if bool(current) != original:
                print(f"restoring map_switch={original}")
                set_value(vac, MAP_SIID, MAP_PIID, original)
                restored, _ = get_value(vac, MAP_SIID, MAP_PIID)
                print(f"map_switch_restored={restored!r}")


if __name__ == "__main__":
    main()
