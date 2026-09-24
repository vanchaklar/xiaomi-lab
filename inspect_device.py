#!/usr/bin/env python3
"""Read-only inspection of the confirmed mijia.vacuum.v2 interface."""

from __future__ import annotations

import argparse
import inspect
from pprint import pprint

from vacuum import connect


# Properties from the public mijia.vacuum.v2 MIoT specification that are readable.
READ_ONLY_PROBES = [
    ("status", 2, 1),
    ("fault", 2, 2),
    ("operating_mode", 2, 4),
    ("water_level", 2, 5),
    ("fan_level", 2, 6),
    ("battery", 3, 1),
    ("charging_state", 3, 2),
    ("alarm", 4, 1),
    ("volume", 4, 2),
    ("map_switch", 7, 2),
    ("language", 12, 1),
    ("dnd_switch", 12, 2),
    ("dnd_time", 12, 3),
    ("timezone", 12, 4),
    ("mop_state", 16, 1),
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
    for name, siid, piid in READ_ONLY_PROBES:
        try:
            value = vac.get_property_by(siid, piid)
            print(f"{name:18} ({siid},{piid}) => {value!r}")
        except Exception as exc:
            print(f"{name:18} ({siid},{piid}) => ERROR: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--methods", action="store_true", help="list callable Python API methods")
    parser.add_argument("--mapping", action="store_true", help="print python-miio's built-in G1 mapping")
    parser.add_argument("--properties", action="store_true", help="probe known readable MIoT properties")
    args = parser.parse_args()

    vac = connect()

    print("info:")
    print(vac.info())

    if args.methods:
        print("\nmethods:")
        print_methods(vac)

    if args.mapping:
        print("\npython-miio mapping:")
        pprint(vac._get_mapping())

    if args.properties:
        print("\nMIoT property probes:")
        probe_properties(vac)

    if not (args.methods or args.mapping or args.properties):
        print("\nUse --methods, --mapping, or --properties for additional read-only inspection.")


if __name__ == "__main__":
    main()
