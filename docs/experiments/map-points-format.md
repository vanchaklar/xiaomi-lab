# Map-points payload format

Cloud capture finally exposed the vacuum's live map event stream.

The published event is:

```text
SIID 7 / EIID 1  map-points
argument PIID 1  points (string)
```

Observed payloads are whitespace-separated integers whose count is divisible by
three. The captured samples therefore decode naturally as triplets:

```text
x y type
x y type
...
```

For example:

```text
128 128 3 128 128 1 129 128 1 ...
```

becomes:

```text
(128,128,3)
(128,128,1)
(129,128,1)
...
```

The first two fields behave like map-grid coordinates. The third field behaves
like a point/category code. Captured values so far include 1, 2, 3, 4, and 5.

One semantic is now physically correlated:

- **type 4**: challenging / entanglement-risk terrain. These are areas containing
  things the vacuum can sometimes run over but may get stuck on, such as clothes,
  ropes, or large loose debris/junk.

The meanings of types 1, 2, 3, and 5 are still not established and should remain
numeric until controlled experiments identify them.

## Redraw behavior

`SIID 7 / EIID 2 redraw-map` carries no arguments and is observed immediately
before a new map stream. The local visualizer therefore treats it as a map
generation reset and clears accumulated cells.

## Interesting temporal observation

In one capture:

- status 2 (cleaning) was followed by map triplets containing types 1/2/3;
- a front-collision fault was briefly reported as fault 5;
- after status 6 (returning to dock), subsequent map-point packets were type 5.

This is useful correlation but does not prove that type 5 means
"return-to-dock path" or robot position.

## Live visualizer

`experiments/cloud_event_control.py` now:

- parses every 7/1 payload into `(x,y,type)` triplets;
- preserves the raw cloud payload in CSV;
- accumulates the latest type for each coordinate;
- clears the decoded map on 7/2 redraw-map;
- exposes `/api/map`;
- renders the decoded cells live in the browser with a distinct display color
  for each numeric type;
- shows bounds and counts per type.

Run:

```bash
python experiments/cloud_event_control.py
```

and open:

```text
http://127.0.0.1:8768/
```

The display has a Flip Y control because the app's screen coordinate convention
has not yet been confirmed.


## Layer/update behavior

The longer capture shows that the same coordinate can receive several types over
time, sometimes even inside one packet. Therefore the third field is not simply
a permanent class assigned once to each grid cell.

The UI keeps two views of the data:

- the latest value for each `(x,y)`, used for the main raster;
- persistent per-type observations for the current redraw generation.

Type 4 is important enough that the visualizer now preserves every coordinate
that has been observed as type 4 and draws it as a challenge overlay even if a
later packet changes that coordinate to another type. Repeated type-4 hits are
also counted, which gives us a useful measure of how persistently the firmware
classified that location as challenging.
