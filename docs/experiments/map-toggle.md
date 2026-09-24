# Map-switch experiment

## Question

Does firmware 2.2.1 allow the published `map_switch` property to be changed, and can a
controlled off/on transition later be used as part of a navigation re-anchoring cycle?

The first experiment answers only the first part. It does not yet claim that toggling the
property resets odometry or the navigation estimator.

## Preconditions

- Robot is physically on its dock.
- Charging state reports either charging or fully charged.
- `.env` contains the local IP and token.
- The working Python environment has the repository requirements installed.

## Read-only check

```bash
python experiments/map_toggle.py
```

Expected baseline for a normally configured robot:

```text
charging_state=1 or 2
map_switch_before=True
read-only mode; pass --apply to perform the reversible toggle
```

## Apply the reversible toggle

```bash
python experiments/map_toggle.py --apply
```

The script:

1. verifies the robot is docked from charging state;
2. records the existing map-switch value;
3. sets `map_switch=False`;
4. reads it back;
5. waits two seconds;
6. sets `map_switch=True`;
7. reads it back;
8. restores the starting state in a `finally` block if the experiment is interrupted.

No movement command is issued.

## Interpretation

A successful off/on/read-back sequence proves that firmware 2.2.1 implements the writable
map-switch property. It does **not** prove that navigation state is cleared.

If this stage succeeds, the next experiment is behavioral:

1. establish a correct baseline run from the dock;
2. deliberately accumulate obvious carpet drift;
3. return to dock;
4. perform the map-switch toggle;
5. start a fresh run from the same known dock pose;
6. compare the new trajectory with a control run where docking occurs without the toggle.

That A/B comparison is what can tell us whether the switch affects the estimator rather than
only map publication/display.
