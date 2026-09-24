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
- Behavioral A/B result: carpet drift still occurs after both the control restart and the docked map-switch toggle; map-switch cycling does not solve the carpet-drift problem.
- A map screenshot shows two black wall traces produced at the same physical wall location but plotted at substantially different map coordinates. This is direct evidence that the robot's internal pose estimate has moved while the external obstacle remained fixed.

## Working direction

Prefer observation and reversible experiments before firmware changes:

1. Probe event-backing payloads for map points, clean records, and the localization-oriented temp-log event.
2. Use repeated observations of the same physical wall as a landmark constraint: compare its map coordinates and orientation across passes to quantify translation and heading drift.
3. If event payloads are not directly readable, implement/capture MIoT notifications rather than polling them.
4. Characterize direct-controller motion as a controlled input for navigation experiments.
5. Investigate APP/MCU firmware only if the local protocol cannot expose a useful correction or calibration mechanism.

## Constraints

- Never commit device tokens, Xiaomi credentials, Wi-Fi passwords, MAC addresses, or other secrets.
- Treat movement commands as physical actions.
- Keep read-only probes separate from state-changing experiments.
- Do not assume firmware images for similar Xiaomi models are interchangeable.
