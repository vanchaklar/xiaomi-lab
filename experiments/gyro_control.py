#!/usr/bin/env python3
"""Control mijia.vacuum.v2 from phone tilt in a local browser.

The browser uses DeviceOrientation (fused gyro/accelerometer orientation) and
posts tilt samples to this local HTTP server. The server converts them into the
vacuum's MIoT direction-key writes.

Safety:
- starts disarmed;
- explicit STOP button;
- watchdog stops the robot if tilt samples stop arriving;
- final stop on server shutdown;
- logs all received samples and command responses to CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

FIELDNAMES = [
    "timestamp_utc",
    "elapsed_s",
    "armed",
    "beta",
    "gamma",
    "delta_beta",
    "delta_gamma",
    "direction",
    "response_code",
    "response_json",
]


HTML = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Xiaomi Gyro Control</title>
<style>
body { font-family: sans-serif; max-width: 680px; margin: 0 auto; padding: 16px; background: #111; color: #eee; }
.card { background: #1b1b1b; border-radius: 12px; padding: 14px; margin: 12px 0; }
button { font-size: 18px; padding: 14px 18px; margin: 6px; border-radius: 10px; border: 0; }
#arm { background: #2d7; }
#stop { background: #e44; color: white; }
#dock { background: #58c; color: white; }
.big { font-size: 28px; font-weight: 700; }
.row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
label { display:block; margin:8px 0; }
input[type=range] { width:100%; }
small { color:#bbb; }
</style>
</head>
<body>
<h2>Xiaomi vacuum tilt control</h2>

<div class="card">
  <div>Sensor: <span id="sensor">waiting</span></div>
  <div>Direction: <span id="direction" class="big">STOP</span></div>
  <div>β: <span id="beta">0</span>° &nbsp; γ: <span id="gamma">0</span>°</div>
  <div>Δβ: <span id="dbeta">0</span>° &nbsp; Δγ: <span id="dgamma">0</span>°</div>
</div>

<div class="card">
  <button id="enable">Enable orientation</button>
  <button id="calibrate">Calibrate neutral</button>
  <button id="arm">ARM</button>
  <button id="stop">STOP</button>
  <button id="dock">DOCK</button>
  <div id="state">disarmed</div>
</div>

<div class="card">
  <label>Dead zone: <span id="deadv">12</span>°
    <input id="dead" type="range" min="5" max="35" value="12">
  </label>
  <label><input id="invertfb" type="checkbox"> invert forward/back</label>
  <label><input id="invertlr" type="checkbox"> invert left/right</label>
  <small>Verify direction while disarmed. Only ARM after the preview matches how you want the phone tilt mapped.</small>
</div>

<script>
let beta = 0, gamma = 0, beta0 = 0, gamma0 = 0;
let haveSensor = false;
let armed = false;
let lastSend = 0;
let lastDirection = "stop";

const el = id => document.getElementById(id);

function normalize180(x) {
  while (x > 180) x -= 360;
  while (x < -180) x += 360;
  return x;
}

function deriveDirection() {
  let db = normalize180(beta - beta0);
  let dg = gamma - gamma0;

  if (el("invertfb").checked) db = -db;
  if (el("invertlr").checked) dg = -dg;

  const dead = Number(el("dead").value);

  el("dbeta").textContent = db.toFixed(1);
  el("dgamma").textContent = dg.toFixed(1);

  if (Math.max(Math.abs(db), Math.abs(dg)) < dead) return ["stop", db, dg];

  if (Math.abs(db) >= Math.abs(dg)) {
    return [db > 0 ? "forward" : "backward", db, dg];
  }
  return [dg > 0 ? "right" : "left", db, dg];
}

async function post(path, body={}) {
  const r = await fetch(path, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)
  });
  return await r.json();
}

async function sendSample(force=false) {
  if (!haveSensor) return;

  const now = performance.now();
  if (!force && now - lastSend < 100) return;
  lastSend = now;

  const [preview, db, dg] = deriveDirection();
  el("direction").textContent = preview.toUpperCase();

  const requested = armed ? preview : "stop";

  try {
    const result = await post("/tilt", {
      armed,
      beta,
      gamma,
      delta_beta: db,
      delta_gamma: dg,
      direction: requested
    });
    el("state").textContent =
      (armed ? "armed" : "disarmed") + " / robot: " + result.direction;
    lastDirection = result.direction;
  } catch (e) {
    el("state").textContent = "connection error";
    armed = false;
  }
}

function onOrientation(ev) {
  if (ev.beta == null || ev.gamma == null) return;
  beta = ev.beta;
  gamma = ev.gamma;
  haveSensor = true;
  el("sensor").textContent = "active";
  el("beta").textContent = beta.toFixed(1);
  el("gamma").textContent = gamma.toFixed(1);
  sendSample();
}

async function enableOrientation() {
  try {
    if (typeof DeviceOrientationEvent !== "undefined" &&
        typeof DeviceOrientationEvent.requestPermission === "function") {
      const permission = await DeviceOrientationEvent.requestPermission();
      if (permission !== "granted") throw new Error("permission denied");
    }
    window.addEventListener("deviceorientation", onOrientation, true);
    el("sensor").textContent = "enabled; move phone";
  } catch (e) {
    el("sensor").textContent = "failed: " + e;
  }
}

el("enable").onclick = enableOrientation;

el("calibrate").onclick = () => {
  if (!haveSensor) return;
  beta0 = beta;
  gamma0 = gamma;
  deriveDirection();
};

el("arm").onclick = async () => {
  if (!haveSensor) {
    el("state").textContent = "enable sensor first";
    return;
  }
  armed = true;
  el("state").textContent = "armed";
  await sendSample(true);
};

el("stop").onclick = async () => {
  armed = false;
  await post("/stop");
  el("state").textContent = "disarmed / stopped";
};

el("dock").onclick = async () => {
  armed = false;
  await post("/dock");
  el("state").textContent = "disarmed / docking";
};

el("dead").oninput = () => {
  el("deadv").textContent = el("dead").value;
  deriveDirection();
};

document.addEventListener("visibilitychange", async () => {
  if (document.hidden) {
    armed = false;
    try { await post("/stop"); } catch (_) {}
  }
});

window.addEventListener("beforeunload", () => {
  navigator.sendBeacon("/stop");
});
</script>
</body>
</html>
"""


class Controller:
    def __init__(self, vac, csv_path: Path, watchdog_s: float):
        self.vac = vac
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.last_sample = time.monotonic()
        self.last_direction = "stop"
        self.armed = False
        self.watchdog_s = watchdog_s
        self.stop_event = threading.Event()

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = csv_path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=FIELDNAMES)
        self.writer.writeheader()
        self.handle.flush()
        self.csv_path = csv_path

        self.watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog.start()

    def _raw_direction(self, direction: str):
        payload = [{
            "did": f"gyro-set-{CONTROLLER_SIID}-{DIRECTION_PIID}",
            "siid": CONTROLLER_SIID,
            "piid": DIRECTION_PIID,
            "value": DIRECTIONS[direction],
        }]
        return self.vac.raw_command("set_properties", payload)

    @staticmethod
    def _code(response):
        if isinstance(response, list) and response and isinstance(response[0], dict):
            return response[0].get("code")
        if isinstance(response, dict):
            return response.get("code")
        return None

    def _log(self, sample, direction, response):
        self.writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": f"{time.monotonic() - self.started:.6f}",
            "armed": bool(sample.get("armed", False)),
            "beta": sample.get("beta"),
            "gamma": sample.get("gamma"),
            "delta_beta": sample.get("delta_beta"),
            "delta_gamma": sample.get("delta_gamma"),
            "direction": direction,
            "response_code": self._code(response),
            "response_json": json.dumps(response, separators=(",", ":"), sort_keys=True),
        })
        self.handle.flush()

    def handle_tilt(self, sample):
        direction = sample.get("direction", "stop")
        if direction not in DIRECTIONS:
            direction = "stop"

        with self.lock:
            self.last_sample = time.monotonic()
            self.armed = bool(sample.get("armed", False))
            if not self.armed:
                direction = "stop"

            response = None
            if direction != self.last_direction:
                response = self._raw_direction(direction)
                self.last_direction = direction

            self._log(sample, direction, response)
            return direction, response

    def stop(self):
        with self.lock:
            response = self._raw_direction("stop")
            self.last_direction = "stop"
            self.armed = False
            return response

    def dock(self):
        with self.lock:
            self._raw_direction("stop")
            self.last_direction = "stop"
            self.armed = False
            return self.vac.raw_command(
                "action",
                {"did": "gyro-call-2-3", "siid": 2, "aiid": 3, "in": []},
            )

    def _watchdog_loop(self):
        while not self.stop_event.wait(0.1):
            with self.lock:
                stale = self.armed and (time.monotonic() - self.last_sample > self.watchdog_s)
                if stale:
                    try:
                        self._raw_direction("stop")
                    finally:
                        self.last_direction = "stop"
                        self.armed = False

    def close(self):
        self.stop_event.set()
        try:
            self.stop()
        finally:
            self.handle.close()


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def log_message(self, format, *args):
        return

    def _json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        raw = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        try:
            if self.path == "/tilt":
                payload = self._read_json()
                direction, response = self.controller.handle_tilt(payload)
                self._json(200, {"ok": True, "direction": direction, "response": response})
                return

            if self.path == "/stop":
                response = self.controller.stop()
                self._json(200, {"ok": True, "direction": "stop", "response": response})
                return

            if self.path == "/dock":
                response = self.controller.dock()
                self._json(200, {"ok": True, "direction": "dock", "response": response})
                return

            self.send_error(404)
        except Exception as exc:
            try:
                self.controller.stop()
            except Exception:
                pass
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--watchdog", type=float, default=0.6)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or (REPO_ROOT / "data" / f"gyro_control_{stamp}.csv")

    vac = connect()
    controller = Controller(vac, output, args.watchdog)
    Handler.controller = controller
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    def shutdown(_signum=None, _frame=None):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Open on this phone: http://127.0.0.1:{args.port}/")
    print(f"CSV log: {output}")
    print("Starts disarmed. Calibrate neutral, verify preview direction, then ARM.")

    try:
        server.serve_forever()
    finally:
        controller.close()
        server.server_close()


if __name__ == "__main__":
    main()
