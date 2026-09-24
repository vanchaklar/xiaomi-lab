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
