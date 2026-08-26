import asyncio

import gpiod
from gpiod.line import Bias, Direction, Edge, Value

# Tablica przejsc kwadratury: klucz = (stary_stan << 2) | nowy_stan,
# gdzie stan = (A << 1) | B. Nieprawidlowe (pominiete) przejscia -> 0.
_QUADRATURE_DELTA = {
    0b0001: 1, 0b0111: 1, 0b1110: 1, 0b1000: 1,
    0b0010: -1, 0b1011: -1, 0b1101: -1, 0b0100: -1,
}


class EncoderController:
    """Odczyt enkoderow kwadraturowych (kanaly A/B) przez zdarzenia zboczy
    gpiod. Dzialanie jest sterowane zdarzeniami (loop.add_reader), wiec nie
    blokuje petli asyncio ani nie wymaga pollingu."""

    def __init__(self, chip: str, encoders: dict[str, list[int]]):
        self.chip: str = chip
        self.encoders: dict[str, list[int]] = encoders

        self._pin_to_encoder: dict[int, tuple[str, int]] = {}
        for name, (pin_a, pin_b) in encoders.items():
            self._pin_to_encoder[pin_a] = (name, 0)
            self._pin_to_encoder[pin_b] = (name, 1)

        self._ticks: dict[str, int] = {name: 0 for name in encoders}
        self._line_state: dict[str, int] = {name: 0 for name in encoders}

        self.request: gpiod.LineRequest | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def setup(self) -> None:
        config = {}
        for pin_a, pin_b in self.encoders.values():
            for pin in (pin_a, pin_b):
                config[pin] = gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.BOTH,
                    bias=Bias.PULL_UP,
                )

        self.request = gpiod.request_lines(
            self.chip,
            consumer="encoders",
            config=config,
        )

        for name, (pin_a, pin_b) in self.encoders.items():
            values = self.request.get_values([pin_a, pin_b])
            bit_a = 1 if values[0] is Value.ACTIVE else 0
            bit_b = 1 if values[1] is Value.ACTIVE else 0
            self._line_state[name] = (bit_a << 1) | bit_b

    def start(self) -> None:
        if self.request is None:
            self.setup()

        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self.request.fd, self._on_readable)

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.remove_reader(self.request.fd)
            self._loop = None

    def _on_readable(self) -> None:
        for event in self.request.read_edge_events():
            entry = self._pin_to_encoder.get(event.line_offset)
            if entry is None:
                continue

            name, channel = entry
            bit_value = 1 if event.event_type is gpiod.EdgeEvent.Type.RISING_EDGE else 0

            old_state = self._line_state[name]
            new_state = old_state
            if channel == 0:
                new_state = (bit_value << 1) | (old_state & 0b1)
            else:
                new_state = (old_state & 0b10) | bit_value

            delta = _QUADRATURE_DELTA.get((old_state << 2) | new_state, 0)
            self._ticks[name] += delta
            self._line_state[name] = new_state

    def get_ticks(self, name: str) -> int:
        if name not in self._ticks:
            raise KeyError(f"Nieznany enkoder: {name}")
        return self._ticks[name]

    def get_all_ticks(self) -> dict[str, int]:
        return dict(self._ticks)

    def reset(self, name: str | None = None) -> None:
        if name is None:
            for key in self._ticks:
                self._ticks[key] = 0
            return

        if name not in self._ticks:
            raise KeyError(f"Nieznany enkoder: {name}")
        self._ticks[name] = 0
