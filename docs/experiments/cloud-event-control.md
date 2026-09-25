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


## Manual direction command queue

The browser UI can send the raw direction-key property one command at a time.

Known values:

```text
SIID 8 / PIID 1
0 = left
1 = right
2 = forward
3 = backward
4 = stop
```

The UI exposes:

- **SEND ONCE**: immediately sends the current numeric value;
- **ADD TO QUEUE**: appends the current value plus its editable post-command interval;
- **SEND NEXT**: sends exactly one queued row and advances the cursor;
- **RUN QUEUE**: sends queued rows in order, waiting each row's interval before the next;
- **STOP QUEUE + SEND STOP**: stops queue playback and immediately sends value `4`;
- **CLEAR**: clears the local browser queue.

Every queued row remains editable for both `value` and `interval ms`. Values
outside the known 0..4 set can still be entered deliberately; they are sent
literally and may be rejected by the vacuum.

The server keeps a short command log and reports each raw MIoT response in the
UI. Nothing is sent automatically when the page loads.


## MQTT reconnect behavior

The Xiaomi broker can disconnect an otherwise working listener or the phone may
miss keepalives while Android/Termux is busy. Paho reconnects automatically.

After a reconnect, the listener now re-subscribes to the exact topic/QoS set that
was previously authorized. Earlier versions reconnected the socket but did not
restore subscriptions, so event capture silently stopped after the first
disconnect.

Browser polling may also be cancelled by Chrome while a response is being
written. The UI server now treats `BrokenPipeError` and connection reset as a
normal cancelled request instead of printing a traceback.


## Complete device MQTT capture

The underlying cloud listener now tries `device/<did>/#` before the narrower
MIoT topics. When the broker grants it, the UI records the complete device MQTT
subtree, including unknown topic families. Unknown topics remain in the CSV with
their raw topic and payload instead of being discarded.

If the broad wildcard is denied, capture falls back to Xiaomi's known
`event_occured`, `properties_changed`, and `state` families, then to exact
known vacuum events.
