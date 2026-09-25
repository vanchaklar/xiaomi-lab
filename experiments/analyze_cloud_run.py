#!/usr/bin/env python3
"""Analyze a cloud_event_control/cloud_event_listener CSV offline.

Focuses on correlations already present in the captured cloud stream:
- fan-speed transitions (SIID 2 / PIID 6), useful as a carpet marker;
- vacuum status/fault transitions;
- clean area/time counters;
- map-point packets and their coordinate/type distribution;
- redraw boundaries and current-clean-record events.

The script is read-only and does not contact the vacuum or Xiaomi cloud.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


FAN = (2, 6)
STATUS = (2, 1)
FAULT = (2, 2)
CLEAN_AREA = (9, 1)
CLEAN_TIME = (9, 2)


def parse_payload(row):
    raw = row.get("payload_json") or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def property_value(payload):
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    return params.get("value")


def decode_map_points(payload):
    if not isinstance(payload, dict):
        return []
    params = payload.get("params")
    if not isinstance(params, dict):
        return []
    args = params.get("arguments")
    if not isinstance(args, list):
        return []

    for arg in args:
        if (
            isinstance(arg, dict)
            and arg.get("piid") == 1
            and isinstance(arg.get("value"), str)
        ):
            try:
                values = [int(v) for v in arg["value"].split()]
            except ValueError:
                return []
            if len(values) % 3:
                return []
            return [
                (values[i], values[i + 1], values[i + 2])
                for i in range(0, len(values), 3)
            ]
    return []


def summarize_points(points):
    if not points:
        return None
    xs = [x for x, _y, _t in points]
    ys = [y for _x, y, _t in points]
    types = Counter(t for _x, _y, t in points)
    return {
        "count": len(points),
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "types": dict(sorted(types.items())),
    }


def load_rows(path):
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            try:
                elapsed = float(row.get("elapsed_s") or 0.0)
            except ValueError:
                elapsed = 0.0
            try:
                siid = int(row["siid"]) if row.get("siid") else None
            except ValueError:
                siid = None
            try:
                iid = int(row["iid"]) if row.get("iid") else None
            except ValueError:
                iid = None
            payload = parse_payload(row)
            rows.append(
                {
                    "idx": idx,
                    "timestamp_utc": row.get("timestamp_utc") or "",
                    "elapsed_s": elapsed,
                    "kind": row.get("kind") or "",
                    "siid": siid,
                    "iid": iid,
                    "name": row.get("name") or "",
                    "payload": payload,
                }
            )
    return rows


def nearest_map(rows, at_idx, direction, limit_s):
    base_t = rows[at_idx]["elapsed_s"]
    step = 1 if direction > 0 else -1
    i = at_idx + step
    while 0 <= i < len(rows):
        dt = rows[i]["elapsed_s"] - base_t
        if abs(dt) > limit_s:
            return None
        row = rows[i]
        if row["kind"] == "event_occured" and (row["siid"], row["iid"]) == (7, 1):
            points = decode_map_points(row["payload"])
            return {
                "dt_s": dt,
                "summary": summarize_points(points),
                "points": points,
            }
        i += step
    return None


def recent_state(state, key):
    item = state.get(key)
    return None if item is None else item["value"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--map-window",
        type=float,
        default=5.0,
        help="seconds around each fan transition to inspect map packets (default: 5)",
    )
    parser.add_argument(
        "--show-map-points",
        action="store_true",
        help="print the actual nearest map triplets around fan transitions",
    )
    args = parser.parse_args()

    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit("empty CSV")

    state = {}
    fan_events = []
    redraws = 0
    map_packets = 0
    map_triplets = 0
    all_type_counts = Counter()
    challenge_hits = Counter()
    clean_records = []

    for i, row in enumerate(rows):
        key = (row["siid"], row["iid"])

        if row["kind"] == "properties_changed":
            value = property_value(row["payload"])
            old = state.get(key)
            state[key] = {
                "value": value,
                "elapsed_s": row["elapsed_s"],
                "timestamp_utc": row["timestamp_utc"],
            }

            if key == FAN:
                fan_events.append(
                    {
                        "idx": i,
                        "elapsed_s": row["elapsed_s"],
                        "timestamp_utc": row["timestamp_utc"],
                        "old": None if old is None else old["value"],
                        "new": value,
                        "status": recent_state(state, STATUS),
                        "fault": recent_state(state, FAULT),
                        "clean_area": recent_state(state, CLEAN_AREA),
                        "clean_time": recent_state(state, CLEAN_TIME),
                    }
                )

        elif row["kind"] == "event_occured" and key == (7, 1):
            points = decode_map_points(row["payload"])
            map_packets += 1
            map_triplets += len(points)
            all_type_counts.update(t for _x, _y, t in points)
            for x, y, point_type in points:
                if point_type == 4:
                    challenge_hits[(x, y)] += 1

        elif row["kind"] == "event_occured" and key == (7, 2):
            redraws += 1

        elif row["kind"] == "event_occured" and key == (9, 1):
            clean_records.append(row)

    first = rows[0]
    last = rows[-1]
    print(f"file={args.csv}")
    print(f"events={len(rows)} elapsed_s={last['elapsed_s'] - first['elapsed_s']:.3f}")
    print(
        f"map_packets={map_packets} map_triplets={map_triplets} "
        f"redraws={redraws} map_types={dict(sorted(all_type_counts.items()))}"
    )
    print(f"type4_unique_cells={len(challenge_hits)} type4_hits={sum(challenge_hits.values())}")
    print(f"fan_events={len(fan_events)} clean_record_events={len(clean_records)}")

    if not fan_events:
        print("\nNO FAN-SPEED (2/6) notifications are present in this CSV.")
        print(
            "The cloud subscription captured properties_changed, but this run did not "
            "contain a 2/6 notification. That means this file alone cannot timestamp "
            "the automatic carpet fan boost."
        )
    else:
        print("\nfan-speed transitions")
        for n, event in enumerate(fan_events, start=1):
            print(
                f"[{n}] t={event['elapsed_s']:.3f}s "
                f"{event['old']!r}->{event['new']!r} "
                f"status={event['status']!r} fault={event['fault']!r} "
                f"area={event['clean_area']!r} time={event['clean_time']!r}"
            )

            before = nearest_map(rows, event["idx"], -1, args.map_window)
            after = nearest_map(rows, event["idx"], 1, args.map_window)

            if before:
                print(
                    f"    map_before dt={before['dt_s']:.3f}s "
                    f"{before['summary']}"
                )
                if args.show_map_points:
                    print(f"      {before['points']}")
            else:
                print("    map_before: none in window")

            if after:
                print(
                    f"    map_after  dt=+{after['dt_s']:.3f}s "
                    f"{after['summary']}"
                )
                if args.show_map_points:
                    print(f"      {after['points']}")
            else:
                print("    map_after: none in window")

    if clean_records:
        print("\ncurrent-clean-record events")
        for row in clean_records:
            params = (row["payload"] or {}).get("params") or {}
            args_list = params.get("arguments") or []
            value = None
            for arg in args_list:
                if isinstance(arg, dict) and arg.get("piid") == 6:
                    value = arg.get("value")
                    break
            print(f"  t={row['elapsed_s']:.3f}s value={value!r}")


if __name__ == "__main__":
    main()
