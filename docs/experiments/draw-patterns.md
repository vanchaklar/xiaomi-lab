# Drawn path patterns

This controller is separate from gyro control. You draw a geometric path directly on
the phone screen, save it by name, and replay it later.

## Run

```bash
python experiments/draw_pattern_control.py
```

Open on the same phone:

```text
http://127.0.0.1:8766/
```

## Drawing semantics

- the first point is the robot's current position;
- **up** on the canvas is the robot's current forward direction;
- the drawn line is simplified into straight segments;
- for each segment the controller:
  1. turns left/right toward that segment;
  2. stops;
  3. drives forward for the segment distance;
  4. stops;
  5. continues with the next segment.

The robot exposes discrete direction-key commands, not wheel velocity or a target XY
position, so playback is open-loop.

## Calibration

Two values determine how the drawing becomes motion:

- **Forward seconds per canvas width**: how long the robot should drive forward for a
  line equal to the full canvas width.
- **Turn seconds per 90°**: how long a 90-degree left/right rotation takes.

These are deliberately editable because hard floor and carpet can require different
calibration.

The default values are only initial UI values. Measure and tune them before relying on
the path shape.

## Save and load

Saved patterns are JSON files under:

```text
data/patterns/
```

Coordinates are normalized to 0..1, so patterns are independent of phone screen size.

The `data/` directory should remain local and not be committed.

## Playback

Movement commands are refreshed every 0.25 seconds by default because the vacuum treats
the direction-key write as momentary.

```bash
python experiments/draw_pattern_control.py --repeat 0.20
```

Use **STOP** to cancel a pattern immediately. **DOCK** cancels playback, stops, and sends
return-to-dock.

## Limitation relevant to carpet drift

A saved drawing is a command pattern, not a localization solution. On carpet, wheel slip
can still make the physical path diverge from the drawing. That divergence is useful for
measuring the carpet error once the hard-floor timing is calibrated.
