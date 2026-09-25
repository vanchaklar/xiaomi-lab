# Xiaomi Cloud event listener

The local `miIO.sub` experiments are rejected by firmware 2.2.1. Xiaomi's
current cloud integration, however, receives MIoT events over its MIPS/MQTT
broker on topics such as:

```text
device/<did>/up/event_occured/<siid>/<eiid>
```

This experiment connects to that cloud channel and listens for the vacuum's
events.

## Install

After pulling the repository:

```bash
pip install -r requirements.txt
```

## Region

The region must match the region selected for the vacuum in Xiaomi Home:

```text
cn  China mainland
de  Europe
i2  India
ru  Russia
sg  Singapore
us  United States
```

You can pass it on the command line or keep it local:

```bash
export XIAOMI_CLOUD_REGION=de
```

## First login

```bash
python experiments/cloud_event_listener.py --region de --login --auth-only
```

The script prints an official Xiaomi OAuth URL. Open it, authorize the account,
and let the browser redirect.

The registered redirect hostname is `homeassistant.local`. On a phone without
Home Assistant that final page will normally fail to load. This is expected.
Copy the complete final URL from the browser address bar and paste it back into
the terminal. The script extracts the OAuth code and exchanges it for an access
token.

The token is stored only in:

```text
data/xiaomi_cloud_auth.json
```

`data/` is gitignored. The file is chmod 0600 where supported.

## Capture live map events

Start a one-minute capture:

```bash
python experiments/cloud_event_listener.py --region de --duration 60
```

Then start a cleaning run in Xiaomi Home.

The listener now first asks the broker for the complete device subtree:

```text
device/<did>/#
```

If the broker authorizes it, this captures all channels published under the
vacuum DID, including undocumented or legacy topic families.

If the full-device wildcard is rejected, the listener falls back to every
device channel family exposed by Xiaomi's current cloud client:

```text
device/<did>/up/event_occured/#
device/<did>/up/properties_changed/#
device/<did>/state/#
```

If the event wildcard is rejected, the known exact vacuum events are then tried
at QoS 2, 1, and 0.

The DID defaults to the numeric local miIO device ID. Override it only if the
cloud account uses a different DID:

```bash
python experiments/cloud_event_listener.py --region de --did <cloud-did>
```

Interesting events are labelled:

```text
7/1   map_points
7/2   redraw_map
9/1   current_clean_record
16/1  temp_log
```

All received payloads are saved to:

```text
data/cloud_events_YYYYMMDD_HHMMSS.csv
```

## Expected result

If Xiaomi Home's live map is driven by the published MIoT event stream, a
cleaning run should produce messages similar to:

```text
CLOUD event_occured 7/1 map_points: ...
```

The first useful payload should be kept completely raw. Do not assume its string
encoding until multiple samples establish the format.

## Security

The OAuth access/refresh tokens are account credentials. Do not paste them into
issues or commit them. The listener never prints either token.


## Probe every Xiaomi MQTT region

If the account's broker region is uncertain, authenticate against the account
region once and probe all MQTT brokers:

```bash
python experiments/cloud_event_listener.py \
  --region all \
  --auth-region de \
  --login \
  --duration 120
```

Replace `de` with the region used for OAuth/account data. The same OAuth token
is then tried against all six Xiaomi MQTT broker regions. Brokers that reject
the token are reported and skipped; any broker that accepts it remains connected
for the capture.

After the OAuth token has been cached, `--auth-region` can be omitted:

```bash
python experiments/cloud_event_listener.py --region all --duration 120
```

Each connected region gets its own CSV file.


## Observed broker authorization

With the current OAuth token and vacuum DID, MQTT TCP/TLS connection succeeds
against all tested Xiaomi regional brokers, but the SUBACK result is what
determines whether the topic is actually authorized.

Observed results:

```text
cn  event/property subscription: rejected (unspecified error)
de  event/property subscription: rejected (unspecified error)
i2  event/property subscription: Granted QoS 2
ru  event/property subscription: rejected (unspecified error)
sg  event/property subscription: rejected (unspecified error)
us  event/property subscription: Not authorized
```

Therefore `i2-ha.mqtt.io.mi.com` is currently the only verified broker for
this token/DID/topic combination.

The listener now waits for SUBACK and treats rejected subscriptions as failed
regions. It also verifies the cloud device list and prefers the cloud DID for
`mijia.vacuum.v2` when it can resolve one unambiguously.

A focused capture can use the US OAuth token against the i2 broker:

```bash
python experiments/cloud_event_listener.py \
  --region i2 \
  --auth-region us \
  --duration 120
```


## Fan-speed implication

A successful `properties_changed/#` subscription already covers
`SIID 2 / PIID 6` fan speed. Therefore a run that captures other property
notifications but contains no `2/6` message did not miss it because of a
property-topic filter.

The new `device/<did>/#` probe is broader: if authorized, it also lets us see
whether this older vacuum publishes the carpet/fan transition through an
undocumented topic family rather than `properties_changed`.
