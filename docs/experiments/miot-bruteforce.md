# MIoT brute-force property scan

This experiment scans the MIoT property address space without relying on the
published model specification.

It sends only `get_properties` requests. It does **not** invoke actions.

## Default scan

```bash
python experiments/miot_bruteforce.py
```

The default range is:

```text
SIID 1..32
PIID 1..32
```

That covers 1,024 property addresses and already extends well beyond the
published `mijia.vacuum.v2` services.

Successful properties are printed immediately. Every response, including errors,
is stored in CSV under `data/`.

## Larger ranges

```bash
python experiments/miot_bruteforce.py --siid-max 64 --piid-max 64
```

Full one-byte ID space:

```bash
python experiments/miot_bruteforce.py --exhaustive
```

The exhaustive mode scans 65,025 property addresses, so it should be allowed to
run for some time.

## Robustness

Requests are batched. If a batch fails at the transport level, it is retried and
then recursively split so one problematic address does not hide the rest.

Useful controls:

```bash
python experiments/miot_bruteforce.py \
  --batch-size 8 \
  --delay 0.1 \
  --retries 2
```

Use `--print-all` to print every result instead of only successful or unusual
responses.

## Why actions are not brute-forced here

There is no read-only "does AIID exist?" operation. Sending an `action` request
to a valid unknown AIID can immediately cause movement, docking, reset behavior,
or another state change. Therefore this scanner exhausts SIID/PIID reads only.

Action IDs can be tested separately once there is an allowlist or a specific
candidate worth invoking.
