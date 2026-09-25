#!/usr/bin/env python3
"""Listen for MIoT LAN push events from mijia.vacuum.v2.

The listener keeps one UDP socket open, probes the vacuum's LAN subscription
capability, optionally negotiates miIO.sub, decrypts device-initiated uplinks,
ACKs them, and logs event_occured / properties_changed payloads.

It does not modify cleaning settings or start movement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import secrets
import signal
import socket
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect


OT_PORT = 54321
OT_HEADER = 0x2131
OT_PROBE_LEN = 32
OT_SUPPORT_WILDCARD_SUB = 0xFE
MAX_PACKET = 4096

CSV_FIELDS = [
    "timestamp_utc",
    "elapsed_s",
    "kind",
    "siid",
    "iid",
    "name",
    "payload_json",
]

EVENT_NAMES = {
    (7, 1): "map_points",
    (7, 2): "redraw_map",
    (9, 1): "current_clean_record",
    (16, 1): "temp_log",
}


def md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()  # nosec - protocol-defined checksum


def key_iv(token: bytes) -> tuple[bytes, bytes]:
    key = md5(token)
    return key, md5(key + token)


def encrypt_payload(token: bytes, payload: dict) -> bytes:
    clear = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(clear) + padder.finalize()
    key, iv = key_iv(token)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()


def decrypt_payload(token: bytes, packet: bytes) -> dict:
    if len(packet) < 32:
        raise ValueError("packet too short")
    declared = struct.unpack(">H", packet[2:4])[0]
    if declared != len(packet):
        raise ValueError(f"length mismatch: header={declared} actual={len(packet)}")

    packet_for_hash = bytearray(packet)
    original = bytes(packet_for_hash[16:32])
    packet_for_hash[16:32] = token
    calculated = md5(bytes(packet_for_hash))

    if original != calculated:
        raise ValueError("packet MD5 mismatch")

    key, iv = key_iv(token)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(packet[32:]) + dec.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    clear = unpadder.update(padded) + unpadder.finalize()
    clear = clear.rstrip(b"\x00")
    return json.loads(clear)


def build_packet(
    *,
    did: int,
    token: bytes,
    timestamp: int,
    payload: dict,
) -> bytes:
    encrypted = encrypt_payload(token, payload)
    length = 32 + len(encrypted)

    header = bytearray(
        struct.pack(
            ">HHQI16s",
            OT_HEADER,
            length,
            did,
            timestamp & 0xFFFFFFFF,
            token,
        )
    )
    packet = header + encrypted
    packet[16:32] = md5(bytes(packet))
    return bytes(packet)


def build_probe(virtual_did: int) -> bytes:
    packet = bytearray(32)
    packet[:20] = b"!1\x00\x20" + b"\xff" * 12 + b"MDID"
    packet[20:28] = struct.pack(">Q", virtual_did)
    packet[28:32] = b"\x00\x00\x00\x00"
    return bytes(packet)


def parse_probe(packet: bytes) -> dict:
    if len(packet) != OT_PROBE_LEN:
        raise ValueError(f"expected 32-byte probe response, got {len(packet)}")

    magic, length = struct.unpack(">HH", packet[:4])
    if magic != OT_HEADER or length != OT_PROBE_LEN:
        raise ValueError("not an OT probe response")

    did = struct.unpack(">Q", packet[4:12])[0]
    timestamp = struct.unpack(">I", packet[12:16])[0]

    advertises_sub = (
        packet[16:20] == b"MSUB"
        and packet[24:27] == b"PUB"
    )
    sub_ts = struct.unpack(">I", packet[20:24])[0] if advertises_sub else None
    sub_type = packet[27] if advertises_sub else None
    capability_byte = packet[28] if advertises_sub else None
    wildcard = (
        advertises_sub
        and capability_byte == OT_SUPPORT_WILDCARD_SUB
    )

    return {
        "did": did,
        "timestamp": timestamp,
        "advertises_sub": advertises_sub,
        "sub_ts": sub_ts,
        "sub_type": sub_type,
        "capability_byte": capability_byte,
        "wildcard": wildcard,
        "raw_hex": packet.hex(),
    }


class Listener:
    def __init__(
        self,
        ip: str,
        token_hex: str,
        output: Path,
        *,
        virtual_did: int | None = None,
        timeout: float = 1.0,
        probe_interval: float = 10.0,
        sub_method: str = ".",
    ):
        self.ip = ip
        self.token = bytes.fromhex(token_hex)
        self.virtual_did = virtual_did or secrets.randbits(64) or 1
        self.timeout = timeout
        self.probe_interval = probe_interval
        self.sub_method = sub_method

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(timeout)

        self.device_did: int | None = None
        self.device_offset = 0
        self.sub_ts: int | None = None
        self.subscribed = False
        self.msg_id = secrets.randbelow(0x3FFFFFFF) + 1
        self.stop_requested = False
        self.started = time.monotonic()
        self.last_probe = 0.0

        output.parent.mkdir(parents=True, exist_ok=True)
        self.output = output
        self.handle = output.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=CSV_FIELDS)
        self.writer.writeheader()
        self.handle.flush()

    def next_id(self) -> int:
        self.msg_id += 1
        if self.msg_id > 0x7FFFFFFF:
            self.msg_id = 1
        return self.msg_id

    def device_timestamp(self) -> int:
        return int(time.time()) - self.device_offset

    def send_probe(self) -> None:
        self.sock.sendto(build_probe(self.virtual_did), (self.ip, OT_PORT))
        self.last_probe = time.monotonic()

    def wait_for_probe(self, wait_seconds: float = 5.0) -> dict:
        deadline = time.monotonic() + wait_seconds
        self.send_probe()

        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            self.sock.settimeout(min(self.timeout, remaining))
            try:
                packet, addr = self.sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                self.send_probe()
                continue

            if addr[0] != self.ip:
                continue

            if len(packet) == OT_PROBE_LEN:
                info = parse_probe(packet)
                self.device_did = info["did"]
                self.device_offset = int(time.time()) - info["timestamp"]
                return info

        raise TimeoutError("no MDID probe response from the vacuum")

    def send_message(self, payload: dict) -> None:
        if self.device_did is None:
            raise RuntimeError("device DID not established")
        packet = build_packet(
            did=self.device_did,
            token=self.token,
            timestamp=self.device_timestamp(),
            payload=payload,
        )
        self.sock.sendto(packet, (self.ip, OT_PORT))

    def subscribe(self) -> dict:
        self.sub_ts = int(time.time())
        msg_id = self.next_id()
        request = {
            "id": msg_id,
            "from": "xiaomi-lab",
            "method": "miIO.sub",
            "params": {
                "version": "2.0",
                "did": str(self.virtual_did),
                "update_ts": self.sub_ts,
                "sub_method": self.sub_method,
            },
        }
        self.send_message(request)

        response = self.wait_for_id(msg_id, 5.0)
        result = response.get("result")
        ok = isinstance(result, dict) and result.get("code") == 0
        self.subscribed = ok
        if not ok:
            raise RuntimeError(
                f"miIO.sub rejected for sub_method={self.sub_method!r}: {response!r}"
            )
        return response

    def unsubscribe(self) -> None:
        if not self.subscribed or self.device_did is None:
            return

        msg_id = self.next_id()
        request = {
            "id": msg_id,
            "from": "xiaomi-lab",
            "method": "miIO.unsub",
            "params": {
                "version": "2.0",
                "did": str(self.virtual_did),
                "update_ts": self.sub_ts or 0,
                "sub_method": self.sub_method,
            },
        }
        try:
            self.send_message(request)
            self.wait_for_id(msg_id, 2.0)
        except Exception as exc:
            print(f"unsubscribe warning: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            self.subscribed = False

    def ack(self, msg_id: int) -> None:
        self.send_message({"id": msg_id, "result": {"code": 0}})

    def wait_for_id(self, wanted_id: int, wait_seconds: float) -> dict:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            self.sock.settimeout(min(self.timeout, remaining))
            try:
                packet, addr = self.sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                continue

            if addr[0] != self.ip:
                continue

            if len(packet) == OT_PROBE_LEN:
                try:
                    info = parse_probe(packet)
                    self.device_offset = int(time.time()) - info["timestamp"]
                except Exception:
                    pass
                continue

            msg = decrypt_payload(self.token, packet)
            if msg.get("id") == wanted_id:
                return msg

            self.handle_uplink(msg)

        raise TimeoutError(f"timeout waiting for message id {wanted_id}")

    def log_event(
        self,
        *,
        kind: str,
        siid: int | None,
        iid: int | None,
        name: str,
        payload,
    ) -> None:
        self.writer.writerow(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": f"{time.monotonic() - self.started:.6f}",
                "kind": kind,
                "siid": "" if siid is None else siid,
                "iid": "" if iid is None else iid,
                "name": name,
                "payload_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
        self.handle.flush()

    def handle_uplink(self, msg: dict) -> None:
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params")

        if not isinstance(msg_id, int) or method is None or params is None:
            print("unmatched packet:", json.dumps(msg, ensure_ascii=False))
            return

        if method == "event_occured" and isinstance(params, dict):
            siid = params.get("siid")
            eiid = params.get("eiid")
            name = EVENT_NAMES.get((siid, eiid), "event")
            arguments = params.get("arguments")
            print(
                f"EVENT {siid}/{eiid} {name}: "
                f"{json.dumps(arguments, ensure_ascii=False)}"
            )
            self.log_event(
                kind="event_occured",
                siid=siid,
                iid=eiid,
                name=name,
                payload=params,
            )
            self.ack(msg_id)
            return

        if method == "properties_changed" and isinstance(params, list):
            for prop in params:
                if not isinstance(prop, dict):
                    continue
                siid = prop.get("siid")
                piid = prop.get("piid")
                print(
                    f"PROP {siid}/{piid}: "
                    f"{json.dumps(prop.get('value'), ensure_ascii=False)}"
                )
                self.log_event(
                    kind="properties_changed",
                    siid=siid,
                    iid=piid,
                    name="property",
                    payload=prop,
                )
            self.ack(msg_id)
            return

        print(
            f"UPLINK {method}: "
            f"{json.dumps(params, ensure_ascii=False)}"
        )
        self.log_event(
            kind=str(method),
            siid=None,
            iid=None,
            name="uplink",
            payload=params,
        )
        self.ack(msg_id)

    def run(self, duration: float | None = None) -> None:
        deadline = None if duration is None else time.monotonic() + duration
        self.sock.settimeout(self.timeout)

        while not self.stop_requested:
            if deadline is not None and time.monotonic() >= deadline:
                return

            now = time.monotonic()
            if now - self.last_probe >= self.probe_interval:
                self.send_probe()

            try:
                packet, addr = self.sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                continue

            if addr[0] != self.ip:
                continue

            if len(packet) == OT_PROBE_LEN:
                try:
                    info = parse_probe(packet)
                    self.device_offset = int(time.time()) - info["timestamp"]
                except Exception as exc:
                    print(f"probe parse warning: {exc}", file=sys.stderr)
                continue

            try:
                msg = decrypt_payload(self.token, packet)
            except Exception as exc:
                print(f"decrypt warning: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            self.handle_uplink(msg)

    def close(self) -> None:
        try:
            self.unsubscribe()
        finally:
            self.handle.close()
            self.sock.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="optional listen duration in seconds; default is until Ctrl-C",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV path; defaults to data/lan_events_<timestamp>.csv",
    )
    parser.add_argument(
        "--sub-method",
        default=".",
        help=(
            "miIO.sub method filter. '.' is Xiaomi's wildcard form; for older "
            "non-wildcard devices test 'event_occured' or 'properties_changed'"
        ),
    )
    parser.add_argument(
        "--allow-no-wildcard",
        action="store_true",
        help=(
            "allow sub_method='.' even when the probe does not advertise "
            "wildcard support; explicit --sub-method values do not need this flag"
        ),
    )
    args = parser.parse_args()

    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    if not args.sub_method:
        parser.error("--sub-method cannot be empty")

    vac = connect()
    info = vac.info()
    ip = vac.ip
    token = vac.token

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or (REPO_ROOT / "data" / f"lan_events_{stamp}.csv")

    listener = Listener(ip, token, output, sub_method=args.sub_method)

    def request_stop(_signum=None, _frame=None):
        listener.stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print(f"device={info.model} firmware={info.firmware_version}")
    print(f"local_udp_port={listener.sock.getsockname()[1]}")
    print(f"virtual_did={listener.virtual_did}")
    print(f"sub_method={args.sub_method!r}")
    print("probing MIoT LAN push capability...")

    try:
        probe = listener.wait_for_probe()
        print(
            "probe="
            + json.dumps(
                {
                    "did": probe["did"],
                    "advertises_sub": probe["advertises_sub"],
                    "sub_type": probe["sub_type"],
                    "capability_byte": probe["capability_byte"],
                    "wildcard": probe["wildcard"],
                },
                separators=(",", ":"),
            )
        )

        if (
            args.sub_method == "."
            and not probe["wildcard"]
            and not args.allow_no_wildcard
        ):
            raise RuntimeError(
                "device advertises subscriptions but not wildcard sub_method='.'; "
                "try --sub-method event_occured"
            )

        response = listener.subscribe()
        print("subscribe_response=" + json.dumps(response, separators=(",", ":")))
        print(f"csv={output}")
        print("listening for device uplinks; Ctrl-C to stop")

        listener.run(args.duration)
    finally:
        listener.close()


if __name__ == "__main__":
    main()
