# Cloud event control UI

This is the interactive version of the Xiaomi cloud event experiment. It starts
the authorized cloud event subscription first and then exposes a browser UI with:

- START CLEANING
- STOP
- DOCK
- live vacuum state/battery
- live cloud event feed
- CSV logging

## Run

The UI now probes all Xiaomi MQTT regions by default:

```bash
python experiments/cloud_event_control.py
```

If this is the first OAuth login, specify the account/API region explicitly:

```bash
python experiments/cloud_event_control.py --auth-region us --login
```

Each regional broker is tested independently. Wildcard topics are tried first;
if rejected, the known exact event topics are tried at QoS 2, 1, and 0.

Then open:

```text
http://127.0.0.1:8768/
```

on the same phone.

If the cached OAuth file already records the correct auth region, this is enough:

```bash
python experiments/cloud_event_control.py
```

## Automatically begin the experiment

To start cleaning immediately after the cloud subscription is confirmed:

```bash
python experiments/cloud_event_control.py --region i2 --auto-start
```

The UI still remains available for STOP and DOCK.

## Safety/lifecycle

The UI sends cleaning controls over the existing local miIO connection. Cloud
event subscriptions remain read-only.

If this process itself started cleaning and the process exits while still in
cleaning mode, it sends STOP. If the user has already pressed STOP or DOCK, the
shutdown path does not override that state.

Events are written under `data/cloud_ui_*.csv`.


## Cloud subscription failure

The control UI does not exit if the MQTT event subscription is rejected. It
still starts the local web interface so START/STOP/DOCK remain available, and
the page shows the broker error under **Cloud errors**.

The DID resolver now keeps the proven local miIO DID unless the cloud device
list contains an exact DID match. A sole model-name match is shown as a
candidate but is not substituted automatically, because using a different DID
can change MQTT topic authorization.
