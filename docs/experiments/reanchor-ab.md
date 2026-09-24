# Re-anchoring A/B experiment

## Purpose

Determine whether toggling the writable `map_switch` while the robot is physically docked
changes the **navigation estimator**, rather than merely changing map publication/display.

The map switch itself has already been verified writable on firmware 2.2.1.

## Experimental conditions

Both trials begin only after the robot has accumulated clearly visible carpet drift and then
successfully returned to the dock.

### Control

Docking only. No map property is changed.

```bash
python experiments/reanchor_trial.py control
```

When ready to launch the observed run:

```bash
python experiments/reanchor_trial.py control --start-clean
```

### Toggle

While docked, set `map_switch=False`, verify it, wait two seconds, set it back to
`True`, and verify it again.

```bash
python experiments/reanchor_trial.py toggle
```

When ready to launch the observed run:

```bash
python experiments/reanchor_trial.py toggle --start-clean
```

## What to compare

Use the same physical starting condition and, as far as practical, the same first area of
hard floor/carpet.

Observe:

- initial heading leaving the dock;
- first long straight segment;
- first turn and lane spacing;
- whether the pre-existing map rotation/stretch appears to persist;
- how quickly any new drift becomes visible after reaching carpet.

The useful comparison is **control vs toggle after comparable accumulated drift**.

## Interpretation

- If both runs retain the old directional/map error, `map_switch` probably controls only
  map generation/publication and does not reset the pose estimator.
- If the control retains the error but the toggle starts from a clean orientation/geometry,
  the switch is acting as, or triggering, a useful reinitialization mechanism.
- If both start clean after docking, some other event in the procedure is resetting state
  and the original observation should be reproduced more carefully.
- If both start equally wrong but then diverge only on carpet, the dominant problem remains
  new wheel-slip accumulation rather than retained state.

This test does not require firmware modification.
