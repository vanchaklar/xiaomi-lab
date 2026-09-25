#!/usr/bin/env python3
"""Brute-force the MIoT property address space using read-only get_properties.

This deliberately does NOT brute-force actions. Calling an unknown AIID can move,
reset, dock, or otherwise change the vacuum. Property reads are the safe discovery
surface.

Examples:
    python experiments/miot_bruteforce.py
    python experiments/miot_bruteforce.py --siid-max 64 --piid-max 64
    python experiments/miot_bruteforce.py --exhaustive
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect, safe_info


DEFAULT_MAX = 32
EXHAUSTIVE_MAX = 255

CSV_FIELDS = [
    "timestamp_utc",
    "siid",
    "piid",
    "did",
    "code",
    "value_type",
    "value_json",
    "raw_json",
    "transport_error",
]


def chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def response_key(item):
    if not isinstance(item, dict):
        return None
    try:
        return int(item["siid"]), int(item["piid"])
    except (KeyError, TypeError, ValueError):
        return None


def request_batch(vac, probes, retries=1):
    """Query a batch, retry transient failures, then recursively split.

    Splitting prevents one problematic address from hiding the rest of a batch.
    """
    payload = [
        {
            "did": f"bf-{siid}-{piid}",
            "siid": siid,
            "piid": piid,
        }
        for siid, piid in probes
    ]

    last_exc = None
    for attempt in range(retries + 1):
        try:
            result = vac.raw_command("get_properties", payload)
            if not isinstance(result, list):
                raise RuntimeError(f"unexpected get_properties result: {result!r}")
            by_key = {
                key: item
                for item in result
                if (key := response_key(item)) is not None
            }
            return {
                probe: {
                    "item": by_key.get(probe),
                    "transport_error": None,
                }
                for probe in probes
            }
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.25)

    if len(probes) > 1:
        midpoint = len(probes) // 2
        left = request_batch(vac, probes[:midpoint], retries=retries)
        right = request_batch(vac, probes[midpoint:], retries=retries)
        return {**left, **right}

    return {
        probes[0]: {
            "item": None,
            "transport_error": f"{type(last_exc).__name__}: {last_exc}",
        }
    }


def json_value(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only brute-force scan of MIoT SIID/PIID property IDs"
    )
    parser.add_argument("--siid-min", type=int, default=1)
    parser.add_argument("--siid-max", type=int, default=DEFAULT_MAX)
    parser.add_argument("--piid-min", type=int, default=1)
    parser.add_argument("--piid-max", type=int, default=DEFAULT_MAX)
    parser.add_argument(
        "--exhaustive",
        action="store_true",
        help="scan SIID 1..255 and PIID 1..255",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="properties per get_properties request (default: 16)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="delay between batches in seconds (default: 0.05)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="transport retries before a failed batch is split (default: 1)",
    )
    parser.add_argument(
        "--print-all",
        action="store_true",
        help="print every result, not only successful/unusual responses",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path; defaults under data/",
    )
    args = parser.parse_args()

    if args.exhaustive:
        args.siid_min = 1
        args.siid_max = EXHAUSTIVE_MAX
        args.piid_min = 1
        args.piid_max = EXHAUSTIVE_MAX

    for name in ("siid_min", "siid_max", "piid_min", "piid_max"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")

    if args.siid_min > args.siid_max:
        parser.error("--siid-min cannot exceed --siid-max")
    if args.piid_min > args.piid_max:
        parser.error("--piid-min cannot exceed --piid-max")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    if args.retries < 0:
        parser.error("--retries must be >= 0")

    probes = [
        (siid, piid)
        for siid in range(args.siid_min, args.siid_max + 1)
        for piid in range(args.piid_min, args.piid_max + 1)
    ]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or (
        REPO_ROOT / "data" / f"miot_bruteforce_{stamp}.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    vac = connect()
    info = safe_info(vac)

    # Prime the session so startup discovery errors are less likely to be
    # mistaken for address-level failures.
    vac.info()

    print(
        f"device={info['model']} firmware={info['firmware_version']} "
        f"range=SIID {args.siid_min}..{args.siid_max}, "
        f"PIID {args.piid_min}..{args.piid_max}"
    )
    print(
        f"probes={len(probes)} batch_size={args.batch_size} "
        f"output={output}"
    )
    if args.exhaustive:
        print(
            "exhaustive scan: 65,025 read-only property addresses; "
            "this may take a while"
        )

    code_counts = Counter()
    successes = []
    unusual = []
    transport_errors = 0
    completed = 0
    started = time.monotonic()

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for batch_index, batch in enumerate(chunks(probes, args.batch_size), start=1):
            results = request_batch(vac, batch, retries=args.retries)

            for siid, piid in batch:
                result = results[(siid, piid)]
                item = result["item"]
                transport_error = result["transport_error"]

                if item is None:
                    code = None
                    value = None
                    raw = None
                    transport_errors += 1
                else:
                    code = item.get("code")
                    value = item.get("value")
                    raw = item

                code_counts[str(code)] += 1
                if code == 0:
                    successes.append((siid, piid, value))
                elif code not in (-4001, -4004, None):
                    unusual.append((siid, piid, code, raw))

                writer.writerow(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "siid": siid,
                        "piid": piid,
                        "did": f"bf-{siid}-{piid}",
                        "code": "" if code is None else code,
                        "value_type": "" if code != 0 else type(value).__name__,
                        "value_json": "" if code != 0 else json_value(value),
                        "raw_json": "" if raw is None else json_value(raw),
                        "transport_error": transport_error or "",
                    }
                )

                if args.print_all:
                    if transport_error:
                        print(f"{siid:3}/{piid:<3} TRANSPORT {transport_error}")
                    else:
                        print(
                            f"{siid:3}/{piid:<3} code={code:<6} "
                            f"value={value!r}"
                        )
                elif code == 0:
                    print(f"FOUND {siid}/{piid} = {value!r}")
                elif code not in (-4001, -4004, None):
                    print(f"UNUSUAL {siid}/{piid} code={code} raw={raw!r}")

                completed += 1

            handle.flush()

            if not args.print_all and (
                batch_index == 1 or completed == len(probes) or batch_index % 25 == 0
            ):
                elapsed = max(0.001, time.monotonic() - started)
                rate = completed / elapsed
                print(
                    f"progress={completed}/{len(probes)} "
                    f"({100 * completed / len(probes):.1f}%) "
                    f"rate={rate:.1f} addresses/s"
                )

            if args.delay and completed < len(probes):
                time.sleep(args.delay)

    elapsed = time.monotonic() - started

    print("\nsummary")
    print(f"elapsed_s={elapsed:.2f}")
    print(f"successful_properties={len(successes)}")
    print(f"unusual_nonzero_responses={len(unusual)}")
    print(f"transport_errors={transport_errors}")
    print("codes=" + json.dumps(dict(sorted(code_counts.items()))))
    print(f"csv={output}")

    if successes:
        print("\nsuccesses:")
        for siid, piid, value in successes:
            print(f"  {siid}/{piid} = {value!r}")

    if unusual:
        print("\nunusual responses:")
        for siid, piid, code, raw in unusual:
            print(f"  {siid}/{piid} code={code} raw={raw!r}")


if __name__ == "__main__":
    main()
