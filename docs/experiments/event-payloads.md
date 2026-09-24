# Event-payload probe

## Why this matters

The public MIoT description for `mijia.vacuum.v2` exposes three event payloads that are not
ordinary readable properties:

| Event | SIID/EIID | Backing property | SIID/PIID |
| --- | --- | --- | --- |
| map points | 7/1 | `points` | 7/1 |
| current clean record | 9/1 | `current-clean-record` | 9/6 |
| temporary log | 16/1 | `log-str` | 16/2 |

The `temp-log` event is especially interesting: the public specification describes it as
being used for analysis/localization, while `log-str` is described as temporary log data.

If firmware 2.2.1 allows any of these payload properties to be read directly, we can inspect
navigation/map data without first implementing event capture.

## New landmark observation

The Xiaomi Home map has shown the **same physical wall** at two separated map locations after
carpet drift. That gives us an external landmark constraint:

- the wall did not move;
- the mapped wall position did move;
- therefore the difference directly measures pose-estimation error.

If `map-points` contains the corresponding wall geometry, repeated encounters with this same
wall can be used to estimate both translation error and heading error. This is much stronger
than judging drift only from the overall shape of the blue cleaned area.

## One-shot read-only probe

```bash
python experiments/event_payload_probe.py
```

## Sampling while the robot is moving

This still performs only `get_properties` requests:

```bash
python experiments/event_payload_probe.py --samples 20 --interval 1
```

For the most useful run, start sampling before the robot reaches the known wall and continue
through the second encounter with that same physical wall.

## Interpretation

- `code: 0` with a string payload is immediately useful; save the raw values and compare them
  around the two wall encounters.
- A stable permission/not-readable error is also useful: it means these are event-only in this
  firmware and the next implementation should capture MIoT notifications instead of polling.
- If `temp_log` changes while the robot moves, inspect it first because the service explicitly
  identifies that event with localization analysis.
- If `map_points` exposes geometry, cluster the points belonging to the repeated wall and
  compare their centroids/orientations between encounters.

This experiment does not change any property or action.
