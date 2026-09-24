import threading
from typing import Generic, TypeVar

T = TypeVar("T")


class DeviceSlot(Generic[T]):
    """Trzyma aktualnie aktywna instancje sterownika urzadzenia (prawdziwy
    sprzet albo dummy). Konsumenci (workery, command_processor, robot_logic)
    wywoluja slot.get() przy KAZDYM uzyciu zamiast trzymac referencje do
    instancji na stale - dzieki temu podmiana zrobiona przez DeviceMonitor
    (fallback/reconnect) jest widoczna natychmiast wszedzie, bez restartu
    workerow."""

    def __init__(self, initial: T):
        self._lock = threading.Lock()
        self._current = initial

    def get(self) -> T:
        with self._lock:
            return self._current

    def set(self, value: T) -> None:
        with self._lock:
            self._current = value


def resolve(value):
    """Odpakowuje DeviceSlot do aktualnie aktywnej instancji; przepuszcza
    wszystko inne bez zmian. Dzieki temu konsumenci (workery,
    CommandProcessor, RobotLogic) moga wywolywac resolve(self.x_slot) przy
    kazdym uzyciu urzadzenia (zeby zobaczyc hot-swap zrobiony przez
    DeviceMonitor), a testy moga nadal wstrzykiwac gole mocki/faki bez
    zawijania ich w DeviceSlot."""
    if isinstance(value, DeviceSlot):
        return value.get()
    return value
