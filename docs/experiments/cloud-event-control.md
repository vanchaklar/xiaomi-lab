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

With the current experiment, the i2 broker is the only one that has granted the
event subscription while the cached OAuth token was issued in the US region:

```bash
python experiments/cloud_event_control.py \
  --region i2 \
  --auth-region us
```

Then open:

```text
http://127.0.0.1:8768/
```

on the same phone.

If the cached OAuth file already records the correct auth region, this is enough:

```bash
python experiments/cloud_event_control.py --region i2
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
