#!/usr/bin/env python3
"""Listen to Xiaomi Cloud MIoT events for the vacuum.

This targets the same cloud MIPS/MQTT event channel used by Xiaomi's current
Home Assistant integration:

    device/<did>/up/event_occured/<siid>/<eiid>

First-time use performs Xiaomi OAuth in the terminal and stores the resulting
OAuth token under data/ (gitignored). The local vacuum token remains in .env.

This experiment does not send cleaning actions or modify vacuum settings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
import ssl
import sys
import threading
import time
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect, safe_info


OAUTH_CLIENT_ID = "2882303761520251711"
OAUTH_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
OAUTH_API_HOST = "ha.api.io.mi.com"
MQTT_HOST = "ha.mqtt.io.mi.com"
MQTT_PORT = 8883

REGIONS = ("cn", "de", "i2", "ru", "sg", "us")
REGION_CHOICES = (*REGIONS, "all")

AUTH_PATH = REPO_ROOT / "data" / "xiaomi_cloud_auth.json"

EVENT_NAMES = {
    (7, 1): "map_points",
    (7, 2): "redraw_map",
    (9, 1): "current_clean_record",
    (16, 1): "temp_log",
}

CSV_FIELDS = [
    "timestamp_utc",
    "elapsed_s",
    "topic",
    "kind",
    "siid",
    "iid",
    "name",
    "payload_json",
]


def api_host(region: str) -> str:
    return OAUTH_API_HOST if region == "cn" else f"{region}.{OAUTH_API_HOST}"


def mqtt_host(region: str) -> str:
    return f"{region}-{MQTT_HOST}"


def oauth_redirect_url(run_uuid: str) -> str:
    # Xiaomi's registered Home Assistant OAuth client accepts webhook paths
    # under this redirect origin.
    return (
        "http://homeassistant.local:8123/api/webhook/"
        f"xiaomi-lab-{run_uuid}"
    )


def oauth_state(run_uuid: str) -> str:
    device_id = f"ha.{run_uuid}"
    return hashlib.sha1(f"d={device_id}".encode("utf-8")).hexdigest()


def auth_url(region: str, run_uuid: str) -> tuple[str, str, str]:
    redirect = oauth_redirect_url(run_uuid)
    state = oauth_state(run_uuid)
    params = {
        "redirect_uri": redirect,
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "device_id": f"ha.{run_uuid}",
        "state": state,
        "skip_confirm": "false",
    }
    return f"{OAUTH_AUTH_URL}?{urlencode(params)}", redirect, state


def cloud_api_post(region: str, access_token: str, path: str, data: dict) -> dict:
    url = f"https://{api_host(region)}{path}"
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Host": api_host(region),
            "X-Client-BizId": "haapi",
            "Content-Type": "application/json",
            "Authorization": f"Bearer{access_token}",
            "X-Client-AppId": OAUTH_CLIENT_ID,
        },
        method="POST",
    )

    with urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    obj = json.loads(raw)
    if obj.get("code") != 0:
        raise RuntimeError(f"Xiaomi cloud API failed: {obj!r}")
    return obj


def get_cloud_devices(region: str, access_token: str) -> list[dict]:
    devices: list[dict] = []
    start_did = None

    while True:
        data = {
            "limit": 200,
            "get_split_device": True,
            "get_third_device": True,
            "dids": [],
        }
        if start_did:
            data["start_did"] = start_did

        obj = cloud_api_post(
            region,
            access_token,
            "/app/v2/home/device_list_page",
            data,
        )
        result = obj.get("result") or {}
        devices.extend(result.get("list") or [])

        if not result.get("has_more"):
            break
        start_did = result.get("next_start_did")
        if not start_did:
            break

    return devices


def token_request(region: str, data: dict) -> dict:
    query = urlencode({"data": json.dumps(data, separators=(",", ":"))})
    url = f"https://{api_host(region)}/app/v2/ha/oauth/get_token?{query}"
    req = Request(
        url,
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="GET",
    )

    with urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    obj = json.loads(raw)
    if obj.get("code") != 0 or not isinstance(obj.get("result"), dict):
        raise RuntimeError(f"OAuth token exchange failed: {obj!r}")

    result = obj["result"]
    if "access_token" not in result:
        raise RuntimeError(f"OAuth response has no access_token: {obj!r}")

    expires_in = int(result.get("expires_in", 0))
    return {
        **result,
        "expires_ts": int(time.time()) + expires_in,
    }


def save_auth(auth: dict) -> None:
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_PATH.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(AUTH_PATH, 0o600)
    except OSError:
        pass


def load_auth(region: str) -> dict | None:
    if not AUTH_PATH.exists():
        return None
    try:
        auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if auth.get("region") != region:
        return None
    return auth


def parse_oauth_code(value: str, expected_state: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("empty OAuth result")

    if "://" not in value:
        return value

    parsed = urlparse(value)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]

    if not code:
        raise ValueError("redirect URL does not contain code=")
    if state and state != expected_state:
        raise ValueError("OAuth state mismatch")
    return code


def interactive_login(region: str) -> dict:
    run_uuid = uuidlib.uuid4().hex
    url, redirect, expected_state = auth_url(region, run_uuid)

    print("\nOpen this URL in a browser and authorize Xiaomi Home:")
    print(url)
    print()
    print(
        "The final redirect may fail to load at homeassistant.local. "
        "That is fine. Copy the final address-bar URL and paste it here."
    )
    entered = input("redirect URL or code> ")
    code = parse_oauth_code(entered, expected_state)

    token = token_request(
        region,
        {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": redirect,
            "code": code,
            "device_id": f"ha.{run_uuid}",
        },
    )

    auth = {
        "region": region,
        "uuid": run_uuid,
        "redirect_url": redirect,
        **token,
    }
    save_auth(auth)
    return auth


def refresh_auth(auth: dict) -> dict:
    refresh_token = auth.get("refresh_token")
    if not refresh_token:
        return auth

    token = token_request(
        auth["region"],
        {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": auth["redirect_url"],
            "refresh_token": refresh_token,
        },
    )
    refreshed = {**auth, **token}
    save_auth(refreshed)
    return refreshed


def get_auth(region: str, force_login: bool = False) -> dict:
    env_token = os.environ.get("XIAOMI_CLOUD_ACCESS_TOKEN", "").strip()
    env_uuid = os.environ.get("XIAOMI_CLOUD_UUID", "").strip()

    if env_token:
        return {
            "region": region,
            "uuid": env_uuid or uuidlib.uuid4().hex,
            "access_token": env_token,
            "expires_ts": 0,
        }

    auth = None if force_login else load_auth(region)
    if auth is None:
        return interactive_login(region)

    expires_ts = int(auth.get("expires_ts", 0) or 0)
    if expires_ts and expires_ts <= int(time.time()) + 300:
        try:
            auth = refresh_auth(auth)
            print("OAuth token refreshed")
        except Exception as exc:
            print(
                f"OAuth refresh failed ({type(exc).__name__}: {exc}); "
                "starting a new login"
            )
            auth = interactive_login(region)

    return auth


def decode_topic(topic: str) -> tuple[str, int | None, int | None, str]:
    parts = topic.split("/")

    try:
        up_index = parts.index("up")
    except ValueError:
        return "unknown", None, None, "unknown"

    if up_index + 1 >= len(parts):
        return "unknown", None, None, "unknown"

    kind = parts[up_index + 1]

    try:
        siid = int(parts[up_index + 2])
        iid = int(parts[up_index + 3])
    except (IndexError, ValueError):
        siid = None
        iid = None

    if kind == "event_occured":
        name = EVENT_NAMES.get((siid, iid), "event")
    elif kind == "properties_changed":
        name = "property"
    else:
        name = kind

    return kind, siid, iid, name


class CloudListener:
    def __init__(
        self,
        *,
        region: str,
        run_uuid: str,
        access_token: str,
        did: str,
        output: Path,
        debug: bool = False,
        event_callback=None,
    ) -> None:
        self.region = region
        self.did = did
        self.output = output
        self.started = time.monotonic()
        self.connected = threading.Event()
        self.subscribe_complete = threading.Event()
        self.failed_reason: str | None = None
        self.subscription_mids: dict[int, str] = {}
        self.subscription_results: dict[str, tuple[bool, str]] = {}
        self.debug = debug
        self.event_callback = event_callback

        output.parent.mkdir(parents=True, exist_ok=True)
        self.handle = output.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=CSV_FIELDS)
        self.writer.writeheader()
        self.handle.flush()

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha.{run_uuid}",
            protocol=mqtt.MQTTv5,
        )
        self.client.username_pw_set(
            username=OAUTH_CLIENT_ID,
            password=access_token,
        )
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.tls_insecure_set(False)

        self.client.on_connect = self.on_connect
        self.client.on_connect_fail = self.on_connect_fail
        self.client.on_disconnect = self.on_disconnect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message

        if debug:
            self.client.enable_logger()

    @property
    def topics(self) -> list[tuple[str, int]]:
        return [
            (f"device/{self.did}/up/event_occured/#", 2),
            (f"device/{self.did}/up/properties_changed/#", 2),
        ]

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            self.failed_reason = f"MQTT connect rejected: {reason_code}"
            self.connected.set()
            return

        print(f"mqtt_connected={mqtt_host(self.region)}:{MQTT_PORT}")
        self.connected.set()

        for topic, qos in self.topics:
            result, mid = client.subscribe(topic, qos=qos)
            self.subscription_mids[mid] = topic
            print(f"subscribe topic={topic} result={result} mid={mid}")

    def on_connect_fail(self, client, userdata):
        self.failed_reason = "MQTT TCP/TLS connection failed"
        self.connected.set()

    def on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):
        if reason_code != 0:
            print(f"mqtt_disconnected reason={reason_code}", file=sys.stderr)

    def on_subscribe(
        self,
        client,
        userdata,
        mid,
        reason_code_list,
        properties,
    ):
        printable = [str(code) for code in reason_code_list]
        topic = self.subscription_mids.get(mid, f"mid:{mid}")

        success = True
        for code in reason_code_list:
            value = getattr(code, "value", None)
            if isinstance(value, int):
                success = success and value < 128
            else:
                text = str(code)
                success = success and (
                    text.startswith("Granted QoS")
                    or text in {"Success", "No subscription existed"}
                )

        self.subscription_results[topic] = (success, ",".join(printable))
        print(
            f"subscribed topic={topic} mid={mid} "
            f"accepted={str(success).lower()} reason_codes={printable}"
        )

        if len(self.subscription_results) >= len(self.topics):
            self.subscribe_complete.set()

    def on_message(self, client, userdata, msg):
        try:
            raw = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            raw = json.dumps({"hex": msg.payload.hex()})

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}

        kind, siid, iid, name = decode_topic(msg.topic)

        # Some broker messages carry the IDs only inside params.
        if isinstance(payload, dict):
            params = payload.get("params")
            if isinstance(params, dict):
                if siid is None and isinstance(params.get("siid"), int):
                    siid = params["siid"]
                if iid is None:
                    key = "eiid" if kind == "event_occured" else "piid"
                    if isinstance(params.get(key), int):
                        iid = params[key]
                if kind == "event_occured":
                    name = EVENT_NAMES.get((siid, iid), name)

        compact = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        print(f"CLOUD {kind} {siid}/{iid} {name}: {compact}")

        event_record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": f"{time.monotonic() - self.started:.6f}",
            "topic": msg.topic,
            "kind": kind,
            "siid": siid,
            "iid": iid,
            "name": name,
            "payload": payload,
        }
        if self.event_callback is not None:
            try:
                self.event_callback(self.region, event_record)
            except Exception as exc:
                print(
                    f"event_callback_error={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        self.writer.writerow(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": f"{time.monotonic() - self.started:.6f}",
                "topic": msg.topic,
                "kind": kind,
                "siid": "" if siid is None else siid,
                "iid": "" if iid is None else iid,
                "name": name,
                "payload_json": compact,
            }
        )
        self.handle.flush()

    def start(self) -> None:
        host = mqtt_host(self.region)
        print(f"mqtt_host={host}:{MQTT_PORT}")
        self.client.connect(host, MQTT_PORT, keepalive=60)
        self.client.loop_start()

        if not self.connected.wait(15):
            raise TimeoutError("timed out waiting for MQTT connection")
        if self.failed_reason:
            raise RuntimeError(self.failed_reason)

        if not self.subscribe_complete.wait(10):
            raise TimeoutError("timed out waiting for MQTT SUBACKs")

        event_topic = f"device/{self.did}/up/event_occured/#"
        event_result = self.subscription_results.get(event_topic)
        if not event_result or not event_result[0]:
            detail = "; ".join(
                f"{topic}={reason}"
                for topic, (_ok, reason) in self.subscription_results.items()
            )
            raise RuntimeError(
                "broker connected but event subscription was rejected"
                + (f": {detail}" if detail else "")
            )

        property_topic = f"device/{self.did}/up/properties_changed/#"
        property_result = self.subscription_results.get(property_topic)
        if property_result and not property_result[0]:
            print(
                f"property_subscription_rejected={property_result[1]} "
                "(event stream is still usable)"
            )

    def stop(self) -> None:
        try:
            self.client.disconnect()
            self.client.loop_stop()
        finally:
            self.handle.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--region",
        default=os.environ.get("XIAOMI_CLOUD_REGION"),
        choices=REGION_CHOICES,
        help="Mi Home region: cn/de/i2/ru/sg/us, or all to probe every broker",
    )
    parser.add_argument(
        "--auth-region",
        default=os.environ.get("XIAOMI_CLOUD_AUTH_REGION"),
        choices=REGIONS,
        help=(
            "OAuth region when --region all is used. On later runs this can be "
            "omitted if data/xiaomi_cloud_auth.json already identifies the region."
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60,
        help="listen duration in seconds (default: 60; 0 = until Ctrl-C)",
    )
    parser.add_argument(
        "--did",
        default=None,
        help="override cloud DID; default is the local miIO device id",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="force a new Xiaomi OAuth login",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="authenticate and save the OAuth token, then exit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV path; defaults under data/",
    )
    parser.add_argument(
        "--start-cleaning",
        action="store_true",
        help=(
            "start cleaning after the cloud event subscription is confirmed; "
            "the script sends stop when the capture ends"
        ),
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.region:
        parser.error(
            "--region is required unless XIAOMI_CLOUD_REGION is set "
            "(cn/de/i2/ru/sg/us/all)"
        )
    if args.duration < 0:
        parser.error("--duration must be >= 0")

    cached_auth = None
    if AUTH_PATH.exists():
        try:
            cached_auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        except Exception:
            cached_auth = None

    if args.region == "all":
        auth_region = args.auth_region
        if not auth_region and isinstance(cached_auth, dict):
            cached_region = cached_auth.get("region")
            if cached_region in REGIONS:
                auth_region = cached_region
        if not auth_region:
            parser.error(
                "--region all needs --auth-region on the first login, for example "
                "--region all --auth-region de --login"
            )
        mqtt_regions = list(REGIONS)
    else:
        auth_region = args.auth_region or args.region
        mqtt_regions = [args.region]

    auth = get_auth(auth_region, force_login=args.login)
    print(
        f"cloud_auth=ok auth_region={auth_region} "
        f"cached={AUTH_PATH.exists() and not bool(os.environ.get('XIAOMI_CLOUD_ACCESS_TOKEN'))}"
    )

    if args.auth_only:
        return

    vac = connect()
    info = safe_info(vac)
    local_did = str(vac.device_id)

    if args.did:
        did = args.did
        print(f"did_source=override did={did}")
    else:
        did = local_did
        try:
            cloud_devices = get_cloud_devices(auth_region, auth["access_token"])
            model_matches = [
                device
                for device in cloud_devices
                if device.get("model") == info["model"]
            ]
            exact = [
                device
                for device in model_matches
                if str(device.get("did")) == local_did
            ]
            if exact:
                did = str(exact[0]["did"])
                print(f"did_source=cloud_exact did={did}")
            elif len(model_matches) == 1:
                did = str(model_matches[0]["did"])
                print(
                    f"did_source=cloud_model_match did={did} "
                    f"local_did={local_did}"
                )
            elif model_matches:
                print(
                    "cloud_did_ambiguous="
                    + ",".join(str(device.get("did")) for device in model_matches)
                    + f"; using local_did={local_did}"
                )
            else:
                print(
                    f"cloud_device_match=none model={info['model']}; "
                    f"using local_did={local_did}"
                )
        except Exception as exc:
            print(
                f"cloud_device_lookup_failed={type(exc).__name__}: {exc}; "
                f"using local_did={local_did}"
            )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_output = args.output

    print(f"device={info['model']} firmware={info['firmware_version']}")
    print(f"did={did}")

    def output_for_region(region: str) -> Path:
        if base_output is None:
            suffix = f"_{region}" if len(mqtt_regions) > 1 else ""
            return REPO_ROOT / "data" / f"cloud_events_{stamp}{suffix}.csv"
        if len(mqtt_regions) == 1:
            return base_output
        return base_output.with_name(
            f"{base_output.stem}_{region}{base_output.suffix or '.csv'}"
        )

    listeners = []
    failures = []

    try:
        for region in mqtt_regions:
            output = output_for_region(region)
            print(f"\ntrying_region={region} csv={output}")
            listener = CloudListener(
                region=region,
                run_uuid=auth["uuid"],
                access_token=auth["access_token"],
                did=did,
                output=output,
                debug=args.debug,
            )
            try:
                listener.start()
            except Exception as exc:
                listener.stop()
                failures.append((region, f"{type(exc).__name__}: {exc}"))
                print(f"region_failed={region} error={type(exc).__name__}: {exc}")
                continue
            listeners.append(listener)

        if not listeners:
            detail = "; ".join(f"{region}: {error}" for region, error in failures)
            raise RuntimeError(
                "no Xiaomi MQTT region accepted the current OAuth token"
                + (f": {detail}" if detail else "")
            )

        print(
            "connected_regions="
            + ",".join(listener.region for listener in listeners)
        )

        started_cleaning = False
        if args.start_cleaning:
            response = vac.start()
            started_cleaning = True
            print(f"cleaning_started response={response!r}")
        else:
            print(
                "listening for cloud event_occured/properties_changed; "
                "start a cleaning run now"
            )

        if args.duration == 0:
            while True:
                time.sleep(1)
        else:
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                time.sleep(min(1, max(0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        if "started_cleaning" in locals() and started_cleaning:
            try:
                response = vac.stop()
                print(f"cleaning_stopped response={response!r}")
            except Exception as exc:
                print(
                    f"cleaning_stop_failed={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        for listener in listeners:
            listener.stop()


if __name__ == "__main__":
    main()
