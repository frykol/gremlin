from collections.abc import Mapping


class DevicePowerController:
    def __init__(self, camera, lidar, mic, speaker):
        self._monitors = {
            "OAK-D": camera,
            "LIDAR": lidar,
            "MIC": mic,
            "SPEAKER": speaker,
        }

    async def apply(self, devices: Mapping) -> None:
        for name, powered in devices.items():
            monitor = self._monitors.get(name)
            if monitor is None or type(powered) is not bool:
                continue
            try:
                await monitor.set_powered(powered)
            except Exception as exc:
                print(f"{name}: device power change failed: {exc}")
