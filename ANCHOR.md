# Project anchor

## Goal

Understand and mitigate carpet-only navigation drift on a Xiaomi Mi Robot Vacuum-Mop Essential without making unnecessary firmware changes.

## Confirmed baseline

- Internal model: `mijia.vacuum.v2`
- App firmware: `2.2.1`
- Drift occurs only on carpet.
- Hard-floor navigation is initially correct.
- The dock IR system can home successfully after drift, but docking does not reset the navigation estimate.
- Xiaomi Home exposes direct directional control.
- Local miIO access works with the device token.
- `python-miio==0.5.12` is the currently tested client.
- OTA state reads as idle when no update is active.
- Firmware 2.2.1 responds successfully to all currently probed published MIoT properties, including `map_switch` at SIID 7 / PIID 2.
- The dock-only map-switch toggle is verified on firmware 2.2.1: both writes return code 0 and read back correctly as `False` then `True` while fully charged on the dock.

## Working direction

Prefer observation and reversible experiments before firmware changes:

1. Continue enumerating the actual MIoT surface implemented by firmware 2.2.1.
2. Run the docked control-vs-toggle A/B experiment to test whether map-switch cycling changes the retained navigation estimate.
3. Characterize direct-controller motion and any map/event feedback.
4. Explore map/event feedback so drift can eventually be detected automatically.
5. Investigate APP/MCU firmware only if the local protocol cannot expose a useful re-anchoring mechanism.

## Constraints

- Never commit device tokens, Xiaomi credentials, Wi-Fi passwords, MAC addresses, or other secrets.
- Treat movement commands as physical actions.
- Keep read-only probes separate from state-changing experiments.
- Do not assume firmware images for similar Xiaomi models are interchangeable.
