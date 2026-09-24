#!/usr/bin/env python3
"""Read-only inspection of the confirmed mijia.vacuum.v2 interface."""

from __future__ import annotations

import argparse
import inspect
from pprint import pprint

from vacuum import connect, safe_info


# Complete set of properties marked readable in the public mijia.vacuum.v2 MIoT spec.
# Event-only payloads (7/1, 9/6, 16/2) and write-only direction-key (8/1)
# are intentionally excluded here.
READ_ONLY_PROBES = [
    ("vacuum", "status", 2, 1),
    ("vacuum", "fault", 2, 2),
    ("vacuum", "operating_mode", 2, 4),
    ("vacuum", "water_level", 2, 5),
    ("vacuum", "fan_level", 2, 6),

    ("battery", "battery", 3, 1),
    ("battery", "charging_state", 3, 2),

    ("alarm", "alarm", 4, 1),
    ("alarm", "volume", 4, 2),

    ("map", "map_switch", 7, 2),

    ("clean_record", "clean_area", 9, 1),
    ("clean_record", "clean_time", 9, 2),
    ("clean_record", "total_clean_area", 9, 3),
    ("clean_record", "total_clean_time", 9, 4),
    ("clean_record", "total_clean_count", 9, 5),

    ("filter", "filter_life_level", 11, 1),
    ("filter", "filter_time_left", 11, 2),

    ("language", "language", 12, 1),
    ("language", "dnd_switch", 12, 2),
    ("language", "dnd_time", 12, 3),
    ("language", "timezone", 12, 4),

    ("main_brush", "main_brush_life_level", 14, 1),
    ("main_brush", "main_brush_time_left", 14, 2),

    ("side_brush", "side_brush_life_level", 15, 1),
    ("side_brush", "side_brush_time_left", 15, 2),

    ("other_status", "mop_state", 16, 1),
]


def print_methods(vac) -> None:
    for name, obj in inspect.getmembers(vac):
        if not callable(obj) or name.startswith("_"):
            continue
        try:
            signature = inspect.signature(obj)
        except (TypeError, ValueError):
            signature = ""
        print(f"{name}{signature}")


def probe_properties(vac) -> None:
    ok = 0
    failed = 0

    print(f"probing {len(READ_ONLY_PROBES)} readable properties")
    print(f"{'service':14} {'property':28} {'id':8} result")
    print("-" * 90)

    for service, name, siid, piid in READ_ONLY_PROBES:
        try:
            response = vac.get_property_by(siid, piid)
            item = response[0] if response else {}
            code = item.get("code")
            value = item.get("value")

            if code == 0:
                ok += 1
                result = repr(value)
            else:
                failed += 1
                result = f"ERROR code={code} raw={response!r}"

            print(f"{service:14} {name:28} {f'{siid}/{piid}':8} {result}")
        except Exception as exc:
            failed += 1
            print(
                f"{service:14} {name:28} {f'{siid}/{piid}':8} "
                f"EXCEPTION {type(exc).__name__}: {exc}"
            )

    print("-" * 90)
    print(f"successful={ok} failed={failed} total={len(READ_ONLY_PROBES)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--methods", action="store_true", help="list callable Python API methods")
    parser.add_argument("--mapping", action="store_true", help="print python-miio's built-in G1 mapping")
    parser.add_argument(
        "--properties",
        action="store_true",
        help="probe all properties marked readable by the mijia.vacuum.v2 MIoT spec",
    )
    args = parser.parse_args()

    vac = connect()

    print("info:")
    pprint(safe_info(vac))

    if args.methods:
        print("\nmethods:")
        print_methods(vac)

    if args.mapping:
        print("\npython-miio mapping:")
        pprint(vac._get_mapping())

    if args.properties:
        print("\nMIoT readable property probes:")
        probe_properties(vac)

    if not (args.methods or args.mapping or args.properties):
        print("\nUse --methods, --mapping, or --properties for additional read-only inspection.")


if __name__ == "__main__":
    main()
