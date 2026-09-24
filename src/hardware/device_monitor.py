import asyncio
from typing import Callable, Generic, Optional, TypeVar

from .device_slot import DeviceSlot
from .status_log import log_device_status

T = TypeVar("T")


class DeviceMonitor(Generic[T]):
    """Cyklicznie sprawdza, czy aktywne w slocie urzadzenie (prawdziwy
    sprzet) nadal dziala (is_healthy()) - jesli nie, przelacza slot na
    dummy. Gdy w slocie jest dummy, cyklicznie probuje zbudowac swiezy
    prawdziwy sterownik - jesli sie uda, przelacza slot z powrotem.

    Nieudane proby ponownego polaczenia (dummy -> real) NIE sa logowane,
    zeby nie zasmiecac current_simulation_status.log co interval - loguje
    sie tylko faktyczna zmiana stanu."""

    def __init__(
        self,
        name: str,
        slot: DeviceSlot[T],
        build_real: Callable[[], T],
        build_dummy: Callable[[], T],
        poll_interval: float = 5.0,
        desired_powered: bool | None = None,
    ):
        self.name = name
        self.slot = slot
        self.build_real = build_real
        self.build_dummy = build_dummy
        self.poll_interval = poll_interval
        self.desired_powered = desired_powered

    @staticmethod
    def _is_dummy(instance: T) -> bool:
        return getattr(instance, "IS_DUMMY", False)

    async def set_powered(self, powered: bool) -> None:
        """Apply an explicit real/dummy selection immediately."""
        self.desired_powered = powered
        loop = asyncio.get_running_loop()
        current = self.slot.get()

        if powered:
            if self._is_dummy(current):
                candidate = await loop.run_in_executor(None, self.build_real)
                self.slot.set(candidate)
                log_device_status(self.name, "SUCCESS")
            return

        if not self._is_dummy(current):
            stop = getattr(current, "stop", None)
            if stop is not None:
                try:
                    stop()
                except Exception as exc:
                    print(f"{self.name}: error stopping device: {exc}")
            dummy = await loop.run_in_executor(None, self.build_dummy)
            self.slot.set(dummy)
            log_device_status(self.name, "SUCCESS - DUMMY")

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        while True:
            await asyncio.sleep(self.poll_interval)

            current = self.slot.get()

            if self.desired_powered is False:
                if not self._is_dummy(current):
                    await self.set_powered(False)
                continue

            if self.desired_powered is True:
                if self._is_dummy(current):
                    try:
                        await self.set_powered(True)
                    except Exception:
                        pass
                    if self._is_dummy(self.slot.get()):
                        continue

            if not self._is_dummy(current):
                try:
                    healthy = await loop.run_in_executor(None, current.is_healthy)
                except Exception:
                    healthy = False

                if not healthy:
                    stop = getattr(current, "stop", None)
                    if stop is not None:
                        try:
                            stop()
                        except Exception as e:
                            print(f"{self.name}: error stopping unhealthy device: {e}")

                    self.slot.set(self.build_dummy())
                    log_device_status(self.name, "ERROR - FALLBACK TO DUMMY")

                continue

            try:
                candidate = await loop.run_in_executor(None, self.build_real)
            except Exception:
                candidate = None

            if candidate is not None:
                self.slot.set(candidate)
                log_device_status(self.name, "SUCCESS")


def start_device_monitor(monitor: "DeviceMonitor") -> Optional[asyncio.Task]:
    """Odpala DeviceMonitor.run() jako task w biezacym event loopie. Zwraca
    None (bez podnoszenia wyjatku) jesli nie ma aktualnie uruchomionego loopa
    - factory bywaja wywolywane synchronicznie poza asyncio.run() (np.
    wczesna probka sd_card w program_manager.main() przed startem petli), a
    brak cyklicznego health-checka w takim przypadku jest akceptowalna
    degradacja, nie powod do crasha calego programu."""
    coro = monitor.run()
    try:
        return asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return None
