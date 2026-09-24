# Raw random-controller test

This experiment tests the lowest useful local control path we currently know for
`mijia.vacuum.v2`:

```text
raw_command("set_properties", ...)
    -> service 8 / property 1
    -> direction-key
```

It intentionally bypasses `set_property_by()`.

At the end of an applied run it sends a raw return-to-dock action:

```text
raw_command("action", {"siid": 2, "aiid": 3, ...})
```

## Safety

Run only with the robot on the floor, in an open area, away from stairs or other
drop-offs. The robot's own cliff sensors remain active, but this experiment should
not rely on them as the only physical safeguard.

Every movement pulse is followed by an explicit stop. On exit, the script sends a
final stop and then a return-to-dock command. Use `--no-dock` to suppress that
last action.

The default movement pulses are intentionally long:

| direction | pulse |
| --- | ---: |
| forward | 10.0 s |
| backward | 1.0 s |
| left | 1.5 s |
| right | 1.5 s |

## Preview a random sequence

```bash
python experiments/raw_random_walk.py --duration 30
```

No commands are sent and no CSV is written without `--apply`.

## Run it

```bash
python experiments/raw_random_walk.py --apply --duration 30
```

The duration is a soft run limit: a movement pulse that has already started is
allowed to finish, so the total elapsed time can exceed `--duration` by up to one
pulse.

Pulse lengths can be overridden:

```bash
python experiments/raw_random_walk.py --apply \
  --duration 30 \
  --forward-pulse 10 \
  --backward-pulse 1 \
  --side-pulse 1.5
```

Each applied run writes a timestamped CSV under `data/`, for example:

```text
data/raw_random_walk_20260924_220500.csv
```

The table includes movement, stop, and final dock command responses. The `phase`
column can contain `initial_stop`, `move`, `stop`, `final_stop`, or `dock`.

A custom output path can be supplied:

```bash
python experiments/raw_random_walk.py --apply --duration 30 --output data/test1.csv
```

The CSV can be loaded directly into a pandas DataFrame:

```python
import pandas as pd

df = pd.read_csv("data/test1.csv")
print(df)
```

Pandas is not required by the experiment itself; the logger uses Python's standard
`csv` module so it stays lightweight on the Android/Debian environment.
