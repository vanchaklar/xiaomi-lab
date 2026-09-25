# xiaomi-lab

Experimental tooling for inspecting and controlling a Xiaomi Mi Robot Vacuum-Mop Essential (`mijia.vacuum.v2`).

## Confirmed device

- Model: `mijia.vacuum.v2`
- App firmware: `2.2.1`
- Local protocol: miIO / MIoT
- Python interface: `python-miio==0.5.12`

The current goal is to understand and, if possible, correct carpet-only navigation drift without blindly flashing firmware.

## Safety

Never commit the vacuum token, Xiaomi credentials, Wi-Fi password, or other secrets.

Use environment variables:

```bash
export VACUUM_IP=192.168.x.x
export VACUUM_TOKEN=<32-hex-character-token>
```

Movement commands can move the robot immediately. Keep it on the floor and away from stairs while testing.

## Planned work

1. Enumerate the Python and MIoT interfaces exposed by the device.
2. Probe read-only properties and undocumented-but-advertised MIoT services.
3. Test whether docking plus map-state changes can re-anchor navigation after carpet drift.
4. Inspect direct-controller behavior and map events.
5. Investigate firmware/MCU options only after the local interface is understood.


## Current experiment

The first state-changing experiment is a guarded map-switch toggle while the robot is docked.

Read-only check:

```bash
python experiments/map_toggle.py
```

Apply the reversible toggle:

```bash
python experiments/map_toggle.py --apply
```

The map-switch A/B test is complete: carpet drift still occurs in both conditions, so toggling
that property is not a useful calibration mechanism. The active next step is probing the model's
event-backed map and localization telemetry in `docs/experiments/event-payloads.md`.


## Raw direct-controller test

A guarded random-walk experiment is available at:

```bash
python experiments/raw_random_walk.py --duration 5
python experiments/raw_random_walk.py --apply --duration 5
```

It uses `raw_command("set_properties", ...)` directly and always sends an explicit stop
between pulses and on exit.


## Drawn path patterns

A separate touch controller lets you draw a path on the phone, save it by name, and
replay it later:

```bash
python experiments/draw_pattern_control.py
```

Then open `http://127.0.0.1:8766/` on the same phone. Patterns are stored locally
under `data/patterns/`. See `docs/experiments/draw-patterns.md`.


## Raw MIoT LAN events

A raw LAN listener now tests Xiaomi's wildcard push subscription and records
`event_occured` / `properties_changed` messages:

```bash
python experiments/lan_event_listener.py --duration 60
```

See `docs/experiments/lan-events.md`.


## MIoT brute-force property scan

A read-only scanner can enumerate SIID/PIID property addresses beyond the
published model specification:

```bash
python experiments/miot_bruteforce.py
```

Use `--exhaustive` for SIID/PIID 1..255. The scanner does not invoke actions.
See `docs/experiments/miot-bruteforce.md`.


## Xiaomi Cloud event capture

Firmware 2.2.1 rejects the local `miIO.sub` forms tested so far. A cloud
listener now connects to Xiaomi's MIPS/MQTT event channel and records
`event_occured` / `properties_changed` payloads:

```bash
pip install -r requirements.txt
python experiments/cloud_event_listener.py --region de --login --auth-only
python experiments/cloud_event_listener.py --region de --duration 60
```

Use the Xiaomi Home account region instead of `de` where appropriate. See
`docs/experiments/cloud-events.md`.


## Cloud event control UI

The cloud event probe has a local browser UI that can start/stop cleaning,
send the vacuum home, and show incoming cloud events live:

```bash
python experiments/cloud_event_control.py
```

Then open `http://127.0.0.1:8768/`. Use `--auto-start` to begin cleaning
immediately after the cloud subscription is confirmed.
