#!/usr/bin/env python3
"""Draw, save, and replay motion patterns for mijia.vacuum.v2.

The phone browser provides a touch canvas. A drawn polyline is stored as normalized
coordinates. Playback converts the polyline into turn + forward segments and drives
the vacuum through repeated MIoT direction-key writes.

The drawing is geometric, not a recording of gyro input.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
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

PATTERN_DIR = REPO_ROOT / "data" / "patterns"
PATTERN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

LOG_FIELDS = [
    "timestamp_utc",
    "elapsed_s",
    "source",
    "pattern",
    "segment",
    "direction",
    "duration_s",
    "response_code",
    "response_json",
]


HTML = r"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Xiaomi Draw Control</title>
<style>
body { font-family:sans-serif; max-width:720px; margin:0 auto; padding:12px; background:#111; color:#eee; }
.card { background:#1b1b1b; border-radius:12px; padding:12px; margin:10px 0; }
canvas { width:100%; height:52vh; background:#fafafa; border-radius:10px; touch-action:none; display:block; }
button { font-size:17px; padding:12px 16px; margin:5px; border:0; border-radius:9px; }
input, select { font-size:16px; padding:9px; margin:5px; border-radius:8px; max-width:95%; }
#play { background:#2d7; }
#stop { background:#e44; color:#fff; }
#dock { background:#58c; color:#fff; }
.row { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
small { color:#bbb; }
</style>
</head>
<body>
<h2>Draw vacuum pattern</h2>

<div class="card">
  <canvas id="pad" width="600" height="600"></canvas>
  <div class="row">
    <button id="clear">CLEAR</button>
    <button id="undo">UNDO</button>
  </div>
  <small>Start point is the robot position. Up on the canvas means the robot's current forward direction.</small>
</div>

<div class="card">
  <div class="row">
    <input id="name" value="pattern1" maxlength="64" placeholder="pattern name">
    <button id="save">SAVE</button>
    <button id="refresh">REFRESH</button>
  </div>
  <div class="row">
    <select id="patterns"></select>
    <button id="load">LOAD</button>
  </div>
  <div id="patternState">no pattern loaded</div>
</div>

<div class="card">
  <label>
    Forward seconds per canvas width:
    <input id="forwardScale" type="number" min="0.1" step="0.1" value="10">
  </label><br>
  <label>
    Turn seconds per 90°:
    <input id="turn90" type="number" min="0.05" step="0.05" value="1.5">
  </label><br>
  <label>
    Simplify tolerance (% of canvas):
    <input id="tolerance" type="number" min="0" max="20" step="0.5" value="2">
  </label>
  <div class="row">
    <button id="play">PLAY</button>
    <button id="stop">STOP</button>
    <button id="dock">DOCK</button>
  </div>
  <div id="state">idle</div>
  <small>PLAY is open-loop. Carpet slip will still affect the physical trajectory.</small>
</div>

<script>
const el = id => document.getElementById(id);
const canvas = el("pad");
const ctx = canvas.getContext("2d");
let points = [];
let drawing = false;

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const old = points.slice();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  points = old;
  redraw();
}

function pxy(ev) {
  const r = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)),
    y: Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height))
  };
}

function redraw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (points.length === 0) return;

  ctx.lineWidth = Math.max(3, canvas.width / 180);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#111";
  ctx.beginPath();
  ctx.moveTo(points[0].x * canvas.width, points[0].y * canvas.height);
  for (const p of points.slice(1)) {
    ctx.lineTo(p.x * canvas.width, p.y * canvas.height);
  }
  ctx.stroke();

  const s = points[0];
  ctx.fillStyle = "#1a7";
  ctx.beginPath();
  ctx.arc(s.x * canvas.width, s.y * canvas.height, Math.max(5, canvas.width/80), 0, Math.PI*2);
  ctx.fill();

  if (points.length > 1) {
    const e = points[points.length - 1];
    ctx.fillStyle = "#d33";
    ctx.beginPath();
    ctx.arc(e.x * canvas.width, e.y * canvas.height, Math.max(5, canvas.width/80), 0, Math.PI*2);
    ctx.fill();
  }
}

canvas.addEventListener("pointerdown", ev => {
  drawing = true;
  points = [pxy(ev)];
  canvas.setPointerCapture(ev.pointerId);
  redraw();
});
canvas.addEventListener("pointermove", ev => {
  if (!drawing) return;
  const p = pxy(ev);
  const last = points[points.length - 1];
  const dx = p.x - last.x, dy = p.y - last.y;
  if (dx*dx + dy*dy > 0.000025) {
    points.push(p);
    redraw();
  }
});
canvas.addEventListener("pointerup", ev => {
  drawing = false;
  try { canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
  el("patternState").textContent = points.length + " raw points";
});
canvas.addEventListener("pointercancel", () => { drawing = false; });

el("clear").onclick = () => {
  points = [];
  redraw();
  el("patternState").textContent = "cleared";
};

el("undo").onclick = () => {
  if (points.length > 1) points.pop();
  redraw();
};

async function post(path, body={}) {
  const r = await fetch(path, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)
  });
  return await r.json();
}

async function refreshPatterns() {
  const r = await fetch("/patterns");
  const data = await r.json();
  const list = el("patterns");
  list.innerHTML = "";
  for (const name of data.patterns || []) {
    const o = document.createElement("option");
    o.value = name;
    o.textContent = name;
    list.appendChild(o);
  }
}

el("save").onclick = async () => {
  if (points.length < 2) {
    el("patternState").textContent = "draw a path first";
    return;
  }
  const name = el("name").value.trim();
  const result = await post("/pattern/save", {name, points});
  el("patternState").textContent = result.ok
    ? "saved " + result.name + " (" + result.points + " points)"
    : result.error;
  await refreshPatterns();
};

el("load").onclick = async () => {
  const name = el("patterns").value;
  if (!name) return;
  const r = await fetch("/pattern?name=" + encodeURIComponent(name));
  const data = await r.json();
  if (!data.ok) {
    el("patternState").textContent = data.error;
    return;
  }
  points = data.points || [];
  el("name").value = name;
  redraw();
  el("patternState").textContent = "loaded " + name;
};

el("play").onclick = async () => {
  if (points.length < 2) {
    el("state").textContent = "draw or load a pattern first";
    return;
  }
  const payload = {
    name: el("name").value.trim() || "unsaved",
    points,
    forward_seconds_per_width: Number(el("forwardScale").value),
    turn_seconds_per_90: Number(el("turn90").value),
    tolerance: Number(el("tolerance").value) / 100
  };
  const result = await post("/pattern/play", payload);
  el("state").textContent = result.ok
    ? "playing " + result.name + " (" + result.segments + " segments)"
    : result.error;
};

el("stop").onclick = async () => {
  const r = await post("/stop");
  el("state").textContent = r.ok ? "stopped" : r.error;
};

el("dock").onclick = async () => {
  const r = await post("/dock");
  el("state").textContent = r.ok ? "docking" : r.error;
};

el("refresh").onclick = refreshPatterns;
window.addEventListener("resize", resizeCanvas);
resizeCanvas();
refreshPatterns();
</script>
</body>
</html>
"""


def normalize_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle <= -math.pi:
        angle += 2 * math.pi
    return angle


def point_line_distance(point, start, end) -> float:
    x, y = point["x"], point["y"]
    x1, y1 = start["x"], start["y"]
    x2, y2 = end["x"], end["y"]
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x-x1)*dx + (y-y1)*dy) / (dx*dx + dy*dy)))
    px, py = x1 + t*dx, y1 + t*dy
    return math.hypot(x - px, y - py)


def simplify(points, tolerance: float):
    if len(points) <= 2 or tolerance <= 0:
        return points

    start, end = points[0], points[-1]
    max_distance = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        distance = point_line_distance(points[i], start, end)
        if distance > max_distance:
            index = i
            max_distance = distance

    if max_distance > tolerance:
        left = simplify(points[: index + 1], tolerance)
        right = simplify(points[index:], tolerance)
        return left[:-1] + right

    return [start, end]


class Controller:
    def __init__(self, vac, csv_path: Path, repeat_s: float):
        self.vac = vac
        self.lock = threading.RLock()
        self.repeat_s = repeat_s
        self.started = time.monotonic()
        self.cancel = threading.Event()
        self.playback_thread = None

        PATTERN_DIR.mkdir(parents=True, exist_ok=True)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = csv_path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=LOG_FIELDS)
        self.writer.writeheader()
        self.handle.flush()

    @staticmethod
    def validate_name(name: str) -> str:
        name = (name or "").strip()
        if not PATTERN_NAME_RE.fullmatch(name):
            raise ValueError(
                "pattern name must be 1-64 characters using letters, numbers, '.', '_' or '-'"
            )
        return name

    def _raw_direction(self, direction: str):
        payload = [{
            "did": f"draw-set-{CONTROLLER_SIID}-{DIRECTION_PIID}",
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

    def _log(self, source, pattern, segment, direction, duration, response):
        self.writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": f"{time.monotonic() - self.started:.6f}",
            "source": source,
            "pattern": pattern,
            "segment": segment,
            "direction": direction,
            "duration_s": "" if duration is None else f"{duration:.6f}",
            "response_code": self._code(response),
            "response_json": json.dumps(response, separators=(",", ":"), sort_keys=True),
        })
        self.handle.flush()

    def save_pattern(self, name: str, points):
        name = self.validate_name(name)
        clean = []
        for p in points:
            x = float(p["x"])
            y = float(p["y"])
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("all pattern coordinates must be normalized to 0..1")
            clean.append({"x": x, "y": y})
        if len(clean) < 2:
            raise ValueError("pattern needs at least two points")

        path = PATTERN_DIR / f"{name}.json"
        path.write_text(json.dumps({"name": name, "points": clean}, indent=2) + "\n")
        return name, len(clean)

    def list_patterns(self):
        return sorted(p.stem for p in PATTERN_DIR.glob("*.json"))

    def load_pattern(self, name: str):
        name = self.validate_name(name)
        path = PATTERN_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(name)
        return json.loads(path.read_text())

    def _hold(self, pattern, segment, direction: str, duration: float):
        deadline = time.monotonic() + duration
        first = True
        while first or time.monotonic() < deadline:
            if self.cancel.is_set():
                return False
            response = self._raw_direction(direction)
            self._log("play", pattern, segment, direction, duration, response)
            first = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self.cancel.wait(min(self.repeat_s, remaining)):
                return False
        return True

    def stop(self):
        self.cancel.set()
        with self.lock:
            response = self._raw_direction("stop")
            self._log("stop", "", "", "stop", None, response)
            return response

    def dock(self):
        self.cancel.set()
        with self.lock:
            stop_response = self._raw_direction("stop")
            self._log("dock_stop", "", "", "stop", None, stop_response)
            response = self.vac.raw_command(
                "action",
                {"did": "draw-call-2-3", "siid": 2, "aiid": 3, "in": []},
            )
            self._log("dock", "", "", "dock", None, response)
            return response

    def play(self, name, points, forward_seconds_per_width, turn_seconds_per_90, tolerance):
        if forward_seconds_per_width <= 0:
            raise ValueError("forward_seconds_per_width must be positive")
        if turn_seconds_per_90 <= 0:
            raise ValueError("turn_seconds_per_90 must be positive")
        if tolerance < 0:
            raise ValueError("tolerance cannot be negative")

        pattern = self.validate_name(name)
        clean = [{"x": float(p["x"]), "y": float(p["y"])} for p in points]
        if len(clean) < 2:
            raise ValueError("pattern needs at least two points")
        path = simplify(clean, tolerance)
        if len(path) < 2:
            raise ValueError("pattern collapsed to fewer than two points")

        self.cancel.set()
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)
        self.cancel = threading.Event()

        def run():
            heading = 0.0  # up on canvas
            try:
                self._raw_direction("stop")
                for i, (a, b) in enumerate(zip(path, path[1:]), start=1):
                    if self.cancel.is_set():
                        break

                    dx = b["x"] - a["x"]
                    dy = b["y"] - a["y"]
                    distance = math.hypot(dx, dy)
                    if distance < 1e-6:
                        continue

                    target_heading = math.atan2(dx, -dy)
                    delta = normalize_angle(target_heading - heading)

                    if abs(delta) > math.radians(2):
                        turn_direction = "right" if delta > 0 else "left"
                        turn_duration = abs(delta) / (math.pi / 2) * turn_seconds_per_90
                        if not self._hold(pattern, i, turn_direction, turn_duration):
                            break
                        self._raw_direction("stop")

                    forward_duration = distance * forward_seconds_per_width
                    if not self._hold(pattern, i, "forward", forward_duration):
                        break
                    self._raw_direction("stop")
                    heading = target_heading
            finally:
                try:
                    response = self._raw_direction("stop")
                    self._log("play_end", pattern, "", "stop", None, response)
                except Exception:
                    pass

        self.playback_thread = threading.Thread(target=run, daemon=True)
        self.playback_thread.start()
        return pattern, len(path) - 1

    def close(self):
        self.cancel.set()
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)
        try:
            self._raw_direction("stop")
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

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/":
            raw = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if self.path == "/patterns":
            self._json(200, {"ok": True, "patterns": self.controller.list_patterns()})
            return

        if self.path.startswith("/pattern?"):
            from urllib.parse import parse_qs, urlparse
            name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
            try:
                data = self.controller.load_pattern(name)
                self._json(200, {"ok": True, **data})
            except Exception as exc:
                self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        self.send_error(404)

    def do_POST(self):
        try:
            payload = self._read_json()

            if self.path == "/pattern/save":
                name, count = self.controller.save_pattern(
                    payload.get("name", ""), payload.get("points", [])
                )
                self._json(200, {"ok": True, "name": name, "points": count})
                return

            if self.path == "/pattern/play":
                name, segments = self.controller.play(
                    payload.get("name", "unsaved"),
                    payload.get("points", []),
                    float(payload.get("forward_seconds_per_width", 0)),
                    float(payload.get("turn_seconds_per_90", 0)),
                    float(payload.get("tolerance", 0)),
                )
                self._json(200, {"ok": True, "name": name, "segments": segments})
                return

            if self.path == "/stop":
                response = self.controller.stop()
                self._json(200, {"ok": True, "response": response})
                return

            if self.path == "/dock":
                response = self.controller.dock()
                self._json(200, {"ok": True, "response": response})
                return

            self.send_error(404)
        except Exception as exc:
            try:
                self.controller.stop()
            except Exception:
                pass
            self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--repeat",
        type=float,
        default=0.25,
        help="seconds between repeated movement commands during playback (default: 0.25)",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.repeat <= 0:
        parser.error("--repeat must be positive")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or (REPO_ROOT / "data" / f"draw_control_{stamp}.csv")

    vac = connect()
    controller = Controller(vac, output, args.repeat)
    Handler.controller = controller
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    def shutdown(_signum=None, _frame=None):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Open on this phone: http://127.0.0.1:{args.port}/")
    print(f"Patterns: {PATTERN_DIR}")
    print(f"CSV log: {output}")

    try:
        server.serve_forever()
    finally:
        controller.close()
        server.server_close()


if __name__ == "__main__":
    main()
