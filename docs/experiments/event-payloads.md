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

## One-shot read-only probe

```bash
python experiments/event_payload_probe.py
```

## Sampling while the robot is moving

This still performs only `get_properties` requests:

```bash
python experiments/event_payload_probe.py --samples 20 --interval 1
```

Run this during a short cleaning segment, ideally including the transition from hard floor to
carpet.

## Interpretation

- `code: 0` with a string payload is immediately useful; save the raw values and compare them
  before/after drift.
- A stable permission/not-readable error is also useful: it means these are event-only in this
  firmware and the next implementation should capture MIoT notifications instead of polling.
- If `temp_log` changes while the robot moves, inspect it first because the service explicitly
  identifies that event with localization analysis.

This experiment does not change any property or action.
