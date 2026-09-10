from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GamepadState:
    buttons: dict[str, bool] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)


class GamepadInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_state(self) -> GamepadState:
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        pass
