import asyncio
import time

from src.hardware.lidar.slam import LidarSlam
from src.logic.mecanum_odometry import MecanumGeometry, MecanumOdometry
from src.robot_state import RobotState, RobotPose


class SlamWorker:
    """
    Okresowo bierze aktualna zawartosc bufora punktow lidara i aktualizuje
    estymowana pozycje robota przez BreezySLAM.

    UWAGA: unitree_l1.py NIE koryguje juz przechylenia montazu (usuniete na
    zyczenie) - punkty w buforze sa w surowym ukladzie CZUJNIKA, nie w
    poziomym ukladzie robota. LidarSlam.update() bierze x,y wprost z tych
    punktow jako rzut 2D pod SLAM - jesli czujnik jest fizycznie przechylony,
    ten rzut nie jest juz plaszczyzna pozioma i dokladnosc SLAM-u dodatkowo
    ucierpi (poza juz udokumentowanymi ograniczeniami w hardware/lidar/slam.py).

    Odometria z enkoderow kol (mecanum) jest podawana jako pose_change -
    patrz src/logic/mecanum_odometry.py PO INSTRUKCJE KALIBRACJI: geometria
    kol (poza srednica 48mm) jest na razie PLACEHOLDEREM, wiec pozycja z
    tego workera jest przyblizona, dopoki ktos nie skalibruje wartosci w
    config.json["drivetrain"].
    """

    def __init__(self, state: RobotState, config: dict, poll_interval: float = 0.15):
        self.state: RobotState = state
        self.poll_interval: float = poll_interval

        slam_config = config.get("slam", {})
        self.enabled: bool = slam_config.get("enabled", False)

        self.slam = LidarSlam(
            map_size_pixels=slam_config.get("map_size_pixels", 500),
            map_size_meters=slam_config.get("map_size_meters", 10.0),
            max_range_mm=slam_config.get("max_range_mm", 8000.0),
            max_points_per_scan=slam_config.get("max_points_per_scan", 500),
            sigma_xy_mm=slam_config.get("sigma_xy_mm", 100.0),
            sigma_theta_degrees=slam_config.get("sigma_theta_degrees", 20.0),
        )

        drivetrain_config = config.get("drivetrain", {})
        self.odometry = MecanumOdometry(
            MecanumGeometry(
                wheel_diameter_mm=drivetrain_config.get("wheel_diameter_mm", 48.0),
                ticks_per_revolution=drivetrain_config.get("ticks_per_revolution", 560),
                wheelbase_mm=drivetrain_config.get("wheelbase_mm", 160.0),
                track_width_mm=drivetrain_config.get("track_width_mm", 160.0),
                encoder_sign=drivetrain_config.get(
                    "encoder_sign", {"FL": 1, "FR": 1, "RL": 1, "RR": 1}
                ),
            )
        )
        self._last_odom_time: float | None = None

        self.state.robot_pose = RobotPose()

        self.running: bool = False
        self.task: asyncio.Task | None = None

    def _read_pose_change(self):
        encoder_state = self.state.encoder_state
        if encoder_state is None:
            return None

        now = time.monotonic()
        if self._last_odom_time is None:
            self._last_odom_time = now
            self.odometry.reset(encoder_state.ticks)
            return None

        dt_s = now - self._last_odom_time
        self._last_odom_time = now
        return self.odometry.compute_pose_change(encoder_state.ticks, dt_s)

    async def run(self):
        while self.running:
            buffer = self.state.lidar_point_buffer
            if buffer is not None and len(buffer) > 0:
                points_xy = [(p[0], p[1]) for p in buffer.get_points()]
                pose_change = self._read_pose_change()
                x_mm, y_mm, theta_deg = self.slam.update(points_xy, pose_change)
                self.state.robot_pose = RobotPose(
                    x_m=x_mm / 1000.0,
                    y_m=y_mm / 1000.0,
                    theta_deg=theta_deg,
                )

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running or not self.enabled:
            return

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task
