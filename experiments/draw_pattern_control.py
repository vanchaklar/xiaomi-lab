#!/usr/bin/env python3
"""Draw, edit, save, and replay motion patterns for mijia.vacuum.v2.

A drawn polyline is converted into an explicit editable command sequence. Saved
patterns contain both the drawing and the exact command sequence used for replay.
"""

from __future__ import annotations

import argparse
import csv
import json
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
    "command_index",
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
body { font-family:sans-serif; max-width:760px; margin:0 auto; padding:12px; background:#111; color:#eee; }
.card { background:#1b1b1b; border-radius:12px; padding:12px; margin:10px 0; }
canvas { width:100%; height:45vh; background:#fafafa; border-radius:10px; touch-action:none; display:block; }
button { font-size:16px; padding:10px 14px; margin:4px; border:0; border-radius:9px; }
input, select { font-size:15px; padding:7px; margin:3px; border-radius:7px; max-width:95%; }
#play { background:#2d7; }
#stop { background:#e44; color:#fff; }
#dock { background:#58c; color:#fff; }
.row { display:flex; flex-wrap:wrap; gap:5px; align-items:center; }
small { color:#bbb; }
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { border-bottom:1px solid #444; padding:6px 3px; text-align:left; }
td input, td select { width:90%; margin:0; }
.cmdButtons button { padding:6px 9px; margin:1px; font-size:14px; }
#commandsWrap { overflow-x:auto; }
</style>
</head>
<body>
<h2>Draw vacuum pattern</h2>

<div class="card">
  <canvas id="pad"></canvas>
  <div class="row">
    <button id="clear">CLEAR</button>
    <button id="undo">UNDO</button>
    <button id="build">BUILD COMMANDS</button>
  </div>
  <small>First point = robot position. Up = current robot forward direction.</small>
</div>

<div class="card">
  <label>Forward seconds per canvas width:
    <input id="forwardScale" type="number" min="0.1" step="0.1" value="10">
  </label><br>
  <label>Turn seconds per 90°:
    <input id="turn90" type="number" min="0.05" step="0.05" value="1.5">
  </label><br>
  <label>Stop between generated commands:
    <input id="stopDuration" type="number" min="0" step="0.01" value="0.08">
  </label><br>
  <label>Simplify tolerance (% of canvas):
    <input id="tolerance" type="number" min="0" max="20" step="0.5" value="2">
  </label>
</div>

<div class="card">
  <div class="row">
    <strong>Command sequence</strong>
    <button id="addCommand">ADD COMMAND</button>
  </div>
  <div id="commandsWrap">
    <table>
      <thead>
        <tr><th>#</th><th>Direction</th><th>Duration s</th><th>Edit</th></tr>
      </thead>
      <tbody id="commandsBody"></tbody>
    </table>
  </div>
  <div id="commandState">no commands</div>
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
  <div class="row">
    <button id="play">PLAY COMMANDS</button>
    <button id="stop">STOP</button>
    <button id="dock">DOCK</button>
  </div>
  <div id="state">idle</div>
  <small>Playback uses the table exactly. It is open-loop; carpet slip can still distort the path.</small>
</div>

<script>
const el = id => document.getElementById(id);
const canvas = el("pad");
const ctx = canvas.getContext("2d");
let points = [];
let commands = [];
let drawing = false;

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  redraw();
}

function pxy(ev) {
  const r = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(1, (ev.clientX-r.left)/r.width)),
    y: Math.max(0, Math.min(1, (ev.clientY-r.top)/r.height))
  };
}

function redraw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!points.length) return;
  ctx.lineWidth = Math.max(3, canvas.width/180);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#111";
  ctx.beginPath();
  ctx.moveTo(points[0].x*canvas.width, points[0].y*canvas.height);
  for (const p of points.slice(1)) ctx.lineTo(p.x*canvas.width, p.y*canvas.height);
  ctx.stroke();

  const s = points[0];
  ctx.fillStyle = "#1a7";
  ctx.beginPath();
  ctx.arc(s.x*canvas.width, s.y*canvas.height, Math.max(5,canvas.width/80), 0, Math.PI*2);
  ctx.fill();

  if (points.length > 1) {
    const e = points[points.length-1];
    ctx.fillStyle = "#d33";
    ctx.beginPath();
    ctx.arc(e.x*canvas.width, e.y*canvas.height, Math.max(5,canvas.width/80), 0, Math.PI*2);
    ctx.fill();
  }
}

function pointLineDistance(p, a, b) {
  const dx=b.x-a.x, dy=b.y-a.y;
  if (dx===0 && dy===0) return Math.hypot(p.x-a.x,p.y-a.y);
  let t=((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy);
  t=Math.max(0,Math.min(1,t));
  return Math.hypot(p.x-(a.x+t*dx), p.y-(a.y+t*dy));
}

function simplifyPath(ps, tol) {
  if (ps.length<=2 || tol<=0) return ps.slice();
  let max=0, idx=0;
  for (let i=1;i<ps.length-1;i++) {
    const d=pointLineDistance(ps[i],ps[0],ps[ps.length-1]);
    if (d>max) { max=d; idx=i; }
  }
  if (max>tol) {
    const l=simplifyPath(ps.slice(0,idx+1),tol);
    const r=simplifyPath(ps.slice(idx),tol);
    return l.slice(0,-1).concat(r);
  }
  return [ps[0],ps[ps.length-1]];
}

function normalizeAngle(a) {
  while (a>Math.PI) a-=2*Math.PI;
  while (a<=-Math.PI) a+=2*Math.PI;
  return a;
}

function buildCommands() {
  if (points.length<2) {
    el("commandState").textContent="draw a path first";
    return;
  }
  const path=simplifyPath(points, Number(el("tolerance").value)/100);
  const fscale=Number(el("forwardScale").value);
  const turn90=Number(el("turn90").value);
  const stopDuration=Number(el("stopDuration").value);
  let heading=0;
  const out=[];

  for (let i=0;i<path.length-1;i++) {
    const a=path[i], b=path[i+1];
    const dx=b.x-a.x, dy=b.y-a.y;
    const distance=Math.hypot(dx,dy);
    if (distance<1e-6) continue;

    const target=Math.atan2(dx,-dy);
    const delta=normalizeAngle(target-heading);

    if (Math.abs(delta)>Math.PI/90) {
      out.push({
        direction: delta>0 ? "right" : "left",
        duration_s: Math.abs(delta)/(Math.PI/2)*turn90
      });
      if (stopDuration>0) out.push({direction:"stop",duration_s:stopDuration});
    }

    out.push({direction:"forward",duration_s:distance*fscale});
    if (stopDuration>0) out.push({direction:"stop",duration_s:stopDuration});
    heading=target;
  }

  commands=out;
  renderCommands();
  el("commandState").textContent=commands.length+" commands generated";
}

function renderCommands() {
  const body=el("commandsBody");
  body.innerHTML="";
  commands.forEach((cmd,index)=>{
    const tr=document.createElement("tr");

    const n=document.createElement("td");
    n.textContent=index+1;

    const d=document.createElement("td");
    const select=document.createElement("select");
    for (const name of ["forward","backward","left","right","stop"]) {
      const o=document.createElement("option");
      o.value=name; o.textContent=name;
      if (cmd.direction===name) o.selected=true;
      select.appendChild(o);
    }
    select.onchange=()=>{ commands[index].direction=select.value; };
    d.appendChild(select);

    const dur=document.createElement("td");
    const input=document.createElement("input");
    input.type="number";
    input.min="0.01";
    input.step="0.01";
    input.value=Number(cmd.duration_s).toFixed(3);
    input.onchange=()=>{ commands[index].duration_s=Number(input.value); };
    dur.appendChild(input);

    const actions=document.createElement("td");
    actions.className="cmdButtons";
    const up=document.createElement("button");
    up.textContent="↑";
    up.onclick=()=>{ if(index>0){ [commands[index-1],commands[index]]=[commands[index],commands[index-1]]; renderCommands(); } };
    const down=document.createElement("button");
    down.textContent="↓";
    down.onclick=()=>{ if(index<commands.length-1){ [commands[index+1],commands[index]]=[commands[index],commands[index+1]]; renderCommands(); } };
    const del=document.createElement("button");
    del.textContent="×";
    del.onclick=()=>{ commands.splice(index,1); renderCommands(); };
    actions.append(up,down,del);

    tr.append(n,d,dur,actions);
    body.appendChild(tr);
  });
  el("commandState").textContent=commands.length ? commands.length+" commands" : "no commands";
}

canvas.addEventListener("pointerdown",ev=>{
  drawing=true;
  points=[pxy(ev)];
  commands=[];
  renderCommands();
  canvas.setPointerCapture(ev.pointerId);
  redraw();
});
canvas.addEventListener("pointermove",ev=>{
  if(!drawing)return;
  const p=pxy(ev), last=points[points.length-1];
  const dx=p.x-last.x,dy=p.y-last.y;
  if(dx*dx+dy*dy>0.000025){points.push(p);redraw();}
});
canvas.addEventListener("pointerup",ev=>{
  drawing=false;
  try{canvas.releasePointerCapture(ev.pointerId);}catch(_){}
  el("patternState").textContent=points.length+" raw points";
});
canvas.addEventListener("pointercancel",()=>drawing=false);

el("clear").onclick=()=>{points=[];commands=[];redraw();renderCommands();};
el("undo").onclick=()=>{if(points.length>1)points.pop();commands=[];redraw();renderCommands();};
el("build").onclick=buildCommands;
el("addCommand").onclick=()=>{commands.push({direction:"forward",duration_s:1});renderCommands();};

async function post(path,body={}) {
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  return await r.json();
}

async function refreshPatterns() {
  const r=await fetch("/patterns"),data=await r.json(),list=el("patterns");
  list.innerHTML="";
  for(const name of data.patterns||[]){
    const o=document.createElement("option");o.value=name;o.textContent=name;list.appendChild(o);
  }
}

el("save").onclick=async()=>{
  if(points.length<2){el("patternState").textContent="draw a path first";return;}
  if(!commands.length) buildCommands();
  const name=el("name").value.trim();
  const result=await post("/pattern/save",{name,points,commands});
  el("patternState").textContent=result.ok
    ? "saved "+result.name+" ("+result.commands+" commands)"
    : result.error;
  await refreshPatterns();
};

el("load").onclick=async()=>{
  const name=el("patterns").value;if(!name)return;
  const r=await fetch("/pattern?name="+encodeURIComponent(name)),data=await r.json();
  if(!data.ok){el("patternState").textContent=data.error;return;}
  points=data.points||[];
  commands=data.commands||[];
  el("name").value=name;
  redraw();renderCommands();
  el("patternState").textContent="loaded "+name;
};

el("play").onclick=async()=>{
  if(!commands.length) buildCommands();
  if(!commands.length){el("state").textContent="no commands";return;}
  const result=await post("/pattern/play",{
    name:el("name").value.trim()||"unsaved",
    commands
  });
  el("state").textContent=result.ok
    ? "playing "+result.name+" ("+result.commands+" commands)"
    : result.error;
};

el("stop").onclick=async()=>{const r=await post("/stop");el("state").textContent=r.ok?"stopped":r.error;};
el("dock").onclick=async()=>{const r=await post("/dock");el("state").textContent=r.ok?"docking":r.error;};
el("refresh").onclick=refreshPatterns;

window.addEventListener("resize",resizeCanvas);
resizeCanvas();renderCommands();refreshPatterns();
</script>
</body>
</html>
"""


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

    @staticmethod
    def validate_points(points):
        clean = []
        for p in points:
            x, y = float(p["x"]), float(p["y"])
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("all coordinates must be normalized to 0..1")
            clean.append({"x": x, "y": y})
        if len(clean) < 2:
            raise ValueError("pattern needs at least two points")
        return clean

    @staticmethod
    def validate_commands(commands):
        clean = []
        if not commands:
            raise ValueError("command sequence is empty")
        for i, cmd in enumerate(commands, start=1):
            direction = str(cmd.get("direction", ""))
            if direction not in DIRECTIONS:
                raise ValueError(f"command {i}: invalid direction {direction!r}")
            duration = float(cmd.get("duration_s", 0))
            if duration <= 0 or duration > 120:
                raise ValueError(f"command {i}: duration must be > 0 and <= 120 seconds")
            clean.append({"direction": direction, "duration_s": duration})
        return clean

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

    def _log(self, source, pattern, index, direction, duration, response):
        self.writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": f"{time.monotonic()-self.started:.6f}",
            "source": source,
            "pattern": pattern,
            "command_index": index,
            "direction": direction,
            "duration_s": "" if duration is None else f"{duration:.6f}",
            "response_code": self._code(response),
            "response_json": json.dumps(response, separators=(",", ":"), sort_keys=True),
        })
        self.handle.flush()

    def save_pattern(self, name: str, points, commands):
        name = self.validate_name(name)
        clean_points = self.validate_points(points)
        clean_commands = self.validate_commands(commands)
        path = PATTERN_DIR / f"{name}.json"
        path.write_text(
            json.dumps(
                {"name": name, "points": clean_points, "commands": clean_commands},
                indent=2,
            ) + "\n"
        )
        return name, len(clean_points), len(clean_commands)

    def list_patterns(self):
        return sorted(p.stem for p in PATTERN_DIR.glob("*.json"))

    def load_pattern(self, name: str):
        name = self.validate_name(name)
        path = PATTERN_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(name)
        data = json.loads(path.read_text())
        data.setdefault("commands", [])
        return data

    def _hold(self, pattern, index, direction: str, duration: float):
        deadline = time.monotonic() + duration
        first = True
        while first or time.monotonic() < deadline:
            if self.cancel.is_set():
                return False
            response = self._raw_direction(direction)
            self._log("play", pattern, index, direction, duration, response)
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

    def play(self, name, commands):
        pattern = self.validate_name(name)
        sequence = self.validate_commands(commands)

        self.cancel.set()
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)
        self.cancel = threading.Event()

        def run():
            try:
                self._raw_direction("stop")
                for index, cmd in enumerate(sequence, start=1):
                    if self.cancel.is_set():
                        break
                    if not self._hold(
                        pattern,
                        index,
                        cmd["direction"],
                        cmd["duration_s"],
                    ):
                        break
            finally:
                try:
                    response = self._raw_direction("stop")
                    self._log("play_end", pattern, "", "stop", None, response)
                except Exception:
                    pass

        self.playback_thread = threading.Thread(target=run, daemon=True)
        self.playback_thread.start()
        return pattern, len(sequence)

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
                name, points, commands = self.controller.save_pattern(
                    payload.get("name", ""),
                    payload.get("points", []),
                    payload.get("commands", []),
                )
                self._json(
                    200,
                    {"ok": True, "name": name, "points": points, "commands": commands},
                )
                return

            if self.path == "/pattern/play":
                name, commands = self.controller.play(
                    payload.get("name", "unsaved"),
                    payload.get("commands", []),
                )
                self._json(200, {"ok": True, "name": name, "commands": commands})
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
        help="seconds between repeated movement writes during a command (default: 0.25)",
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
