# Phone tilt / gyro control

This mode uses the phone browser's `DeviceOrientation` API. That is preferable to
integrating raw angular velocity from the gyroscope because Android/browser orientation
is already fused with other motion sensors and does not accumulate gyro drift as quickly.

The vacuum still receives the same local MIoT `direction-key` commands.

## Run

From the Debian/venv environment:

```bash
python experiments/gyro_control.py
```

Then open this URL in the browser **on the same phone**:

```text
http://127.0.0.1:8765/
```

The proot environment shares the phone network namespace, so localhost should reach
the Python server.

## Use

1. Tap **Enable orientation**.
2. Hold the phone in your preferred neutral driving position.
3. Tap **Calibrate neutral**.
4. Tilt the phone while still disarmed and verify the direction preview.
5. Use the invert checkboxes if forward/back or left/right feels reversed.
6. Tap **ARM** only after the preview is correct.
7. Tilt within the dead zone to stop.
8. **STOP** immediately disarms and sends a stop command.
9. **DOCK** disarms, stops, then sends return-to-dock.

## Safety behavior

- starts disarmed;
- no movement before ARM;
- watchdog stops the robot if browser tilt updates stop for 0.6 s;
- hiding/leaving the browser page sends stop;
- server shutdown sends stop;
- only one cardinal direction is commanded at a time because the robot exposes a
  single `direction-key` value rather than independent left/right wheel velocities.

## Logging

Every received tilt sample is written to a timestamped CSV under `data/`:

```text
data/gyro_control_YYYYMMDD_HHMMSS.csv
```

Columns include beta/gamma orientation, calibrated deltas, armed state, derived
direction, and raw MIoT response data.

This will also let us compare how operator-commanded motion behaves on hard floor
versus carpet.
