# Raw random-controller test

This experiment tests the lowest useful local control path we currently know for
`mijia.vacuum.v2`:

```text
raw_command("set_properties", ...)
    -> service 8 / property 1
    -> direction-key
```

It intentionally bypasses `set_property_by()`.

## Safety

Run only with the robot on the floor, in an open area, away from stairs or other
drop-offs. The robot's own cliff sensors remain active, but this experiment should
not rely on them as the only physical safeguard.

Every movement pulse is followed by an explicit stop, and a final stop is sent from
a `finally` block.

## Preview a random sequence

```bash
python experiments/raw_random_walk.py --duration 15
```

No commands are sent without `--apply`.

## Run it

```bash
python experiments/raw_random_walk.py --apply --duration 15
```

Useful shorter first test:

```bash
python experiments/raw_random_walk.py --apply --duration 5
```

The current direction mapping follows the direct-controller mapping already used by
this project:

| value | direction |
| ---: | --- |
| 0 | left |
| 1 | right |
| 2 | forward |
| 3 | backward |
| 4 | stop |

The public specification leaves the value descriptions blank, so live behavior is
the final verification of those labels.

## Why this test matters

If raw direct-control works reliably, we can later use deterministic pulse sequences
to characterize wheel/turn response separately on hard floor and carpet. That gives
us a way to measure the odometry distortion instead of only observing its final map
effect.
