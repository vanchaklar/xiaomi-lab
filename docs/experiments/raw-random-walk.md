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

No commands are sent and no CSV is written without `--apply`.

## Run it

```bash
python experiments/raw_random_walk.py --apply --duration 15
```

Useful shorter first test:

```bash
python experiments/raw_random_walk.py --apply --duration 5
```

Each applied run writes a timestamped CSV under `data/`, for example:

```text
data/raw_random_walk_20260924_220500.csv
```

The table columns are:

| column | meaning |
| --- | --- |
| `timestamp_utc` | wall-clock timestamp of the command/response |
| `elapsed_s` | seconds from the start of the run |
| `step` | movement step number |
| `phase` | `initial_stop`, `move`, `stop`, or `final_stop` |
| `direction` | left/right/forward/backward/stop |
| `value` | raw MIoT direction value |
| `requested_pulse_s` | requested movement duration |
| `response_code` | MIoT result code, normally 0 |
| `response_json` | complete raw response serialized as JSON |

A custom output path can be supplied:

```bash
python experiments/raw_random_walk.py --apply --duration 5 --output data/test1.csv
```

The CSV can be loaded directly into a pandas DataFrame:

```python
import pandas as pd

df = pd.read_csv("data/test1.csv")
print(df)
```

Pandas is not required by the experiment itself; the logger uses Python's standard
`csv` module so it stays lightweight on the Android/Debian environment.

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
