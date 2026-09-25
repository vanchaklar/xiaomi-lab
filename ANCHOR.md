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

1. Direct polling of `7/1`, `9/6`, and `16/2` returns MIoT `-4004`. The device's MDID probe advertises subscriptions (`MSUB/PUB`, type 1) but not wildcard support; forced `miIO.sub` with `sub_method='.'` returns `-10`. The LAN listener now tests explicit `event_occured` / `properties_changed` subscription methods before falling back to the older scene-based push path.
2. Treat generic walls/obstacles as diagnostic geometry only, not as trusted self-calibration anchors.
3. Use the dock as the primary trusted external reference because its IR signal has a distinct identity and docking constrains the robot to a known physical pose.
4. Use raw direct-controller pulses as controlled inputs to characterize hard-floor versus carpet motion/odometry behavior.
5. A touch-drawn path controller can save normalized geometric patterns and replay them as repeated turn/forward commands; use separate timing calibration for floor surfaces.
6. Find a navigation-estimator reset/reinitialization primitive that can be applied while docked; map-switch cycling is already ruled out.
7. Investigate APP/MCU firmware only if the local protocol cannot expose a useful reset/correction mechanism.

## Constraints

- Never commit device tokens, Xiaomi credentials, Wi-Fi passwords, MAC addresses, or other secrets.
- Treat movement commands as physical actions.
- Keep read-only probes separate from state-changing experiments.
- Do not assume firmware images for similar Xiaomi models are interchangeable.
- Do not use an obstacle as a calibration landmark unless the robot has an independent way to identify that obstacle.
