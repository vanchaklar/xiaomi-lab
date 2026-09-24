# `mijia.vacuum.v2` interface notes

The installed client currently used by this project is `python-miio==0.5.12`.

Its `G1Vacuum` wrapper exposes the common cleaning/status operations, but the generic
`MiotDevice` base class can address additional MIoT properties and actions directly by
service/property/action IDs.

## Useful generic calls

```python
vac.get_property_by(siid, piid)
vac.set_property_by(siid, piid, value)
vac.call_action_by(siid, aiid, params)
vac.raw_command(command, parameters)
vac.send(command, parameters)
```

## Known services of interest

| Feature | SIID | PIID/AIID | Access |
| --- | ---: | ---: | --- |
| status | 2 | PIID 1 | read |
| fault | 2 | PIID 2 | read |
| operating mode | 2 | PIID 4 | read/write |
| water level | 2 | PIID 5 | read/write |
| fan level | 2 | PIID 6 | read/write |
| start cleaning | 2 | AIID 1 | action |
| stop cleaning | 2 | AIID 2 | action |
| return to dock | 2 | AIID 3 | action |
| battery | 3 | PIID 1 | read |
| charging state | 3 | PIID 2 | read |
| alarm | 4 | PIID 1 | read/write |
| volume | 4 | PIID 2 | read/write |
| map switch | 7 | PIID 2 | read/write |
| remote direction | 8 | PIID 1 | write |
| language | 12 | PIID 1 | read/write |
| DND switch | 12 | PIID 2 | read/write |
| DND time | 12 | PIID 3 | read/write |
| timezone | 12 | PIID 4 | read/write |
| start charging | 13 | AIID 1 | action |
| stop charging | 13 | AIID 2 | action |
| mop state | 16 | PIID 1 | read |

### Remote direction values

| Value | Direction |
| ---: | --- |
| 0 | left |
| 1 | right |
| 2 | forward |
| 3 | backward |
| 4 | stop |

## OTA interface inherited from `Device`

```python
vac.update(url, md5)
vac.update_state()
vac.update_progress()
```

`update()` sends `miIO.ota`. No firmware update should be attempted until the
firmware binary, exact target model, and checksum are independently verified.

## Sources

- python-miio 0.5.12 G1 implementation:
  https://github.com/rytilahti/python-miio/blob/0.5.12/miio/integrations/vacuum/mijia/g1vacuum.py
- python-miio 0.5.12 generic device implementation:
  https://github.com/rytilahti/python-miio/blob/0.5.12/miio/device.py
- Public MIoT specification mirror:
  https://home.miot-spec.com/spec?type=urn:miot-spec-v2:device:vacuum:0000A006:mijia-v2:2


## Observed on firmware 2.2.1

A read-only probe against the confirmed device returned successful `code: 0` responses for every tested property below:

| Property | SIID/PIID | Observed value |
| --- | --- | --- |
| status | 2/1 | 5 |
| fault | 2/2 | 0 |
| operating mode | 2/4 | 1 |
| water level | 2/5 | 2 |
| fan level | 2/6 | 1 |
| battery | 3/1 | 100 |
| charging state | 3/2 | 2 |
| alarm | 4/1 | true |
| volume | 4/2 | 50 |
| map switch | 7/2 | true |
| language | 12/1 | 0 |
| DND switch | 12/2 | true |
| DND time | 12/3 | 20000700 |
| timezone | 12/4 | 8 |
| mop state | 16/1 | 0 |

The key result for the navigation work is that `map_switch` is not merely present in the public MIoT description: firmware 2.2.1 responds to it successfully.

These values are snapshots, not constants. In particular, status, battery, charging, and user-configurable settings vary with device state.


## Event-only navigation data worth probing

The same public model specification exposes event-backed values that are not ordinary readable
properties:

| Service | Event | Event ID | Payload property |
| --- | --- | --- | --- |
| map (7) | `map-points` | EIIDs 1 | `points` at PIID 1 |
| clean-record (9) | `current-clean-record` | EIID 1 | PIID 6 |
| other-status (16) | `temp-log` | EIID 1 | `log-str` at PIID 2 |

The `temp-log` description explicitly relates it to analysis/localization. That makes it the
highest-value telemetry candidate for the carpet-drift investigation.

Use `experiments/event_payload_probe.py` to test whether firmware 2.2.1 allows these backing
properties to be read directly before implementing event subscription/capture.
