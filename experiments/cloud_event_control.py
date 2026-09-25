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
#map { width:100%; height:52vh; min-height:320px; background:#090909; border-radius:8px; touch-action:none; }
#legend { font-family:monospace; font-size:12px; margin-top:8px; }
#events { white-space:pre-wrap; overflow-wrap:anywhere; font-family:monospace; font-size:12px; max-height:38vh; overflow:auto; }
.bad { color:#f88; }
.good { color:#8f8; }
small { color:#bbb; }
input, select { font-size:16px; padding:8px; margin:4px; background:#222; color:#eee; border:1px solid #555; border-radius:6px; }
table { width:100%; border-collapse:collapse; }
th, td { padding:6px; border-bottom:1px solid #333; text-align:left; }
.mono { font-family:monospace; }
.dpad { display:grid; grid-template-columns:repeat(3, minmax(72px, 110px)); gap:8px; justify-content:center; margin:12px 0; }
.dpad button { margin:0; min-height:62px; font-size:22px; }
.dpad .forward { grid-column:2; grid-row:1; }
.dpad .left { grid-column:1; grid-row:2; }
.dpad .stopdir { grid-column:2; grid-row:2; background:#e44; color:white; }
.dpad .right { grid-column:3; grid-row:2; }
.dpad .backward { grid-column:2; grid-row:3; }
</style>
</head>
<body>
<h2>Xiaomi vacuum cloud event probe</h2>

<div class="card">
  <div>Device: <span id="device">...</span></div>
  <div>Cloud DID: <span id="did">...</span></div>
  <div>Broker regions: <span id="regions">...</span></div>
  <div>Cloud errors: <span id="clouderrors">none</span></div>
  <div>Authorized topics: <span id="topics">none</span></div>
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
  <h3>Manual direction commands</h3>
  <div class="dpad">
    <button class="forward dirbtn" data-value="2">▲</button>
    <button class="left dirbtn" data-value="0">◀</button>
    <button class="stopdir dirbtn" data-value="4">STOP</button>
    <button class="right dirbtn" data-value="1">▶</button>
    <button class="backward dirbtn" data-value="3">▼</button>
  </div>
  <small>Each direction button sends its raw SIID 8 / PIID 1 value immediately, once per tap.</small>
  <div>
    <label>Value
      <input id="rawvalue" type="number" min="0" max="255" step="1" value="4">
    </label>
    <label>Interval after command (ms)
      <input id="rawinterval" type="number" min="0" max="60000" step="10" value="250">
    </label>
    <button id="sendraw">SEND ONCE</button>
    <button id="addraw">ADD TO QUEUE</button>
  </div>
  <small>
    Known SIID 8 / PIID 1 values: 0=left, 1=right, 2=forward, 3=backward, 4=stop.
    Other values are sent literally and may be rejected by the vacuum.
  </small>

  <div style="margin-top:10px">
    <button id="nextcmd">SEND NEXT</button>
    <button id="runcmds">RUN QUEUE</button>
    <button id="stopcmds">STOP QUEUE + SEND STOP</button>
    <button id="clearcmds">CLEAR</button>
  </div>

  <table>
    <thead><tr><th>#</th><th>value</th><th>interval ms</th><th></th></tr></thead>
    <tbody id="cmdrows"></tbody>
  </table>
  <div>Queue cursor: <span id="cmdcursor">0</span> / <span id="cmdcount">0</span></div>
  <div id="cmdresult" class="mono"></div>
</div>

<div class="card">
  <div>Decoded map triples: <span id="mapcount">0</span> &nbsp; generation: <span id="generation">0</span></div>
  <label><input id="flipy" type="checkbox" checked> flip Y for display</label>
  <canvas id="map"></canvas>
  <div id="legend">waiting for 7/1 map_points...</div>
</div>

<div class="card">
  <div>Cloud events: <span id="count">0</span></div>
  <div id="events">waiting...</div>
</div>

<script>
let lastSeq = 0;
let commandQueue = [];
let commandCursor = 0;
let queueRunning = false;
const el = id => document.getElementById(id);

async function getJSON(path) {
  const r = await fetch(path);
  return await r.json();
}

async function post(path) {
  const r = await fetch(path, {method:"POST"});
  return await r.json();
}

async function postJSON(path, body) {
  const r = await fetch(path, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)
  });
  return await r.json();
}

function renderQueue() {
  const body = el("cmdrows");
  body.innerHTML = "";
  commandQueue.forEach((cmd, index) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>" + (index + 1) + (index === commandCursor ? " ▶" : "") + "</td>" +
      "<td><input data-field='value' data-index='" + index + "' type='number' min='0' max='255' step='1' value='" + cmd.value + "' style='width:80px'></td>" +
      "<td><input data-field='interval' data-index='" + index + "' type='number' min='0' max='60000' step='10' value='" + cmd.interval_ms + "' style='width:110px'></td>" +
      "<td><button data-delete='" + index + "'>×</button></td>";
    body.appendChild(tr);
  });

  body.querySelectorAll("input[data-field]").forEach(input => {
    input.onchange = () => {
      const index = Number(input.dataset.index);
      const field = input.dataset.field;
      let value = Number(input.value);
      if (!Number.isFinite(value)) value = 0;
      if (field === "value") commandQueue[index].value = Math.trunc(value);
      if (field === "interval") commandQueue[index].interval_ms = Math.max(0, Math.trunc(value));
      renderQueue();
    };
  });

  body.querySelectorAll("button[data-delete]").forEach(button => {
    button.onclick = () => {
      const index = Number(button.dataset.delete);
      commandQueue.splice(index, 1);
      if (commandCursor > index) commandCursor--;
      if (commandCursor > commandQueue.length) commandCursor = commandQueue.length;
      renderQueue();
    };
  });

  el("cmdcursor").textContent = commandCursor;
  el("cmdcount").textContent = commandQueue.length;
}

async function sendRawValue(value, source="manual") {
  const result = await postJSON("/api/raw-direction", {value, source});
  el("cmdresult").className = result.ok ? "mono good" : "mono bad";
  el("cmdresult").textContent =
    new Date().toLocaleTimeString() + " value=" + value + " -> " + JSON.stringify(result);
  return result;
}

async function sendNextCommand() {
  if (commandCursor >= commandQueue.length) return null;
  const cmd = commandQueue[commandCursor];
  const result = await sendRawValue(cmd.value, "queue");
  commandCursor++;
  renderQueue();
  return {cmd, result};
}

async function runQueue() {
  if (queueRunning) return;
  queueRunning = true;
  try {
    while (queueRunning && commandCursor < commandQueue.length) {
      const sent = await sendNextCommand();
      if (!sent) break;
      if (!sent.result.ok) break;
      if (sent.cmd.interval_ms > 0) {
        await new Promise(resolve => setTimeout(resolve, sent.cmd.interval_ms));
      }
    }
  } finally {
    queueRunning = false;
  }
}

document.querySelectorAll(".dirbtn").forEach(button => {
  button.onclick = async () => {
    const value = Number(button.dataset.value);
    await sendRawValue(value, "button");
  };
});

el("sendraw").onclick = async () => {
  await sendRawValue(Math.trunc(Number(el("rawvalue").value)), "manual");
};

el("addraw").onclick = () => {
  commandQueue.push({
    value: Math.trunc(Number(el("rawvalue").value)),
    interval_ms: Math.max(0, Math.trunc(Number(el("rawinterval").value)))
  });
  renderQueue();
};

el("nextcmd").onclick = sendNextCommand;
el("runcmds").onclick = runQueue;
el("stopcmds").onclick = async () => {
  queueRunning = false;
  await sendRawValue(4, "queue-stop");
};
el("clearcmds").onclick = () => {
  queueRunning = false;
  commandQueue = [];
  commandCursor = 0;
  renderQueue();
};

async function refreshState() {
  try {
    const s = await getJSON("/api/status");
    el("device").textContent = s.model + " / " + s.firmware;
    el("did").textContent = s.did;
    el("regions").textContent = s.regions.length ? s.regions.join(", ") : "none";
    el("clouderrors").textContent =
      Object.keys(s.cloud_errors).length ? JSON.stringify(s.cloud_errors) : "none";
    el("topics").textContent =
      s.authorized_topics.length ? s.authorized_topics.join(", ") : "none";
    el("vacstate").textContent = JSON.stringify(s.state);
    el("battery").textContent = JSON.stringify(s.battery);
    el("action").textContent = s.last_action || "none";
  } catch (e) {
    el("vacstate").textContent = "status error";
  }
}

function typeColor(type) {
  const hue = ((Number(type) || 0) * 67) % 360;
  return "hsl(" + hue + " 80% 60%)";
}

function typeLabel(type) {
  if (Number(type) === 4) return "challenging / entanglement-risk";
  return "type " + type;
}

async function refreshMap() {
  try {
    const data = await getJSON("/api/map");
    el("mapcount").textContent = data.point_count;
    el("generation").textContent = data.generation;

    const canvas = el("map");
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(320, canvas.clientWidth);
    const height = Math.max(320, canvas.clientHeight);
    const pxw = Math.round(width * dpr);
    const pxh = Math.round(height * dpr);
    if (canvas.width !== pxw || canvas.height !== pxh) {
      canvas.width = pxw;
      canvas.height = pxh;
    }

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    if (!data.points.length) {
      el("legend").textContent = "waiting for 7/1 map_points...";
      return;
    }

    let minX = data.bounds.min_x, maxX = data.bounds.max_x;
    let minY = data.bounds.min_y, maxY = data.bounds.max_y;
    if (minX === maxX) { minX -= 1; maxX += 1; }
    if (minY === maxY) { minY -= 1; maxY += 1; }

    const pad = 24;
    const sx = (width - pad * 2) / (maxX - minX + 1);
    const sy = (height - pad * 2) / (maxY - minY + 1);
    const scale = Math.max(2, Math.min(sx, sy));
    const drawW = (maxX - minX + 1) * scale;
    const drawH = (maxY - minY + 1) * scale;
    const ox = (width - drawW) / 2;
    const oy = (height - drawH) / 2;
    const flipY = el("flipy").checked;

    for (const p of data.points) {
      const x = ox + (p.x - minX) * scale;
      const yIndex = flipY ? (maxY - p.y) : (p.y - minY);
      const y = oy + yIndex * scale;
      ctx.fillStyle = typeColor(p.type);
      const s = Math.max(2, Math.min(8, scale));
      ctx.fillRect(x, y, s, s);
    }

    const legendParts = Object.entries(data.type_counts)
      .sort((a,b) => Number(a[0]) - Number(b[0]))
      .map(([type,count]) =>
        typeLabel(type) + ": " + count
      );
    el("legend").textContent =
      "bounds x=" + minX + ".." + maxX +
      " y=" + minY + ".." + maxY +
      " | " + legendParts.join(" | ");
  } catch (e) {
    el("legend").textContent = "map error: " + e;
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
setInterval(refreshMap, 350);
el("flipy").onchange = refreshMap;
window.addEventListener("resize", refreshMap);
renderQueue();
refreshState();
refreshEvents();
refreshMap();
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
        self.map_lock = threading.Lock()
        self.map_generation = 0
        self.map_cells: dict[tuple[int, int], int] = {}
        self.map_triplet_count = 0
        self.command_seq = 0
        self.command_log = deque(maxlen=200)

    @property
    def regions(self) -> list[str]:
        return [listener.region for listener in self.listeners]

    @staticmethod
    def _decode_map_points(payload) -> list[tuple[int, int, int]]:
        if not isinstance(payload, dict):
            return []
        params = payload.get("params")
        if not isinstance(params, dict):
            return []
        arguments = params.get("arguments")
        if not isinstance(arguments, list):
            return []

        point_string = None
        for argument in arguments:
            if (
                isinstance(argument, dict)
                and argument.get("piid") == 1
                and isinstance(argument.get("value"), str)
            ):
                point_string = argument["value"]
                break
        if point_string is None:
            return []

        try:
            values = [int(value) for value in point_string.split()]
        except ValueError:
            return []
        if len(values) % 3:
            return []

        return [
            (values[index], values[index + 1], values[index + 2])
            for index in range(0, len(values), 3)
        ]

    def add_event(self, region: str, event: dict) -> None:
        siid = event.get("siid")
        iid = event.get("iid")

        if event.get("kind") == "event_occured" and siid == 7 and iid == 2:
            with self.map_lock:
                self.map_generation += 1
                self.map_cells.clear()
                self.map_triplet_count = 0

        if event.get("kind") == "event_occured" and siid == 7 and iid == 1:
            points = self._decode_map_points(event.get("payload"))
            if points:
                with self.map_lock:
                    self.map_triplet_count += len(points)
                    for x, y, point_type in points:
                        self.map_cells[(x, y)] = point_type

        with self.event_lock:
            self.seq += 1
            self.total_events += 1
            self.events.append(
                {
                    "seq": self.seq,
                    "region": region,
                    "kind": event.get("kind"),
                    "siid": siid,
                    "iid": iid,
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

    def raw_direction(self, value: int, source: str = "manual"):
        if not isinstance(value, int):
            raise ValueError("direction value must be an integer")
        if value < 0 or value > 255:
            raise ValueError("direction value must be between 0 and 255")

        with self.action_lock:
            payload = [{
                "did": f"cloud-ui-dir-{value}",
                "siid": 8,
                "piid": 1,
                "value": value,
            }]
            response = self.vac.raw_command("set_properties", payload)
            self.command_seq += 1
            self.last_action = f"direction:{value}"
            self.command_log.append({
                "seq": self.command_seq,
                "timestamp": time.time(),
                "source": source,
                "siid": 8,
                "piid": 1,
                "value": value,
                "response": response,
            })
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
            "authorized_topics": [
                topic
                for listener in self.listeners
                for topic in listener.authorized_topics
            ],
            "state": self.read_property(2, 1),
            "battery": self.read_property(3, 1),
            "last_action": self.last_action,
            "last_raw_command": self.command_log[-1] if self.command_log else None,
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

    def map_payload(self):
        with self.map_lock:
            points = [
                {"x": x, "y": y, "type": point_type}
                for (x, y), point_type in self.map_cells.items()
            ]
            if points:
                xs = [point["x"] for point in points]
                ys = [point["y"] for point in points]
                bounds = {
                    "min_x": min(xs),
                    "max_x": max(xs),
                    "min_y": min(ys),
                    "max_y": max(ys),
                }
            else:
                bounds = {
                    "min_x": 0,
                    "max_x": 0,
                    "min_y": 0,
                    "max_y": 0,
                }

            type_counts = {}
            for point in points:
                key = str(point["type"])
                type_counts[key] = type_counts.get(key, 0) + 1

            return {
                "generation": self.map_generation,
                "triplet_count": self.map_triplet_count,
                "point_count": len(points),
                "bounds": bounds,
                "type_counts": type_counts,
                "points": points,
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
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            return

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

        if path == "/api/map":
            self._json(200, self.controller.map_payload())
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

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        try:
            if self.path == "/api/raw-direction":
                payload = self._read_json()
                value = payload.get("value")
                if isinstance(value, bool):
                    raise ValueError("direction value must be an integer")
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("direction value must be an integer") from exc
                source = str(payload.get("source") or "manual")
                response = self.controller.raw_direction(value, source)
                self._json(200, {
                    "ok": True,
                    "siid": 8,
                    "piid": 1,
                    "value": value,
                    "response": response,
                })
                return

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
        default=os.environ.get("XIAOMI_CLOUD_REGION", "all"),
        choices=REGION_CHOICES,
        help="MQTT broker region; default all probes every Xiaomi broker",
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
