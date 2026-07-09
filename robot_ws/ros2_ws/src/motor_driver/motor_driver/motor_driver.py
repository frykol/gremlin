import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from tf2_ros import TransformBroadcaster

from motor_driver.odometry import integrate_odometry, quaternion_from_yaw

CONTROL_RATE_HZ = 50.0
WATCHDOG_TIMEOUT_S = 0.3

# Dwie plytki BTS7960 (potwierdzone w dr.py): pierwsza (R_EN/L_EN) obsluguje
# kanaly PCA9685 0-3 (FL, RL), druga (R2_EN/L2_EN) kanaly 4-7 (FR, RR).
# config.json zna tylko pierwsza pare — bez wlaczenia drugiej dwa silniki
# (FR, RR) nigdy nie dostawaly zasilania, stad krecenie w kolko zamiast jazdy prosto.
GPIO_CHIP = '/dev/gpiochip0'
ENABLE_PINS = {'R_EN': 5, 'L_EN': 6, 'R2_EN': 17, 'L2_EN': 27}

# (kanal_przod, kanal_tyl) per kolo — zmierzone recznie i potwierdzone
# aplikacja Tkinter do sterowania (motor_pairs: M1=FL, M2=RL, M3=FR, M4=RR).
WHEEL_CHANNELS = {
    'FL': (0, 1),
    'RL': (2, 3),
    'FR': (5, 4),
    'RR': (7, 6),
}

# Robot geometry — measure and correct once the chassis is final.
WHEEL_RADIUS_M = 0.04
WHEEL_BASE_LX_M = 0.10  # half distance between front and rear axles
WHEEL_BASE_LY_M = 0.10  # half distance between left and right wheels


def mecanum_inverse_kinematics(vx, vy, wz):
    """Twist (vx, vy, wz) -> wheel angular speeds (rad/s) for FL, FR, RL, RR."""
    k = WHEEL_BASE_LX_M + WHEEL_BASE_LY_M
    fl = (vx - vy - k * wz) / WHEEL_RADIUS_M
    fr = (vx + vy + k * wz) / WHEEL_RADIUS_M
    rl = (vx + vy - k * wz) / WHEEL_RADIUS_M
    rr = (vx - vy + k * wz) / WHEEL_RADIUS_M
    return fl, fr, rl, rr


class MotorDriver(Node):

    def __init__(self):
        super().__init__('motor_driver')

        self._cmd_sub = self.create_subscription(Twist, '/cmd_vel', self._cmd_vel_callback, 10)
        self._odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        self._last_cmd = Twist()
        self._last_cmd_time = time.monotonic()

        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
            i2c = busio.I2C(board.SCL, board.SDA)
            self._pca = PCA9685(i2c)
            self._pca.frequency = 50
            self.get_logger().info('PCA9685 zainicjalizowany na 0x40')
        except Exception as e:
            self.get_logger().warn(f'PCA9685 niedostępny: {e}')
            self._pca = None

        self._gpio_request = None
        try:
            import gpiod
            from gpiod.line import Direction, Value
            line_config = {
                pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)
                for pin in ENABLE_PINS.values()
            }
            self._gpio_request = gpiod.request_lines(
                GPIO_CHIP, consumer='motor_driver', config=line_config
            )
            pins_str = ', '.join(f'{name}={pin}' for name, pin in ENABLE_PINS.items())
            self.get_logger().info(f'BTS7960 (x2) wlaczone: {pins_str}')
        except Exception as e:
            self.get_logger().warn(f'GPIO enable BTS7960 niedostępne: {e}')
            self._gpio_request = None

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

        self._timer = self.create_timer(1.0 / CONTROL_RATE_HZ, self._tick)

    def _cmd_vel_callback(self, msg: Twist):
        self._last_cmd = msg
        self._last_cmd_time = time.monotonic()
        self.get_logger().info(
            f'/cmd_vel odebrany: linear.x={msg.linear.x:.2f} linear.y={msg.linear.y:.2f} angular.z={msg.angular.z:.2f}'
        )

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

    def _drive_wheels(self, fl, fr, rl, rr):
        if self._pca is None:
            return
        # Przelicz rad/s na duty cycle 0-65535
        # TODO: ustaw MAX_RAD_S wg realnej maks. predkosci silnikow.
        # Im wieksze MAX_RAD_S, tym nizszy duty dla tej samej komendy.
        # MAX_RAD_S=25 -> "do przodu" (7.5 rad/s/kolo) = ok. 30% duty
        MAX_RAD_S = 25.0

        def to_duty(w):
            duty = int(abs(w) / MAX_RAD_S * 65535)
            return min(duty, 65535)

        wheel_speeds = {'FL': fl, 'FR': fr, 'RL': rl, 'RR': rr}
        for name, w in wheel_speeds.items():
            fwd_ch, back_ch = WHEEL_CHANNELS[name]
            duty = to_duty(w)
            if w >= 0:
                self._pca.channels[fwd_ch].duty_cycle = duty
                self._pca.channels[back_ch].duty_cycle = 0
                active_ch = fwd_ch
            else:
                self._pca.channels[fwd_ch].duty_cycle = 0
                self._pca.channels[back_ch].duty_cycle = duty
                active_ch = back_ch
            if duty > 0:
                kierunek = 'przod' if w >= 0 else 'tyl'
                self.get_logger().info(f'{name}: {kierunek} kanal={active_ch} rad/s={w:.2f} duty={duty}')

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


def main(args=None):
    rclpy.init(args=args)
    node = MotorDriver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node._gpio_request is not None:
            node._gpio_request.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
