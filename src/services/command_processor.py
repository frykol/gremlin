import base64
import json
import os
import asyncio
import time

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.gpio.encoder_controller import EncoderController
from ..hardware.i2c.interface import I2CPWMInterface
from ..hardware.speaker.interface import SpeakerInterface
from ..hardware.respeaker.interface import AudioFilterConfig, MicArrayInterface, NoiseProfileStatus
from ..robot_state import RobotState
from ..dev_connection.interface import WSClientInterface

LOG_PATH = "sim.log"
STATUS_LOG_PATH = "current_simulation_status.log"
WHEEL_STATE_PATH = "/tmp/wheel_state.json"


_COLOR_STOP_DANGER = (0.90, 0.20, 0.20)  # czerwony - slabe odbicie / przeszkoda
_COLOR_STOP_MID = (0.95, 0.80, 0.20)     # zolty - odbicie posrednie
_COLOR_STOP_SAFE = (0.15, 0.75, 0.60)    # turkusowy - silne odbicie (np. podloga)


def _reflectivity_to_color(intensity: int) -> str:
    """Mapuje sile odbicia (0-255) na kolor 3-stopniowym gradientem: czerwony
    (slabe odbicie, np. przeszkoda) -> zolty -> turkusowy (silne odbicie).
    Ten sam gradient co heightToColor w lidar.js/SLAM, dla spojnosci wizualnej
    w calej aplikacji. Trzeci, wyrazny punkt posredni (zolty) unika brudnego,
    trudnego do odczytania fioletu, ktory wychodzi przy interpolacji tylko
    miedzy dwoma kolorami (np. samym czerwonym i niebieskim)."""
    ratio = max(0, min(255, intensity)) / 255.0

    if ratio < 0.5:
        t = ratio / 0.5
        start, end = _COLOR_STOP_DANGER, _COLOR_STOP_MID
    else:
        t = (ratio - 0.5) / 0.5
        start, end = _COLOR_STOP_MID, _COLOR_STOP_SAFE

    r = round(255 * (start[0] + (end[0] - start[0]) * t))
    g = round(255 * (start[1] + (end[1] - start[1]) * t))
    b = round(255 * (start[2] + (end[2] - start[2]) * t))
    return f"#{r:02x}{g:02x}{b:02x}"

class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, encoder: EncoderController, i2c_pwm: I2CPWMInterface, state: RobotState, ws: WSClientInterface, udp_frame_sender, speaker: SpeakerInterface, mic_array: MicArrayInterface | None = None):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.encoder: EncoderController = encoder
        self.i2c_pwm: I2CPWMInterface = i2c_pwm
        self.state: RobotState = state
        self.ws: WSClientInterface = ws
        self.udp_frame_sender = udp_frame_sender
        self.speaker: SpeakerInterface = speaker
        self.mic_array: MicArrayInterface | None = mic_array
        self.wheel_channel_state: dict[int, int] = {}

    async def run(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()
                try:
                    await self._dispatch_command(cmd)
                except Exception:
                    # Jedna wadliwa komenda (np. suwak filtra audio zjechany
                    # do zdegenerowanej szerokosci pasma -> ValueError ze
                    # scipy) nie moze ubijac calej petli obslugi komend -
                    # bez tego wyjatek z dowolnej komendy blokowal WSZYSTKIE
                    # kolejne komendy (silniki, GPIO, wszystkie zakladki) az
                    # do restartu procesu. Patrz sim.log:
                    # "ValueError: Wn[0] must be less than Wn[1]", a potem
                    # kaskada "Program manager not running, ignoring
                    # instruction" dla kazdej kolejnej komendy.
                    import traceback
                    traceback.print_exc()
        except asyncio.QueueEmpty:
            pass

    async def _dispatch_command(self, cmd: dict) -> None:
        # if cmd:
        #     print(cmd)

        if cmd.get("send") == "logs":
            await self._send_log()

        elif cmd.get("send") == "status":
            await self._send_status()

        elif cmd.get("type") == "gpio":
            if cmd["pin_name"] in self.gpio.pins:
                self.gpio.set_named_pin(cmd["pin_name"], cmd["value"])
            elif cmd["pin_name"] in self.gpio.standard_pins:
                self.gpio.set_standard_pin(cmd["pin_name"], cmd["value"])
            else:
                print(f"Unknown pin name: {cmd['pin_name']}")

        elif cmd.get("type") == "motor":
            if self.state.follow_band_mode:
                # tryb podazania steruje silnikami sam - ignorujemy
                # reczne komendy, zeby nie kolidowaly z autonomiczna jazda
                pass
            else:
                self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])
                self.wheel_channel_state[cmd["channel"]] = cmd["pwm"]

        elif cmd.get("type") == "set_follow_band_mode":
            self.state.follow_band_mode = cmd["enabled"]

        elif cmd.get("type") == "set_follow_band_speed":
            self.state.follow_band_max_pwm = max(0, min(4095, int(cmd["pwm"])))

        elif cmd.get("type") == "stream":
            self.state.stream_enabled = cmd["enabled"]

        elif cmd.get("type") == "audio_stream":
            self.state.audio_stream_enabled = cmd["enabled"]

        elif cmd.get("type") == "register_video_sink":
            self.udp_frame_sender.set_target(cmd["host"], cmd["port"])

        elif cmd.get("type") == "get_lidar_points":
            await self._send_lidar_points()

        elif cmd.get("type") == "get_slam_pose":
            await self._send_slam_pose()

        elif cmd.get("type") == "get_encoder_ticks":
            await self._send_encoder_ticks()

        elif cmd.get("type") == "reset_encoders":
            self.encoder.reset(cmd.get("name"))
            await self._send_encoder_ticks()

        elif cmd.get("type") == "get_ads1115_values":
            await self._send_ads1115_values()

        elif cmd.get("type") == "get_band_detection_state":
            await self._send_band_detection_state()

        elif cmd.get("type") == "get_color_detection_state":
            await self._send_color_detection_state()

        elif cmd.get("type") == "get_voice_recognition_state":
            await self._send_voice_recognition_state()

        elif cmd.get("type") == "get_audio_filter_config":
            await self._send_audio_filter_config()

        elif cmd.get("type") == "set_audio_filter_config":
            self._update_audio_filter_config(cmd)
            await self._send_audio_filter_config()

        elif cmd.get("type") == "get_noise_profile_status":
            await self._send_noise_profile_status()

        elif cmd.get("type") == "start_noise_profile_calibration":
            if self.mic_array is not None:
                self.mic_array.start_noise_profile_calibration()
            await self._send_noise_profile_status()

        elif cmd.get("type") == "stop_noise_profile_calibration":
            if self.mic_array is not None:
                self.mic_array.stop_noise_profile_calibration()
            await self._send_noise_profile_status()

        elif cmd.get("type") == "reset_noise_profile":
            if self.mic_array is not None:
                self.mic_array.reset_noise_profile()
            await self._send_noise_profile_status()

        elif cmd.get("type") == "play_sound":
            file_path = cmd.get("file")
            if file_path:
                volume = cmd.get("volume", 1.0)
                self.speaker.play(file_path, volume=volume)
            else:
                print("play_sound command missing 'file' parameter")

        elif cmd.get("type") == "stop_sound":
            self.speaker.stop()

    async def _send_lidar_points(self) -> None:
        buffer = self.state.lidar_point_buffer
        points = buffer.get_points() if buffer is not None else []

        colored_points = [
            {
                "x": x,
                "y": y,
                "z": z,
                "intensity": intensity,
                "color": _reflectivity_to_color(intensity),
            }
            for x, y, z, intensity in points
        ]

        await self.ws.send(json.dumps({
            "type": "lidar_points",
            "points": colored_points,
        }))

    async def _send_slam_pose(self) -> None:
        pose = self.state.robot_pose

        await self.ws.send(json.dumps({
            "type": "slam_pose",
            "x_m": pose.x_m if pose is not None else 0.0,
            "y_m": pose.y_m if pose is not None else 0.0,
            "theta_deg": pose.theta_deg if pose is not None else 0.0,
        }))

    async def _send_encoder_ticks(self) -> None:
        encoder_state = self.state.encoder_state
        ticks = encoder_state.ticks if encoder_state is not None else {}

        await self.ws.send(json.dumps({
            "type": "encoder_ticks",
            "ticks": ticks,
        }))

    async def _send_ads1115_values(self) -> None:
        ads_state = self.state.last_ads1115_state

        await self.ws.send(json.dumps({
            "type": "ads1115_values",
            "values": {
                "a0": ads_state.a0,
                "a1": ads_state.a1,
                "a2": ads_state.a2,
                "a3": ads_state.a3,
                "raw_a0": ads_state.raw_a0,
                "raw_a1": ads_state.raw_a1,
                "raw_a2": ads_state.raw_a2,
                "raw_a3": ads_state.raw_a3,
            } if ads_state is not None else {},
        }))

    async def _send_band_detection_state(self) -> None:
        band_state = self.state.band_detection_state

        await self.ws.send(json.dumps({
            "type": "band_detection_state",
            "both_detected": band_state.both_detected if band_state is not None else False,
            "left": band_state.left if band_state is not None else False,
            "right": band_state.right if band_state is not None else False,
            "last_update": band_state.last_update if band_state is not None else 0.0,
            "debug_frame": band_state.debug_frame if band_state is not None else "",
        }))

    async def _send_color_detection_state(self) -> None:
        color_state = self.state.color_detection_state

        await self.ws.send(json.dumps({
            "type": "color_detection_state",
            "detected": color_state.detected if color_state is not None else False,
            "blue_ratio": color_state.blue_ratio if color_state is not None else 0.0,
            "last_update": color_state.last_update if color_state is not None else 0.0,
            "debug_frame": color_state.debug_frame if color_state is not None else "",
            "blue_bboxes": [list(box) for box in color_state.blue_bboxes] if color_state is not None else [],
            "yellow_bboxes": [list(box) for box in color_state.yellow_bboxes] if color_state is not None else [],
            "target_bbox": list(color_state.target_bbox) if color_state is not None and color_state.target_bbox is not None else None,
            "green_on_yellow_detected": color_state.green_on_yellow_detected if color_state is not None else False,
        }))

    async def _send_voice_recognition_state(self) -> None:
        voice_state = self.state.voice_recognition_state

        await self.ws.send(json.dumps({
            "type": "voice_recognition_state",
            "last_text": voice_state.last_text if voice_state is not None else "",
            "last_action": voice_state.last_action if voice_state is not None else None,
            "last_update": voice_state.last_update if voice_state is not None else 0.0,
            "history": voice_state.history if voice_state is not None else [],
        }))

    async def _send_audio_filter_config(self) -> None:
        config = self.mic_array.get_filter_config() if self.mic_array is not None else AudioFilterConfig()

        await self.ws.send(json.dumps({
            "type": "audio_filter_config",
            "lidar_center_hz": config.lidar_center_hz,
            "lidar_width_hz": config.lidar_width_hz,
            "lidar_enabled": config.lidar_enabled,
            "motor_center_hz": config.motor_center_hz,
            "motor_width_hz": config.motor_width_hz,
            "motor_enabled": config.motor_enabled,
        }))

    def _update_audio_filter_config(self, cmd: dict) -> None:
        if self.mic_array is None:
            return

        current = self.mic_array.get_filter_config()
        updated = AudioFilterConfig(
            lidar_center_hz=cmd.get("lidar_center_hz", current.lidar_center_hz),
            lidar_width_hz=cmd.get("lidar_width_hz", current.lidar_width_hz),
            lidar_enabled=cmd.get("lidar_enabled", current.lidar_enabled),
            motor_center_hz=cmd.get("motor_center_hz", current.motor_center_hz),
            motor_width_hz=cmd.get("motor_width_hz", current.motor_width_hz),
            motor_enabled=cmd.get("motor_enabled", current.motor_enabled),
        )
        self.mic_array.update_filter_config(updated)

    async def _send_noise_profile_status(self) -> None:
        status = self.mic_array.get_noise_profile_status() if self.mic_array is not None else NoiseProfileStatus()

        await self.ws.send(json.dumps({
            "type": "noise_profile_status",
            "is_calibrating": status.is_calibrating,
            "has_profile": status.has_profile,
        }))

    async def _send_log(self) -> None:
        try:
            with open(LOG_PATH, "rb") as file:
                encoded = base64.b64encode(file.read()).decode("utf-8")
        except OSError:
            encoded = ""

        await self.ws.send(json.dumps({
            "type": "logs",
            "file": encoded,
        }))

    async def _send_status(self) -> None:
        try:
            with open(STATUS_LOG_PATH, "rb") as file:
                encoded = base64.b64encode(file.read()).decode("utf-8")
        except OSError:
            encoded = ""

        await self.ws.send(json.dumps({
            "type": "status",
            "file": encoded,
        }))

    def write_wheel_state(self, path: str = WHEEL_STATE_PATH) -> None:
        """Zapisuje aktualny stan kanalow PWM uzywanych do napedu kol wraz
        ze znacznikiem czasu monotonicznego, do odczytu przez
        wheel_odometry_reader.py (robot_ws) w osobnym procesie. Zapis
        atomowy (plik tymczasowy + rename), zeby czytelnik nigdy nie
        zobaczyl niekompletnego JSON-a."""
        payload = {
            "t_mono": time.monotonic(),
            "channels": {str(ch): pwm for ch, pwm in self.wheel_channel_state.items()},
        }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)

    async def run_wheel_state_writer(self, path: str = WHEEL_STATE_PATH, interval: float = 0.075):
        while True:
            self.write_wheel_state(path)
            await asyncio.sleep(interval)