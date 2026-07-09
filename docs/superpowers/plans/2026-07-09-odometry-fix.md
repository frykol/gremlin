# Odometry Fix (motor_driver) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-zero odometry stub in `motor_driver` with open-loop (dead-reckoning) odometry integrated from `/cmd_vel`, so `slam_toolbox` gets a real motion prior between lidar scans.

**Architecture:** Extract the pure kinematic-integration math (position/heading update given `vx, vy, wz, dt`) into a standalone, ROS-free module so it can be unit tested without `rclpy`. Wire that function into `motor_driver.py`'s existing `_tick()`/`_publish_odom()` methods, replacing the static `(0,0,0)` pose with the integrated one, adding a real orientation quaternion, twist fields, and covariance matrices.

**Tech Stack:** Python 3, ROS2 (rclpy, `nav_msgs/Odometry`, `tf2_ros`), pytest.

## Global Constraints

- Scope is limited to the `motor_driver` ROS2 package — no changes to `robot.launch.py`, `slam_toolbox.yaml`, or TF offsets (tracked separately per the spec).
- No physical robot access this session — verification is via unit tests + code review + (if a ROS2 environment is sourced) `colcon build`, not live hardware runs.
- Covariance values are placeholders reflecting "dead-reckoning from commanded velocity, no wheel feedback" — order of magnitude 0.05–0.1 linear, 0.1–0.2 angular, per spec.

---

### Task 1: Pure kinematic odometry integration function + unit tests

**Files:**
- Create: `robot_ws/ros2_ws/src/motor_driver/motor_driver/odometry.py`
- Create: `robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py`

**Interfaces:**
- Produces:
  - `wrap_to_pi(angle: float) -> float` — normalizes any angle (radians) to `(-pi, pi]`.
  - `integrate_odometry(x: float, y: float, theta: float, vx: float, vy: float, wz: float, dt: float) -> tuple[float, float, float]` — returns updated `(x, y, theta)` after integrating body-frame velocities `vx, vy, wz` over `dt` seconds, rotated into the odom frame by `theta`.
  - `quaternion_from_yaw(theta: float) -> tuple[float, float]` — returns `(qz, qw)` for a rotation of `theta` radians about Z.

- [ ] **Step 1: Write the failing tests**

Create `robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py`:

```python
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from motor_driver.odometry import wrap_to_pi, integrate_odometry, quaternion_from_yaw


def test_wrap_to_pi_identity_within_range():
    assert wrap_to_pi(0.5) == pytest_approx(0.5)


def test_wrap_to_pi_wraps_positive_overflow():
    result = wrap_to_pi(math.pi + 0.1)
    assert result == pytest_approx(-math.pi + 0.1)


def test_wrap_to_pi_wraps_negative_overflow():
    result = wrap_to_pi(-math.pi - 0.1)
    assert result == pytest_approx(math.pi - 0.1)


def test_integrate_odometry_pure_forward_motion():
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=0.0, vx=1.0, vy=0.0, wz=0.0, dt=1.0
    )
    assert x == pytest_approx(1.0)
    assert y == pytest_approx(0.0)
    assert theta == pytest_approx(0.0)


def test_integrate_odometry_pure_rotation():
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=0.0, vx=0.0, vy=0.0, wz=math.pi / 2, dt=1.0
    )
    assert x == pytest_approx(0.0)
    assert y == pytest_approx(0.0)
    assert theta == pytest_approx(math.pi / 2)


def test_integrate_odometry_forward_motion_rotates_with_existing_heading():
    # Robot already facing +90deg (theta=pi/2): commanding vx should move
    # it in +y in the odom frame, not +x.
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=math.pi / 2, vx=1.0, vy=0.0, wz=0.0, dt=1.0
    )
    assert x == pytest_approx(0.0, abs=1e-9)
    assert y == pytest_approx(1.0)
    assert theta == pytest_approx(math.pi / 2)


def test_integrate_odometry_zero_dt_is_noop():
    x, y, theta = integrate_odometry(
        x=1.0, y=2.0, theta=0.3, vx=5.0, vy=5.0, wz=5.0, dt=0.0
    )
    assert x == pytest_approx(1.0)
    assert y == pytest_approx(2.0)
    assert theta == pytest_approx(0.3)


def test_quaternion_from_yaw_zero():
    qz, qw = quaternion_from_yaw(0.0)
    assert qz == pytest_approx(0.0)
    assert qw == pytest_approx(1.0)


def test_quaternion_from_yaw_half_pi():
    qz, qw = quaternion_from_yaw(math.pi / 2)
    assert qz == pytest_approx(math.sin(math.pi / 4))
    assert qw == pytest_approx(math.cos(math.pi / 4))


def pytest_approx(value, abs=1e-9):
    import pytest
    return pytest.approx(value, abs=abs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'motor_driver.odometry'`

- [ ] **Step 3: Write the implementation**

Create `robot_ws/ros2_ws/src/motor_driver/motor_driver/odometry.py`:

```python
import math


def wrap_to_pi(angle: float) -> float:
    """Normalize an angle in radians to the range (-pi, pi]."""
    wrapped = math.fmod(angle + math.pi, 2 * math.pi)
    if wrapped <= 0:
        wrapped += 2 * math.pi
    return wrapped - math.pi


def integrate_odometry(x, y, theta, vx, vy, wz, dt):
    """Dead-reckon (x, y, theta) forward by dt using body-frame velocities.

    vx, vy are in the robot's body frame; they are rotated by the current
    heading (theta) before being added to the odom-frame position, matching
    the standard 2D differential-drive/mecanum odometry integration used
    when no wheel encoder feedback is available.
    """
    dx = (vx * math.cos(theta) - vy * math.sin(theta)) * dt
    dy = (vx * math.sin(theta) + vy * math.cos(theta)) * dt
    dtheta = wz * dt

    new_x = x + dx
    new_y = y + dy
    new_theta = wrap_to_pi(theta + dtheta)
    return new_x, new_y, new_theta


def quaternion_from_yaw(theta: float):
    """Return (qz, qw) for a pure yaw rotation, x/y components are 0."""
    return math.sin(theta / 2.0), math.cos(theta / 2.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add robot_ws/ros2_ws/src/motor_driver/motor_driver/odometry.py \
        robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py
git commit -m "feat(motor_driver): add pure kinematic odometry integration functions"
```

---

### Task 2: Wire integration into MotorDriver node

**Files:**
- Modify: `robot_ws/ros2_ws/src/motor_driver/motor_driver/motor_driver.py:1-179`

**Interfaces:**
- Consumes: `wrap_to_pi`, `integrate_odometry`, `quaternion_from_yaw` from `motor_driver.odometry` (Task 1).

- [ ] **Step 1: Add import and dt tracking**

In `robot_ws/ros2_ws/src/motor_driver/motor_driver/motor_driver.py`, change the import block at the top:

```python
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from tf2_ros import TransformBroadcaster

from motor_driver.odometry import integrate_odometry, quaternion_from_yaw
```

- [ ] **Step 2: Track last tick time and last commanded velocity for odometry**

Replace the odometry-stub block:

```python
        # Odometry stub — no encoder feedback yet, pose stays at origin.
        # TODO: integrate wheel encoder ticks into vx/vy/wz -> x/y/theta.
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0
```

with:

```python
        # Open-loop (dead-reckoning) odometry: no wheel encoders exist on
        # this chassis, so position is integrated from the commanded
        # /cmd_vel rather than measured wheel motion. Drifts under wheel
        # slip, but is far better than the previous always-zero stub for
        # slam_toolbox's motion prior between scans.
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self._wz = 0.0
        self._last_tick_time = time.monotonic()
```

- [ ] **Step 3: Integrate position in `_tick()`**

Replace `_tick`:

```python
    def _tick(self):
        if (time.monotonic() - self._last_cmd_time) > WATCHDOG_TIMEOUT_S:
            cmd = Twist()  # no recent command: stop
        else:
            cmd = self._last_cmd

        fl, fr, rl, rr = mecanum_inverse_kinematics(cmd.linear.x, cmd.linear.y, cmd.angular.z)
        self._drive_wheels(fl, fr, rl, rr)
        self._publish_odom()
```

with:

```python
    def _tick(self):
        if (time.monotonic() - self._last_cmd_time) > WATCHDOG_TIMEOUT_S:
            cmd = Twist()  # no recent command: stop
        else:
            cmd = self._last_cmd

        fl, fr, rl, rr = mecanum_inverse_kinematics(cmd.linear.x, cmd.linear.y, cmd.angular.z)
        self._drive_wheels(fl, fr, rl, rr)

        now = time.monotonic()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        self._vx, self._vy, self._wz = cmd.linear.x, cmd.linear.y, cmd.angular.z
        self._x, self._y, self._theta = integrate_odometry(
            self._x, self._y, self._theta, self._vx, self._vy, self._wz, dt
        )

        self._publish_odom()
```

- [ ] **Step 4: Publish real orientation, twist, and covariance in `_publish_odom()`**

Replace `_publish_odom`:

```python
    def _publish_odom(self):
        now = self.get_clock().now()

        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.orientation.z = 0.0
        odom.pose.pose.orientation.w = 1.0
        self._odom_pub.publish(odom)

        tf = TransformStamped()
        tf.header.stamp = now.to_msg()
        tf.header.frame_id = 'odom'
        tf.child_frame_id = 'base_link'
        tf.transform.translation.x = self._x
        tf.transform.translation.y = self._y
        tf.transform.rotation.z = 0.0
        tf.transform.rotation.w = 1.0
        self._tf_broadcaster.sendTransform(tf)
```

with:

```python
    # Open-loop odometry covariance: no wheel feedback, so these reflect
    # dead-reckoning-from-commanded-velocity uncertainty, not a measured
    # sensor. Order of magnitude only — tune once real drift is observed.
    _POSE_COVARIANCE = [
        0.05, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.05, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 1e6, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 1e6, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 1e6, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.2,
    ]
    _TWIST_COVARIANCE = [
        0.1, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.1, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 1e6, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 1e6, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 1e6, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.2,
    ]

    def _publish_odom(self):
        now = self.get_clock().now()
        qz, qw = quaternion_from_yaw(self._theta)

        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.pose.covariance = self._POSE_COVARIANCE
        odom.twist.twist.linear.x = self._vx
        odom.twist.twist.linear.y = self._vy
        odom.twist.twist.angular.z = self._wz
        odom.twist.covariance = self._TWIST_COVARIANCE
        self._odom_pub.publish(odom)

        tf = TransformStamped()
        tf.header.stamp = now.to_msg()
        tf.header.frame_id = 'odom'
        tf.child_frame_id = 'base_link'
        tf.transform.translation.x = self._x
        tf.transform.translation.y = self._y
        tf.transform.rotation.z = qz
        tf.transform.rotation.w = qw
        self._tf_broadcaster.sendTransform(tf)
```

- [ ] **Step 5: Verify the file is syntactically valid**

Run: `python3 -c "import ast; ast.parse(open('robot_ws/ros2_ws/src/motor_driver/motor_driver/motor_driver.py').read())"`
Expected: no output (parses cleanly)

- [ ] **Step 6: Run the Task 1 unit tests again to confirm nothing broke**

Run: `python3 -m pytest robot_ws/ros2_ws/src/motor_driver/test/test_odometry.py -v`
Expected: PASS (9 passed)

- [ ] **Step 7: If a ROS2 environment is available, build the package**

Run (only if `/opt/ros/*/setup.bash` or equivalent is sourced in this environment):
```bash
cd robot_ws/ros2_ws && colcon build --packages-select motor_driver
```
Expected: `Summary: 1 package finished`. If no ROS2 environment is available in this session, skip this step and note it in the task summary — Step 5's `ast.parse` check plus code review is the fallback verification.

- [ ] **Step 8: Commit**

```bash
git add robot_ws/ros2_ws/src/motor_driver/motor_driver/motor_driver.py
git commit -m "fix(motor_driver): integrate open-loop odometry instead of always-zero stub"
```

---

## Post-plan note (out of scope, tracked for later)

TF offsets for lidar/camera (`base_to_laser_tf`, `base_to_camera_tf` in
`robot_ws/ros2_ws/src/robot_bringup/launch/robot.launch.py`) remain
unmeasured placeholders — separate task once the robot chassis is
physically accessible for measurement.
