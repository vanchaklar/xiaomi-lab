# Drawn path patterns

This controller is separate from gyro control. You draw a geometric path directly on
the phone screen, convert it into a command sequence, edit that sequence, save it by
name, and replay it later.

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
- **BUILD COMMANDS** simplifies the drawn line and converts it into explicit
  `left`, `right`, `forward`, and `stop` rows.

## Editable command sequence

The generated sequence is shown as a table before playback. Every row has:

- command number;
- direction;
- duration in seconds;
- move-up / move-down / delete controls.

You can also add commands manually with **ADD COMMAND**.

The table is the source of truth for playback. Editing the table changes exactly what
will be sent to the robot; the drawing is only a convenient way to generate an initial
sequence.

Example:

```text
1  right    0.75
2  stop     0.08
3  forward  3.20
4  stop     0.08
5  left     1.10
6  stop     0.08
7  forward  2.45
8  stop     0.08
```

## Calibration

The automatic drawing-to-command conversion uses:

- **Forward seconds per canvas width**
- **Turn seconds per 90°**
- **Stop between generated commands**
- **Simplify tolerance**

After **BUILD COMMANDS**, you can edit every generated duration manually.

## Save and load

Saved JSON patterns contain both:

```text
points
commands
```

so manual command edits survive reloads.

Patterns are stored locally under:

```text
data/patterns/
```

Coordinates are normalized to 0..1, so drawings remain independent of phone screen size.
The `data/` directory is ignored by Git.

## Playback

**PLAY COMMANDS** executes the currently visible table in order.

A non-stop row is repeatedly written every 0.25 seconds by default for the duration of
that row, because this vacuum treats direction-key writes as momentary.

```bash
python experiments/draw_pattern_control.py --repeat 0.20
```

Use **STOP** to cancel immediately. **DOCK** cancels playback, stops, and sends
return-to-dock.

## Limitation relevant to carpet drift

A saved sequence is open-loop. It reproduces the command pattern, not an absolute
trajectory. Running the exact same saved sequence on hard floor and carpet is therefore
a useful way to quantify how much the carpet changes the robot's physical response.
