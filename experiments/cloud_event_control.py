#!/usr/bin/env python3
"""Browser UI for Xiaomi cloud event capture plus vacuum controls.

Starts the authorized Xiaomi cloud event listener first, then exposes a local
web page with START CLEANING, STOP, and DOCK controls plus a live event feed.

The UI is intended for short experiments. If this process started cleaning and
exits while still in cleaning mode, it sends STOP before shutting down.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vacuum import connect, safe_info
from cloud_event_listener import (
    AUTH_PATH,
    REGIONS,
    REGION_CHOICES,
    CloudListener,
    get_auth,
    get_cloud_devices,
)


HTML = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Xiaomi Cloud Map Probe</title>
<style>
body { font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 16px; background:#111; color:#eee; }
.card { background:#1b1b1b; border-radius:12px; padding:14px; margin:12px 0; }
button { font-size:18px; padding:14px 18px; margin:6px; border-radius:10px; border:0; }
#start { background:#2d7; }
#stop { background:#e44; color:white; }
#dock { background:#58c; color:white; }
#events { white-space:pre-wrap; overflow-wrap:anywhere; font-family:monospace; font-size:12px; max-height:55vh; overflow:auto; }
.bad { color:#f88; }
.good { color:#8f8; }
small { color:#bbb; }
</style>
</head>
<body>
<h2>Xiaomi vacuum cloud event probe</h2>

<div class="card">
  <div>Device: <span id="device">...</span></div>
  <div>Cloud DID: <span id="did">...</span></div>
  <div>Broker regions: <span id="regions">...</span></div>
  <div>Cloud errors: <span id="clouderrors">none</span></div>
  <div>Vacuum state: <span id="vacstate">...</span></div>
  <div>Battery: <span id="battery">...</span></div>
  <div>Last action: <span id="action">none</span></div>
</div>

<div class="card">
  <button id="start">START CLEANING</button>
  <button id="stop">STOP</button>
  <button id="dock">DOCK</button>
  <div id="result"></div>
  <small>Controls are sent over the local miIO connection. Cloud events remain read-only.</small>
</div>

<div class="card">
  <div>Cloud events: <span id="count">0</span></div>
  <div id="events">waiting...</div>
</div>

<script>
let lastSeq = 0;
const el = id => document.getElementById(id);

async function getJSON(path) {
  const r = await fetch(path);
  return await r.json();
}

async function post(path) {
  const r = await fetch(path, {method:"POST"});
  return await r.json();
}

async function refreshState() {
  try {
    const s = await getJSON("/api/status");
    el("device").textContent = s.model + " / " + s.firmware;
    el("did").textContent = s.did;
    el("regions").textContent = s.regions.length ? s.regions.join(", ") : "none";
    el("clouderrors").textContent =
      Object.keys(s.cloud_errors).length ? JSON.stringify(s.cloud_errors) : "none";
    el("vacstate").textContent = JSON.stringify(s.state);
    el("battery").textContent = JSON.stringify(s.battery);
    el("action").textContent = s.last_action || "none";
  } catch (e) {
    el("vacstate").textContent = "status error";
  }
}

async function refreshEvents() {
  try {
    const data = await getJSON("/api/events?since=" + lastSeq);
    if (data.events.length) {
      lastSeq = data.events[data.events.length - 1].seq;
    }
    el("count").textContent = data.total;
    const lines = data.tail.map(e =>
      "[" + e.seq + "] " + e.region + " " + e.kind + " " +
      e.siid + "/" + e.iid + " " + e.name + "\n" +
      JSON.stringify(e.payload)
    );
    el("events").textContent = lines.length ? lines.join("\n\n") : "waiting...";
    el("events").scrollTop = el("events").scrollHeight;
  } catch (e) {}
}

async function act(name) {
  el("result").textContent = "sending " + name + "...";
  try {
    const r = await post("/api/" + name);
    el("result").className = r.ok ? "good" : "bad";
    el("result").textContent = JSON.stringify(r);
  } catch (e) {
    el("result").className = "bad";
    el("result").textContent = String(e);
  }
  await refreshState();
}

el("start").onclick = () => act("start");
el("stop").onclick = () => act("stop");
el("dock").onclick = () => act("dock");

setInterval(refreshState, 1200);
setInterval(refreshEvents, 500);
refreshState();
refreshEvents();
</script>
</body>
</html>
"""


class ExperimentController:
    def __init__(self, vac, info, did: str):
        self.vac = vac
        self.info = info
        self.did = did
        self.listeners: list[CloudListener] = []
        self.cloud_errors: dict[str, str] = {}
        self.events = deque(maxlen=500)
        self.event_lock = threading.Lock()
        self.action_lock = threading.Lock()
        self.seq = 0
        self.total_events = 0
        self.last_action = None
        self.mode = "idle"

    @property
    def regions(self) -> list[str]:
        return [listener.region for listener in self.listeners]

    def add_event(self, region: str, event: dict) -> None:
        with self.event_lock:
            self.seq += 1
            self.total_events += 1
            self.events.append(
                {
                    "seq": self.seq,
                    "region": region,
                    "kind": event.get("kind"),
                    "siid": event.get("siid"),
                    "iid": event.get("iid"),
                    "name": event.get("name"),
                    "payload": event.get("payload"),
                    "timestamp_utc": event.get("timestamp_utc"),
                }
            )

    def start_cleaning(self):
        with self.action_lock:
            response = self.vac.start()
            self.mode = "cleaning"
            self.last_action = "start"
            return response

    def stop_cleaning(self):
        with self.action_lock:
            response = self.vac.stop()
            self.mode = "idle"
            self.last_action = "stop"
            return response

    def dock(self):
        with self.action_lock:
            response = self.vac.home()
            self.mode = "docking"
            self.last_action = "dock"
            return response

    def read_property(self, siid: int, piid: int):
        try:
            return self.vac.get_property_by(siid, piid)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def status(self):
        return {
            "model": self.info["model"],
            "firmware": self.info["firmware_version"],
            "did": self.did,
            "regions": self.regions,
            "cloud_errors": dict(self.cloud_errors),
            "state": self.read_property(2, 1),
            "battery": self.read_property(3, 1),
            "last_action": self.last_action,
        }

    def events_payload(self, since: int):
        with self.event_lock:
            all_events = list(self.events)
            new_events = [event for event in all_events if event["seq"] > since]
            return {
                "events": new_events,
                "tail": all_events[-60:],
                "total": self.total_events,
            }

    def close(self):
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
        if self.mode == "cleaning":
            try:
                self.vac.stop()
            except Exception as exc:
                print(
                    f"final_stop_failed={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )


class Handler(BaseHTTPRequestHandler):
    controller: ExperimentController

    def log_message(self, format, *args):
        return

    def _json(self, status: int, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path, _, query = self.path.partition("?")

        if path == "/":
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/api/status":
            self._json(200, self.controller.status())
            return

        if path == "/api/events":
            since = 0
            for part in query.split("&"):
                key, _, value = part.partition("=")
                if key == "since":
                    try:
                        since = int(value)
                    except ValueError:
                        since = 0
            self._json(200, self.controller.events_payload(since))
            return

        self.send_error(404)

    def do_POST(self):
        try:
            if self.path == "/api/start":
                response = self.controller.start_cleaning()
                self._json(200, {"ok": True, "action": "start", "response": response})
                return

            if self.path == "/api/stop":
                response = self.controller.stop_cleaning()
                self._json(200, {"ok": True, "action": "stop", "response": response})
                return

            if self.path == "/api/dock":
                response = self.controller.dock()
                self._json(200, {"ok": True, "action": "dock", "response": response})
                return

            self.send_error(404)
        except Exception as exc:
            self._json(
                500,
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )


def load_cached_auth_region() -> str | None:
    if not AUTH_PATH.exists():
        return None
    try:
        auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    region = auth.get("region")
    return region if region in REGIONS else None


def resolve_did(vac, info, auth_region: str, access_token: str, override: str | None):
    local_did = str(vac.device_id)
    if override:
        print(f"did_source=override did={override}")
        return override

    try:
        devices = get_cloud_devices(auth_region, access_token)
        matches = [device for device in devices if device.get("model") == info["model"]]
        exact = [device for device in matches if str(device.get("did")) == local_did]

        if exact:
            did = str(exact[0]["did"])
            print(f"did_source=cloud_exact did={did}")
            return did

        if len(matches) == 1:
            cloud_did = str(matches[0]["did"])
            print(
                f"cloud_model_match_candidate={cloud_did} "
                f"local_did={local_did}; keeping local DID because it previously "
                "received authorized MQTT subscriptions"
            )
            return local_did

        if matches:
            print(
                "cloud_did_ambiguous="
                + ",".join(str(device.get("did")) for device in matches)
                + f"; using local_did={local_did}"
            )
    except Exception as exc:
        print(f"cloud_device_lookup_failed={type(exc).__name__}: {exc}")

    print(f"did_source=local did={local_did}")
    return local_did


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--region",
        default=os.environ.get("XIAOMI_CLOUD_REGION", "i2"),
        choices=REGION_CHOICES,
        help="MQTT broker region; default i2 based on current vacuum experiment",
    )
    parser.add_argument(
        "--auth-region",
        default=os.environ.get("XIAOMI_CLOUD_AUTH_REGION"),
        choices=REGIONS,
        help="OAuth/account API region; cached auth region is used when omitted",
    )
    parser.add_argument("--did", default=None)
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="start cleaning immediately after authorized event subscriptions are live",
    )
    args = parser.parse_args()

    cached_region = load_cached_auth_region()
    if args.region == "all":
        auth_region = args.auth_region or cached_region
        if not auth_region:
            parser.error("--region all needs --auth-region for first login")
        mqtt_regions = list(REGIONS)
    else:
        auth_region = args.auth_region or cached_region or args.region
        mqtt_regions = [args.region]

    auth = get_auth(auth_region, force_login=args.login)

    vac = connect()
    info = safe_info(vac)
    did = resolve_did(vac, info, auth_region, auth["access_token"], args.did)

    controller = ExperimentController(vac, info, did)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for region in mqtt_regions:
        output = REPO_ROOT / "data" / f"cloud_ui_{stamp}_{region}.csv"
        print(f"trying_region={region} csv={output}")
        listener = CloudListener(
            region=region,
            run_uuid=auth["uuid"],
            access_token=auth["access_token"],
            did=did,
            output=output,
            debug=args.debug,
            event_callback=controller.add_event,
        )
        try:
            listener.start()
        except Exception as exc:
            listener.stop()
            error = f"{type(exc).__name__}: {exc}"
            controller.cloud_errors[region] = error
            print(f"region_failed={region} error={error}")
            continue
        controller.listeners.append(listener)

    if not controller.listeners:
        print(
            "WARNING: no Xiaomi cloud event subscription was authorized; "
            "starting the control UI anyway so START/STOP/DOCK remain usable"
        )

    if args.auto_start:
        response = controller.start_cleaning()
        print(f"cleaning_started response={response!r}")

    Handler.controller = controller
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    def shutdown(_signum=None, _frame=None):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(
        "connected_regions="
        + (",".join(controller.regions) if controller.regions else "none")
    )
    print(f"Open on this phone: http://127.0.0.1:{args.port}/")
    print("UI controls cleaning and shows cloud events live.")

    try:
        server.serve_forever()
    finally:
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
