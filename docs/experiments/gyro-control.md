# Phone tilt / gyro control

This mode uses the phone browser's `DeviceOrientation` API. That is preferable to
integrating raw angular velocity from the gyroscope because Android/browser orientation
is already fused with other motion sensors and does not accumulate gyro drift as quickly.

The vacuum still receives the same local MIoT `direction-key` commands.

## Continuous action

The vacuum treats a direction-key write as a momentary command rather than a persistent
motor state. While the controller is armed, the server now re-sends the selected non-stop
direction every 0.25 seconds by default.

That means holding the phone tilted forward keeps issuing `forward`; holding it left keeps
issuing `left`; returning to the dead zone sends `stop`.

The refresh interval can be changed:

```bash
python experiments/gyro_control.py --repeat 0.20
```

The repeat interval must remain shorter than the watchdog timeout.

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
7. Keep the phone tilted to continue that direction.
8. Tilt within the dead zone to stop.
9. **STOP** immediately disarms and sends a stop command.
10. **DOCK** disarms, stops, then sends return-to-dock.

## Safety behavior

- starts disarmed;
- no movement before ARM;
- selected non-stop directions are refreshed every 0.25 s by default;
- watchdog stops the robot if browser tilt updates stop for 0.6 s;
- hiding/leaving the browser page sends stop;
- server shutdown sends stop;
- only one cardinal direction is commanded at a time because the robot exposes a
  single `direction-key` value rather than independent left/right wheel velocities.

## Logging

Every received tilt sample and repeated command is written to a timestamped CSV under `data/`:

```text
data/gyro_control_YYYYMMDD_HHMMSS.csv
```

The `source` column distinguishes ordinary sensor samples, immediate direction changes,
periodic repeats, explicit stops, and watchdog stops.

Columns include beta/gamma orientation, calibrated deltas, armed state, derived direction,
and raw MIoT response data.

This will also let us compare how operator-commanded motion behaves on hard floor versus
carpet.
