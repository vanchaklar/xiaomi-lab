# MIoT LAN event listener

This experiment targets the event streams that cannot be read with
`get_properties`:

- map points: service 7 / event 1
- redraw map: service 7 / event 2
- current clean record: service 9 / event 1
- temp/localization log: service 16 / event 1

Firmware 2.2.1 returned `-4004` when the event-backing properties were polled
directly, so this listener uses Xiaomi's LAN push subscription mechanism instead.

## Protocol

The listener keeps one UDP socket open and:

1. sends an `MDID` probe to UDP 54321;
2. inspects the response for `MSUB` / `PUB` wildcard subscription support;
3. sends:

```text
miIO.sub
version = 2.0
sub_method = "."
```

4. waits for device-initiated `event_occured` and `properties_changed` messages;
5. ACKs each uplink message;
6. sends `miIO.unsub` on clean shutdown.

The spelling `event_occured` is Xiaomi's protocol spelling.

## Run

```bash
python experiments/lan_event_listener.py
```

Or collect for one minute:

```bash
python experiments/lan_event_listener.py --duration 60
```

Output is written to:

```text
data/lan_events_YYYYMMDD_HHMMSS.csv
```

## Expected first result

The script first prints whether this particular firmware advertises wildcard LAN
subscription support.

If it prints:

```text
wildcard=true
```

and `miIO.sub` succeeds, start a short cleaning run and watch especially for:

```text
EVENT 7/1  map_points
EVENT 16/1 temp_log
```

If the device does not advertise wildcard subscription, that is also a useful
result. This vacuum is old enough that it may require the older local-scene push
mechanism instead; that mechanism needs event-specific scene metadata.

## Notes

This listener is read-only with respect to the vacuum's cleaning/settings state.
It does create a temporary LAN push subscription and removes it on clean shutdown.

Use Ctrl-C rather than killing the process when possible so `miIO.unsub` can be
sent.


## Firmware 2.2.1 subscription result

Observed probe:

```text
advertises_sub=true
sub_type=1
wildcard=false
```

Forcing the wildcard request:

```text
miIO.sub
sub_method="."
```

returned:

```text
result.code = -10
```

This establishes that the device advertises a subscription mechanism but rejects
Xiaomi's newer wildcard form. The exact generic meaning of `-10` is not being
assumed here; in this experiment it is the response to the unsupported wildcard
request.

The next narrow probe is an explicit method subscription:

```bash
python experiments/lan_event_listener.py --sub-method event_occured --duration 60
```

If that is rejected too, try the property channel independently:

```bash
python experiments/lan_event_listener.py --sub-method properties_changed --duration 60
```

An explicit method does not require `--allow-no-wildcard`. The script also now
prints the raw subscription capability byte from the MDID response.


## Explicit method subscription result

Firmware 2.2.1 also rejects both explicit method filters:

```text
sub_method="event_occured"      -> result.code -10
sub_method="properties_changed" -> result.code -10
```

So the modern `miIO.sub` path is ruled out here for both wildcard and
explicit-method subscriptions.

The remaining local push path implemented by older Xiaomi tooling is the
`send_data_frame` / local-scene mechanism. That mechanism requires
event-specific scene metadata, especially its trigger `extra` value. The MIoT
spec gives the event IDs and argument properties but not that legacy scene
encoding, so it should be captured from Xiaomi Home traffic or another real scene
definition rather than guessed.
