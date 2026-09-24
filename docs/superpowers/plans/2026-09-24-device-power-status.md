# Device Power Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply incoming `device_power_status` messages on Raspberry Pi by switching OAK-D, LiDAR, microphone, and speaker slots between real drivers and dummy drivers at runtime.

**Architecture:** Extend `DeviceMonitor` with an explicit desired power state and an async method that performs an immediate slot swap. Route the existing command queue message through `CommandProcessor` to a small controller holding the four device monitors. Health checks may recover a real device only when its desired state is powered on; a forced-off device remains dummy.

**Tech Stack:** Python 3, asyncio, pytest, existing `DeviceSlot` and hardware factories.

## Global Constraints

- The sender and site must remain unchanged.
- The message shape is `{\"type\": \"device_power_status\", \"devices\": {\"OAK-D\": bool, \"LIDAR\": bool, \"MIC\": bool, \"SPEAKER\": bool}}`.
- Unknown device names and malformed values are ignored without stopping command processing.
- Existing automatic health fallback and reconnect behavior must remain unchanged when no explicit power status has been received.

### Task 1: Add explicit power control to DeviceMonitor

**Files:**
- Modify: `src/hardware/device_monitor.py`
- Test: `tests/test_device_monitor.py`

- [ ] Write tests proving `set_powered(False)` stops the real instance, installs dummy, and prevents reconnect; proving `set_powered(True)` builds and installs real.
- [ ] Run the focused tests and confirm they fail because the API is absent.
- [ ] Add `desired_powered: bool | None`, `async set_powered(powered: bool)`, and make `run()` honor explicit false/true states while preserving legacy behavior when state is `None`.
- [ ] Run `pytest tests/test_device_monitor.py -q`.

### Task 2: Register monitors for all four runtime-controlled devices

**Files:**
- Modify: `src/hardware/oak_d/factory.py`
- Modify: `src/hardware/lidar/factory.py`
- Modify: `src/hardware/respeaker/factory.py`
- Modify: `src/hardware/speaker/factory.py`
- Test: `tests/test_device_power_status.py`

- [ ] Add a focused test using fake monitors/slots that the controller maps the four protocol names to the correct monitor.
- [ ] Run the test and confirm it fails before the controller exists.
- [ ] Ensure each factory creates and attaches a monitor even when initially configured dummy; preserve `external_bridge` LiDAR behavior.
- [ ] Run the focused factory/controller tests.

### Task 3: Route `device_power_status` through the command processor

**Files:**
- Modify: `src/robot_controller.py`
- Modify: `src/services/command_processor.py`
- Create: `src/hardware/device_power_controller.py`
- Test: `tests/test_device_power_status.py`

- [ ] Add a failing dispatch test for the exact message shape and boolean values.
- [ ] Implement a controller that stores `{\"OAK-D\": monitor, \"LIDAR\": monitor, \"MIC\": monitor, \"SPEAKER\": monitor}` and applies recognized entries with `await monitor.set_powered(value)`.
- [ ] Inject the controller from `RobotController` and dispatch the message before other command branches.
- [ ] Ignore malformed/unknown entries without raising out of `process_commands`.
- [ ] Run the focused test file and then the complete Python test suite.

### Task 4: Validate integration

**Files:**
- No source changes expected.

- [ ] Run `python3 -m compileall -q src tests/test_device_monitor.py tests/test_device_power_status.py`.
- [ ] Run `pytest -q`.
- [ ] Inspect `git diff --check` and confirm no sender/UI files changed.
