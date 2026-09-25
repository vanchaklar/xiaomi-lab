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
- Repeated black wall traces at the same real-world location are useful external evidence of accumulated pose error, but they are not a trustworthy onboard landmark because the robot has no identity signal proving that two obstacle observations came from the same wall.

## Working direction

Prefer observation and reversible experiments before firmware changes:

1. Direct polling of `7/1`, `9/6`, and `16/2` returns MIoT `-4004`. The device advertises `MSUB/PUB` subscription type 1 but rejects direct-LAN `miIO.sub` for wildcard `.`, `event_occured`, and `properties_changed` with `-10`. Cloud MQTT probing is more promising: only the `i2` broker has so far granted QoS 2 for both event and property subscriptions for the current OAuth token/DID; the other tested brokers rejected the SUBACK.
2. A read-only MIoT property brute-force scanner now covers arbitrary SIID/PIID ranges (including full 1..255 exhaustive mode). The current scan's successful reads match the published readable surface; `-4003` is treated as nonexistent, while `-4001`/`-4004` remain discovery candidates because event-backed properties return `-4004`.
3. The cloud control UI now includes a manual direction command queue for `SIID 8 / PIID 1`, with editable raw values and per-command intervals; commands can be sent once, stepped one-by-one, or run explicitly as a queue. Nothing is sent automatically on page load.
4. MQTT reconnects now restore the exact previously authorized topic/QoS subscriptions; earlier code reconnected the socket without re-subscribing. Browser-aborted UI polls are treated as benign and no longer print BrokenPipe tracebacks.
5. Longer captures confirm that the same coordinate can receive multiple map types over time, so the type field is an update/layer signal rather than a permanently immutable cell class. The UI now preserves type-4 challenge observations as an overlay and counts repeated hits per coordinate.
6. Cloud capture confirmed the live map stream: `SIID 7 / EIID 1 map-points` arrives during cleaning with PIID 1 strings that decode cleanly into repeated `(x, y, type)` integer triplets. `SIID 7 / EIID 2 redraw-map` precedes/reset a new stream. Observed values include 1, 2, 3, 4, and 5. Type 4 is now physically correlated with challenging / entanglement-risk terrain such as clothes, ropes, or large loose debris that the vacuum may traverse but can get stuck on; the other type semantics remain unresolved. The cloud control UI now renders these triplets live while preserving the raw payloads.
7. Treat generic walls/obstacles as diagnostic geometry only, not as trusted self-calibration anchors.
8. Use the dock as the primary trusted external reference because its IR signal has a distinct identity and docking constrains the robot to a known physical pose.
9. Use raw direct-controller pulses as controlled inputs to characterize hard-floor versus carpet motion/odometry behavior.
10. A touch-drawn path controller can save normalized geometric patterns and replay them as repeated turn/forward commands; use separate timing calibration for floor surfaces.
11. Find a navigation-estimator reset/reinitialization primitive that can be applied while docked; map-switch cycling is already ruled out.
12. Investigate APP/MCU firmware only if the local protocol cannot expose a useful reset/correction mechanism.

## Constraints

- Never commit device tokens, Xiaomi credentials, Wi-Fi passwords, MAC addresses, or other secrets.
- Treat movement commands as physical actions.
- Keep read-only probes separate from state-changing experiments.
- Do not assume firmware images for similar Xiaomi models are interchangeable.
- Do not use an obstacle as a calibration landmark unless the robot has an independent way to identify that obstacle.
