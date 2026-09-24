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
